"""
Feedback loop orchestration tests.

The feedback loop is the product's core differentiator — human corrections
re-synthesize skills and calibrate the CriticAgent so the same mistake is
caught next time. These tests verify the control flow of
``FeedbackProcessor.process_new_feedback`` with mocked dependencies, so a
regression in the orchestration (e.g. the calibrator silently never firing,
which was a real bug) is caught without needing a live database.

Skipped automatically if SQLAlchemy is not installed (local dev without the
full backend deps); runs in CI where requirements.txt is installed.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("sqlalchemy")

from app.services.feedback_loop.processor import FeedbackProcessor  # noqa: E402


def _make_result(scalar=None, scalars_all=None):
    """Build a mock SQLAlchemy Result supporting scalar_one_or_none / scalars().all()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars = MagicMock()
    scalars.all.return_value = scalars_all or []
    result.scalars.return_value = scalars
    return result


def _make_processor(session, *, anomalous=False, quorum_met=True, updated_def=True):
    proc = FeedbackProcessor(
        db_session=session,
        updater=AsyncMock(),
        anomaly_detector=AsyncMock(),
        quorum_engine=AsyncMock(),
        calibrator=AsyncMock(),
    )
    proc.anomaly_detector.is_anomalous = AsyncMock(return_value=anomalous)
    quorum_status = MagicMock(is_met=quorum_met)
    proc.quorum_engine.check_quorum = AsyncMock(return_value=quorum_status)
    proc.quorum_engine.mark_quorum_processed = AsyncMock()
    proc.updater.update_skill = AsyncMock(
        return_value=(MagicMock(model_dump=lambda: {"name": "x"}) if updated_def else None)
    )
    proc.calibrator.calibrate_from_feedback = AsyncMock(return_value=True)
    # Replace the repo built in __init__ with a mock.
    proc.repo = MagicMock()
    proc.repo.get_by_id = AsyncMock()
    proc.repo.update_skill_definition = AsyncMock()
    return proc


@pytest.mark.asyncio
async def test_happy_path_resynthesizes_and_calibrates():
    """Quorum met + actionable feedback → skill updated AND critic calibrated."""
    tenant_id = uuid.uuid4()
    skill_id = uuid.uuid4()
    feedback_id = uuid.uuid4()

    record = MagicMock(skill_id=skill_id, submitted_by="a@x.com", reason="missed the limit", corrected_output=None)
    pending = [record]
    skill = MagicMock(id=skill_id, slug="refund")
    tenant_obj = MagicMock(id=tenant_id)

    session = MagicMock()
    # execute() is called: (1) fetch record, (2) fetch pending, (3) fetch tenant
    session.execute = AsyncMock(side_effect=[
        _make_result(scalar=record),
        _make_result(scalars_all=pending),
        _make_result(scalar=tenant_obj),
    ])

    proc = _make_processor(session)
    proc.repo.get_by_id = AsyncMock(return_value=skill)

    result = await proc.process_new_feedback(tenant_id, feedback_id)

    assert result is True
    proc.updater.update_skill.assert_awaited_once()
    proc.repo.update_skill_definition.assert_awaited_once()
    proc.calibrator.calibrate_from_feedback.assert_awaited_once()
    proc.quorum_engine.mark_quorum_processed.assert_awaited_once()


@pytest.mark.asyncio
async def test_anomalous_feedback_is_quarantined():
    """Poisoning attempt → nothing is re-synthesized."""
    tenant_id, feedback_id = uuid.uuid4(), uuid.uuid4()
    record = MagicMock(skill_id=uuid.uuid4(), submitted_by="bad@x.com")
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_make_result(scalar=record)])

    proc = _make_processor(session, anomalous=True)

    result = await proc.process_new_feedback(tenant_id, feedback_id)

    assert result is False
    proc.updater.update_skill.assert_not_awaited()
    proc.calibrator.calibrate_from_feedback.assert_not_awaited()


@pytest.mark.asyncio
async def test_quorum_not_met_waits():
    """Below quorum → wait for more humans, do not alter the skill."""
    tenant_id, feedback_id = uuid.uuid4(), uuid.uuid4()
    skill_id = uuid.uuid4()
    record = MagicMock(skill_id=skill_id, submitted_by="a@x.com")
    skill = MagicMock(id=skill_id, slug="refund")

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_make_result(scalar=record)])

    proc = _make_processor(session, quorum_met=False)
    proc.repo.get_by_id = AsyncMock(return_value=skill)

    result = await proc.process_new_feedback(tenant_id, feedback_id)

    assert result is False
    proc.updater.update_skill.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_skill_returns_false():
    """Feedback with no associated skill → nothing to do."""
    tenant_id, feedback_id = uuid.uuid4(), uuid.uuid4()
    record = MagicMock(skill_id=None)
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_make_result(scalar=record)])

    proc = _make_processor(session)

    result = await proc.process_new_feedback(tenant_id, feedback_id)
    assert result is False
