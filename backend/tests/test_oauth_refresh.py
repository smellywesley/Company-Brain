"""Refresh-on-401 behavior of executors' shared OAuth HTTP helper.

Offline — httpx.AsyncClient and SecretsService are stubbed; no real HTTP.
Covers the contract that matters: exactly one refresh + one retry on 401,
rotated credentials persisted, quickbooks realm_id preserved, and a failed
refresh returning the original 401 rather than looping.
"""

import asyncio

import httpx

from app.services.executors import oauth_http
from app.services.security.secrets_service import SecretsService

_TENANT = "11111111-1111-1111-1111-111111111111"


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _SeqClient:
    """AsyncClient stub that returns queued responses and records every POST."""

    queue: list = []
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        _SeqClient.calls.append({"url": url, **kw})
        return _SeqClient.queue.pop(0)


def _wire(monkeypatch, creds, queue):
    _SeqClient.queue = list(queue)
    _SeqClient.calls = []
    saved = {}
    monkeypatch.setattr(httpx, "AsyncClient", _SeqClient)
    monkeypatch.setattr(SecretsService, "get_tenant_credentials", lambda self, tid, integ: dict(creds))
    monkeypatch.setattr(
        SecretsService, "save_tenant_credentials",
        lambda self, tid, integ, c: saved.update({"integration": integ, "creds": c}),
    )
    return saved


def test_non_401_passes_through_without_refresh(monkeypatch):
    saved = _wire(monkeypatch, {"access_token": "tok"}, [_Resp(200, {"ok": True})])
    resp = asyncio.run(oauth_http.post_with_refresh(_TENANT, "google", "https://x/api", json={}))
    assert resp.status_code == 200
    assert len(_SeqClient.calls) == 1  # no refresh, no retry
    assert saved == {}  # nothing persisted


def test_401_triggers_one_refresh_and_one_retry(monkeypatch):
    saved = _wire(
        monkeypatch,
        {"access_token": "old", "refresh_token": "rt"},
        [
            _Resp(401),                               # original call
            _Resp(200, {"access_token": "new"}),      # token endpoint
            _Resp(200, {"ok": True}),                 # retried call
        ],
    )
    resp = asyncio.run(oauth_http.post_with_refresh(_TENANT, "google", "https://x/api", json={}))
    assert resp.status_code == 200
    assert len(_SeqClient.calls) == 3
    # refresh hit the provider token endpoint with grant_type=refresh_token
    assert _SeqClient.calls[1]["url"] == "https://oauth2.googleapis.com/token"
    assert _SeqClient.calls[1]["data"]["grant_type"] == "refresh_token"
    # retry used the NEW token
    assert _SeqClient.calls[2]["headers"]["Authorization"] == "Bearer new"
    # rotated creds persisted
    assert saved["creds"]["access_token"] == "new"
    # provider didn't rotate refresh_token -> old one kept
    assert saved["creds"]["refresh_token"] == "rt"


def test_quickbooks_realm_id_survives_refresh(monkeypatch):
    saved = _wire(
        monkeypatch,
        {"access_token": "old", "refresh_token": "rt", "realm_id": "realm-9"},
        [
            _Resp(401),
            _Resp(200, {"access_token": "new", "refresh_token": "rt2"}),
            _Resp(200, {"ok": True}),
        ],
    )
    resp = asyncio.run(oauth_http.post_with_refresh(_TENANT, "quickbooks", "https://x/api", json={}))
    assert resp.status_code == 200
    assert saved["creds"]["realm_id"] == "realm-9"       # preserved through merge
    assert saved["creds"]["refresh_token"] == "rt2"      # rotated token adopted
    # quickbooks refresh uses basic auth, not form client creds
    assert "auth" in _SeqClient.calls[1]


def test_failed_refresh_returns_original_401_without_looping(monkeypatch):
    saved = _wire(
        monkeypatch,
        {"access_token": "old", "refresh_token": "rt"},
        [
            _Resp(401),   # original call
            _Resp(401),   # refresh itself rejected
        ],
    )
    resp = asyncio.run(oauth_http.post_with_refresh(_TENANT, "hubspot", "https://x/api", json={}))
    assert resp.status_code == 401
    assert len(_SeqClient.calls) == 2  # no retry, no loop
    assert saved == {}  # failed refresh persists nothing


def test_no_refresh_token_returns_401_immediately(monkeypatch):
    _wire(monkeypatch, {"access_token": "old"}, [_Resp(401)])
    resp = asyncio.run(oauth_http.post_with_refresh(_TENANT, "google", "https://x/api", json={}))
    assert resp.status_code == 401
    assert len(_SeqClient.calls) == 1  # no token-endpoint call without a refresh_token
