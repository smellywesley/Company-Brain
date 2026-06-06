import os
import time
import logging
from uuid import UUID
from typing import Any
import jwt
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.services.security.secrets_service import SecretsService

logger = logging.getLogger("company_brain.oauth")

router = APIRouter(prefix="/oauth", tags=["OAuth"])
secrets_service = SecretsService()

# ── Keys & Configs ──────────────────────────────────────────────────────────
STATE_JWT_SECRET = os.getenv("SKILL_SIGNING_KEY", "change-me-signing-key-minimum-32-chars")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

# OAuth credentials loaded from env
SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
NOTION_CLIENT_ID = os.getenv("NOTION_CLIENT_ID", "")
NOTION_CLIENT_SECRET = os.getenv("NOTION_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")


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
    tenant_id: str = Query(..., description="The ID of the active tenant"),
    user_id: str = Query(..., description="The ID of the requesting user")
):
    """Initiate OAuth connection flow by redirecting to provider auth page."""
    state = _generate_state_token(tenant_id, user_id)
    
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
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported OAuth source: {source}")

    return RedirectResponse(url=auth_url)


# ── OAuth Callback Endpoints ─────────────────────────────────────────────────

@router.get("/callback/{source}")
async def oauth_callback(
    source: str,
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query(..., description="Signed state token to prevent CSRF")
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
