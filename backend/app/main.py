"""
Company Brain Backend – FastAPI Application Entry Point.

Middleware stack (applied bottom-to-top by Starlette, so the first
``add_middleware`` call is the **innermost** layer):

    Request ──►  SecurityHeaders ──►  AuditLog ──►  CORS
            ──►  OIDCAuth ──►  RateLimiter ──►  InputSanitization ──►  Route

All security middleware is imported from ``app.middleware``.
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

# Security middleware
from app.middleware.auth import OIDCAuthMiddleware
from app.middleware.audit_logger import AuditLogMiddleware
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.middleware.rbac import RBACPolicy
from app.middleware.sanitizer import InputSanitizationMiddleware, SecurityHeadersMiddleware

# Database
from app.db.database import init_db, close_db, get_db_session
from app.db.models import Tenant, WorkflowRun, FeedbackRecord, Skill, IngestionCursor
from app.db.tenancy import resolve_tenant

# Governed workflow execution (agents, critic, skill match, persistence) lives
# in app.services.workflow.runner; routes delegate to it (imported where used).

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("company_brain.api")

# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown hooks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise database on startup, close on shutdown."""
    logger.info("Starting Company Brain backend...")
    await init_db()
    logger.info("Database initialised")
    yield
    await close_db()
    logger.info("Shutdown complete")

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Company Brain Backend",
    version="0.2.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# RBAC policy instance (used as a FastAPI dependency)
# ---------------------------------------------------------------------------
rbac = RBACPolicy()

# ---------------------------------------------------------------------------
# Middleware registration
# ---------------------------------------------------------------------------
# NOTE: Starlette processes middleware in **reverse** registration order.
# The LAST middleware added here is the OUTERMOST (first to see the request).

# 1. Input sanitization (innermost – runs closest to route handlers)
app.add_middleware(InputSanitizationMiddleware, block_on_detection=True)

# 2. Rate limiter — added before auth so it is INNER to auth on the request
#    path (Starlette runs the last-added middleware first). This guarantees
#    OIDCAuth has populated request.state.user before the limiter keys its
#    bucket, so limits are per-user, not a single shared per-IP bucket.
app.add_middleware(RateLimiterMiddleware)

# 3. OIDC authentication
app.add_middleware(
    OIDCAuthMiddleware,
    oidc_issuer=os.getenv("OIDC_ISSUER"),
    audience=os.getenv("OIDC_AUDIENCE"),
)

# 4. CORS – allow only internal origins (frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Audit logger
app.add_middleware(AuditLogMiddleware)

# 6. Security headers (outermost – always runs)
app.add_middleware(SecurityHeadersMiddleware)

# Register OAuth Router
from app.routes.oauth import router as oauth_router
app.include_router(oauth_router)

# Register Webhooks Router
from app.routes.webhooks import router as webhooks_router
app.include_router(webhooks_router)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class WorkflowRequest(BaseModel):
    """Request body for workflow execution."""
    trigger_data: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    """Request body for submitting feedback on a workflow run."""
    workflow_run_id: str
    feedback_type: str = Field(..., description="approve | reject | modify | escalate")
    corrected_output: dict[str, Any] | None = None
    reason: str = ""


# Map a human feedback decision to the workflow run's new status. Returns None
# when the decision does not resolve the run (e.g. "escalate" keeps it pending
# for higher sign-off), so the caller leaves the status untouched.
_STATUS_BY_FEEDBACK = {
    "approve": "completed",
    "modify": "completed",
    "reject": "rejected",
}


def status_for_feedback(feedback_type: str) -> str | None:
    """Resolve the post-decision WorkflowRun status, or None to leave unchanged."""
    return _STATUS_BY_FEEDBACK.get(feedback_type)


class SearchRequest(BaseModel):
    """Request body for knowledge base search."""
    query: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    source_filter: str | None = None


class OnboardingRequest(BaseModel):
    """Body for onboarding a company: name + industry + risk posture."""
    company_name: str = Field(..., min_length=1, max_length=120)
    industry: str = Field(default="saas")
    risk_posture: str | None = None


