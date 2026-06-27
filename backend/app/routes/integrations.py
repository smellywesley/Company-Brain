"""Manual-credential connect endpoints.

Lets a tenant paste an access token for an integration without standing up a
full OAuth app. Complements the OAuth flow in app.routes.oauth — the executors
and connectors read the same SecretsService creds either way.

Security (mirrors oauth.py): this is a secret-writing trust boundary. Tenant is
ALWAYS derived from the authenticated session via resolve_tenant — never from
client input — so a caller cannot bind credentials to another tenant (IDOR).
Provider is validated against an allowlist so an attacker cannot inject an
arbitrary secret name. Credential VALUES are never logged.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.middleware.rbac import RBACPolicy
from app.services.security.secrets_service import SecretsService
from app.db.database import get_db_session
from app.db.tenancy import resolve_tenant

logger = logging.getLogger("company_brain.integrations")

router = APIRouter(prefix="/integrations", tags=["Integrations"])

# RBACPolicy is stateless policy config (loads a YAML allowlist); instantiating
# it here is equivalent to the shared instance in main.py.
rbac = RBACPolicy()
secrets_service = SecretsService()

# Providers a tenant may store manual credentials for. Must match the provider
# keys the OAuth flow and executors use (app.routes.oauth, services/executors/*).
# Gating on this prevents arbitrary secret-name injection.
PROVIDER_ALLOWLIST = {"slack", "notion", "github", "google", "hubspot", "quickbooks", "zendesk"}


def connected_providers(creds_by_provider: dict[str, dict]) -> list[str]:
    """Providers whose stored creds are non-empty, sorted. Pure — no DB/auth."""
    return sorted(p for p, creds in creds_by_provider.items() if creds)


class CredentialsBody(BaseModel):
    """Free-form credential blob (e.g. {"access_token": "..."}); at least one key."""
    credentials: dict[str, Any] = Field(..., min_length=1)


@router.post("/{provider}/credentials")
async def save_credentials(
    provider: str,
    body: CredentialsBody,
    request: Request,
    _: None = Depends(rbac.require_permission("write", "connectors")),
):
    """Store manually-supplied credentials for an integration (tenant-scoped)."""
    if provider not in PROVIDER_ALLOWLIST:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)

    # Never log credential values.
    secrets_service.save_tenant_credentials(tenant.id, provider, body.credentials)
    logger.info("Saved manual credentials for tenant %s integration %s", tenant.id, provider)

    return {"status": "saved", "provider": provider}


@router.get("")
async def list_integrations(
    request: Request,
    _: None = Depends(rbac.require_permission("read", "connectors")),
):
    """Which allowlisted integrations the tenant has connected, and what's available."""
    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)

    creds_by_provider = {
        p: secrets_service.get_tenant_credentials(tenant.id, p) for p in PROVIDER_ALLOWLIST
    }
    return {
        "connected": connected_providers(creds_by_provider),
        "available": sorted(PROVIDER_ALLOWLIST),
    }
