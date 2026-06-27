import os
import time
import logging
from urllib.parse import quote
from uuid import UUID
from typing import Any
import jwt
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.services.security.secrets_service import SecretsService
from app.db.database import get_db_session
from app.db.tenancy import resolve_tenant

logger = logging.getLogger("company_brain.oauth")

router = APIRouter(prefix="/oauth", tags=["OAuth"])
secrets_service = SecretsService()

# ── Keys & Configs ──────────────────────────────────────────────────────────
from app.services.security.secret_config import require_secret

# Fail closed in production: a guessable signing key lets an attacker forge the
# OAuth state token (CSRF) and amplifies tenant/credential injection.
STATE_JWT_SECRET = require_secret("SKILL_SIGNING_KEY", min_length=32)
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

# OAuth credentials loaded from env
SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
NOTION_CLIENT_ID = os.getenv("NOTION_CLIENT_ID", "")
NOTION_CLIENT_SECRET = os.getenv("NOTION_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
# Executor providers (Google Calendar, HubSpot CRM, QuickBooks accounting). The
# provider key MUST match what the executors read in services/executors/*.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
HUBSPOT_CLIENT_ID = os.getenv("HUBSPOT_CLIENT_ID", "")
HUBSPOT_CLIENT_SECRET = os.getenv("HUBSPOT_CLIENT_SECRET", "")
QBO_CLIENT_ID = os.getenv("QUICKBOOKS_CLIENT_ID", "")
QBO_CLIENT_SECRET = os.getenv("QUICKBOOKS_CLIENT_SECRET", "")


def _generate_state_token(tenant_id: str, user_id: str) -> str:
    """Generate a signed state token containing tenant and user metadata."""
    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "exp": int(time.time()) + 600  # Token valid for 10 minutes
    }
    return jwt.encode(payload, STATE_JWT_SECRET, algorithm="HS256")


def _verify_state_token(token: str) -> dict[str, Any]:
    """Verify state token signature and return decoded payload."""
    try:
        return jwt.decode(token, STATE_JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="State token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid state token")


# ── OAuth Ingress Endpoints ──────────────────────────────────────────────────