class ObserveRequest(BaseModel):
    """Ingestion input for the universal OODA core graph engine.

    Vertical-agnostic: ``source_platform`` / ``industry_vertical`` are tags on a
    single generic compiler, not selectors for per-vertical parsers.
    """
    source_platform: str = Field(..., min_length=1)
    industry_vertical: str = Field(default="generic")
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    skill_id: str | None = None
    stale_artifact: str | None = None


class ProfileUpdate(BaseModel):
    """Partial update of a tenant's Company Profile."""
    display_name: str | None = Field(default=None, max_length=120)
    accent: str | None = Field(default=None, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    industry: str | None = None
    risk_posture: str | None = None
    connectors: dict[str, bool] | None = None


# ---------------------------------------------------------------------------
# Routes: Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Liveness / readiness probe – unauthenticated."""
    return {"status": "ok", "version": "0.2.0"}


@app.get("/events")
async def events_stream():
    """SSE endpoint for real-time frontend updates."""
    from app.sse import sse_endpoint
    return await sse_endpoint()


# ---------------------------------------------------------------------------
# Routes: Ingestion
# ---------------------------------------------------------------------------

@app.post("/ingest/{source}")
async def trigger_ingest(
    source: str,
    request: Request,
    _: None = Depends(rbac.require_permission("write", "ingestion")),
):
    """Trigger ingestion for a given source (slack, notion, github).

    In production this would enqueue a Celery task. For now, we import
    the connector and run it inline to prove the wiring works.
    """
    # Lazy import connectors so they register with ConnectorRegistry
    import ingestion.slack_connector  # noqa: F401
    import ingestion.notion_connector  # noqa: F401
    import ingestion.github_connector  # noqa: F401
    import ingestion.zendesk_connector  # noqa: F401
    from ingestion.base_connector import ConnectorRegistry

    try:
        connector_class = ConnectorRegistry.get(source)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Available: {ConnectorRegistry.list_sources()}",
        )

    connector = connector_class()
    start = time.monotonic()

    try:
        documents = connector.ingest_all()
    except Exception as exc:
        logger.exception("Ingestion failed for source %s", source)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")

    elapsed_ms = (time.monotonic() - start) * 1000

    return JSONResponse({
        "source": source,
        "documents_ingested": len(documents),
        "duration_ms": round(elapsed_ms, 1),
        "status": "completed",
    })


def _build_observe_collaborators():
    """Build the LLM-backed extractor, contradiction synthesizer, and injection
    scanner if an LLM key is configured; otherwise return (None, None, None) so
    the pipeline uses its deterministic heuristic fallback. Never raises."""
    try:
        provider = os.getenv("LLM_PROVIDER", "gemini")
        api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
        )
        if not api_key:
            return None, None, None
        from app.agents.llm_adapter import LLMAdapter
        from app.services.knowledge_graph.entity_extractor import EntityExtractor
        from app.services.contradiction.synthesizer import ContradictionSynthesizer
        from app.services.security.prompt_injection import AdversarialDetector

        llm = LLMAdapter(provider=provider, api_key=api_key, model=os.getenv("LLM_MODEL", ""))
        extractor = EntityExtractor(llm)

        async def extract(text: str):
            result = await extractor.extract_with_relations(text)
            triplets = [
                {
                    "subject": r.source_name,
                    "predicate": r.relation_type,
                    "object": r.target_name,
                    "attributes": {"extractor": "llm", "confidence": 0.85, **(r.properties or {})},
                }
                for r in result.relationships
            ]
            for e in result.entities:
                triplets.append({
                    "subject": e.name,
                    "predicate": "is_a",
                    "object": e.entity_type,
                    "attributes": {"extractor": "llm", "confidence": 0.8},
                })
            return triplets

        synth = ContradictionSynthesizer(llm)
        detector = AdversarialDetector(llm)
        return extract, synth.synthesize, detector.scan_text
    except Exception:  # noqa: BLE001
        logger.exception("LLM extractor build failed; falling back to heuristic")
        return None, None, None


