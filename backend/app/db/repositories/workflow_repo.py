"""
Workflow Repository.

Read-side data access for WorkflowRun rows that powers the dashboard:
active workflows, critic verdicts, knowledge stats, and the activity feed.
Every method is tenant-scoped — callers pass the resolved tenant_id and the
repo never returns another tenant's rows.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FeedbackRecord, Skill, WorkflowRun

logger = logging.getLogger(__name__)


class WorkflowRepo:
    """Repository for reading WorkflowRun data for the dashboard."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        status: str | None = None,
        limit: int = 20,
    ) -> Sequence[WorkflowRun]:
        """Return recent workflow runs for a tenant, newest first.

        Optional ``status`` filter (e.g. ``"pending_review"`` for the approval
        queue).
        """
        stmt = select(WorkflowRun).where(WorkflowRun.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(WorkflowRun.status == status)
        stmt = stmt.order_by(WorkflowRun.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def recent_with_verdicts(
        self,
        tenant_id: uuid.UUID,
        limit: int = 10,
    ) -> Sequence[WorkflowRun]:
        """Return recent runs that carry a critic verdict (risk score set)."""
        stmt = (
            select(WorkflowRun)
            .where(
                WorkflowRun.tenant_id == tenant_id,
                WorkflowRun.critic_risk_score.is_not(None),
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def counts_for_tenant(self, tenant_id: uuid.UUID) -> dict[str, int]:
        """Return aggregate counts used by the Knowledge Stats card."""

        async def _count(stmt) -> int:
            result = await self.session.execute(stmt)
            return int(result.scalar() or 0)

        total_runs = await _count(
            select(func.count(WorkflowRun.id)).where(WorkflowRun.tenant_id == tenant_id)
        )
        pending = await _count(
            select(func.count(WorkflowRun.id)).where(
                WorkflowRun.tenant_id == tenant_id,
                WorkflowRun.status == "pending_review",
            )
        )
        total_feedback = await _count(
            select(func.count(FeedbackRecord.id)).where(FeedbackRecord.tenant_id == tenant_id)
        )
        total_skills = await _count(
            select(func.count(Skill.id)).where(Skill.tenant_id == tenant_id)
        )
        active_skills = await _count(
            select(func.count(Skill.id)).where(
                Skill.tenant_id == tenant_id,
                Skill.status == "active",
            )
        )

        return {
            "total_workflow_runs": total_runs,
            "pending_review": pending,
            "total_feedback": total_feedback,
            "total_skills": total_skills,
            "active_skills": active_skills,
        }

    async def recent_activity(
        self,
        tenant_id: uuid.UUID,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Return recent runs shaped as activity-feed items."""
        runs = await self.list_for_tenant(tenant_id, limit=limit)
        items: list[dict[str, Any]] = []
        for run in runs:
            items.append(
                {
                    "id": str(run.id),
                    "type": _activity_type(run.status),
                    "title": f"{run.workflow_name.replace('_', ' ')} — {run.status.replace('_', ' ')}",
                    "description": _verdict_description(run),
                    "timestamp": run.created_at.isoformat() if run.created_at else None,
                }
            )
        return items


# ── Shaping helpers (shared by routes) ───────────────────────────────────────

def risk_level(score: float | None) -> str:
    """Map a 0-1 critic risk score to a label."""
    if score is None:
        return "unknown"
    if score < 0.3:
        return "low"
    if score < 0.7:
        return "medium"
    return "high"


def verdict_label(status: str) -> str:
    """Map a workflow status to the dashboard verdict vocabulary."""
    return {
        "completed": "approved",
        "pending_review": "needs-review",
        "rejected": "rejected",
        "error": "rejected",
    }.get(status, "needs-review")


def _activity_type(status: str) -> str:
    return {
        "completed": "workflow",
        "pending_review": "feedback",
        "rejected": "system",
        "error": "system",
    }.get(status, "workflow")


def _verdict_description(run: WorkflowRun) -> str:
    reasons = run.critic_reasons or []
    if reasons:
        return str(reasons[0])
    if run.critic_risk_score is not None:
        return f"Risk score {round(run.critic_risk_score * 100)}"
    return "Workflow event"
