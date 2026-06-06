"""
Dashboard read-endpoint tests.

Covers WorkflowRepo (the data access behind /workflows, /verdicts, /stats,
/activity) and the pure shaping helpers. Uses the established mocked-session
pattern (no live Postgres needed) and is guarded by importorskip so it skips
cleanly on machines without SQLAlchemy installed.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("sqlalchemy")

from app.db.repositories.workflow_repo import (  # noqa: E402
    WorkflowRepo,
    risk_level,
    verdict_label,
)


def _scalars_result(rows):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


def _scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _run(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        workflow_name="refund_automation",
        status="completed",
        critic_approved=True,
        critic_risk_score=0.2,
        critic_reasons=["within policy"],
        final_action={},
        trigger_data={},
        created_at=None,
    )
    defaults.update(kw)
    return MagicMock(**defaults)


# ── Pure helpers ─────────────────────────────────────────────────────────────

def test_risk_level_buckets():
    assert risk_level(None) == "unknown"
    assert risk_level(0.0) == "low"
    assert risk_level(0.29) == "low"
    assert risk_level(0.3) == "medium"
    assert risk_level(0.69) == "medium"
    assert risk_level(0.7) == "high"
    assert risk_level(0.95) == "high"


def test_verdict_label_mapping():
    assert verdict_label("completed") == "approved"
    assert verdict_label("pending_review") == "needs-review"
    assert verdict_label("rejected") == "rejected"
    assert verdict_label("error") == "rejected"
    assert verdict_label("anything_else") == "needs-review"


def test_status_for_feedback_transitions():
    """Approving/rejecting must move a run out of the review queue; escalate keeps it."""
    main = pytest.importorskip("app.main")  # skips if app deps unavailable
    assert main.status_for_feedback("approve") == "completed"
    assert main.status_for_feedback("modify") == "completed"
    assert main.status_for_feedback("reject") == "rejected"
    # escalate stays pending (needs higher sign-off); unknown is a no-op.
    assert main.status_for_feedback("escalate") is None
    assert main.status_for_feedback("unknown") is None


# ── WorkflowRepo ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_for_tenant_returns_rows():
    runs = [_run(), _run(status="pending_review")]
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result(runs))

    repo = WorkflowRepo(session)
    out = await repo.list_for_tenant(uuid.uuid4(), limit=5)

    assert list(out) == runs
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_recent_with_verdicts_returns_rows():
    runs = [_run(critic_risk_score=0.8, status="rejected")]
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result(runs))

    repo = WorkflowRepo(session)
    out = await repo.recent_with_verdicts(uuid.uuid4(), limit=5)

    assert list(out) == runs


@pytest.mark.asyncio
async def test_counts_for_tenant_shape():
    # counts_for_tenant runs 5 count() queries in order:
    # total_runs, pending, total_feedback, total_skills, active_skills
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[
        _scalar_result(10),
        _scalar_result(3),
        _scalar_result(7),
        _scalar_result(4),
        _scalar_result(2),
    ])

    repo = WorkflowRepo(session)
    counts = await repo.counts_for_tenant(uuid.uuid4())

    assert counts == {
        "total_workflow_runs": 10,
        "pending_review": 3,
        "total_feedback": 7,
        "total_skills": 4,
        "active_skills": 2,
    }


@pytest.mark.asyncio
async def test_recent_activity_maps_runs():
    runs = [_run(workflow_name="ticket_escalation", status="pending_review",
                 critic_reasons=["needs manager sign-off"])]
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result(runs))

    repo = WorkflowRepo(session)
    items = await repo.recent_activity(uuid.uuid4(), limit=5)

    assert len(items) == 1
    item = items[0]
    assert set(item.keys()) == {"id", "type", "title", "description", "timestamp"}
    assert "ticket escalation" in item["title"]
    assert item["description"] == "needs manager sign-off"