@app.post("/observe")
async def observe_ingest(
    body: ObserveRequest,
    request: Request,
    _: None = Depends(rbac.require_permission("write", "ingestion")),
):
    """Universal OODA ingestion: turn any vertical's raw exhaust into canonical
    triplets, run the quarantine pre-flight + contradiction synthesis, and return
    the mandated core-graph contract."""
    from app.services.observe.pipeline import observe as run_observe
    from app.services.quarantine import lock as quarantine_lock

    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)

    extract, synthesize, scan = _build_observe_collaborators()
    result = await run_observe(
        tenant_id=str(tenant.id),
        source_platform=body.source_platform,
        industry_vertical=body.industry_vertical,
        raw_payload=body.raw_payload,
        skill_id=body.skill_id,
        stale_artifact=body.stale_artifact,
        extract=extract,
        synthesize=synthesize,
        scan=scan,
        quarantine_get=quarantine_lock.get_sync,
    )
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Routes: Workflows
# ---------------------------------------------------------------------------

@app.post("/workflow/{name}")
async def run_workflow(
    name: str,
    body: WorkflowRequest,
    request: Request,
    _: None = Depends(rbac.require_permission("execute_workflow", "workflows")),
):
    """Execute a named workflow with real LLM agents.

    1. Resolves the Tenant and fetches active skills
    2. Runs SkillMatcher to find the most relevant SOP
    3. Executes the full pipeline (retrieve → generate → critique → act)
    4. Persists the result to PostgreSQL
    """
    # Delegate to the single governed-workflow runner so the API path and the
    # Celery scheduler share one critic-gated, approval-gated, audited loop —
    # there is no second, ungoverned path (docs/POSITIONING.md, Governed Action).
    from app.services.workflow.runner import run_governed_workflow

    # Resolve the caller's tenant first (enforces auth + isolation). A 403/404
    # from resolution must propagate untouched.
    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)
        tenant_id = tenant.id
        tenant_settings = dict(tenant.settings or {})

    user = getattr(request.state, "user", None)
    triggered_by = getattr(user, "email", None) or "system"

    try:
        result = await run_governed_workflow(
            tenant_id=tenant_id,
            tenant_settings=tenant_settings,
            workflow_name=name,
            trigger_data=body.trigger_data,
            config=body.config,
            triggered_by=triggered_by,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Workflow '%s' failed", name)
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {exc}")

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Routes: Feedback
# ---------------------------------------------------------------------------

@app.post("/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    request: Request,
    _: None = Depends(rbac.require_permission("write", "feedback")),
):
    """Submit human feedback on a workflow run.

    Stores the feedback in PostgreSQL, then enqueues a background task that runs
    the feedback loop: anomaly check → quorum → skill re-synthesis → critic
    calibration. The task is enqueued only after the row commits so the worker
    never races ahead of the write.
    """
    user = getattr(request.state, "user", None)
    user_email = getattr(user, "email", "unknown") if user else "unknown"
    user_role = (getattr(user, "roles", []) or ["engineer"])[0] if user else "engineer"

    feedback_id: str | None = None
    tenant_id: str | None = None
    has_skill = False

    async with get_db_session() as session:
        # Resolve the caller's tenant first, then find the workflow run and
        # verify it belongs to that tenant — a user must not submit feedback
        # against another tenant's run.
        current_tenant = await resolve_tenant(request, session)

        from sqlalchemy import select
        stmt = select(WorkflowRun).where(WorkflowRun.id == body.workflow_run_id)
        result = await session.execute(stmt)
        wf_run = result.scalar_one_or_none()

        if wf_run is None:
            raise HTTPException(status_code=404, detail="Workflow run not found")

        if wf_run.tenant_id != current_tenant.id:
            # Do not reveal that the run exists under another tenant — 404.
            raise HTTPException(status_code=404, detail="Workflow run not found")

        record = FeedbackRecord(
            tenant_id=wf_run.tenant_id,
            workflow_run_id=wf_run.id,
            skill_id=wf_run.skill_id,
            feedback_type=body.feedback_type,
            original_output=wf_run.final_action,
            corrected_output=body.corrected_output,
            reason=body.reason,
            submitted_by=user_email,
            submitted_by_role=user_role,
        )
        session.add(record)

        # Transition the run out of the review queue based on the human decision,
        # so the approvals queue does not repopulate the same item on reload.
        new_status = status_for_feedback(body.feedback_type)
        if new_status is not None:
            wf_run.status = new_status
            # Append an immutable human-decision entry to the audit trail
            # (reassign a new list so SQLAlchemy detects the JSONB change).
            decision = {
                "event": "human_feedback",
                "feedback_type": body.feedback_type,
                "new_status": new_status,
                "by": user_email,
                "role": user_role,
                "reason": body.reason,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            wf_run.audit_trail = [*(wf_run.audit_trail or []), decision]

        await session.flush()  # populate record.id before the session commits

        feedback_id = str(record.id)
        tenant_id = str(wf_run.tenant_id)
        has_skill = wf_run.skill_id is not None

    # Enqueue the feedback loop AFTER commit. Only when the feedback maps to a
    # skill — there is nothing to re-synthesize otherwise.
    queued = False
    if has_skill and feedback_id and tenant_id:
        try:
            from celery import Celery
            celery_app = Celery(
                "company_brain",
                broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
            )
            celery_app.send_task(
                "tasks.process_feedback",
                args=[tenant_id, feedback_id],
                queue="default",
            )
            queued = True
        except Exception:
            logger.exception("Failed to enqueue feedback processing (non-fatal)")

    message = (
        "Feedback stored. Skill re-synthesis enqueued."
        if queued
        else "Feedback stored. No associated skill — re-synthesis not triggered."
    )
    return JSONResponse({
        "status": "recorded",
        "feedback_type": body.feedback_type,
        "processed": False,
        "queued": queued,
        "message": message,
    })


# ---------------------------------------------------------------------------
# Routes: Search
# ---------------------------------------------------------------------------

@app.post("/search")
async def search_knowledge_base(
    request: Request,
    body: SearchRequest,
    _: None = Depends(rbac.require_permission("read", "knowledge_base")),
):
    """Semantic search over the vectorised knowledge base (tenant-scoped).

    Results are filtered to the caller's tenant so one tenant can never read
    another tenant's documents.
    """
    try:
        from ingestion.embedding_pipeline import Embedder, WeaviateStore

        async with get_db_session() as session:
            tenant = await resolve_tenant(request, session)
        tenant_id = str(tenant.id)

        embedder = Embedder()
        store = WeaviateStore()
        store.connect()
        try:
            query_vector = embedder.embed([body.query])[0]
            results = store.search(
                query_vector=query_vector,
                tenant_id=tenant_id,
                limit=body.limit,
            )
        finally:
            store.close()

        return JSONResponse({
            "query": body.query,
            "results": results,
            "count": len(results),
        })
    except HTTPException:
        raise
    except Exception:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail="Search failed")


# ---------------------------------------------------------------------------
# Routes: Connectors (list available sources)
# ---------------------------------------------------------------------------

@app.get("/connectors")
async def list_connectors(
    _: None = Depends(rbac.require_permission("read", "connectors")),
):
    """List all registered data source connectors."""
    import ingestion.slack_connector  # noqa: F401
    import ingestion.notion_connector  # noqa: F401
    import ingestion.github_connector  # noqa: F401
    import ingestion.zendesk_connector  # noqa: F401
    from ingestion.base_connector import ConnectorRegistry

    return JSONResponse({
        "connectors": ConnectorRegistry.list_sources(),
    })


# ---------------------------------------------------------------------------
# Routes: Skills (CRUD)
# ---------------------------------------------------------------------------

@app.get("/skills")
async def list_skills(
    request: Request,
    _: None = Depends(rbac.require_permission("read", "skills")),
):
    """List all skills for the current tenant (scoped to the caller's tenant)."""
    async with get_db_session() as session:
        from sqlalchemy import select
        tenant = await resolve_tenant(request, session)
        stmt = (
            select(Skill)
            .where(Skill.tenant_id == tenant.id)
            .order_by(Skill.updated_at.desc())
            .limit(100)
        )
        result = await session.execute(stmt)
        skills = result.scalars().all()

        return JSONResponse({
            "skills": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "slug": s.slug,
                    "version": s.version,
                    "status": s.status,
                    "risk_level": s.risk_level,
                    "confidence_score": s.confidence_score,
                    "created_by": s.created_by,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
                for s in skills
            ],
        })


