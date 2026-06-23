"""
Quarantine read/release service for the Knowledge Reconciliation surface.

Sits between the API routes and the Redis lock module. Listing iterates the
tenant's *active* skills (a bounded, indexed query) and probes each lock key —
deliberately no Redis SCAN, so the cost is O(active skills), never O(keyspace),
and tenant scoping is by construction rather than by key-pattern filtering.

Release is the human resolution step ("Dismiss" = false positive, "Accept" =
synthesis applied). Both currently release the Redis lock; the resolution kind
and reason are returned for the caller's audit log. The durable Postgres state
machine (pending/confirmed/dismissed/expired) is the P1 enforcement plan — see
docs/TIER4_RECONCILIATION_DESIGN.md.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.db.models import Skill
from app.services.quarantine import lock as quarantine

logger = logging.getLogger(__name__)

_RESOLUTIONS = {"dismiss", "accept"}


async def list_active_locks(session, tenant_id) -> list[dict[str, Any]]:
    """All active quarantine locks for a tenant, joined with skill identity.

    Returns one entry per locked skill: ``{skill_id, skill_name, lock}`` where
    ``lock`` is the raw Redis record (pr_ref, summary, severity, locked_at, …).
    """
    result = await session.execute(
        select(Skill).where(
            Skill.tenant_id == tenant_id,
            Skill.status == "active",
        )
    )
    skills = result.scalars().all()

    locked: list[dict[str, Any]] = []
    for skill in skills:
        record = await quarantine.get(str(tenant_id), str(skill.id))
        if record:
            locked.append(
                {
                    "skill_id": str(skill.id),
                    "skill_name": skill.name,
                    "lock": record,
                }
            )
    return locked


async def release_lock(
    session,
    tenant_id,
    skill_id: str,
    resolution: str,
    resolved_by: str,
    reason: str = "",
) -> dict[str, Any]:
    """Release a skill's quarantine lock after human review.

    Raises ``ValueError`` on an unknown resolution and ``LookupError`` when the
    skill does not belong to the tenant (IDOR guard) or carries no active lock.
    """
    if resolution not in _RESOLUTIONS:
        raise ValueError(f"resolution must be one of {sorted(_RESOLUTIONS)}")

    # Tenant-scoped lookup — a skill id from another tenant must 404, not act.
    result = await session.execute(
        select(Skill).where(Skill.id == skill_id, Skill.tenant_id == tenant_id)
    )
    skill = result.scalars().first()
    if skill is None:
        raise LookupError("skill not found for this tenant")

    record = await quarantine.get(str(tenant_id), str(skill.id))
    if not record:
        raise LookupError("no active quarantine lock on this skill")

    await quarantine.release(str(tenant_id), str(skill.id))
    logger.warning(
        "Quarantine released: tenant=%s skill=%s resolution=%s by=%s reason=%s",
        tenant_id, skill_id, resolution, resolved_by, reason or "-",
    )
    return {
        "skill_id": str(skill.id),
        "skill_name": skill.name,
        "resolution": resolution,
        "resolved_by": resolved_by,
        "reason": reason,
        "released_lock": record,
    }
