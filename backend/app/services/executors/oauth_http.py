"""Shared refresh-on-401 helper for executor providers (Google, HubSpot, QBO).

Closes the gap flagged in app/routes/oauth.py (~line 261): refresh_token was
stored on OAuth callback but never used. One helper, reused by every executor
call site, instead of four separate retry patches — see crm_calendar.py and
accounting.py.

ponytail: refresh failure just returns the failed response (no retry loop, no
backoff). Add backoff/jitter here if a provider's refresh endpoint starts
flaking under load.
"""

from __future__ import annotations

import os
from uuid import UUID

import httpx

from app.services.security.secrets_service import SecretsService

_TOKEN_URLS = {
    "google": "https://oauth2.googleapis.com/token",
    "hubspot": "https://api.hubapi.com/oauth/v1/token",
    "quickbooks": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
}

# Same env vars app/routes/oauth.py reads for these providers — reused, not duplicated.
_CLIENT_CREDS = {
    "google": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "hubspot": ("HUBSPOT_CLIENT_ID", "HUBSPOT_CLIENT_SECRET"),
    "quickbooks": ("QUICKBOOKS_CLIENT_ID", "QUICKBOOKS_CLIENT_SECRET"),
}


async def _refresh(tenant_id: str, provider: str, creds: dict) -> dict | None:
    """Exchange the stored refresh_token for a new access_token.

    Returns the new merged credentials dict on success, or None on failure.
    """
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        return None

    client_id_env, client_secret_env = _CLIENT_CREDS[provider]
    client_id = os.getenv(client_id_env, "")
    client_secret = os.getenv(client_secret_env, "")

    async with httpx.AsyncClient(timeout=15.0) as client:
        if provider == "quickbooks":
            resp = await client.post(
                _TOKEN_URLS[provider],
                headers={"Accept": "application/json"},
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                auth=(client_id, client_secret),
            )
        else:
            resp = await client.post(
                _TOKEN_URLS[provider],
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )

    if resp.status_code >= 400:
        return None

    data = resp.json()
    new_creds = dict(creds)
    new_creds["access_token"] = data.get("access_token")
    # Not every provider rotates the refresh_token on each refresh — keep the
    # old one unless the provider issued a new one.
    if data.get("refresh_token"):
        new_creds["refresh_token"] = data["refresh_token"]
    if "expires_in" in data:
        new_creds["expires_in"] = data["expires_in"]
    # realm_id (quickbooks) isn't returned by the refresh response — dict(creds) above preserves it.
    return new_creds


async def post_with_refresh(
    tenant_id: str,
    provider: str,
    url: str,
    *,
    json: dict,
    headers: dict | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """POST with the stored bearer token; on 401, refresh once and retry once."""
    secrets = SecretsService()
    creds = secrets.get_tenant_credentials(UUID(tenant_id), provider) or {}
    req_headers = dict(headers or {})
    req_headers["Authorization"] = f"Bearer {creds.get('access_token')}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=req_headers, json=json)

    if resp.status_code != 401:
        return resp

    new_creds = await _refresh(tenant_id, provider, creds)
    if new_creds is None:
        # Refresh failed (or no refresh_token available) — return the original
        # 401 as-is rather than looping.
        return resp

    secrets.save_tenant_credentials(UUID(tenant_id), provider, new_creds)
    req_headers["Authorization"] = f"Bearer {new_creds.get('access_token')}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=req_headers, json=json)
    return resp
