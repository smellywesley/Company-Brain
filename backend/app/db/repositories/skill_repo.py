"""
Skill Repository.

Provides data access methods for the Skill and SkillVersion models.
Ensures that any mutation to a skill automatically creates an immutable
version history record, allowing full rollback capabilities.
"""

from __future__ import annotations

import uuid
from typing import Sequence
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill, SkillVersion

logger = logging.getLogger(__name__)


class SkillRepo:
    """Repository for managing Skills and their version history."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, skill_id: uuid.UUID) -> Skill | None:
        """Fetch a skill by its UUID."""
        stmt = select(Skill).where(Skill.id == skill_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, tenant_id: uuid.UUID, slug: str) -> Skill | None:
        """Fetch a skill by tenant_id and slug."""
        stmt = select(Skill).where(
            Skill.tenant_id == tenant_id,
            Skill.slug == slug
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_for_tenant(self, tenant_id: uuid.UUID) -> Sequence[Skill]:
        """Fetch all ACTIVE skills for a tenant (used by WorkflowAgent)."""
        stmt = select(Skill).where(
            Skill.tenant_id == tenant_id,
            Skill.status == "active"
        ).order_by(Skill.confidence_score.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_skill(
        self,
        tenant_id: uuid.UUID,
        slug: str,
        name: str,
        description: str,
        definition: dict,
        status: str = "draft",
        risk_level: str = "medium",
        confidence_score: float = 0.0,
        discovered_from: list[str] | None = None,
        created_by: str = "system",
        signature: str | None = None,
    ) -> Skill:
        """Create a new skill and its initial v1 version history record."""
        # 1. Create the base skill
        skill = Skill(
            tenant_id=tenant_id,
            slug=slug,
            name=name,
            description=description,
            version=1,
            status=status,
            risk_level=risk_level,
            confidence_score=confidence_score,
            definition=definition,
            discovered_from=discovered_from or [],
            created_by=created_by,
            signature=signature,
        )
        self.session.add(skill)
        await self.session.flush()  # To get the generated skill.id

        # 2. Create the immutable version snapshot
        version = SkillVersion(
            skill_id=skill.id,
            version_number=1,
            definition=definition,
            change_reason="Initial creation",
            changed_by=created_by,
            signature=signature,
        )
        self.session.add(version)
        await self.session.flush()

        logger.info("Created new skill '%s' (v1) for tenant %s", slug, tenant_id)
        return skill

    async def update_skill_definition(
        self,
        skill: Skill,
        new_definition: dict,
        change_reason: str,
        changed_by: str = "system",
        new_signature: str | None = None,
        new_status: str | None = None,
    ) -> Skill:
        """Update a skill's definition and bump its version number."""
        # Bump version
        new_version_num = skill.version + 1
        
        # 1. Update the base skill
        skill.version = new_version_num
        skill.definition = new_definition
        skill.signature = new_signature
        if new_status:
            skill.status = new_status

        # 2. Create the immutable version snapshot
        version = SkillVersion(
            skill_id=skill.id,
            version_number=new_version_num,
            definition=new_definition,
            change_reason=change_reason,
            changed_by=changed_by,
            signature=new_signature,
        )
        self.session.add(version)
        await self.session.flush()

        logger.info("Updated skill '%s' to v%d. Reason: %s", skill.slug, new_version_num, change_reason)
        return skill

    async def update_status(self, skill: Skill, new_status: str) -> Skill:
        """Update just the status of a skill (e.g., draft -> active) without bumping version."""
        old_status = skill.status
        skill.status = new_status
        await self.session.flush()
        logger.info("Skill '%s' status changed: %s -> %s", skill.slug, old_status, new_status)
        return skill