# ---------------------------------------------------------------------------
# Routes: Quarantine (Contradiction Handshake reconciliation)
# ---------------------------------------------------------------------------

@app.get("/quarantine")
async def list_quarantines(
    request: Request,
    _: None = Depends(rbac.require_permission("read", "skills")),
):
    """Active contradiction quarantines for the caller's tenant.

    Backs the Knowledge Reconciliation queue: each entry is a skill whose SOP
    is under conflict review, with the lock evidence (pr_ref, summary,
    severity, locked_at) the reviewer adjudicates.
    """
    from app.services.quarantine import service as quarantine_service

    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)
        locks = await quarantine_service.list_active_locks(session, tenant.id)
        return JSONResponse({"quarantines": locks, "count": len(locks)})


class QuarantineReleaseRequest(BaseModel):
    resolution: str = Field(..., description="'dismiss' (false positive) or 'accept' (synthesis applied)")
    reason: str = Field("", max_length=2000)


@app.post("/quarantine/{skill_id}/release")
async def release_quarantine(
    skill_id: str,
    payload: QuarantineReleaseRequest,
    request: Request,
    _: None = Depends(rbac.require_permission("approve_action", "quarantine")),
):
    """Resolve a quarantine after human review (manager/admin only).

    'dismiss' records a false positive; 'accept' records that the synthesized
    fix was applied. Both release the lock so the CriticAgent stops vetoing.
    """
    from app.services.quarantine import service as quarantine_service

    user = getattr(request.state, "user", None)
    resolved_by = (getattr(user, "email", None) or getattr(user, "sub", None) or "unknown") if user else "unknown"

    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)
        try:
            outcome = await quarantine_service.release_lock(
                session,
                tenant.id,
                skill_id,
                resolution=payload.resolution,
                resolved_by=resolved_by,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return JSONResponse(outcome)


# ---------------------------------------------------------------------------
# Routes: Dashboard read APIs (workflows, verdicts, stats, activity)
# ---------------------------------------------------------------------------

@app.get("/workflows")
async def list_workflows(
    request: Request,
    status: str | None = None,
    limit: int = 20,
    _: None = Depends(rbac.require_permission("read", "workflows")),
):
    """List recent workflow runs for the caller's tenant.

    Optional ``status`` filter (e.g. ``pending_review`` for the approval queue).
    """
    limit = max(1, min(limit, 100))
    async with get_db_session() as session:
        from app.db.repositories.workflow_repo import WorkflowRepo, risk_level
        from app.services.risk.forecaster import forecast_risk

        tenant = await resolve_tenant(request, session)
        repo = WorkflowRepo(session)
        runs = await repo.list_for_tenant(tenant.id, status=status, limit=limit)

        n_history, miss_rate, thr_base, max_aut = await _tenant_risk_history(repo, tenant)

        return JSONResponse({
            "workflows": [
                {
                    "id": str(r.id),
                    "workflow_name": r.workflow_name,
                    "status": r.status,
                    "critic_approved": r.critic_approved,
                    "critic_risk_score": r.critic_risk_score,
                    "critic_risk_level": risk_level(r.critic_risk_score),
                    "critic_reasons": r.critic_reasons or [],
                    "final_action": r.final_action or {},
                    "trigger_data": r.trigger_data or {},
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "forecast": forecast_risk(
                        r.critic_risk_score or 0.0,
                        n_history=n_history,
                        miss_rate=miss_rate,
                        reasons=r.critic_reasons,
                        threshold_base=thr_base,
                        max_autonomy=max_aut,
                    ).as_dict(),
                }
                for r in runs
            ],
        })


@app.get("/verdicts")
async def list_verdicts(
    request: Request,
    limit: int = 10,
    _: None = Depends(rbac.require_permission("read", "workflows")),
):
    """Recent critic verdicts for the caller's tenant (Critic Verdicts card)."""
    limit = max(1, min(limit, 50))
    async with get_db_session() as session:
        from app.db.repositories.workflow_repo import WorkflowRepo, risk_level, verdict_label

        from app.services.risk.forecaster import forecast_risk

        tenant = await resolve_tenant(request, session)
        repo = WorkflowRepo(session)
        runs = await repo.recent_with_verdicts(tenant.id, limit=limit)

        n_history, miss_rate, thr_base, max_aut = await _tenant_risk_history(repo, tenant)

        verdicts = []
        for r in runs:
            forecast = forecast_risk(
                r.critic_risk_score or 0.0,
                n_history=n_history,
                miss_rate=miss_rate,
                reasons=r.critic_reasons,
                threshold_base=thr_base,
                max_autonomy=max_aut,
            )
            verdicts.append({
                "id": str(r.id),
                "title": f"{r.workflow_name.replace('_', ' ')} · {str(r.id)[:8]}",
                "verdict": verdict_label(r.status),
                "risk_score": round((r.critic_risk_score or 0.0) * 100),
                "risk_level": risk_level(r.critic_risk_score),
                "reasons": r.critic_reasons or [],
                "probability": round(forecast.probability * 100),
                "confidence_low": round(forecast.confidence_low * 100),
                "confidence_high": round(forecast.confidence_high * 100),
                "dynamic_threshold": round(forecast.dynamic_threshold * 100),
                "autonomy_level": forecast.autonomy_level,
            })

        return JSONResponse({"verdicts": verdicts})


@app.get("/stats")
async def get_stats(
    request: Request,
    _: None = Depends(rbac.require_permission("read", "workflows")),
):
    """Tenant-scoped counts + token usage for the Knowledge Stats card.

    Uses Postgres counts only (no Weaviate/Neo4j dependency) so it works on the
    lean demo stack.
    """
    async with get_db_session() as session:
        from app.db.repositories.workflow_repo import WorkflowRepo

        tenant = await resolve_tenant(request, session)
        repo = WorkflowRepo(session)
        counts = await repo.counts_for_tenant(tenant.id)

        settings = tenant.settings or {}
        input_tokens = settings.get("total_input_tokens", 0)
        output_tokens = settings.get("total_output_tokens", 0)

        return JSONResponse({
            "stats": {
                **counts,
                "accumulated_cost_usd": settings.get("accumulated_llm_cost", 0.0),
                "total_tokens": input_tokens + output_tokens,
            },
        })


@app.get("/activity")
async def get_activity(
    request: Request,
    limit: int = 12,
    _: None = Depends(rbac.require_permission("read", "workflows")),
):
    """Recent activity feed for the caller's tenant."""
    limit = max(1, min(limit, 50))
    async with get_db_session() as session:
        from app.db.repositories.workflow_repo import WorkflowRepo

        tenant = await resolve_tenant(request, session)
        repo = WorkflowRepo(session)
        activity = await repo.recent_activity(tenant.id, limit=limit)
        return JSONResponse({"activity": activity})


# ---------------------------------------------------------------------------
# Routes: Differentiators — probabilistic risk, blast radius, audit chain,
# policy evolution. These power the standout views.
# ---------------------------------------------------------------------------

async def _tenant_risk_history(repo, tenant) -> tuple[int, float, float, int]:
    """Inputs for the risk forecaster: sample size, human-intervention rate, and
    the tenant's risk-posture parameters.

    ``n_history`` sizes the confidence band; ``miss_rate`` (how often a human had
    to step in) tightens the dynamic threshold; the posture sets the threshold
    centre and the autonomy cap.
    """
    from app.services.tenant.industry_templates import posture_params

    counts = await repo.counts_for_tenant(tenant.id)
    n = int(counts.get("total_workflow_runs", 0))
    feedback = int(counts.get("total_feedback", 0))
    miss_rate = min(1.0, feedback / n) if n else 0.0
    p = posture_params((tenant.settings or {}).get("risk_posture"))
    return n, miss_rate, float(p["threshold_base"]), int(p["max_autonomy_level"])


async def _load_run_for_tenant(session, request, run_id: str):
    """Fetch a workflow run, scoped to the caller's tenant (404 otherwise)."""
    import uuid as _uuid
    from sqlalchemy import select

    tenant = await resolve_tenant(request, session)
    try:
        rid = _uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run id")
    result = await session.execute(select(WorkflowRun).where(WorkflowRun.id == rid))
    run = result.scalar_one_or_none()
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run


@app.get("/critic/calibration")
async def get_critic_calibration(
    request: Request,
    _: None = Depends(rbac.require_permission("read", "workflows")),
):
    """Reliability curve: predicted risk probability vs observed negative
    outcomes. A well-calibrated critic tracks the diagonal."""
    async with get_db_session() as session:
        from app.db.repositories.workflow_repo import WorkflowRepo
        from app.services.risk.forecaster import (
            calibrate_probability,
            calibration_curve,
        )

        tenant = await resolve_tenant(request, session)
        repo = WorkflowRepo(session)
        runs = await repo.recent_with_verdicts(tenant.id, limit=500)

        points: list[tuple[float, bool]] = []
        for r in runs:
            if r.status not in ("completed", "rejected", "error"):
                continue  # only resolved runs have an observed outcome
            p = calibrate_probability(r.critic_risk_score or 0.0)
            negative = r.status in ("rejected", "error")
            points.append((p, negative))

        curve = calibration_curve(points, bins=5)
        # Mean absolute calibration error across populated buckets.
        errs = [
            abs((b["observed"] or 0.0) - b["predicted_mid"])
            for b in curve
            if b["observed"] is not None
        ]
        mace = round(sum(errs) / len(errs), 3) if errs else None

        return JSONResponse({
            "calibration": {
                "curve": curve,
                "samples": len(points),
                "mean_abs_error": mace,
            }
        })


@app.get("/blast-radius/{run_id}")
async def get_blast_radius(
    run_id: str,
    request: Request,
    _: None = Depends(rbac.require_permission("read", "workflows")),
):
    """Downstream systems an action would touch, for the approval card."""
    async with get_db_session() as session:
        from app.services.risk.blast_radius import compute_blast_radius

        run = await _load_run_for_tenant(session, request, run_id)
        br = compute_blast_radius(
            run.workflow_name,
            trigger_data=run.trigger_data,
            final_action=run.final_action,
        )
        return JSONResponse({"blast_radius": br.as_dict()})


@app.get("/audit")
async def get_audit(
    request: Request,
    limit: int = 50,
    _: None = Depends(rbac.require_permission("read", "workflows")),
):
    """Tamper-evident audit chain (newest first) with a verify flag."""
    limit = max(1, min(limit, 200))
    async with get_db_session() as session:
        from app.db.repositories.workflow_repo import WorkflowRepo
        from app.services.audit.chain import build_chain, verify_chain

        tenant = await resolve_tenant(request, session)
        repo = WorkflowRepo(session)
        runs = await repo.list_for_tenant(tenant.id, limit=limit)
        chain = build_chain(list(runs))  # oldest -> newest (links read forward)
        return JSONResponse({
            "audit": list(reversed(chain)),  # newest first for display
            "verified": verify_chain(chain),
            "length": len(chain),
        })


@app.get("/audit/{run_id}/snapshot")
async def get_audit_snapshot(
    run_id: str,
    request: Request,
    _: None = Depends(rbac.require_permission("read", "workflows")),
):
    """Time-travel: the decision-time state snapshot for one run."""
    async with get_db_session() as session:
        from app.services.audit.chain import digest, snapshot_of

        run = await _load_run_for_tenant(session, request, run_id)
        snap = snapshot_of(run)
        return JSONResponse({"snapshot": snap, "digest": digest(snap)})


@app.get("/policy/history")
async def get_policy_history(
    request: Request,
    _: None = Depends(rbac.require_permission("read", "connectors")),
):
    """The tenant's evolving Critic policy: invariants the CriticCalibrator has
    appended over time (the visible moat)."""
    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)
        settings = tenant.settings or {}
        history = settings.get("policy_history") or []
        rules = settings.get("critic_rules") or []
        return JSONResponse({
            "policy_history": history,
            "active_rules": rules,
            "count": len(rules),
        })


