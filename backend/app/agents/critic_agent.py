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

import functools
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.agents.base_agent import BaseAgent, AgentResult
from app.agents.llm_adapter import LLMAdapter
from app.services.quarantine import lock as quarantine

logger = logging.getLogger(__name__)

# ── Verdict ─────────────────────────────────────────────────────────────────

@dataclass
class CriticVerdict:
    """Structured output of the critic's evaluation."""

    approved: bool
    reasons: list[str] = field(default_factory=list)
    risk_score: float = 0.0  # 0 = no risk, 1 = maximum risk
    suggested_modifications: dict[str, Any] = field(default_factory=dict)


# ── Base policy loader ───────────────────────────────────────────────────────

_POLICY_PATH = Path(__file__).parent / "critic_policy.yaml"


@functools.lru_cache(maxsize=1)
def _load_policy() -> dict[str, Any]:
    """Load and validate the base critic policy from YAML.

    Fails closed, like ``rbac.py``: a missing file, unparseable YAML, or a
    policy lacking a non-empty ``rules`` list or an int ``version`` raises
    rather than silently falling back to a stale hardcoded policy.
    """
    if not _POLICY_PATH.exists():
        raise FileNotFoundError(f"Critic policy file not found: {_POLICY_PATH}")

    try:
        with open(_POLICY_PATH, "r", encoding="utf-8") as fh:
            policy = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ValueError(f"Critic policy at {_POLICY_PATH} is not valid YAML: {exc}") from exc

    if not isinstance(policy, dict):
        raise ValueError(f"Critic policy at {_POLICY_PATH} did not parse to a mapping")

    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError(f"Critic policy at {_POLICY_PATH} must have a non-empty 'rules' list")

    version = policy.get("version")
    if not isinstance(version, int):
        raise ValueError(f"Critic policy at {_POLICY_PATH} must have an integer 'version'")

    return policy


class CriticAgent(BaseAgent):
    """Second‑pass validator that critiques candidate actions."""

    def __init__(self, llm: LLMAdapter, tenant_rules: list[str] | None = None) -> None:
        # Load the base policy from critic_policy.yaml (fail-closed).
        policy = _load_policy()
        version: int = policy["version"]
        rules_block = "\n".join(f"- {rule}" for rule in policy["rules"])
        policy_docs = f"## BASE POLICY (v{version})\n{rules_block}"

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
        self.policy_version: int = version

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
        # ── Quarantine gate (Contradiction Handshake) ───────────────────────
        # If the SOP behind this action is under conflict review, veto
        # unconditionally and deterministically — before any LLM call, so the
        # model cannot be talked past it. The lock is an *added* safety layer:
        # if Redis is unreachable we log and fall through to standard review
        # rather than bricking every workflow on an infra outage.
        tenant_id = context.get("tenant_id")
        skill_id = context.get("skill_id")
        if tenant_id and skill_id:
            try:
                active_lock = await quarantine.get(str(tenant_id), str(skill_id))
            except Exception as exc:  # noqa: BLE001 — infra failure must not crash critique
                active_lock = None
                logger.warning(
                    "CriticAgent: quarantine check failed (%s) — proceeding with standard review",
                    exc,
                )
            if active_lock:
                pr_ref = active_lock.get("pr_ref", "a pending contradiction")
                logger.warning(
                    "CriticAgent: vetoing action — skill %s is quarantined (%s)",
                    skill_id, pr_ref,
                )
                return CriticVerdict(
                    approved=False,
                    risk_score=1.0,
                    reasons=[
                        f"Action blocked. Underlying SOP is under conflict review due to {pr_ref}."
                    ],
                )

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
        except (json.JSONDecodeError, IndexError, AttributeError):
            logger.error("CriticAgent: failed to parse LLM response as JSON: %s", str(response.content)[:200])
            return CriticVerdict(
                approved=False,
                reasons=["Critic could not parse its own output — defaulting to REJECT for safety"],
                risk_score=1.0,
            )

        # The model's own verdict fields are untrusted output — validate before
        # trusting them, same fail-closed posture as the parse failure above.
        def _anomaly(detail: str) -> CriticVerdict:
            logger.error("CriticAgent: anomalous verdict from model (%s) — defaulting to REJECT for safety", detail)
            return CriticVerdict(
                approved=False,
                reasons=[f"Critic verdict failed validation ({detail}) — defaulting to REJECT for safety"],
                risk_score=1.0,
            )

        if not isinstance(parsed, dict):
            return _anomaly(f"top-level JSON is {type(parsed).__name__}, not an object")

        approved = parsed.get("approved")
        if not isinstance(approved, bool):
            return _anomaly(f"'approved' is {type(approved).__name__}, not a boolean")

        risk_raw = parsed.get("risk_score", 0.5)
        if isinstance(risk_raw, bool) or not isinstance(risk_raw, (int, float)) or not math.isfinite(risk_raw):
            return _anomaly(f"'risk_score' is not a finite number: {risk_raw!r}")
        risk_score = min(1.0, max(0.0, float(risk_raw)))
        if risk_score != risk_raw:
            logger.warning("CriticAgent: clamped out-of-range risk_score %r to %s", risk_raw, risk_score)

        reasons = parsed.get("reasons", [])
        if not (isinstance(reasons, list) and all(isinstance(r, str) for r in reasons)):
            reasons = []
        mods = parsed.get("suggested_modifications", {})
        if not isinstance(mods, dict):
            mods = {}

        return CriticVerdict(
            approved=approved,
            reasons=reasons,
            risk_score=risk_score,
            suggested_modifications=mods,
        )
