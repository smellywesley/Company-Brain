"""
Tests for the quarantine reconciliation service and its RBAC grant.

Follows the suite's mocked-session pattern: no live Postgres or Redis. The
lock module's async accessors are monkeypatched; sessions are MagicMocks.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("sqlalchemy")

from app.middleware.rbac import RBACPolicy  # noqa: E402
from app.services.quarantine import service  # noqa: E402


def _scalars_result(rows):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    scalars.first.return_value = rows[0] if rows else None
    result.scalars.return_value = scalars
    return result


def _skill(name="Refund processing"):
    skill = MagicMock(id=uuid.uuid4(), status="active")
    skill.name = name  # `name` is a reserved MagicMock kwarg — set explicitly
    return skill


_LOCK = {"pr_ref": "PR #842", "summary": "OAuth2 replaced", "severity": "high"}


# ── list_active_locks ────────────────────────────────────────────────────────

async def test_list_returns_only_locked_skills(monkeypatch):
    locked_skill, free_skill = _skill("Locked"), _skill("Free")
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result([locked_skill, free_skill]))

    async def _get(tenant_id, skill_id):
        return _LOCK if skill_id == str(locked_skill.id) else None

    monkeypatch.setattr("app.services.quarantine.lock.get", _get)

    out = await service.list_active_locks(session, uuid.uuid4())
    assert len(out) == 1
    assert out[0]["skill_name"] == "Locked"
    assert out[0]["lock"]["pr_ref"] == "PR #842"


async def test_list_empty_when_nothing_locked(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result([_skill()]))
    monkeypatch.setattr("app.services.quarantine.lock.get", AsyncMock(return_value=None))
    assert await service.list_active_locks(session, uuid.uuid4()) == []


# ── release_lock ─────────────────────────────────────────────────────────────

async def test_release_dismiss_releases_and_reports(monkeypatch):
    skill = _skill()
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result([skill]))
    monkeypatch.setattr("app.services.quarantine.lock.get", AsyncMock(return_value=_LOCK))
    released = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.quarantine.lock.release", released)

    out = await service.release_lock(
        session, uuid.uuid4(), str(skill.id),
        resolution="dismiss", resolved_by="a@b.co", reason="title-only noise",
    )
    released.assert_awaited_once()
    assert out["resolution"] == "dismiss"
    assert out["released_lock"] == _LOCK
    assert out["resolved_by"] == "a@b.co"


async def test_release_rejects_unknown_resolution():
    with pytest.raises(ValueError):
        await service.release_lock(
            MagicMock(), uuid.uuid4(), "s1", resolution="yeet", resolved_by="x",
        )


async def test_release_404_for_foreign_tenant_skill(monkeypatch):
    """IDOR guard: a skill id outside the tenant must LookupError, not release."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result([]))  # scoped query finds nothing
    released = AsyncMock()
    monkeypatch.setattr("app.services.quarantine.lock.release", released)

    with pytest.raises(LookupError):
        await service.release_lock(
            session, uuid.uuid4(), str(uuid.uuid4()), resolution="dismiss", resolved_by="x",
        )
    released.assert_not_awaited()


async def test_release_404_when_no_lock(monkeypatch):
    skill = _skill()
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalars_result([skill]))
    monkeypatch.setattr("app.services.quarantine.lock.get", AsyncMock(return_value=None))

    with pytest.raises(LookupError):
        await service.release_lock(
            session, uuid.uuid4(), str(skill.id), resolution="accept", resolved_by="x",
        )


# ── RBAC grant ───────────────────────────────────────────────────────────────

def test_quarantine_release_rbac_matrix():
    """Managers and admins release quarantines; engineers and viewers cannot."""
    rbac = RBACPolicy()
    assert rbac.check_permission("admin", "approve_action", "quarantine") is True
    assert rbac.check_permission("manager", "approve_action", "quarantine") is True
    assert rbac.check_permission("engineer", "approve_action", "quarantine") is False
    assert rbac.check_permission("viewer", "approve_action", "quarantine") is False
