"""
Skill Updater (LLM).

Uses the LLM to analyze human feedback and re-write an existing
SkillDefinition to fix the flaws identified by the humans.
Strictly validates the output against the Pydantic schema.
"""

import json
import logging

from pydantic import ValidationError

from app.agents.llm_adapter import LLMAdapter
from app.db.models import Skill
from app.schemas.skill import SkillDefinition

logger = logging.getLogger(__name__)

_UPDATER_PROMPT = """
You are the Company Brain Skill Updater.
An existing Standard Operating Procedure (Skill) has failed in production, 
and human operators have provided corrective feedback.

Your job is to read the CURRENT skill definition and the HUMAN FEEDBACK, 
and output an UPDATED skill definition that permanently fixes the issue.

RULES:
1. Do not break existing steps that were working correctly.
2. If feedback says a condition was missing (e.g. "didn't check subscription length"), add that condition to 'execution_conditions'.
3. If feedback says an action was wrong, modify the 'action_name' or 'required_inputs'.
4. If feedback introduces a hard rule, add it to 'guardrails'.

OUTPUT FORMAT:
You MUST return ONLY a JSON object that exactly matches the SkillDefinition schema.
Do not include markdown blocks, risk scores, or reasoning in the JSON, ONLY the definition.

{
  "name": "String",
  "description": "String",
  "trigger_keywords": ["String"],
  "trigger_conditions": ["String"],
  "steps": [ ... ],
  "guardrails": ["String"]
}
"""

class SkillUpdater:
    """Uses LLM to modify a skill based on feedback."""

    def __init__(self, llm: LLMAdapter) -> None:
        self.llm = LLMAdapter(
            provider=llm.provider,
            api_key=llm.api_key,
            model=llm.model,
            temperature=0.1,  # Highly deterministic for updates
            max_tokens=4000,
        )

    async def update_skill(self, current_skill: Skill, feedback_texts: list[str]) -> SkillDefinition | None:
        """Analyze feedback and synthesize an updated SkillDefinition."""
        
        feedback_block = "\n".join([f"- {fb}" for fb in feedback_texts])
        
        user_prompt = (
            "## CURRENT SKILL DEFINITION\n"
            f"```json\n{json.dumps(current_skill.definition, indent=2)}\n```\n\n"
            "## HUMAN CORRECTIVE FEEDBACK\n"
            f"{feedback_block}\n\n"
            "Produce the UPDATED skill definition JSON."
        )

        try:
            response = await self.llm.generate(
                system_prompt=_UPDATER_PROMPT,
                user_prompt=user_prompt,
                retries=2
            )
            
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
                
            parsed_json = json.loads(raw)
            
            # Strict Pydantic validation
            validated_definition = SkillDefinition(**parsed_json)
            
            logger.info("SkillUpdater successfully re-synthesized skill '%s'", validated_definition.name)
            return validated_definition
            
        except json.JSONDecodeError as exc:
            logger.error("SkillUpdater failed to produce valid JSON: %s", exc)
            return None
        except ValidationError as exc:
            logger.error("SkillUpdater output failed Pydantic validation: %s", exc)
            return None
        except Exception as exc:
            logger.error("SkillUpdater LLM request failed: %s", exc)
            return None
