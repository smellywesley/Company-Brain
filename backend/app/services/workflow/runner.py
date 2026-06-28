"""
Canonical governed-workflow runner.

This is the **single** implementation of Company Brain's governed action loop:

    match SOP (skill)  ->  WorkflowAgent (retrieve + propose)
                       ->  CriticAgent (risk / policy / PII / quarantine veto)
                       ->  human approval gate (status=pending_review when risky)
                       ->  persist a tamper-evident WorkflowRun

Both entry points use it so a scheduled run is governed *identically* to an
API-triggered one — there is no second, ungoverned path. Per docs/POSITIONING.md
(Governed Action pillar + governance acceptance test), nothing may execute an
action outside this loop.

Callers:
    * ``POST /workflow/{name}``           (app.main) — human/API trigger
    * ``tasks.execute_scheduled_workflow`` (app.worker) — Celery beat trigger
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def _get_llm():
    """Build an LLMAdapter from the environment (matches app.main._get_llm)."""
    from app.agents.llm_adapter import LLMAdapter

    return LLMAdapter(
        provider=os.getenv("LLM_PROVIDER", "gemini"),
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", ""),
    )


async def _match_skill(tenant_id: uuid.UUID, trigger_data: dict[str, Any]):
    """Return ``(definition, skill_id)`` of the best active SOP, or ``(None, None)``.

    Failures degrade gracefully to "no match" so a flaky DB/embedder never
    blocks a run — the run simply proceeds without an SOP injected, still fully
    critic-gated.
    """
    from app.db.database import get_db_session
    from app.db.repositories.skill_repo import SkillRepo
    from app.services.skills_generator.matcher import SkillMatcher

    try:
        async with get_db_session() as session:
            repo = SkillRepo(session)
            active_skills = await repo.list_active_for_tenant(tenant_id)
            if not active_skills:
                return None, None
            best = SkillMatcher().match_skill(trigger_data, list(active_skills))
            if best is not None:
                return best.definition, best.id
    except Exception:  # noqa: BLE001 — matching is best-effort, never fatal
        logger.exception("runner: skill match failed; proceeding unmatched")
    return None, None


async def _blocked_run(
    *,
    tenant_id: uuid.UUID,
    workflow_name: str,
    trigger_data: dict[str, Any],
    matched_skill_id: Any,
    reason: str,
    elapsed_ms: float,
    triggered_by: str,
    persist: bool,
    budget: float,
    spent: float,
) -> dict[str, Any]:
    """Return (and optionally persist) a run blocked before any LLM call.

    Used when the tenant's LLM budget is exhausted. The action is never built or
    executed; the run is recorded with status ``blocked`` for auditability.
    """
    run_id: str | None = None
    if persist:
        try:
            from app.db.database import get_db_session
            from app.db.models import WorkflowRun

            async with get_db_session() as session:
                run = WorkflowRun(
                    tenant_id=tenant_id,
                    workflow_name=workflow_name,
                    skill_id=matched_skill_id,
                    status="blocked",
                    trigger_data=trigger_data,
                    final_action=None,
                    critic_approved=False,
                    critic_risk_score=None,
                    critic_reasons=[reason],
                    steps_executed=[],
                    audit_trail=[{"event": "budget_block", "reason": reason}],
                    duration_ms=elapsed_ms,
                    llm_cost_usd=0.0,
                    triggered_by=triggered_by or "system",
                )
                session.add(run)
                await session.flush()
                run_id = str(run.id)
        except Exception:  # noqa: BLE001 — recording the block must not raise
            logger.exception("runner: failed to persist blocked run (non-fatal)")

    return {
        "workflow": workflow_name,
        "status": "blocked",
        "steps": [],
        "critic": {"approved": False, "risk_score": None, "reasons": [reason]},
        "final_action": None,
        "duration_ms": round(elapsed_ms, 1),
        "audit_trail": [{"event": "budget_block", "reason": reason}],
        "run_id": run_id,
    }


async def run_governed_workflow(
    *,
    tenant_id: uuid.UUID,
    tenant_settings: dict[str, Any] | None,
    workflow_name: str,
    trigger_data: dict[str, Any],
    config: dict[str, Any],
    triggered_by: str = "system",
    persist: bool = True,
) -> dict[str, Any]:
    """Execute one governed workflow and (optionally) persist the run.

    Args:
        tenant_id: the owning tenant (results are always tenant-scoped).
        tenant_settings: the tenant's settings dict (for learned critic rules);
            passed in rather than re-queried so this works from both the request
            path and the worker without holding an ORM object across sessions.
        workflow_name: the workflow / role action being run.
        trigger_data: the event that triggered the run.
        config: workflow configuration (e.g. ``context_queries``).
        triggered_by: provenance string for the audit trail (user email,
            ``"scheduler:<id>"``, ``"system"``).
        persist: write a WorkflowRun row (set False only in unit tests).

    Returns the API-shaped result dict (``workflow``, ``status``, ``steps``,
    ``critic``, ``final_action``, ``duration_ms``, ``audit_trail``, ``run_id``).
    """
    start = time.monotonic()
    tenant_settings = tenant_settings or {}

    # 1. Match the most relevant active SOP for this trigger.
    matched_def, matched_skill_id = await _match_skill(tenant_id, trigger_data)

    # 2. Inject tenant + skill identity into the context so the CriticAgent's
    #    quarantine veto (Contradiction Handshake) always engages — the gate is
    #    keyed on tenant_id + skill_id, and must not depend on the caller having
    #    remembered to pass them.
    enriched_config = {**config, "tenant_id": str(tenant_id)}
    if matched_skill_id is not None:
        enriched_config["skill_id"] = str(matched_skill_id)
    enriched_trigger = {**trigger_data, "tenant_id": str(tenant_id)}

    # 2b. Per-tenant LLM budget gate — block before spending on the agents.
    #     A blocked run is recorded (and audited) so the cap is observable.
    from app.services.budget import BudgetExceededError, enforce_budget

    try:
        await enforce_budget(str(tenant_id))
    except BudgetExceededError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.warning(
            "runner: workflow '%s' blocked — tenant %s over LLM budget", workflow_name, tenant_id
        )
        return await _blocked_run(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            trigger_data=trigger_data,
            matched_skill_id=matched_skill_id,
            reason="Monthly LLM budget reached for this workspace.",
            elapsed_ms=elapsed_ms,
            triggered_by=triggered_by,
            persist=persist,
            budget=exc.budget,
            spent=exc.spent,
        )

    # 3. Build the agents and run the governed pipeline.
    from app.agents.critic_agent import CriticAgent
    from app.agents.workflow_agent import WorkflowAgent
    from app.services.executors.registry import load_executors

    llm = _get_llm()
    critic = CriticAgent(llm=llm, tenant_rules=tenant_settings.get("critic_rules") or None)
    workflow = WorkflowAgent(
        llm=llm,
        critic=critic,
        workflow_name=workflow_name,
        action_executors=load_executors(),
    )

    try:
        result = await workflow.execute_workflow(
            workflow_config=enriched_config,
            trigger_data=enriched_trigger,
            matched_skill=matched_def,
        )
        llm_cost = llm.estimate_cost({})
    finally:
        await llm.close()

    elapsed_ms = (time.monotonic() - start) * 1000.0
    verdict = result.critic_verdict

    # 4. Persist a tamper-evident record of the run (non-fatal on failure).
    run_id: str | None = None
    if persist:
        try:
            from app.db.database import get_db_session
            from app.db.models import WorkflowRun

            async with get_db_session() as session:
                run = WorkflowRun(
                    tenant_id=tenant_id,
                    workflow_name=workflow_name,
                    skill_id=matched_skill_id,
                    status=result.status,
                    trigger_data=trigger_data,
                    candidate_action=result.final_action,
                    final_action=result.final_action,
                    critic_approved=verdict.approved if verdict else None,
                    critic_risk_score=verdict.risk_score if verdict else None,
                    critic_reasons=verdict.reasons if verdict else [],
                    steps_executed=[
                        {"name": s.name, "status": s.status} for s in result.steps_executed
                    ],
                    audit_trail=result.audit_trail,
                    duration_ms=elapsed_ms,
                    llm_cost_usd=llm_cost,
                    triggered_by=triggered_by or "system",
                )
                session.add(run)
                await session.flush()
                run_id = str(run.id)
        except Exception:  # noqa: BLE001 — persistence failure must not lose the result
            logger.exception("runner: failed to persist workflow run (non-fatal)")

    return {
        "workflow": result.workflow_name,
        "status": result.status,
        "steps": [{"name": s.name, "status": s.status} for s in result.steps_executed],
        "critic": {
            "approved": verdict.approved if verdict else None,
            "risk_score": verdict.risk_score if verdict else None,
            "reasons": verdict.reasons if verdict else [],
        },
        "final_action": result.final_action,
        "duration_ms": round(elapsed_ms, 1),
        "audit_trail": result.audit_trail,
        "run_id": run_id,
    }
