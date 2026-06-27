"""Offline tests for the CRM/calendar executors (no network, no new deps)."""

import asyncio

import httpx

from app.services.executors import crm_calendar
from app.services.security.secrets_service import SecretsService

_TENANT = "11111111-1111-1111-1111-111111111111"


# ── fakes ────────────────────────────────────────────────────────────────
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Stub httpx.AsyncClient: records the POST, returns a canned payload."""

    posted = None

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        _FakeClient.posted = {"url": url, **kw}
        if "calendar" in url:
            return _FakeResponse({"id": "evt_1", "htmlLink": "http://cal/evt_1"})
        return _FakeResponse({"id": "contact_1"})


def _creds(token):
    return lambda self, tid, integ: ({"access_token": token} if token else {})


# ── needs_connection (no creds) ──────────────────────────────────────────
def test_calendar_needs_connection(monkeypatch):
    monkeypatch.setattr(SecretsService, "get_tenant_credentials", _creds(None))
    out = asyncio.run(crm_calendar.calendar_create_event(
        {"_tenant_id": _TENANT, "summary": "x", "start": "2026-01-01T10:00:00Z", "end": "2026-01-01T11:00:00Z"}
    ))
    assert out == {"status": "needs_connection", "provider": "google"}


def test_crm_needs_connection(monkeypatch):
    monkeypatch.setattr(SecretsService, "get_tenant_credentials", _creds(None))
    out = asyncio.run(crm_calendar.crm_upsert_contact(
        {"_tenant_id": _TENANT, "email": "a@b.com"}
    ))
    assert out == {"status": "needs_connection", "provider": "hubspot"}


# ── success path (creds present + stubbed HTTP) ───────────────────────────
def test_calendar_succeeds(monkeypatch):
    monkeypatch.setattr(SecretsService, "get_tenant_credentials", _creds("tok"))
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    out = asyncio.run(crm_calendar.calendar_create_event({
        "_tenant_id": _TENANT,
        "summary": "Sync",
        "start": "2026-01-01T10:00:00Z",
        "end": "2026-01-01T11:00:00Z",
        "attendees": ["a@b.com"],
    }))
    assert out["status"] == "succeeded"
    assert out["event_id"] == "evt_1"
    assert out["html_link"] == "http://cal/evt_1"
    # attendees were mapped into the body
    assert _FakeClient.posted["json"]["attendees"] == [{"email": "a@b.com"}]
    assert _FakeClient.posted["headers"]["Authorization"] == "Bearer tok"


def test_crm_succeeds(monkeypatch):
    monkeypatch.setattr(SecretsService, "get_tenant_credentials", _creds("tok"))
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    out = asyncio.run(crm_calendar.crm_upsert_contact({
        "_tenant_id": _TENANT,
        "email": "jane@acme.com",
        "firstname": "Jane",
    }))
    assert out["status"] == "succeeded"
    assert out["contact_id"] == "contact_1"
    assert out["email"] == "jane@acme.com"
    assert _FakeClient.posted["json"]["properties"] == {"email": "jane@acme.com", "firstname": "Jane"}


# ── missing required param ────────────────────────────────────────────────
def test_calendar_missing_required():
    out = asyncio.run(crm_calendar.calendar_create_event({"_tenant_id": _TENANT, "summary": "x"}))
    assert out["status"] == "error"
    assert "missing" in out["detail"]


def test_crm_missing_email():
    out = asyncio.run(crm_calendar.crm_upsert_contact({"_tenant_id": _TENANT}))
    assert out == {"status": "error", "detail": "missing email"}
