"""
Feedback Quorum Engine.

Enforces rules about how many independent human approvals are required
before a skill can be updated based on feedback. 

Low-risk skills might require 1 engineer.
High-risk financial skills might require 2 managers.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FeedbackRecord, Skill

logger = logging.getLogger(__name__)

@dataclass
class QuorumStatus:
    is_met: bool
    required: int
    current: int
    missing_roles: list[str]


class QuorumEngine:
    """Evaluates if a skill has sufficient feedback to trigger re-synthesis."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_quorum(self, skill: Skill) -> QuorumStatus:
        """Determine if the skill has met the feedback threshold for an update."""
        
        # 1. Determine requirements based on risk level
        # This could be moved to tenant settings later
        if skill.risk_level == "low":
            required_count = 1
            required_role = "engineer"
        elif skill.risk_level == "medium":
            required_count = 2
            required_role = "engineer"
        else: # high risk
            required_count = 2
            required_role = "manager"

        # 2. Fetch unprocessed feedback for this skill
        stmt = select(FeedbackRecord).where(
            FeedbackRecord.skill_id == skill.id,
            FeedbackRecord.processed == False,
            FeedbackRecord.feedback_type.in_(["modify", "correct_skill"])
        )
        result = await self.session.execute(stmt)
        pending_feedback = result.scalars().all()

        if not pending_feedback:
            return QuorumStatus(is_met=False, required=required_count, current=0, missing_roles=[required_role])

        # 3. Evaluate unique approvers and their roles
        # We use a dict to ensure we count unique users (prevent one user submitting 2x)
        valid_approvers: dict[str, str] = {}
        for fb in pending_feedback:
            if fb.submitted_by_role in [required_role, "admin", "manager"]: 
                # admin/manager can always satisfy an engineer requirement
                valid_approvers[fb.submitted_by] = fb.submitted_by_role

        current_count = len(valid_approvers)
        is_met = current_count >= required_count

        if is_met:
            logger.info("Quorum met for skill '%s' (%d/%d unique approvers).", skill.slug, current_count, required_count)
        else:
            logger.debug("Quorum NOT met for skill '%s' (%d/%d required).", skill.slug, current_count, required_count)

        return QuorumStatus(
            is_met=is_met,
            required=required_count,
            current=current_count,
            missing_roles=[required_role] if not is_met else []
        )

    async def mark_quorum_processed(self, skill_id: uuid.UUID) -> None:
        """Mark all currently pending feedback for this skill as processed."""
        stmt = select(FeedbackRecord).where(
            FeedbackRecord.skill_id == skill_id,
            FeedbackRecord.processed == False
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        
        for record in records:
            record.processed = True
            
        await self.session.flush()
        logger.info("Marked %d feedback records as processed for skill %s.", len(records), skill_id)
