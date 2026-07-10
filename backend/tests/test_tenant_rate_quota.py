"""Per-tenant request-rate quota (the aggregate bucket above per-user limits).

Exercises RateLimiterMiddleware.dispatch directly with mocked requests, the
same offline style as test_security_hardening.py. Unique tenant/user ids per
test keep the module-level in-memory store from bleeding state across tests.
"""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.middleware import rate_limiter
from app.middleware.rate_limiter import RateLimiterMiddleware


def _req(sub: str, tenant: str | None, path: str = "/stats"):
    req = MagicMock()
    req.state.user = SimpleNamespace(sub=sub, tenant=tenant) if sub else None
    req.client.host = "9.9.9.9"
    req.headers.get.return_value = ""
    req.url.path = path
    return req


async def _ok(_request):
    return SimpleNamespace(status_code=200)


def _mw() -> RateLimiterMiddleware:
    return RateLimiterMiddleware(MagicMock())


def test_distinct_users_share_one_tenant_bucket(monkeypatch):
    """N users, each well under their own limit, still hit the tenant cap."""
    monkeypatch.setattr(rate_limiter, "_TENANT_MAX", 3)
    monkeypatch.setattr(rate_limiter, "_TENANT_REFILL_RATE", 0.0)  # no refill mid-test
    tenant = f"t-{uuid.uuid4()}"
    mw = _mw()

    results = []
    for i in range(4):  # 4 distinct users, 1 request each
        resp = asyncio.run(mw.dispatch(_req(f"u{i}-{uuid.uuid4()}", tenant), _ok))
        results.append(resp.status_code)

    assert results[:3] == [200, 200, 200]
    assert results[3] == 429  # tenant bucket (3) exhausted despite fresh user buckets


def test_tenants_do_not_starve_each_other(monkeypatch):
    monkeypatch.setattr(rate_limiter, "_TENANT_MAX", 1)
    monkeypatch.setattr(rate_limiter, "_TENANT_REFILL_RATE", 0.0)
    mw = _mw()
    t1, t2 = f"t-{uuid.uuid4()}", f"t-{uuid.uuid4()}"

    assert asyncio.run(mw.dispatch(_req(f"u-{uuid.uuid4()}", t1), _ok)).status_code == 200
    assert asyncio.run(mw.dispatch(_req(f"u-{uuid.uuid4()}", t1), _ok)).status_code == 429
    # t1 being exhausted must not affect t2
    assert asyncio.run(mw.dispatch(_req(f"u-{uuid.uuid4()}", t2), _ok)).status_code == 200


def test_no_tenant_claim_skips_tenant_bucket(monkeypatch):
    """Requests without a tenant claim get only per-user/IP limiting."""
    monkeypatch.setattr(rate_limiter, "_TENANT_MAX", 0)  # would 429 instantly if consulted
    monkeypatch.setattr(rate_limiter, "_TENANT_REFILL_RATE", 0.0)
    mw = _mw()

    resp = asyncio.run(mw.dispatch(_req(f"u-{uuid.uuid4()}", tenant=None), _ok))
    assert resp.status_code == 200


def test_tenant_429_shape_matches_user_429(monkeypatch):
    """Same response contract as the per-user limiter: 429 + Retry-After."""
    monkeypatch.setattr(rate_limiter, "_TENANT_MAX", 1)
    monkeypatch.setattr(rate_limiter, "_TENANT_REFILL_RATE", 0.0)
    tenant = f"t-{uuid.uuid4()}"
    mw = _mw()

    asyncio.run(mw.dispatch(_req(f"u-{uuid.uuid4()}", tenant), _ok))
    resp = asyncio.run(mw.dispatch(_req(f"u-{uuid.uuid4()}", tenant), _ok))
    assert resp.status_code == 429
    assert "retry-after" in {k.lower() for k in resp.headers}
