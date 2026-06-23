"""
Tenant resolution for multi-tenant isolation.

Every authenticated request is scoped to exactly one tenant. The tenant is
derived from a custom claim in the user's OIDC token (``tenant_id`` / ``tenant``
/ ``org_id`` / ``org``), surfaced on ``request.state.user.tenant`` by the auth
middleware.

Security contract:
    - If the token carries a tenant claim, it MUST resolve to an existing
      tenant. A claim that does not resolve raises 403 — never a silent
      fall-through to a different tenant (that would be a cross-tenant
      escalation).
    - If there is NO claim at all (local dev / single-tenant demo, or auth
      bypassed), fall back to a single ``default`` tenant, auto-creating it on
      first use. This keeps the demo working without an OIDC provider.

This is the one place tenant identity is decided. Endpoints call
``resolve_tenant(request, session)`` and filter every query by the returned
``tenant.id``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Tenant

logger = logging.getLogger("company_brain.tenancy")

_DEFAULT_SLUG = "default"


async def resolve_tenant(request: Request, session: AsyncSession) -> Tenant:
    """Return the Tenant ORM object for the current request.

    Raises 403 if the token names a tenant that does not exist.
    """
    user = getattr(request.state, "user", None)
    claim: Optional[str] = getattr(user, "tenant", None) if user is not None else None

    if claim:
        tenant = await _lookup(session, claim)
        if tenant is None:
            logger.warning(
                "Token tenant claim '%s' did not resolve to any tenant (user=%s)",
                claim,
                getattr(user, "sub", "unknown"),
            )
            raise HTTPException(
                status_code=403,
                detail="Token is not associated with a known tenant",
            )
        if not tenant.is_active:
            raise HTTPException(status_code=403, detail="Tenant is inactive")
        return tenant

    # No claim. In production a tokenless/tenantless request must NOT silently
    # land in a shared "default" tenant — that mixes orgs. Fail closed instead.
    # The lazy "default" tenant is for local dev / single-tenant demo only.
    from app.services.security.secret_config import is_production

    if is_production():
        logger.warning(
            "Request has no tenant claim in production (user=%s); refusing rather "
            "than falling back to the shared default tenant",
            getattr(user, "sub", "unknown"),
        )
        raise HTTPException(
            status_code=403,
            detail="Token is not associated with a tenant",
        )

    return await _get_or_create_default(session)


async def _lookup(session: AsyncSession, claim: str) -> Optional[Tenant]:
    """Resolve a claim that may be a UUID (tenant id) or a slug."""
    try:
        tenant_uuid = uuid.UUID(claim)
    except (ValueError, AttributeError):
        tenant_uuid = None

    if tenant_uuid is not None:
        result = await session.execute(select(Tenant).where(Tenant.id == tenant_uuid))
        tenant = result.scalar_one_or_none()
        if tenant is not None:
            return tenant

    result = await session.execute(select(Tenant).where(Tenant.slug == claim))
    return result.scalar_one_or_none()


async def _get_or_create_default(session: AsyncSession) -> Tenant:
    result = await session.execute(select(Tenant).where(Tenant.slug == _DEFAULT_SLUG))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name="Default", slug=_DEFAULT_SLUG)
        session.add(tenant)
        await session.flush()
        logger.info("Created default tenant for single-tenant/dev mode")
    return tenant