# ---------------------------------------------------------------------------
# Routes: Company Profile & Onboarding (per-company tailoring)
# ---------------------------------------------------------------------------

@app.get("/tenant/profile")
async def get_tenant_profile(
    request: Request,
    _: None = Depends(rbac.require_permission("read", "connectors")),
):
    """The tenant's Company Profile: branding, risk posture (with resolved
    forecaster params), connectors, and the catalog of industries/postures."""
    from app.services.tenant.industry_templates import (
        INDUSTRY_TEMPLATES,
        RISK_POSTURES,
        posture_params,
    )

    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)
        settings = tenant.settings or {}
        branding = settings.get("branding") or {}
        posture = settings.get("risk_posture")
        params = posture_params(posture)

        return JSONResponse({
            "tenant_id": str(tenant.id),
            "branding": {
                "display_name": branding.get("display_name") or tenant.name,
                "accent": branding.get("accent") or "#2563eb",
                "industry": branding.get("industry"),
                "logo": branding.get("logo") or tenant.name[:2].upper(),
            },
            "risk_posture": posture or "balanced",
            "risk_params": params,
            "connectors": settings.get("connectors") or {},
            "catalog": {
                "industries": [
                    {"id": k, "label": v["label"]} for k, v in INDUSTRY_TEMPLATES.items()
                ],
                "postures": [
                    {"id": k, "label": v["label"], "blurb": v["blurb"]}
                    for k, v in RISK_POSTURES.items()
                ],
            },
        })


