"""
Critic Calibrator.

When human feedback corrects an agent, it implies the CriticAgent failed
to catch the mistake. This module analyzes the feedback to extract a
new "Calibration Rule" that is permanently added to the Critic's prompt
to prevent the mistake from recurring.
"""

import json
import logging

from pydantic import BaseModel, Field

from app.agents.llm_adapter import LLMAdapter
from app.db.models import Tenant
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_CALIBRATOR_PROMPT = """
You are the Critic Calibration Engine.
A human just corrected a workflow that our automated CriticAgent failed to catch.

Read the human's feedback and extract a single, punchy "Invariant Rule" 
that the CriticAgent must enforce in the future.

Example: If feedback says "Don't refund subscriptions over 30 days old",
output: "Reject any subscription refund if the purchase date is > 30 days ago."

Return ONLY JSON matching this schema:
{
    "new_rule": "String"
}
"""

class CalibrationResult(BaseModel):
    new_rule: str = Field(..., min_length=5)


class CriticCalibrator:
    """Updates the Tenant's Critic rules based on human feedback."""

    def __init__(self, db_session: AsyncSession, llm: LLMAdapter) -> None:
        self.session = db_session
        self.llm = LLMAdapter(
            provider=llm.provider,
            api_key=llm.api_key,
            model=llm.model,
            temperature=0.1,
            max_tokens=150,
        )

    async def calibrate_from_feedback(self, tenant: Tenant, feedback_texts: list[str]) -> bool:
        """Extract a rule from feedback and append it to Tenant settings."""
        if not feedback_texts:
            return False

        feedback_block = "\n".join([f"- {fb}" for fb in feedback_texts])
        user_prompt = f"## HUMAN FEEDBACK\n{feedback_block}\n\nProduce the new invariant rule JSON."

        try:
            response = await self.llm.generate(
                system_prompt=_CALIBRATOR_PROMPT,
                user_prompt=user_prompt,
                retries=2
            )
            
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
                
            parsed = json.loads(raw)
            result = CalibrationResult(**parsed)
            
            # Append to Tenant settings
            settings = dict(tenant.settings) if tenant.settings else {}
            rules = settings.get("critic_rules", [])
            is_new = result.new_rule not in rules
            rules.append(result.new_rule)

            # Deduplicate and cap to prevent prompt bloat (last 20 rules)
            rules = list(dict.fromkeys(rules))[-20:]

            settings["critic_rules"] = rules

            # Record a timestamped entry for the Policy Evolution Timeline (the
            # visible moat). Kept separate from the flat prompt list above.
            if is_new:
                from datetime import datetime, timezone

                history = list(settings.get("policy_history") or [])
                history.append({
                    "rule": result.new_rule,
                    "source": "human_feedback",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "feedback_count": len(feedback_texts),
                })
                settings["policy_history"] = history[-100:]

            tenant.settings = settings

            await self.session.flush()
            logger.info("CriticCalibrator: Added new rule for tenant %s: '%s'", tenant.slug, result.new_rule)
            return True
            
        except Exception as exc:
            logger.error("CriticCalibrator failed to extract rule: %s", exc)
            return False
