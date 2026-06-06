"""
Skill Synthesizer.

Uses the LLM to analyze a cluster of documents and synthesize a formal,
executable SkillDefinition. It strictly enforces output validation via
the Pydantic schemas.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from app.agents.llm_adapter import LLMAdapter
from app.schemas.skill import SkillGenerateRequest, SkillGenerateResponse, SkillDefinition

logger = logging.getLogger(__name__)

_SYNTHESIZER_PROMPT = """
You are the Company Brain Skill Synthesizer.
Your job is to analyze a cluster of operational documents (e.g., Slack threads, 
Notion pages, Zendesk tickets) and deduce the underlying Standard Operating Procedure.

You must extract this procedure into a formal, executable 'Skill'.
A Skill is a step-by-step definition of how a specific task is accomplished, 
what inputs it requires, and what safety guardrails exist.

RULES:
1. Only synthesize a skill if you are confident a clear process exists.
2. Step 'action_name' must be a programmatic identifier (e.g. 'issue_refund', 'escalate_ticket').
3. 'execution_conditions' should be pseudocode-like logic (e.g. 'amount < 100').
4. If a step involves financial transactions or irreversible actions, set 'requires_human_approval' to true.
5. Provide a 'risk_level' (low, medium, high) and a 'confidence_score' (0.0 to 1.0).

OUTPUT FORMAT:
You MUST return ONLY a JSON object that exactly matches this schema:
{
  "definition": {
    "name": "String",
    "description": "String",
    "trigger_keywords": ["String"],
    "trigger_conditions": ["String"],
    "steps": [
      {
        "step_number": 1,
        "action_name": "String",
        "description": "String",
        "required_inputs": ["String"],
        "execution_conditions": ["String"],
        "requires_human_approval": false,
        "escalate_on_failure": true
      }
    ],
    "guardrails": ["String"]
  },
  "confidence_score": 0.85,
  "risk_level": "medium",
  "reasoning": "Brief explanation of how you deduced this skill"
}
"""


class SkillSynthesizer:
    """Pipeline for generating Skills from raw text clusters."""

    def __init__(self, llm: LLMAdapter) -> None:
        self.llm = LLMAdapter(
            provider=llm.provider,
            api_key=llm.api_key,
            model=llm.model,
            temperature=0.2,  # Low temperature for structural consistency
            max_tokens=4000,
        )

    async def synthesize(self, request: SkillGenerateRequest) -> SkillGenerateResponse | None:
        """Analyze documents and synthesize a Skill."""
        
        # Combine documents into a single analytical block
        docs_text = "\n\n---\n\n".join(request.document_contents)
        
        # Truncate if necessary (protect against massive context windows for now)
        if len(docs_text) > 40000:
            docs_text = docs_text[:40000] + "\n...[truncated]"

        user_prompt = f"## RAW DOCUMENTS (Cluster ID: {request.cluster_id})\n\n{docs_text}"

        try:
            response = await self.llm.generate(
                system_prompt=_SYNTHESIZER_PROMPT,
                user_prompt=user_prompt,
                retries=2
            )
            
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
                
            parsed_json = json.loads(raw)
            
            # Validate through Pydantic!
            validated_response = SkillGenerateResponse(**parsed_json)
            
            logger.info(
                "Successfully synthesized skill '%s' with confidence %.2f", 
                validated_response.definition.name, 
                validated_response.confidence_score
            )
            return validated_response
            
        except json.JSONDecodeError as exc:
            logger.error("Synthesizer failed to produce valid JSON: %s", exc)
            return None
        except ValidationError as exc:
            logger.error("Synthesizer output failed Pydantic validation: %s", exc)
            return None
        except Exception as exc:
            logger.error("Synthesizer LLM request failed: %s", exc)
            return None