@app.put("/tenant/profile")
async def update_tenant_profile(
    body: ProfileUpdate,
    request: Request,
    _: None = Depends(rbac.require_permission("write", "connectors")),
):
    """Partial update of the Company Profile (branding / posture / connectors)."""
    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)
        settings = dict(tenant.settings or {})
        branding = dict(settings.get("branding") or {})

        if body.display_name is not None:
            branding["display_name"] = body.display_name
            branding["logo"] = body.display_name[:2].upper()
        if body.accent is not None:
            branding["accent"] = body.accent
        if body.industry is not None:
            branding["industry"] = body.industry
        if branding:
            settings["branding"] = branding
        if body.risk_posture is not None:
            settings["risk_posture"] = body.risk_posture
        if body.connectors is not None:
            settings["connectors"] = body.connectors

        tenant.settings = settings
        if body.display_name:
            tenant.name = body.display_name

        return JSONResponse({"status": "updated", "branding": branding})


@app.post("/onboarding")
async def onboard_company(
    body: OnboardingRequest,
    request: Request,
    _: None = Depends(rbac.require_permission("write", "connectors")),
):
    """Tailor a company in one step: set branding, seed the industry policy pack,
    default connectors, and risk posture. The brain starts smart on day one."""
    from app.services.tenant.industry_templates import build_profile

    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)
        profile = build_profile(
            display_name=body.company_name,
            industry=body.industry,
            risk_posture=body.risk_posture,
        )
        settings = dict(tenant.settings or {})
        settings.update(profile)  # branding, risk_posture, connectors, rules, history
        settings["onboarded"] = True
        tenant.settings = settings
        tenant.name = body.company_name

        return JSONResponse({
            "status": "onboarded",
            "branding": profile["branding"],
            "risk_posture": profile["risk_posture"],
            "rules_seeded": len(profile["critic_rules"]),
        })