@router.get("/connect/{source}")
async def oauth_connect(
    source: str,
    request: Request,
):
    """Initiate OAuth connection flow by redirecting to provider auth page.

    Tenant and user identity are derived from the authenticated session — never
    from client-supplied query params — so a caller cannot bind a provider's
    credentials to another tenant (IDOR).
    """
    user = getattr(request.state, "user", None)
    user_sub = getattr(user, "sub", None) if user is not None else None
    if not user_sub:
        raise HTTPException(status_code=401, detail="Authentication required")

    async with get_db_session() as session:
        tenant = await resolve_tenant(request, session)

    state = _generate_state_token(str(tenant.id), str(user_sub))

    redirect_uri = f"{os.getenv('BACKEND_URL', 'http://localhost:8000')}/oauth/callback/{source}"

    if source == "slack":
        # Slack OAuth v2 flow
        if not SLACK_CLIENT_ID:
            raise HTTPException(status_code=500, detail="Slack client ID not configured")
        scope = "channels:read,channels:history,groups:read,groups:history,chat:write"
        auth_url = (
            f"https://slack.com/oauth/v2/authorize"
            f"?client_id={SLACK_CLIENT_ID}"
            f"&scope={scope}"
            f"&state={state}"
            f"&redirect_uri={redirect_uri}"
        )
    elif source == "notion":
        # Notion OAuth
        if not NOTION_CLIENT_ID:
            raise HTTPException(status_code=500, detail="Notion client ID not configured")
        auth_url = (
            f"https://api.notion.com/v1/oauth/authorize"
            f"?client_id={NOTION_CLIENT_ID}"
            f"&response_type=code"
            f"&owner=user"
            f"&state={state}"
            f"&redirect_uri={redirect_uri}"
        )
    elif source == "github":
        # GitHub OAuth
        if not GITHUB_CLIENT_ID:
            raise HTTPException(status_code=500, detail="GitHub client ID not configured")
        scope = "repo,read:org"
        auth_url = (
            f"https://github.com/login/oauth/authorize"
            f"?client_id={GITHUB_CLIENT_ID}"
            f"&scope={scope}"
            f"&state={state}"
            f"&redirect_uri={redirect_uri}"
        )
    elif source == "google":
        if not GOOGLE_CLIENT_ID:
            raise HTTPException(status_code=500, detail="Google client ID not configured")
        scope = quote("https://www.googleapis.com/auth/calendar.events", safe="")
        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={GOOGLE_CLIENT_ID}"
            "&response_type=code&access_type=offline&prompt=consent"
            f"&scope={scope}&state={state}&redirect_uri={redirect_uri}"
        )
    elif source == "hubspot":
        if not HUBSPOT_CLIENT_ID:
            raise HTTPException(status_code=500, detail="HubSpot client ID not configured")
        scope = quote("crm.objects.contacts.write", safe="")
        auth_url = (
            "https://app.hubspot.com/oauth/authorize"
            f"?client_id={HUBSPOT_CLIENT_ID}"
            f"&scope={scope}&state={state}&redirect_uri={redirect_uri}"
        )
    elif source == "quickbooks":
        if not QBO_CLIENT_ID:
            raise HTTPException(status_code=500, detail="QuickBooks client ID not configured")
        scope = quote("com.intuit.quickbooks.accounting", safe="")
        auth_url = (
            "https://appcenter.intuit.com/connect/oauth2"
            f"?client_id={QBO_CLIENT_ID}&response_type=code"
            f"&scope={scope}&state={state}&redirect_uri={redirect_uri}"
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported OAuth source: {source}")

    return RedirectResponse(url=auth_url)


# ── OAuth Callback Endpoints ─────────────────────────────────────────────────

@router.get("/callback/{source}")
async def oauth_callback(
    source: str,
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query(..., description="Signed state token to prevent CSRF"),
    realm_id: str | None = Query(None, alias="realmId", description="QuickBooks company id"),
):
    """Receive authorization code, exchange for tokens, and store securely."""
    # 1. Verify CSRF state token and extract tenant info
    payload = _verify_state_token(state)
    tenant_id_str = payload["tenant_id"]
    tenant_uuid = UUID(tenant_id_str)
    
    redirect_uri = f"{os.getenv('BACKEND_URL', 'http://localhost:8000')}/oauth/callback/{source}"
    credentials = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            if source == "slack":
                # Exchange Slack authorization code
                resp = await client.post(
                    "https://slack.com/api/oauth.v2.access",
                    data={
                        "client_id": SLACK_CLIENT_ID,
                        "client_secret": SLACK_CLIENT_SECRET,
                        "code": code,
                        "redirect_uri": redirect_uri
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok"):
                    raise HTTPException(status_code=400, detail=f"Slack OAuth error: {data.get('error')}")
                
                credentials = {
                    "access_token": data.get("access_token"),
                    "bot_user_id": data.get("bot_user_id"),
                    "team_id": data.get("team", {}).get("id"),
                    "team_name": data.get("team", {}).get("name")
                }

            elif source == "notion":
                # Exchange Notion authorization code
                resp = await client.post(
                    "https://api.notion.com/v1/oauth/token",
                    json={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri
                    },
                    auth=(NOTION_CLIENT_ID, NOTION_CLIENT_SECRET)
                )
                resp.raise_for_status()
                data = resp.json()
                
                credentials = {
                    "access_token": data.get("access_token"),
                    "workspace_id": data.get("workspace_id"),
                    "workspace_name": data.get("workspace_name"),
                    "bot_id": data.get("bot_id")
                }

            elif source == "github":
                # Exchange GitHub authorization code
                resp = await client.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": GITHUB_CLIENT_ID,
                        "client_secret": GITHUB_CLIENT_SECRET,
                        "code": code,
                        "redirect_uri": redirect_uri
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise HTTPException(status_code=400, detail=f"GitHub OAuth error: {data.get('error_description')}")
                
                credentials = {
                    "access_token": data.get("access_token"),
                    "scope": data.get("scope"),
                    "token_type": data.get("token_type")
                }
            
            elif source == "google":
                resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": GOOGLE_CLIENT_ID,
                        "client_secret": GOOGLE_CLIENT_SECRET,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": redirect_uri,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                # ponytail: refresh_token stored but refresh-on-401 not wired yet;
                # add it when live tokens start expiring mid-action.
                credentials = {
                    "access_token": data.get("access_token"),
                    "refresh_token": data.get("refresh_token"),
                    "expires_in": data.get("expires_in"),
                }

            elif source == "hubspot":
                resp = await client.post(
                    "https://api.hubapi.com/oauth/v1/token",
                    data={
                        "grant_type": "authorization_code",
                        "client_id": HUBSPOT_CLIENT_ID,
                        "client_secret": HUBSPOT_CLIENT_SECRET,
                        "redirect_uri": redirect_uri,
                        "code": code,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                credentials = {
                    "access_token": data.get("access_token"),
                    "refresh_token": data.get("refresh_token"),
                    "expires_in": data.get("expires_in"),
                }

            elif source == "quickbooks":
                resp = await client.post(
                    "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
                    headers={"Accept": "application/json"},
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                    auth=(QBO_CLIENT_ID, QBO_CLIENT_SECRET),
                )
                resp.raise_for_status()
                data = resp.json()
                # realm_id (QuickBooks company id) arrives as the realmId query
                # param on the callback — the executors require it.
                credentials = {
                    "access_token": data.get("access_token"),
                    "refresh_token": data.get("refresh_token"),
                    "realm_id": realm_id,
                }

            else:
                raise HTTPException(status_code=400, detail=f"Unsupported OAuth callback source: {source}")

        except httpx.HTTPError as exc:
            logger.error("HTTP error during OAuth token exchange for %s: %s", source, exc)
            raise HTTPException(status_code=502, detail=f"Failed to exchange token with provider: {exc}")

    # 2. Save credentials in Secrets Manager (or local fallback)
    secrets_service.save_tenant_credentials(tenant_uuid, source, credentials)
    logger.info("Successfully saved OAuth credentials for tenant %s integration %s", tenant_id_str, source)

    # 3. Redirect back to frontend page
    return RedirectResponse(
        url=f"{FRONTEND_ORIGIN}/connectors?status=success&source={source}"
    )
