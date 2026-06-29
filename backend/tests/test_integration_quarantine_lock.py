"""
Live-stack integration test for the quarantine lock (Postgres source of truth +
Redis cache). Like the Weaviate isolation test, this needs real infra and is
skipped unless QUARANTINE_INTEGRATION=1 and DATABASE_URL/CELERY_BROKER_URL point
at a live Postgres + Redis (e.g. the docker-compose stack).

Run:
  QUARANTINE_INTEGRATION=1 \
  DATABASE_URL=postgresql+asyncpg://cb_admin:...@localhost:5432/companybrain \
  CELERY_BROKER_URL=redis://:...@localhost:6379/0 \
  python -m pytest tests/test_integration_quarantine_lock.py

It proves the behavior the unit tests can only fake:
  - acquire writes a durable row to Postgres AND populates the Redis cache
  - a read served from Redis returns the lock
  - on a simulated Redis miss the read falls back to Postgres (and repopulates)
  - release clears both stores
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("QUARANTINE_INTEGRATION") != "1",
    reason="live Postgres+Redis required — set QUARANTINE_INTEGRATION=1 to run",
)

pytest.importorskip("asyncpg")

from app.services.quarantine import lock as quarantine


def test_lock_durable_in_postgres_with_redis_cache():
    tenant = f"itest-{uuid.uuid4()}"
    skill = f"skill-{uuid.uuid4()}"
    try:
        quarantine.acquire_sync(tenant, skill, pr_ref="PR #1", summary="live conflict")

        # Redis cache populated.
        assert quarantine._redis_get(tenant, skill) is not None

        # Read served (Redis fast path).
        rec = quarantine.get_sync(tenant, skill)
        assert rec and rec["pr_ref"] == "PR #1"

        # Simulate Redis eviction/restart → must recover from Postgres.
        quarantine._redis_delete(tenant, skill)
        assert quarantine._redis_get(tenant, skill) is None
        recovered = quarantine.get_sync(tenant, skill)
        assert recovered and recovered["pr_ref"] == "PR #1"
        # Cache repopulated after the Postgres fallback.
        assert quarantine._redis_get(tenant, skill) is not None
    finally:
        assert quarantine.release_sync(tenant, skill) in (True, False)
        # After release, both stores are clear.
        assert quarantine.get_sync(tenant, skill) is None
