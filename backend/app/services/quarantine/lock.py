"""
Quarantine lock for the Contradiction Handshake.

When ingestion detects that a newly merged change contradicts an active
Standard Operating Procedure, a quarantine lock is written here. The
``CriticAgent`` reads it before every autonomous action and unconditionally
vetoes any action whose underlying SOP is locked, until a human resolves the
conflict ("Accept Synthesis") and the lock is released.

Source of truth: PostgreSQL (``quarantine_locks`` table).
Fast-read cache: Redis (same TTL, invalidated on write/release).

This two-layer design means:
- Reads are fast (Redis hit → no DB round-trip).
- Locks survive Redis restarts, eviction-policy changes, and memory pressure.
- A Redis miss always falls back to Postgres — the lock is never silently lost.

Key schema (Redis cache / logging):  ``quarantine:{tenant_id}:{skill_id}``
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import redis

try:
    import asyncpg as _asyncpg  # optional in lean dev/test env — Postgres path degrades gracefully
except ImportError:
    _asyncpg = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_KEY_TEMPLATE = "quarantine:{tenant_id}:{skill_id}"
_DEFAULT_TTL_SECONDS = 86_400  # 24h soft-lock self-heal

_client: "redis.Redis | None" = None


# ── Redis (fast-read cache) ──────────────────────────────────────────────────

def _get_redis() -> "redis.Redis":  # noqa: UP006
    global _client
    if _client is None:
        _client = redis.from_url(
            os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
    return _client


def _cache_key(tenant_id: str, skill_id: str) -> str:
    return _KEY_TEMPLATE.format(tenant_id=tenant_id, skill_id=skill_id)


def _redis_set(tenant_id: str, skill_id: str, payload: dict, ttl_seconds: int | None) -> None:
    """Write or refresh Redis cache entry. Never raises — cache is best-effort."""
    try:
        r = _get_redis()
        raw = json.dumps(payload)
        if ttl_seconds is None:
            r.set(_cache_key(tenant_id, skill_id), raw)
        else:
            r.set(_cache_key(tenant_id, skill_id), raw, ex=ttl_seconds)
    except Exception:  # noqa: BLE001
        logger.warning("Redis cache write failed for quarantine:%s:%s", tenant_id, skill_id)


def _redis_get(tenant_id: str, skill_id: str) -> dict | None:
    """Return cached lock payload or None. Never raises — cache miss is safe."""
    try:
        raw = _get_redis().get(_cache_key(tenant_id, skill_id))
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        logger.debug("Redis cache miss (error) for quarantine:%s:%s", tenant_id, skill_id)
    return None


def _redis_delete(tenant_id: str, skill_id: str) -> None:
    """Invalidate Redis cache entry. Never raises."""
    try:
        _get_redis().delete(_cache_key(tenant_id, skill_id))
    except Exception:  # noqa: BLE001
        logger.warning("Redis cache delete failed for quarantine:%s:%s", tenant_id, skill_id)


def ping() -> bool:
    """True if the Redis broker answers — for the readiness probe. Never raises."""
    try:
        return bool(_get_redis().ping())
    except Exception:  # noqa: BLE001
        return False


# ── Postgres (source of truth) ───────────────────────────────────────────────

def _db_url() -> str:
    """Convert async DATABASE_URL (asyncpg dialect) to a plain asyncpg DSN."""
    url = os.getenv("DATABASE_URL", "postgresql://cb_admin:change-me-in-production@localhost:5432/companybrain")
    # SQLAlchemy async prefix → raw asyncpg DSN
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _pg_available() -> bool:
    return _asyncpg is not None


async def _pg_acquire(
    tenant_id: str,
    skill_id: str,
    pr_ref: str,
    summary: str,
    severity: str,
    locked_by: str,
    ttl_seconds: int | None,
) -> None:
    expires_at = (
        (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        if ttl_seconds is not None
        else None
    )
    if not _pg_available():
        return
    conn = await _asyncpg.connect(dsn=_db_url())
    try:
        await conn.execute(
            """
            INSERT INTO quarantine_locks
                (id, tenant_id, skill_id, pr_ref, summary, severity, locked_by, locked_at, expires_at)
            VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, now(), $7)
            ON CONFLICT (tenant_id, skill_id) DO UPDATE SET
                pr_ref     = EXCLUDED.pr_ref,
                summary    = EXCLUDED.summary,
                severity   = EXCLUDED.severity,
                locked_by  = EXCLUDED.locked_by,
                locked_at  = now(),
                expires_at = EXCLUDED.expires_at
            """,
            tenant_id, skill_id, pr_ref, summary, severity, locked_by, expires_at,
        )
    finally:
        await conn.close()


async def _pg_get(tenant_id: str, skill_id: str) -> dict | None:
    if not _pg_available():
        return None
    conn = await _asyncpg.connect(dsn=_db_url())
    try:
        row = await conn.fetchrow(
            """
            SELECT pr_ref, summary, severity, locked_by, locked_at, expires_at
            FROM quarantine_locks
            WHERE tenant_id = $1 AND skill_id = $2
              AND (expires_at IS NULL OR expires_at > now())
            """,
            tenant_id, skill_id,
        )
        if row is None:
            return None
        return {
            "pr_ref": row["pr_ref"],
            "summary": row["summary"],
            "severity": row["severity"],
            "locked_by": row["locked_by"],
            "locked_at": row["locked_at"].isoformat() if row["locked_at"] else None,
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        }
    finally:
        await conn.close()


async def _pg_release(tenant_id: str, skill_id: str) -> bool:
    if not _pg_available():
        return False
    conn = await _asyncpg.connect(dsn=_db_url())
    try:
        result = await conn.execute(
            "DELETE FROM quarantine_locks WHERE tenant_id = $1 AND skill_id = $2",
            tenant_id, skill_id,
        )
        return result.endswith("1")
    finally:
        await conn.close()


def _run(coro):
    """Run an async coroutine from a sync (Celery/thread) context.

    Uses asyncio.run() which creates and closes a fresh event loop. This is
    safe in Celery worker threads (no running loop) and in asyncio.to_thread
    calls (threads have no running loop by default).
    """
    return asyncio.run(coro)


# ── Synchronous API (Celery worker / ingestion) ──────────────────────────────

def acquire_sync(
    tenant_id: str,
    skill_id: str,
    pr_ref: str,
    summary: str,
    severity: str = "high",
    locked_by: str = "contradiction-worker",
    ttl_seconds: int | None = _DEFAULT_TTL_SECONDS,
) -> str:
    """Place a quarantine lock. Postgres is written first; Redis cache updated after."""
    if _pg_available():
        try:
            _run(_pg_acquire(tenant_id, skill_id, pr_ref, summary, severity, locked_by, ttl_seconds))
        except Exception:  # noqa: BLE001
            logger.error("Postgres quarantine write failed for %s:%s — lock NOT placed", tenant_id, skill_id)
            raise  # fail closed: if Postgres fails, don't silently succeed via cache only
    else:
        # ponytail: asyncpg absent (lean env) — Redis-only path; acceptable in dev/test, not prod
        logger.warning("asyncpg unavailable — quarantine lock is Redis-only for %s:%s", tenant_id, skill_id)

    payload = {
        "pr_ref": pr_ref,
        "summary": summary,
        "severity": severity,
        "locked_by": locked_by,
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "ttl_seconds": ttl_seconds,
    }
    _redis_set(tenant_id, skill_id, payload, ttl_seconds)

    key = _cache_key(tenant_id, skill_id)
    logger.warning("Quarantine lock placed: %s (%s, ttl=%s)", key, pr_ref, ttl_seconds)
    return key


def get_sync(tenant_id: str, skill_id: str) -> dict[str, Any] | None:
    """Return the active lock record — Redis first, Postgres fallback."""
    cached = _redis_get(tenant_id, skill_id)
    if cached is not None:
        return cached

    # Redis miss: check Postgres (the source of truth)
    try:
        record = _run(_pg_get(tenant_id, skill_id))
    except Exception:  # noqa: BLE001
        logger.error("Postgres quarantine read failed for %s:%s — failing closed", tenant_id, skill_id)
        # ponytail: fail closed — a Postgres read error is treated as "locked"
        # so a broken DB doesn't accidentally unblock a quarantined skill.
        return {"pr_ref": "unknown", "summary": "Postgres read error — lock status unknown"}

    if record is None:
        return None

    # Repopulate Redis cache to avoid repeated DB hits
    _redis_set(tenant_id, skill_id, record, _DEFAULT_TTL_SECONDS)
    return record


def release_sync(tenant_id: str, skill_id: str) -> bool:
    """Release a lock (the 'Accept Synthesis' action). True if one existed."""
    removed = False
    if _pg_available():
        try:
            removed = _run(_pg_release(tenant_id, skill_id))
        except Exception:  # noqa: BLE001
            logger.error("Postgres quarantine release failed for %s:%s", tenant_id, skill_id)
            raise  # fail closed

    _redis_delete(tenant_id, skill_id)  # invalidate cache regardless
    if removed:
        logger.info("Quarantine lock released: %s:%s", tenant_id, skill_id)
    return removed


# ── Async wrappers (CriticAgent, FastAPI) ────────────────────────────────────
# Delegate to the sync functions via asyncio.to_thread so:
# (a) tests that monkeypatch get_sync / acquire_sync / release_sync still work, and
# (b) the blocking Postgres calls don't stall the event loop.

async def get(tenant_id: str, skill_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(get_sync, tenant_id, skill_id)


async def acquire(
    tenant_id: str,
    skill_id: str,
    pr_ref: str,
    summary: str,
    severity: str = "high",
    locked_by: str = "contradiction-worker",
    ttl_seconds: int | None = _DEFAULT_TTL_SECONDS,
) -> str:
    return await asyncio.to_thread(
        acquire_sync, tenant_id, skill_id, pr_ref, summary, severity, locked_by, ttl_seconds
    )


async def release(tenant_id: str, skill_id: str) -> bool:
    return await asyncio.to_thread(release_sync, tenant_id, skill_id)
