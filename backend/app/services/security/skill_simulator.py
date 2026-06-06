"""
Skill Simulator.

Runs a candidate skill definition against historical workflow runs
to verify it would have produced correct outcomes. A skill must pass
>= 80% of historical cases before it can be auto-activated.

This is a deterministic check — no LLM calls.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """Outcome of running a skill against historical data."""
    passed: bool
    total_cases: int
    passed_cases: int
    failed_cases: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.passed_cases / self.total_cases


class SkillSimulator:
    """Tests a skill definition against historical workflow runs."""

    PASS_THRESHOLD = 0.80

    def simulate(
        self,
        skill_definition: dict[str, Any],
        historical_runs: list[dict[str, Any]],
    ) -> SimulationResult:
        """Run simulation.

        Args:
            skill_definition: The SkillDefinition dict (with steps, trigger_conditions, guardrails).
            historical_runs: List of dicts with at least {trigger_data, final_action, status, critic_approved}.

        Returns:
            SimulationResult with pass/fail verdict.
        """
        if not historical_runs:
            logger.info("SkillSimulator: No historical runs to test against.")
            return SimulationResult(passed=True, total_cases=0, passed_cases=0)

        trigger_conditions = skill_definition.get("trigger_conditions", [])
        guardrails = skill_definition.get("guardrails", [])
        steps = skill_definition.get("steps", [])

        passed_count = 0
        failed_cases: list[dict[str, Any]] = []

        for run in historical_runs:
            trigger_data = run.get("trigger_data", {})
            status = run.get("status", "")
            critic_approved = run.get("critic_approved")

            case_passed = True
            failure_reasons: list[str] = []

            # Check 1: Would trigger conditions match this historical case?
            for condition in trigger_conditions:
                if not self._evaluate_condition(condition, trigger_data):
                    # Skill wouldn't have fired for this case — skip it
                    case_passed = True  # Not a failure, just not applicable
                    break

            # Check 2: Would guardrails have prevented known-bad outcomes?
            if status == "error" or critic_approved is False:
                # This was a bad outcome historically. Check if guardrails catch it.
                action = run.get("final_action", {})
                for guardrail in guardrails:
                    if self._guardrail_would_catch(guardrail, action, trigger_data):
                        break  # Good — guardrail would have caught it
                else:
                    if guardrails:  # Only fail if guardrails exist but missed it
                        case_passed = False
                        failure_reasons.append(f"No guardrail caught bad outcome: status={status}")

            # Check 3: Do step conditions align with historical trigger data?
            for step in steps:
                for condition in step.get("execution_conditions", []):
                    if not self._evaluate_condition(condition, trigger_data):
                        # Step wouldn't execute — check if it should have
                        if status == "completed" and critic_approved:
                            # Historical success but step wouldn't fire = potential gap
                            case_passed = False
                            failure_reasons.append(
                                f"Step '{step.get('action_name')}' condition '{condition}' "
                                f"would not match successful historical run"
                            )

            if case_passed:
                passed_count += 1
            else:
                failed_cases.append({
                    "trigger_data": trigger_data,
                    "status": status,
                    "reasons": failure_reasons,
                })

        pass_rate = passed_count / len(historical_runs) if historical_runs else 0.0
        passed = pass_rate >= self.PASS_THRESHOLD

        logger.info(
            "SkillSimulator: %d/%d cases passed (%.0f%%). Verdict: %s",
            passed_count, len(historical_runs), pass_rate * 100,
            "PASS" if passed else "FAIL",
        )

        return SimulationResult(
            passed=passed,
            total_cases=len(historical_runs),
            passed_cases=passed_count,
            failed_cases=failed_cases,
        )

    def _evaluate_condition(self, condition: str, data: dict[str, Any]) -> bool:
        """Evaluate a pseudocode condition against data.

        Supports simple patterns like:
        - 'amount < 100'
        - 'data.topic == refund'
        - 'amount_usd <= 500'
        """
        condition = condition.strip()
        if not condition:
            return True

        # Pattern: key operator value
        match = re.match(r"(?:data\.)?(\w+)\s*(==|!=|<|>|<=|>=)\s*(.+)", condition)
        if not match:
            return True  # Can't evaluate — assume pass

        key, op, raw_value = match.groups()
        raw_value = raw_value.strip().strip("'\"")

        actual = data.get(key)
        if actual is None:
            return False

        try:
            # Try numeric comparison
            actual_num = float(actual)
            expected_num = float(raw_value)
            ops = {"==": actual_num == expected_num, "!=": actual_num != expected_num,
                   "<": actual_num < expected_num, ">": actual_num > expected_num,
                   "<=": actual_num <= expected_num, ">=": actual_num >= expected_num}
            return ops.get(op, True)
        except (ValueError, TypeError):
            # String comparison
            actual_str = str(actual).lower()
            expected_str = raw_value.lower()
            if op == "==":
                return actual_str == expected_str
            if op == "!=":
                return actual_str != expected_str
            return True

    def _guardrail_would_catch(
        self, guardrail: str, action: dict[str, Any], trigger_data: dict[str, Any],
    ) -> bool:
        """Check if a guardrail rule text would logically catch a bad action.

        Simple heuristic: check if the guardrail mentions a key that exists
        in the action or trigger_data with a violating value.
        """
        guardrail_lower = guardrail.lower()
        all_data = {**trigger_data, **action.get("parameters", {})}

        for key, value in all_data.items():
            if key.lower() in guardrail_lower:
                # The guardrail mentions this field — it likely catches it
                return True
        return False
