"""
Feedback Anomaly Detector.

Analyzes incoming feedback records to detect malicious or erroneous
feedback patterns (e.g., an account attempting to poison a skill by
submitting a barrage of incorrect 'reject' or 'modify' actions).
"""

import logging
from datetime import datetime, timedelta
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FeedbackRecord

logger = logging.getLogger(__name__)

class AnomalyDetector:
    """Detects malicious or anomalous feedback submission patterns."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # Hard limits to trigger an anomaly flag
        self.MAX_FEEDBACK_PER_HOUR = 20
        self.MAX_REJECTIONS_PER_HOUR = 10

    async def is_anomalous(self, tenant_id: uuid.UUID, submitted_by: str) -> bool:
        """Check if the user's recent feedback behavior is anomalous.
        
        Args:
            tenant_id: The tenant context.
            submitted_by: The user email/ID submitting the feedback.
            
        Returns:
            True if the feedback is deemed anomalous and should be quarantined.
        """
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        
        # 1. Check total volume of feedback in the last hour
        stmt_total = select(func.count(FeedbackRecord.id)).where(
            FeedbackRecord.tenant_id == tenant_id,
            FeedbackRecord.submitted_by == submitted_by,
            FeedbackRecord.created_at >= one_hour_ago
        )
        total_result = await self.session.execute(stmt_total)
        total_feedback = total_result.scalar() or 0

        if total_feedback >= self.MAX_FEEDBACK_PER_HOUR:
            logger.warning(
                "AnomalyDetector: User %s exceeded total feedback velocity limit (%d in last hour).", 
                submitted_by, total_feedback
            )
            return True

        # 2. Check volume of negative feedback (rejects/modifications) in the last hour
        stmt_negative = select(func.count(FeedbackRecord.id)).where(
            FeedbackRecord.tenant_id == tenant_id,
            FeedbackRecord.submitted_by == submitted_by,
            FeedbackRecord.feedback_type.in_(["reject", "modify"]),
            FeedbackRecord.created_at >= one_hour_ago
        )
        negative_result = await self.session.execute(stmt_negative)
        negative_feedback = negative_result.scalar() or 0

        if negative_feedback >= self.MAX_REJECTIONS_PER_HOUR:
            logger.warning(
                "AnomalyDetector: User %s exceeded negative feedback velocity limit (%d in last hour).", 
                submitted_by, negative_feedback
            )
            return True

        return False