# ---------------------------------------------------------------------------
# Routes: Tenant Settings & Usage (Sprint 3)
# ---------------------------------------------------------------------------

@app.get("/tenant/settings")
async def get_tenant_settings(
    request: Request,
    _: None = Depends(rbac.require_permission("read", "connectors")),
):
    """Retrieve billing costs, token count usage, and connected integrations
    for the caller's tenant."""
    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)

        settings = tenant.settings or {}
        accumulated_cost = settings.get("accumulated_llm_cost", 0.0)
        input_tokens = settings.get("total_input_tokens", 0)
        output_tokens = settings.get("total_output_tokens", 0)

        from app.services.security.secrets_service import SecretsService
        secrets_service = SecretsService()
        
        slack_creds = secrets_service.get_tenant_credentials(tenant.id, "slack")
        notion_creds = secrets_service.get_tenant_credentials(tenant.id, "notion")
        github_creds = secrets_service.get_tenant_credentials(tenant.id, "github")

        connected_integrations = []
        if slack_creds:
            connected_integrations.append("slack")
        if notion_creds:
            connected_integrations.append("notion")
        if github_creds:
            connected_integrations.append("github")

        return JSONResponse({
            "tenant_id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "plan": tenant.plan,
            "billing": {
                "accumulated_cost_usd": accumulated_cost,
                "total_input_tokens": input_tokens,
                "total_output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            "connected_integrations": connected_integrations,
        })

