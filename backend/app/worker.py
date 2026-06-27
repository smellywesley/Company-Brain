"""
Celery background worker configuration and tasks.

Handles long-running asynchronous operations:
- Ingestion processing (vector embedding)
- Skill discovery (clustering & LLM synthesis)
- Knowledge Graph population
"""

import asyncio
import json
import logging
import os
import uuid

from celery import Celery

logger = logging.getLogger(__name__)

# Cap on how many active skills a single merged PR is checked against, so a
# tenant with a huge skill library can't turn one webhook into an unbounded
# fan-out of LLM calls. Anything beyond this is logged, never silently dropped.
_MAX_SKILLS_PER_HANDSHAKE = 25
# Cap files/patch pulled per PR so a giant PR can't blow up memory or the LLM
# context. Tier 0 only needs paths + a representative slice of the patch.
_MAX_PR_FILES = 300
_MAX_PATCH_CHARS = 60_000


async def _fetch_pr_changes(pr: dict) -> tuple[list[str], str]:
    """Fetch a merged PR's changed file paths and patch text from GitHub.

    Degrades to ``([], "")`` on any failure (no token, network error, no URL)
    so the handshake falls back to title+body rather than crashing. The Tier 0
    detector treats an empty diff as "unknown" and lets the LLM decide.
    """
    import httpx

    token = os.getenv("GITHUB_TOKEN", "")
    files_url = (pr.get("url") or "").rstrip("/")
    if not token or not files_url:
        return [], ""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    paths: list[str] = []
    patch_parts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            resp = await client.get(f"{files_url}/files", params={"per_page": 100})
            resp.raise_for_status()
            for f in resp.json()[:_MAX_PR_FILES]:
                if f.get("filename"):
                    paths.append(f["filename"])
                if f.get("patch"):
                    patch_parts.append(f"--- {f['filename']}\n{f['patch']}")
    except Exception as exc:  # noqa: BLE001 — detection is best-effort
        logger.warning("Tier 0: could not fetch PR changes (%s) — falling back", exc)
        return [], ""
    return paths, "\n".join(patch_parts)[:_MAX_PATCH_CHARS]


async def _run_contradiction_handshake(session, tenant_id_str: str, pr: dict) -> int:
    """Contradiction Handshake: compare a merged PR against active SOPs.

    For each active skill, ask the ContradictionSynthesizer whether the PR's
    stated changes contradict the SOP. On a real contradiction, place a
    quarantine lock so the CriticAgent vetoes any autonomous action on that
    skill until a human resolves it. Returns the number of skills quarantined.
    """
    from sqlalchemy import select
    from app.db.models import Skill
    from app.agents.llm_adapter import LLMAdapter
    from app.services.contradiction.synthesizer import ContradictionSynthesizer
    from app.services.contradiction import detector
    from app.services.quarantine import lock as quarantine

    pr_number = pr.get("number")
    pr_ref = f"PR #{pr_number}"
    # Tier 0 needs the actual change, not just the title. The webhook does not
    # carry file diffs, so fetch them; degrade to title+body if unavailable.
    changed_paths, patch_text = await _fetch_pr_changes(pr)
    changed_summary = (
        f"\n\nChanged files: {', '.join(changed_paths)}" if changed_paths else ""
    )
    new_reality = (
        f"{pr_ref}: {pr.get('title', '')}\n\n{pr.get('body', '') or ''}"
        f"{changed_summary}\n\n{patch_text[:8000]}"
    )

    result = await session.execute(
        select(Skill).where(
            Skill.tenant_id == uuid.UUID(tenant_id_str),
            Skill.status == "active",
        )
    )
    skills = result.scalars().all()
    if not skills:
        return 0
    if len(skills) > _MAX_SKILLS_PER_HANDSHAKE:
        logger.warning(
            "Contradiction handshake: %d active skills for tenant %s, checking first %d (capped)",
            len(skills), tenant_id_str, _MAX_SKILLS_PER_HANDSHAKE,
        )
        skills = skills[:_MAX_SKILLS_PER_HANDSHAKE]

    llm = LLMAdapter(
        provider=os.getenv("LLM_PROVIDER", "gemini"),
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", ""),
        temperature=0.0,
    )
    synthesizer = ContradictionSynthesizer(llm)
    locked = 0
    try:
        for skill in skills:
            sop_text = json.dumps(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "definition": skill.definition,
                },
                default=str,
            )
            # Tier 0 gate: skip the expensive LLM unless the PR structurally
            # touches something this SOP references. When we have no diff
            # (fetch failed), fall through to the LLM rather than miss a real
            # conflict.
            if changed_paths or patch_text:
                tier0 = detector.detect(changed_paths, patch_text, sop_text)
                if not tier0["has_structural_overlap"]:
                    continue

            report = await synthesizer.synthesize(
                new_reality=new_reality,
                stale_artifact=sop_text,
                skill_id=str(skill.id),
                tenant_id=tenant_id_str,
            )
            if report.get("no_contradiction") or not report.get("conflicts"):
                continue
            # Store every conflict summary, not just the first.
            summary = " | ".join(
                c.get("summary", "Contradiction detected.")
                for c in report["conflicts"]
            )
            quarantine.acquire_sync(
                tenant_id_str,
                str(skill.id),
                pr_ref=pr_ref,
                summary=summary,
                severity=report.get("severity", "high"),
            )
            locked += 1
    finally:
        await llm.close()

    logger.info("Contradiction handshake for %s: %d skill(s) quarantined", pr_ref, locked)
    return locked

