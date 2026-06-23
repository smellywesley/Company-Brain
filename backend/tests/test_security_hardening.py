"""
Regression tests for the production security hardening.

Each test pins a fix that closed a Critical/High finding so it can't silently
regress. These run with no live infrastructure (mocks + injected collaborators).
The live cross-tenant search test lives in test_integration_tenant_isolation.py.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("sqlalchemy")


# ── C4/C5 — fail-closed secrets (secret_config) ──────────────────────────────

from app.services.security import secret_config  # noqa: E402


def test_require_secret_raises_in_prod_when_missing(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SOME_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        secret_config.require_secret("SOME_SECRET", min_length=32)


def test_require_secret_rejects_known_placeholder_in_prod(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SOME_SECRET", "change-me-in-production")
    with pytest.raises(RuntimeError):
        secret_config.require_secret("SOME_SECRET", min_length=16)


def test_require_secret_accepts_strong_value_in_prod(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    strong = "a" * 40
    monkeypatch.setenv("SOME_SECRET", strong)
    assert secret_config.require_secret("SOME_SECRET", min_length=32) == strong


def test_require_secret_uses_ephemeral_in_dev(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("SOME_SECRET", raising=False)
    val = secret_config.require_secret("SOME_SECRET", min_length=32)
    assert val and len(val) >= 32  # ephemeral, app still runs in dev


def test_is_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert secret_config.is_production() is True
    monkeypatch.setenv("ENVIRONMENT", "local")
    assert secret_config.is_production() is False


# ── H3 — rate limiter: ignore spoofable X-Forwarded-For ──────────────────────

from app.middleware.rate_limiter import RateLimiterMiddleware  # noqa: E402


def _req(user=None, peer="9.9.9.9", xff=""):
    req = MagicMock()
    req.state.user = user
    req.client.host = peer
    req.headers.get.return_value = xff
    return req


def test_rate_limit_key_prefers_authenticated_user():
    req = _req(user=SimpleNamespace(sub="u1"), xff="1.1.1.1")
    assert RateLimiterMiddleware._client_id(req) == "user:u1"


def test_rate_limit_ignores_xff_without_trusted_proxy(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
    req = _req(user=None, peer="9.9.9.9", xff="1.1.1.1")  # attacker-supplied XFF
    assert RateLimiterMiddleware._client_id(req) == "ip:9.9.9.9"


def test_rate_limit_uses_trusted_proxy_entry(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    # XFF = "<spoofed>, <real client added by the trusted edge>"
    req = _req(user=None, peer="10.0.0.1", xff="1.1.1.1, 2.2.2.2")
    assert RateLimiterMiddleware._client_id(req) == "ip:2.2.2.2"


# ── C1/C2 — tenant-scoped vector store ───────────────────────────────────────

from ingestion.embedding_pipeline import WeaviateStore  # noqa: E402
from app.services.security.tenant_isolation import TenantIsolatedWeaviateStore  # noqa: E402


def test_search_fails_closed_without_tenant():
    store = WeaviateStore()
    store._client = MagicMock()  # connected, but tenant is empty
    assert store.search(query_vector=[0.1, 0.2], tenant_id="") == []
    store._client.collections.get.assert_not_called()  # never queried


def test_isolated_store_forces_tenant_on_upsert():
    base = MagicMock()
    wrapper = TenantIsolatedWeaviateStore(base)
    chunk = SimpleNamespace(tenant_id="attacker-tenant")
    wrapper.upsert("real-tenant", [chunk])
    assert chunk.tenant_id == "real-tenant"  # overridden, can't write cross-tenant
    base.upsert_chunks.assert_called_once_with([chunk])


def test_isolated_store_search_delegates_with_tenant():
    base = MagicMock()
    base.search.return_value = []
    TenantIsolatedWeaviateStore(base).search("t1", [0.1], limit=5)
    base.search.assert_called_once_with(query_vector=[0.1], tenant_id="t1", limit=5)


# ── H4 — tenantless tokens rejected in production ────────────────────────────

from app.db import tenancy  # noqa: E402
from fastapi import HTTPException  # noqa: E402


@pytest.mark.asyncio
async def test_no_claim_rejected_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    req = MagicMock()
    req.state.user = None
    with pytest.raises(HTTPException) as exc:
        await tenancy.resolve_tenant(req, session)
    assert exc.value.status_code == 403


# ── H1/H5 — observe pipeline: injection scan + quarantine fail-closed ─────────

from app.services.observe.pipeline import observe  # noqa: E402

_PAYLOAD = {"data": "Acme deployed Refunds to Production. The team updated the Policy."}


@pytest.mark.asyncio
async def test_observe_rejects_prompt_injection():
    async def mal_scan(_text):
        return SimpleNamespace(is_malicious=True, reason="ignore previous instructions")

    result = await observe(
        tenant_id="t1", source_platform="slack", industry_vertical="ops",
        raw_payload=_PAYLOAD, scan=mal_scan,
    )
    assert result["rejected_reason"] == "prompt_injection"
    assert result["extracted_triplets"] == []


@pytest.mark.asyncio
async def test_observe_fails_closed_when_scanner_errors():
    async def boom_scan(_text):
        raise RuntimeError("scanner down")

    result = await observe(
        tenant_id="t1", source_platform="slack", industry_vertical="ops",
        raw_payload=_PAYLOAD, scan=boom_scan,
    )
    assert result["rejected_reason"] == "prompt_injection"


@pytest.mark.asyncio
async def test_observe_proceeds_on_clean_scan():
    async def clean_scan(_text):
        return SimpleNamespace(is_malicious=False, reason="ok")

    result = await observe(
        tenant_id="t1", source_platform="slack", industry_vertical="ops",
        raw_payload=_PAYLOAD, scan=clean_scan,
    )
    assert "rejected_reason" not in result
    assert len(result["extracted_triplets"]) > 0


@pytest.mark.asyncio
async def test_quarantine_fails_closed_in_prod_when_redis_down(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")

    def boom_get(_tenant, _skill):
        raise RuntimeError("redis down")

    result = await observe(
        tenant_id="t1", source_platform="slack", industry_vertical="ops",
        raw_payload=_PAYLOAD, skill_id="s1", quarantine_get=boom_get,
    )
    assert result["quarantine_locked"] is True
    assert result["has_contradiction"] is True


@pytest.mark.asyncio
async def test_quarantine_fails_open_in_dev_when_redis_down(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")

    def boom_get(_tenant, _skill):
        raise RuntimeError("redis down")

    result = await observe(
        tenant_id="t1", source_platform="slack", industry_vertical="ops",
        raw_payload=_PAYLOAD, skill_id="s1", quarantine_get=boom_get,
    )
    assert result["quarantine_locked"] is False  # dev convenience: proceed
