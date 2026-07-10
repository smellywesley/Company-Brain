"""
CRM + calendar executors (final mile of the Governed Action loop).

These run ONLY after the CriticAgent approves (docs/POSITIONING.md, Governed
Action pillar). They do not re-check policy — they just do the deed and return a
structured status. Per-tenant creds come from SecretsService; a missing token
returns ``needs_connection`` rather than fabricating a success.

Providers: Google Calendar ("google"), HubSpot CRM ("hubspot"). Plain httpx —
no vendor SDKs. ponytail: no retries/backoff; one timed call per action. Add
backoff here if a provider's 429s start hurting.
"""

from __future__ import annotations

from uuid import UUID

import httpx

from app.services.executors.oauth_http import post_with_refresh
from app.services.executors.registry import ExecutorRegistry
from app.services.security.secrets_service import SecretsService

_TIMEOUT = 30.0


def _access_token(tenant_id: str, provider: str) -> str | None:
    creds = SecretsService().get_tenant_credentials(UUID(tenant_id), provider)
    return (creds or {}).get("access_token")


@ExecutorRegistry.register("calendar_create_event")
async def calendar_create_event(params: dict) -> dict:
    """Create a Google Calendar event."""
    for field in ("summary", "start", "end"):
        if not params.get(field):
            return {"status": "error", "detail": f"missing {field}"}

    token = _access_token(params["_tenant_id"], "google")
    if not token:
        return {"status": "needs_connection", "provider": "google"}

    calendar_id = params.get("calendar_id") or "primary"
    body: dict = {
        "summary": params["summary"],
        "start": {"dateTime": params["start"]},
        "end": {"dateTime": params["end"]},
    }
    if params.get("description"):
        body["description"] = params["description"]
    if params.get("attendees"):
        body["attendees"] = [{"email": e} for e in params["attendees"]]

    try:
        resp = await post_with_refresh(
            params["_tenant_id"],
            "google",
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        return {"status": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}

    return {
        "status": "succeeded",
        "event_id": data.get("id"),
        "html_link": data.get("htmlLink"),
    }


@ExecutorRegistry.register("crm_upsert_contact")
async def crm_upsert_contact(params: dict) -> dict:
    """Create/update a HubSpot contact."""
    if not params.get("email"):
        return {"status": "error", "detail": "missing email"}

    token = _access_token(params["_tenant_id"], "hubspot")
    if not token:
        return {"status": "needs_connection", "provider": "hubspot"}

    properties = {"email": params["email"]}
    for field in ("firstname", "lastname", "company", "phone"):
        if params.get(field):
            properties[field] = params[field]

    try:
        resp = await post_with_refresh(
            params["_tenant_id"],
            "hubspot",
            "https://api.hubapi.com/crm/v3/objects/contacts",
            json={"properties": properties},
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        return {"status": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}

    return {
        "status": "succeeded",
        "contact_id": data.get("id"),
        "email": params["email"],
    }
