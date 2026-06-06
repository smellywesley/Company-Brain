"""
Critic Agent for Company Brain.

Performs a second‑pass validation of any candidate action produced by a
WorkflowAgent.  Uses temperature = 0 for deterministic, policy‑strict
evaluation.  Checks for:

* PII leakage
* RBAC compliance
* Financial / operational limits
* Policy adherence (loaded from config)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base_agent import BaseAgent, AgentResult
from app.agents.llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)

# ── Verdict ─────────────────────────────────────────────────────────────────

@dataclass
class CriticVerdict:
    """Structured output of the critic's evaluation."""

    approved: bool
    reasons: list[str] = field(default_factory=list)
    risk_score: float = 0.0  # 0 = no risk, 1 = maximum risk
    suggested_modifications: dict[str, Any] = field(default_factory=dict)


# ── Default policy prompt ───────────────────────────────────────────────────

_DEFAULT_POLICY = """
You are the Company Brain Critic Agent — an independent quality‑assurance
and policy‑compliance reviewer.  You receive a CANDIDATE ACTION produced by
another agent together with the CONTEXT that was used to generate it.

Your job is to evaluate the candidate and return a JSON object with:
{
  "approved": true | false,
  "reasons": ["<reason 1>", ...],
  "risk_score": <0.0 – 1.0>,
  "suggested_modifications": { ... }  // optional
}

### Rules you MUST enforce
1. **No PII leakage** – the action must not expose names, emails, phone
   numbers, credit‑card numbers, SSNs, or any other personally identifiable
   information.
2. **Financial limits** – reject any unapproved financial action above the
   configured limit.
3. **RBAC compliance** – the action must respect the caller's role and scope.
4. **Policy adherence** – follow all tenant-specific learned rules supplied
   in the context.

Return ONLY the JSON object. No markdown fences.
"""


class CriticAgent(BaseAgent):
    """Second‑pass validator that critiques candidate actions."""

    def __init__(self, llm: LLMAdapter, tenant_rules: list[str] | None = None) -> None:
        # Load default static policies
        policy_docs = "NO PII LEAKAGE\nFinancial Limit: $500 max without approval."
        
        # Inject dynamically learned rules from feedback calibration
        if tenant_rules:
            learned_block = "\n".join([f"- {rule}" for rule in tenant_rules])
            policy_docs += f"\n\n## TENANT-SPECIFIC LEARNED RULES\n{learned_block}"

        system_prompt = (
            "You are the CriticAgent. Your job is to review candidate actions proposed by the WorkflowAgent.\n"
            "You must ensure the action complies with ALL policies and poses no security/financial risk.\n\n"
            "## POLICIES TO ENFORCE\n"
            f"{policy_docs}\n\n"
            "You must return ONLY a JSON object matching this schema:\n"
            "{\n"
            '  "approved": true | false,\n'
            '  "risk_score": 0.0 to 1.0,\n'
            '  "reasons": ["List of specific reasons for approval or rejection"],\n'
            '  "suggested_modifications": {"key": "value"} // Optional\n'
            "}\n"
        )
        
        # Force temperature = 0 for deterministic output
        llm_copy = LLMAdapter(
            provider=llm.provider,
            api_key=llm.api_key,
            model=llm.model,
            temperature=0.0,
            max_tokens=llm.max_tokens,
        )
        super().__init__(
            name="CriticAgent",
            description="Validates proposed actions against security, PII, and financial policies.",
            llm=llm_copy,
            system_prompt=system_prompt,
        )

    async def run(self, input_data: dict[str, Any]) -> AgentResult:
        """Convenience wrapper — delegates to ``critique``."""
        verdict = await self.critique(
            candidate_action=input_data.get("candidate_action", {}),
            context=input_data.get("context", {}),
        )
        return AgentResult(
            success=verdict.approved,
            output={
                "approved": verdict.approved,
                "reasons": verdict.reasons,
                "risk_score": verdict.risk_score,
                "suggested_modifications": verdict.suggested_modifications,
            },
            reasoning="; ".join(verdict.reasons),
            audit_log=[self._log(f"Verdict: approved={verdict.approved}, risk={verdict.risk_score}")],
        )

    async def critique(
        self,
        candidate_action: dict[str, Any],
        context: dict[str, Any],
    ) -> CriticVerdict:
        """Evaluate *candidate_action* against policy and return a verdict."""
        user_prompt = (
            "## Candidate Action\n"
            f"```json\n{json.dumps(candidate_action, indent=2)}\n```\n\n"
            "## Context\n"
            f"```json\n{json.dumps(context, indent=2)}\n```"
        )

        response = await self.llm.generate(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
        )

        try:
            raw = response.content.strip()
            # Strip markdown fences if the model disobeys
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            logger.error("CriticAgent: failed to parse LLM response as JSON: %s", response.content[:200])
            return CriticVerdict(
                approved=False,
                reasons=["Critic could not parse its own output — defaulting to REJECT for safety"],
                risk_score=1.0,
            )

        return CriticVerdict(
            approved=parsed.get("approved", False),
            reasons=parsed.get("reasons", []),
            risk_score=float(parsed.get("risk_score", 0.5)),
            suggested_modifications=parsed.get("suggested_modifications", {}),
        )
