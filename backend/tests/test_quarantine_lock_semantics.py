"""
Production semantics for the quarantine lock (Postgres source of truth).

These tests run without a live Postgres by faking the ``_pg_*`` coroutines with
an in-memory dict, and faking Redis with a recording stub. They prove:

- a write goes to Postgres first, then the Redis cache
- a read is served from the Redis cache without touching Postgres
- a read falls back to Postgres on a Redis miss, then repopulates the cache
- production + no asyncpg → acquire/release FAIL CLOSED (raise)
- dev + explicit escape hatch → Redis-only acquire is allowed
"""

from __future__ import annotations

import pytest

from app.services.quarantine import lock as quarantine


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.get_calls = 0

    def set(self, key, value, ex=None):
        self.store[key] = value

    def get(self, key):
        self.get_calls += 1
        return self.store.get(key)

    def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


class _FakePg:
    """In-memory stand-in for the Postgres quarantine table."""

    def __init__(self):
        self.rows = {}
        self.get_calls = 0

    async def acquire(self, tenant_id, skill_id, pr_ref, summary, severity, locked_by, ttl_seconds):
        self.rows[(tenant_id, skill_id)] = {
            "pr_ref": pr_ref, "summary": summary, "severity": severity,
            "locked_by": locked_by, "locked_at": "2026-06-28T00:00:00+00:00",
            "expires_at": None,
        }

    async def get(self, tenant_id, skill_id):
        self.get_calls += 1
        return self.rows.get((tenant_id, skill_id))

    async def release(self, tenant_id, skill_id):
        return self.rows.pop((tenant_id, skill_id), None) is not None


@pytest.fixture
def wired(monkeypatch):
    """Wire fake Postgres + Redis into the lock module and pretend asyncpg exists."""
    pg = _FakePg()
    redis = _FakeRedis()
    monkeypatch.setattr(quarantine, "_asyncpg", object())  # _pg_available() → True
    monkeypatch.setattr(quarantine, "_client", redis)
    monkeypatch.setattr(quarantine, "_pg_acquire", pg.acquire)
    monkeypatch.setattr(quarantine, "_pg_get", pg.get)
    monkeypatch.setattr(quarantine, "_pg_release", pg.release)
    return pg, redis


# ── Postgres-first write, then Redis cache ────────────────────────────────────

def test_acquire_writes_postgres_then_redis(wired):
    pg, redis = wired
    quarantine.acquire_sync("t1", "s1", pr_ref="PR #1", summary="conflict")
    assert ("t1", "s1") in pg.rows                       # Postgres is source of truth
    assert redis.store.get("quarantine:t1:s1")           # Redis cache populated


def test_read_served_from_redis_cache(wired):
    pg, redis = wired
    quarantine.acquire_sync("t1", "s1", pr_ref="PR #1", summary="conflict")
    pg.get_calls = 0
    rec = quarantine.get_sync("t1", "s1")
    assert rec["pr_ref"] == "PR #1"
    assert pg.get_calls == 0                              # served from cache, no DB hit


def test_read_falls_back_to_postgres_on_cache_miss(wired):
    pg, redis = wired
    quarantine.acquire_sync("t1", "s1", pr_ref="PR #9", summary="conflict")
    redis.store.clear()                                  # simulate Redis eviction/restart
    rec = quarantine.get_sync("t1", "s1")
    assert rec is not None and rec["pr_ref"] == "PR #9"  # recovered from Postgres
    assert pg.get_calls == 1
    assert redis.store.get("quarantine:t1:s1")           # cache repopulated


def test_release_clears_postgres_and_cache(wired):
    pg, redis = wired
    quarantine.acquire_sync("t1", "s1", pr_ref="PR #1", summary="x")
    assert quarantine.release_sync("t1", "s1") is True
    assert ("t1", "s1") not in pg.rows
    assert "quarantine:t1:s1" not in redis.store


# ── Fail-closed when Postgres is unavailable ──────────────────────────────────

def test_production_no_postgres_fails_closed(monkeypatch):
    """Production + no asyncpg → refuse to place a Redis-only safety lock."""
    monkeypatch.setattr(quarantine, "_asyncpg", None)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("QUARANTINE_LOCK_ALLOW_REDIS_ONLY_DEV", "true")  # ignored in prod
    monkeypatch.setattr(quarantine, "_client", _FakeRedis())
    with pytest.raises(RuntimeError, match="requires Postgres"):
        quarantine.acquire_sync("t1", "s1", pr_ref="PR #1", summary="x")


def test_dev_without_optin_fails_closed(monkeypatch):
    """Dev + no asyncpg + flag NOT set → still refuse (safe default)."""
    monkeypatch.setattr(quarantine, "_asyncpg", None)
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("QUARANTINE_LOCK_ALLOW_REDIS_ONLY_DEV", raising=False)
    monkeypatch.setattr(quarantine, "_client", _FakeRedis())
    with pytest.raises(RuntimeError, match="requires Postgres"):
        quarantine.acquire_sync("t1", "s1", pr_ref="PR #1", summary="x")


def test_dev_with_optin_allows_redis_only(monkeypatch):
    """Dev + no asyncpg + explicit opt-in → Redis-only acquire is allowed."""
    monkeypatch.setattr(quarantine, "_asyncpg", None)
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("QUARANTINE_LOCK_ALLOW_REDIS_ONLY_DEV", "true")
    redis = _FakeRedis()
    monkeypatch.setattr(quarantine, "_client", redis)
    quarantine.acquire_sync("t1", "s1", pr_ref="PR #1", summary="x")
    assert redis.store.get("quarantine:t1:s1")