# Initialize Celery app
redis_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
celery_app = Celery("company_brain", broker=redis_url, backend=redis_url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
)

# ── Celery beat: recurring-workflow scheduler ────────────────────────────────
# A single lightweight tick runs every 60s and fans out *governed* workflow
# runs for any tenant schedule that is due (see app.services.scheduler). The
# tick itself does almost no work — it only finds due schedules and enqueues a
# child task — so it is safe to run frequently. Per-tenant cadence lives in
# tenant.settings, so this static beat entry supports arbitrary dynamic
# schedules without RedBeat/django-celery-beat. Run with a SINGLE beat process
# (the `beat` service in docker-compose / a dedicated Railway service); workers
# may scale freely.
_SCHEDULER_TICK_SECONDS = float(os.getenv("SCHEDULER_TICK_SECONDS", "60"))
celery_app.conf.beat_schedule = {
    "scheduler-tick": {
        "task": "tasks.scheduler_tick",
        "schedule": _SCHEDULER_TICK_SECONDS,
    },
}


def _run_async(coro):
    """Helper to run async code inside a sync Celery task."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="tasks.process_ingestion_batch")
def process_ingestion_batch(self, tenant_id_str: str, documents: list[dict]):
    """Process a batch of ingested documents: embed and upsert to vector/graph stores."""
    logger.info("Celery: Processing ingestion batch of %d docs for tenant %s", len(documents), tenant_id_str)
    
    async def _do_process():
        # 1. Init DB
        from app.db.database import get_db_session
        from app.services.knowledge_graph.entity_extractor import EntityExtractor
        from app.services.knowledge_graph.neo4j_store import Neo4jStore
        from app.services.knowledge_graph.ingestion_hook import KnowledgeGraphIngestionHook
        from app.agents.llm_adapter import LLMAdapter
        
        # 2. Extract and upsert to Knowledge Graph
        try:
            kg_store = Neo4jStore()
            kg_store.connect()
            llm = LLMAdapter(provider="gemini", api_key=os.getenv("LLM_API_KEY", ""))
            extractor = EntityExtractor(llm=llm)
            hook = KnowledgeGraphIngestionHook(extractor=extractor, neo4j_store=kg_store)
            
            entities_created = await hook.process_documents(tenant_id_str, documents)
            logger.info("Celery: KG hook created %d entities.", entities_created)
        except Exception as exc:
            logger.error("Celery: KG processing failed: %s", exc)
        finally:
            kg_store.close()

        # Note: Vector embedding upsert would go here using TenantIsolatedWeaviateStore

    return _run_async(_do_process())


@celery_app.task(bind=True, name="tasks.trigger_skill_discovery")
def trigger_skill_discovery(self, tenant_id_str: str, documents: list[dict]):
    """Run the skill discovery pipeline on a new batch of documents."""
    logger.info("Celery: Running skill discovery for tenant %s", tenant_id_str)
    
    async def _do_discovery():
        from app.db.database import get_db_session
        from app.services.skills_generator.manager import SkillManager
        from app.services.skills_generator.synthesizer import SkillSynthesizer
        from app.services.skills_generator.pattern_detector import PatternDetector
        from app.services.security.prompt_injection import AdversarialDetector
        
        async with get_db_session() as session:
            manager = SkillManager(
                db_session=session,
                synthesizer=SkillSynthesizer(),
                pattern_detector=PatternDetector(),
                adversarial_detector=AdversarialDetector()
            )
            
            skills_gen = await manager.run_discovery_pipeline(
                tenant_id=uuid.UUID(tenant_id_str), 
                documents=documents
            )
            return skills_gen

    skills_count = _run_async(_do_discovery())
    logger.info("Celery: Discovered %d new skills.", skills_count)
    return skills_count


# ── Webhook processing tasks (Sprint 2) ──────────────────────────────────────

@celery_app.task(bind=True, name="tasks.process_slack_webhook_event")
def process_slack_webhook_event(self, event_data: dict):
    """Asynchronously process a single incoming Slack webhook event."""
    logger.info("Celery: Processing Slack event %s", event_data.get("event_id", ""))
    
    async def _do_process():
        from app.db.database import get_db_session
        from app.db.models import Tenant
        from sqlalchemy import select
        from ingestion.slack_connector import SlackConnector
        from app.services.knowledge_graph.entity_extractor import EntityExtractor
        from app.services.knowledge_graph.neo4j_store import Neo4jStore
        from app.services.knowledge_graph.ingestion_hook import KnowledgeGraphIngestionHook
        from app.agents.llm_adapter import LLMAdapter
        import os
        
        # 1. Resolve Tenant from Slack team_id
        team_id = event_data.get("team_id")
        if not team_id:
            logger.error("Slack event missing team_id")
            return
            
        async with get_db_session() as session:
            stmt = select(Tenant)
            result = await session.execute(stmt)
            tenants = result.scalars().all()
            
            target_tenant = None
            for tenant in tenants:
                slack_settings = tenant.settings.get("slack", {})
                if slack_settings.get("team_id") == team_id:
                    target_tenant = tenant
                    break
                    
            if not target_tenant:
                if len(tenants) == 1:
                    target_tenant = tenants[0]
                else:
                    logger.error("Could not map Slack team_id %s to any tenant", team_id)
                    return
            
            tenant_id_str = str(target_tenant.id)
            
            # 2. Normalize raw event
            event = event_data.get("event", {})
            if event.get("type") != "message":
                logger.info("Ignoring non-message Slack event type: %s", event.get("type"))
                return
                
            raw_item = {
                "text": event.get("text", ""),
                "user": event.get("user", "unknown"),
                "ts": event.get("ts", ""),
                "_channel_id": event.get("channel", ""),
                "_channel_name": "live_channel",
                "thread_ts": event.get("thread_ts"),
                "reactions": event.get("reactions", []),
                "subtype": event.get("subtype")
            }
            
            connector = SlackConnector()
            normalized_doc = connector.normalize(raw_item)
            
            doc_dict = {
                "source": normalized_doc.source,
                "id": normalized_doc.id,
                "author": normalized_doc.author,
                "timestamp": normalized_doc.timestamp,
                "content": normalized_doc.content,
                "doc_type": normalized_doc.doc_type,
                "sensitivity_level": normalized_doc.sensitivity_level,
                "metadata": normalized_doc.metadata
            }
            
            # 3. Process into Knowledge Graph (Neo4j)
            try:
                kg_store = Neo4jStore()
                kg_store.connect()
                llm = LLMAdapter(provider="gemini", api_key=os.getenv("LLM_API_KEY", ""))
                extractor = EntityExtractor(llm=llm)
                hook = KnowledgeGraphIngestionHook(extractor=extractor, neo4j_store=kg_store)
                
                await hook.process_documents(tenant_id_str, [doc_dict])
            except Exception as exc:
                logger.error("Celery webhook KG hook failed: %s", exc)
            finally:
                kg_store.close()
                
    return _run_async(_do_process())


@celery_app.task(bind=True, name="tasks.process_github_webhook_event")
def process_github_webhook_event(self, x_github_event: str, event_data: dict):
    """Asynchronously process a single incoming GitHub webhook event."""
    logger.info("Celery: Processing GitHub event type %s", x_github_event)
    
    async def _do_process():
        from app.db.database import get_db_session
        from app.db.models import Tenant
        from sqlalchemy import select
        from ingestion.github_connector import GitHubConnector
        from app.services.knowledge_graph.entity_extractor import EntityExtractor
        from app.services.knowledge_graph.neo4j_store import Neo4jStore
        from app.services.knowledge_graph.ingestion_hook import KnowledgeGraphIngestionHook
        from app.agents.llm_adapter import LLMAdapter
        import os
        
        # 1. Resolve Tenant from repository owner
        repo = event_data.get("repository", {})
        owner = repo.get("owner", {}).get("login")
        if not owner:
            logger.error("GitHub webhook event missing repository owner")
            return
            
        async with get_db_session() as session:
            stmt = select(Tenant)
            result = await session.execute(stmt)
            tenants = result.scalars().all()
            
            target_tenant = None
            for tenant in tenants:
                github_settings = tenant.settings.get("github", {})
                if github_settings.get("owner") == owner:
                    target_tenant = tenant
                    break
                    
            if not target_tenant:
                if len(tenants) == 1:
                    target_tenant = tenants[0]
                else:
                    logger.error("Could not map GitHub owner %s to any tenant", owner)
                    return
                    
            tenant_id_str = str(target_tenant.id)
            
            # 2. Normalize GitHub Event
            connector = GitHubConnector()
            normalized_doc = None
            if x_github_event == "issues":
                issue = event_data.get("issue", {})
                normalized_doc = connector.normalize({
                    "_type": "issue",
                    "id": issue.get("id"),
                    "title": issue.get("title", ""),
                    "body": issue.get("body", ""),
                    "user": {"login": issue.get("user", {}).get("login", "unknown")},
                    "created_at": issue.get("created_at", ""),
                    "html_url": issue.get("html_url", "")
                })
            elif x_github_event == "pull_request":
                pr = event_data.get("pull_request", {})
                normalized_doc = connector.normalize({
                    "_type": "pr",
                    "id": pr.get("id"),
                    "title": pr.get("title", ""),
                    "body": pr.get("body", ""),
                    "user": {"login": pr.get("user", {}).get("login", "unknown")},
                    "created_at": pr.get("created_at", ""),
                    "html_url": pr.get("html_url", "")
                })
                
            if not normalized_doc:
                logger.info("GitHub event type %s normalization not implemented for webhook, ignoring", x_github_event)
                return
                
            doc_dict = {
                "source": normalized_doc.source,
                "id": normalized_doc.id,
                "author": normalized_doc.author,
                "timestamp": normalized_doc.timestamp,
                "content": normalized_doc.content,
                "doc_type": normalized_doc.doc_type,
                "sensitivity_level": normalized_doc.sensitivity_level,
                "metadata": normalized_doc.metadata
            }
            
            # 3. Process into Knowledge Graph (Neo4j)
            try:
                kg_store = Neo4jStore()
                kg_store.connect()
                llm = LLMAdapter(provider="gemini", api_key=os.getenv("LLM_API_KEY", ""))
                extractor = EntityExtractor(llm=llm)
                hook = KnowledgeGraphIngestionHook(extractor=extractor, neo4j_store=kg_store)
                
                await hook.process_documents(tenant_id_str, [doc_dict])
            except Exception as exc:
                logger.error("Celery webhook GitHub hook failed: %s", exc)
            finally:
                kg_store.close()

            # 4. Contradiction Handshake — only on *merged* pull requests.
            if x_github_event == "pull_request":
                pr = event_data.get("pull_request", {})
                if event_data.get("action") == "closed" and pr.get("merged"):
                    try:
                        await _run_contradiction_handshake(session, tenant_id_str, pr)
                    except Exception as exc:
                        logger.error("Contradiction handshake failed: %s", exc)

    return _run_async(_do_process())


# ── Feedback loop (skill re-synthesis + critic calibration) ──────────────────

@celery_app.task(bind=True, name="tasks.process_feedback")
def process_feedback(self, tenant_id_str: str, feedback_id_str: str):
    """Run the human-feedback loop for a single feedback record.

    Checks for anomalous (poisoning) behavior, evaluates quorum, and — once met —
    re-synthesizes the affected skill and calibrates the tenant's CriticAgent so
    the same mistake is caught next time. Runs async in the worker so the HTTP
    feedback endpoint stays fast.
    """
    logger.info("Celery: Processing feedback %s for tenant %s", feedback_id_str, tenant_id_str)

    async def _do_process():
        from app.db.database import get_db_session
        from app.agents.llm_adapter import LLMAdapter
        from app.services.feedback_loop.anomaly_detector import AnomalyDetector
        from app.services.feedback_loop.calibrator import CriticCalibrator
        from app.services.feedback_loop.processor import FeedbackProcessor
        from app.services.feedback_loop.quorum import QuorumEngine
        from app.services.feedback_loop.updater import SkillUpdater

        llm = LLMAdapter(
            provider=os.getenv("LLM_PROVIDER", "gemini"),
            api_key=os.getenv("LLM_API_KEY", ""),
            model=os.getenv("LLM_MODEL", ""),
        )
        try:
            async with get_db_session() as session:
                processor = FeedbackProcessor(
                    db_session=session,
                    updater=SkillUpdater(llm=llm),
                    anomaly_detector=AnomalyDetector(session=session),
                    quorum_engine=QuorumEngine(session=session),
                    calibrator=CriticCalibrator(db_session=session, llm=llm),
                )
                resynthesized = await processor.process_new_feedback(
                    tenant_id=uuid.UUID(tenant_id_str),
                    feedback_id=uuid.UUID(feedback_id_str),
                )
            logger.info(
                "Celery: Feedback %s processed (skill re-synthesized=%s)",
                feedback_id_str, resynthesized,
            )
            return resynthesized
        finally:
            await llm.close()

    return _run_async(_do_process())


@celery_app.task(bind=True, name="tasks.accumulate_llm_cost")
def accumulate_llm_cost(self, tenant_id_str: str, cost: float, input_tokens: int, output_tokens: int):
    """Accumulate LLM token usage and estimated cost for a tenant."""
    logger.info("Celery: Accumulating LLM cost of %f USD for tenant %s", cost, tenant_id_str)
    
    async def _do_accumulate():
        from app.db.database import get_db_session
        from app.db.models import Tenant
        from uuid import UUID
        from sqlalchemy.orm.attributes import flag_modified
        
        tenant_uuid = UUID(tenant_id_str)
        async with get_db_session() as session:
            tenant = await session.get(Tenant, tenant_uuid)
            if not tenant:
                logger.error("Tenant %s not found for cost accumulation", tenant_id_str)
                return
                
            if tenant.settings is None:
                tenant.settings = {}
                
            tenant.settings["accumulated_llm_cost"] = round(
                tenant.settings.get("accumulated_llm_cost", 0.0) + cost, 6
            )
            tenant.settings["total_input_tokens"] = (
                tenant.settings.get("total_input_tokens", 0) + input_tokens
            )
            tenant.settings["total_output_tokens"] = (
                tenant.settings.get("total_output_tokens", 0) + output_tokens
            )
            
            flag_modified(tenant, "settings")
            logger.info(
                "Tenant %s accumulated cost updated to %f USD",
                tenant_id_str, tenant.settings["accumulated_llm_cost"]
            )

    return _run_async(_do_accumulate())


# ── Scheduler (Celery beat) ──────────────────────────────────────────────────

@celery_app.task(bind=True, name="tasks.scheduler_tick")
def scheduler_tick(self):
    """Beat-driven tick: enqueue a governed run for every due tenant schedule.

    Scans active tenants, finds schedules in ``tenant.settings["schedules"]``
    that are due, enqueues ``tasks.execute_scheduled_workflow`` for each, and
    stamps ``last_run_at`` so the same slot is not fired twice. The heavy work
    (agents, critic, persistence) happens in the child task; this stays cheap.

    ``last_run_at`` is advanced at enqueue time on purpose: if a child run fails
    it is recorded as an errored WorkflowRun and retried on the next cadence,
    rather than re-fired every 60s.
    """
    async def _do_tick():
        from datetime import datetime, timezone
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified
        from app.db.database import get_db_session
        from app.db.models import Tenant
        from app.services.scheduler.schedules import due_schedules

        enqueued = 0
        now = datetime.now(timezone.utc)
        async with get_db_session() as session:
            result = await session.execute(select(Tenant).where(Tenant.is_active.is_(True)))
            tenants = result.scalars().all()
            for tenant in tenants:
                settings = tenant.settings or {}
                schedules = settings.get("schedules") or []
                if not schedules:
                    continue
                due = due_schedules(schedules, now=now)
                if not due:
                    continue
                for sched in due:
                    try:
                        celery_app.send_task(
                            "tasks.execute_scheduled_workflow",
                            args=[str(tenant.id), sched],
                            queue="default",
                        )
                        # Mutate in place so the write-back persists the stamp.
                        sched["last_run_at"] = now.isoformat()
                        sched["last_status"] = "enqueued"
                        enqueued += 1
                    except Exception:
                        logger.exception(
                            "scheduler_tick: failed to enqueue schedule %s for tenant %s",
                            sched.get("id"), tenant.id,
                        )
                settings["schedules"] = schedules
                tenant.settings = settings
                flag_modified(tenant, "settings")
        if enqueued:
            logger.info("scheduler_tick: enqueued %d due workflow run(s)", enqueued)
        return enqueued

    return _run_async(_do_tick())


@celery_app.task(bind=True, name="tasks.execute_scheduled_workflow")
def execute_scheduled_workflow(self, tenant_id_str: str, schedule: dict):
    """Run one scheduled workflow through the **governed** loop.

    Delegates to the shared runner so a scheduled run is critic-gated,
    approval-gated, and audited exactly like an API-triggered one — there is no
    ungoverned scheduled path (docs/POSITIONING.md, Governed Action pillar).
    """
    schedule = schedule or {}
    sched_id = schedule.get("id") or schedule.get("name") or "schedule"
    workflow_name = schedule.get("workflow") or "scheduled"
    logger.info(
        "Celery: executing scheduled workflow '%s' (%s) for tenant %s",
        workflow_name, sched_id, tenant_id_str,
    )

    async def _do_run():
        from app.db.database import get_db_session
        from app.db.models import Tenant
        from app.services.workflow.runner import run_governed_workflow

        tenant_uuid = uuid.UUID(tenant_id_str)
        async with get_db_session() as session:
            tenant = await session.get(Tenant, tenant_uuid)
            if tenant is None:
                logger.error("scheduled workflow: tenant %s not found", tenant_id_str)
                return None
            tenant_settings = dict(tenant.settings or {})

        summary = schedule.get("name") or workflow_name
        trigger_data = {
            "summary": summary,
            "scheduled": True,
            "schedule_id": schedule.get("id"),
            **(schedule.get("trigger_data") or {}),
        }
        config = {
            "context_queries": schedule.get("context_queries") or [summary],
            **(schedule.get("config") or {}),
        }
        result = await run_governed_workflow(
            tenant_id=tenant_uuid,
            tenant_settings=tenant_settings,
            workflow_name=workflow_name,
            trigger_data=trigger_data,
            config=config,
            triggered_by=f"scheduler:{sched_id}",
        )
        logger.info(
            "Scheduled workflow '%s' for tenant %s -> %s (run %s)",
            workflow_name, tenant_id_str, result.get("status"), result.get("run_id"),
        )
        return result.get("status")

    return _run_async(_do_run())
