"""
Quarantine lock for the Contradiction Handshake.

When ingestion detects that a newly merged change contradicts an active
Standard Operating Procedure, a quarantine lock is written here. The
``CriticAgent`` reads it before every autonomous action and unconditionally
vetoes any action whose underlying SOP is locked, until a human resolves the
conflict ("Accept Synthesis") and the lock is released.

Key schema:   ``quarantine:{tenant_id}:{skill_id}``
Value (JSON): ``{pr_ref, summary, severity, locked_by, locked_at}``
TTL:          none — a stale SOP stays blocked until a human releases it, never
              silently unblocked by a timer.

Built on the synchronous ``redis-py`` client (the same client family the
webhook router uses) so a single module-level pool is safe across both the
long-lived FastAPI event loop and the new-event-loop-per-task Celery worker.
Async callers (the ``CriticAgent``) use the ``await``-able wrappers, which
offload the blocking socket call to a thread so the event loop is never
blocked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import redis

logger = logging.getLogger(__name__)

_KEY_TEMPLATE = "quarantine:{tenant_id}:{skill_id}"
_client: "redis.Redis | None" = None


def _get_client() -> "redis.Redis":
    """Lazily build a process-wide, loop-agnostic sync Redis client."""
    global _client
    if _client is None:
        _client = redis.from_url(
            os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
    return _client


def _key(tenant_id: str, skill_id: str) -> str:
    return _KEY_TEMPLATE.format(tenant_id=tenant_id, skill_id=skill_id)


# ── Synchronous API (Celery worker / ingestion) ──────────────────────────────

def acquire_sync(
    tenant_id: str,
    skill_id: str,
    pr_ref: str,
    summary: str,
    severity: str = "high",
    locked_by: str = "contradiction-worker",
) -> str:
    """Place a quarantine lock on a skill. No TTL — released only by a human."""
    key = _key(tenant_id, skill_id)
    payload = json.dumps(
        {
            "pr_ref": pr_ref,
            "summary": summary,
            "severity": severity,
            "locked_by": locked_by,
            "locked_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _get_client().set(key, payload)  # intentionally no `ex=` — human release only
    logger.warning("Quarantine lock placed: %s (%s)", key, pr_ref)
    return key


def get_sync(tenant_id: str, skill_id: str) -> dict[str, Any] | None:
    """Return the active lock record for a skill, or ``None`` if unlocked."""
    raw = _get_client().get(_key(tenant_id, skill_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Corrupt quarantine lock value for %s", _key(tenant_id, skill_id))
        # A corrupt lock still means the skill is under review — fail closed.
        return {"pr_ref": "unknown", "summary": "corrupt lock record"}


def release_sync(tenant_id: str, skill_id: str) -> bool:
    """Release a lock (the 'Accept Synthesis' action). True if one existed."""
    removed = _get_client().delete(_key(tenant_id, skill_id))
    if removed:
        logger.info("Quarantine lock released: %s", _key(tenant_id, skill_id))
    return bool(removed)


# ── Async wrappers (CriticAgent, FastAPI) ────────────────────────────────────

async def get(tenant_id: str, skill_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(get_sync, tenant_id, skill_id)


async def acquire(
    tenant_id: str,
    skill_id: str,
    pr_ref: str,
    summary: str,
    severity: str = "high",
    locked_by: str = "contradiction-worker",
) -> str:
    return await asyncio.to_thread(
        acquire_sync, tenant_id, skill_id, pr_ref, summary, severity, locked_by
    )


async def release(tenant_id: str, skill_id: str) -> bool:
    return await asyncio.to_thread(release_sync, tenant_id, skill_id)
