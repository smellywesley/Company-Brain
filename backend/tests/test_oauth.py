"""OAuth state-token CSRF + executor-provider callback credential mapping."""

import os

# Module reads SKILL_SIGNING_KEY at import for the state-token secret.
os.environ.setdefault("SKILL_SIGNING_KEY", "x" * 48)

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.routes import oauth


# ── state token (CSRF) ───────────────────────────────────────────────────────

def test_state_token_roundtrip():
    payload = oauth._verify_state_token(oauth._generate_state_token("tid", "uid"))
    assert payload["tenant_id"] == "tid" and payload["user_id"] == "uid"


def test_state_token_rejects_tampered():
    with pytest.raises(HTTPException):
        oauth._verify_state_token("not.a.valid.token")


# ── callback credential mapping (offline) ────────────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    """Stub httpx.AsyncClient that returns a fixed token payload."""
    payload = {"access_token": "AT", "refresh_token": "RT"}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return _FakeResp(self.payload)


def test_quickbooks_callback_saves_access_token_and_realm(monkeypatch):
    saved = {}
    monkeypatch.setattr(oauth.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(
        oauth.secrets_service, "save_tenant_credentials",
        lambda tenant_id, integration, credentials: saved.update(
            integration=integration, creds=credentials
        ),
    )
    state = oauth._generate_state_token(str(uuid4()), "user1")
    asyncio.run(oauth.oauth_callback("quickbooks", code="c", state=state, realm_id="9999"))

    assert saved["integration"] == "quickbooks"
    assert saved["creds"] == {"access_token": "AT", "refresh_token": "RT", "realm_id": "9999"}


def test_google_callback_saves_under_google(monkeypatch):
    saved = {}
    monkeypatch.setattr(oauth.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(
        oauth.secrets_service, "save_tenant_credentials",
        lambda tenant_id, integration, credentials: saved.update(integration=integration, creds=credentials),
    )
    state = oauth._generate_state_token(str(uuid4()), "user1")
    asyncio.run(oauth.oauth_callback("google", code="c", state=state))
    assert saved["integration"] == "google" and saved["creds"]["access_token"] == "AT"
