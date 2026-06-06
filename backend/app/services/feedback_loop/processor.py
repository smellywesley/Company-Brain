"""
Feedback Processor.

Orchestrates the feedback loop. When new feedback arrives:
1. Checks for anomalies.
2. Checks if quorum is met.
3. If quorum met, invokes the SkillUpdater to rewrite the skill.
4. Uses SkillRepo to bump the version and persist.
5. Clears the pending feedback queue.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FeedbackRecord, Skill, Tenant
from app.db.repositories.skill_repo import SkillRepo
from app.services.feedback_loop.anomaly_detector import AnomalyDetector
from app.services.feedback_loop.calibrator import CriticCalibrator
from app.services.feedback_loop.quorum import QuorumEngine
from app.services.feedback_loop.updater import SkillUpdater

logger = logging.getLogger(__name__)

class FeedbackProcessor:
    def __init__(
        self,
        db_session: AsyncSession,
        updater: SkillUpdater,
        anomaly_detector: AnomalyDetector,
        quorum_engine: QuorumEngine,
        calibrator: "CriticCalibrator | None" = None,
    ) -> None:
        self.session = db_session
        self.repo = SkillRepo(db_session)
        self.updater = updater
        self.anomaly_detector = anomaly_detector
        self.quorum_engine = quorum_engine
        # When provided, the calibrator extracts a new invariant rule from the
        # feedback and appends it to the tenant's CriticAgent policy so the same
        # mistake is caught next time. Without it, skills still re-synthesize but
        # the critic does not learn.
        self.calibrator = calibrator

    async def process_new_feedback(self, tenant_id: uuid.UUID, feedback_id: uuid.UUID) -> bool:
        """Handle a newly submitted feedback record.
        
        Returns:
            True if the skill was re-synthesized, False otherwise.
        """
        # 1. Fetch the record
        stmt = select(FeedbackRecord).where(FeedbackRecord.id == feedback_id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record or not record.skill_id:
            logger.warning("FeedbackProcessor: Record %s not found or has no associated skill.", feedback_id)
            return False

        # 2. Check for anomalous behavior (poisoning attempt)
        if await self.anomaly_detector.is_anomalous(tenant_id, record.submitted_by):
            logger.error("FeedbackProcessor: Quarantining feedback %s due to anomalous behavior.", feedback_id)
            # We don't process it, and we might want to flag the account
            return False

        # 3. Get the affected Skill
        skill = await self.repo.get_by_id(record.skill_id)
        if not skill:
            return False

        # 4. Check Quorum
        status = await self.quorum_engine.check_quorum(skill)
        if not status.is_met:
            # We wait for more humans to complain before altering company process
            return False

        # 5. Quorum met! Gather all pending feedback reasons.
        # tenant_id is part of the filter so feedback from one tenant can never
        # drive skill re-synthesis for another tenant sharing a skill_id.
        stmt_pending = select(FeedbackRecord).where(
            FeedbackRecord.tenant_id == tenant_id,
            FeedbackRecord.skill_id == skill.id,
            FeedbackRecord.processed == False
        )
        res_pending = await self.session.execute(stmt_pending)
        pending_records = res_pending.scalars().all()
        
        feedback_texts = []
        for pr in pending_records:
            if pr.reason:
                feedback_texts.append(pr.reason)
            elif pr.corrected_output:
                feedback_texts.append(f"Human corrected output to: {pr.corrected_output}")

        if not feedback_texts:
            logger.info("FeedbackProcessor: Quorum met but no actionable text provided for skill %s.", skill.slug)
            await self.quorum_engine.mark_quorum_processed(skill.id)
            return False

        # 6. Re-synthesize the Skill
        logger.info("FeedbackProcessor: Triggering re-synthesis for skill '%s' based on %d feedback points.", skill.slug, len(feedback_texts))
        new_definition = await self.updater.update_skill(skill, feedback_texts)

        if not new_definition:
            logger.error("FeedbackProcessor: Updater failed to produce a valid new definition. Aborting update.")
            return False

        # 7. Persist the new version
        unique_submitters = len({pr.submitted_by for pr in pending_records})
        await self.repo.update_skill_definition(
            skill=skill,
            new_definition=new_definition.model_dump(),
            change_reason=f"Automated update from feedback quorum ({unique_submitters} unique submitters)",
            changed_by="system_feedback_loop",
        )

        # 8. Calibrate the Critic Agent (only if a calibrator was injected).
        # This is what turns "skills that re-synthesize" into "a critic that
        # learns" — the durable product differentiator.
        if self.calibrator is not None:
            tenant = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant_obj = tenant.scalar_one_or_none()
            if tenant_obj:
                await self.calibrator.calibrate_from_feedback(tenant_obj, feedback_texts)

        # 9. Mark feedback as processed
        await self.quorum_engine.mark_quorum_processed(skill.id)

        return True
