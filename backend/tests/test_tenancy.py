"""
Tenant resolution tests.

Multi-tenant isolation is security-critical: a request must resolve to exactly
the tenant named in its token, a bad claim must be rejected (not silently fall
through to another tenant), and a tokenless request must land on the default
tenant for dev/demo. These tests pin that contract.

Skipped if SQLAlchemy is not installed (local dev without full backend deps).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("sqlalchemy")

from fastapi import HTTPException  # noqa: E402

from app.db import tenancy  # noqa: E402


def _request_with_tenant(tenant_claim):
    req = MagicMock()
    req.state.user = MagicMock(tenant=tenant_claim, sub="u1")
    return req


def _request_no_user():
    req = MagicMock()
    req.state.user = None
    return req


def _result(scalar=None):
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    return r


@pytest.mark.asyncio
async def test_resolves_tenant_by_slug_claim():
    tenant = MagicMock(id=uuid.uuid4(), slug="acme", is_active=True)
    session = MagicMock()
    # _lookup: claim "acme" is not a UUID, so only the slug query runs.
    session.execute = AsyncMock(return_value=_result(scalar=tenant))

    req = _request_with_tenant("acme")
    resolved = await tenancy.resolve_tenant(req, session)
    assert resolved is tenant


@pytest.mark.asyncio
async def test_unknown_claim_raises_403_not_fallthrough():
    """A token naming a tenant that doesn't exist must 403 — never silently
    resolve to a different tenant."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=None))

    req = _request_with_tenant("ghost-tenant")
    with pytest.raises(HTTPException) as exc:
        await tenancy.resolve_tenant(req, session)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_inactive_tenant_rejected():
    tenant = MagicMock(id=uuid.uuid4(), slug="acme", is_active=False)
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=tenant))

    req = _request_with_tenant("acme")
    with pytest.raises(HTTPException) as exc:
        await tenancy.resolve_tenant(req, session)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_no_claim_uses_existing_default():
    default = MagicMock(id=uuid.uuid4(), slug="default", is_active=True)
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=default))
    session.add = MagicMock()
    session.flush = AsyncMock()

    req = _request_no_user()
    resolved = await tenancy.resolve_tenant(req, session)
    assert resolved is default
    session.add.assert_not_called()  # existing default reused, not recreated


@pytest.mark.asyncio
async def test_no_claim_creates_default_when_missing():
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(scalar=None))
    session.add = MagicMock()
    session.flush = AsyncMock()

    req = _request_no_user()
    resolved = await tenancy.resolve_tenant(req, session)
    assert resolved.slug == "default"
    session.add.assert_called_once()  # default lazily created
