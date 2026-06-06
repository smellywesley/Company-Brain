"""
Workflow Agent for Company Brain.

Orchestrates a complete workflow:
    data retrieval → LLM generation → CriticAgent validation → action execution

If the critic rejects the candidate, the workflow escalates to a human
(returns a ``pending_review`` status).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from app.agents.base_agent import BaseAgent, AgentResult
from app.agents.critic_agent import CriticAgent, CriticVerdict
from app.agents.llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)


# ── Result types ────────────────────────────────────────────────────────────

@dataclass
class WorkflowStep:
    """Record of a single step inside a workflow execution."""

    name: str
    status: str  # success | failed | skipped
    output: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class WorkflowResult:
    """Full result of a workflow execution."""

    workflow_name: str
    status: str  # completed | rejected | pending_review | error
    steps_executed: list[WorkflowStep] = field(default_factory=list)
    critic_verdict: CriticVerdict | None = None
    final_action: dict[str, Any] = field(default_factory=dict)
    audit_trail: list[str] = field(default_factory=list)


# ── Workflow Agent ──────────────────────────────────────────────────────────

class WorkflowAgent(BaseAgent):
    """Orchestrates a multi‑step workflow with built‑in critic review."""

    def __init__(
        self,
        llm: LLMAdapter,
        critic: CriticAgent,
        workflow_name: str = "default",
        system_prompt: str = "",
        action_executors: dict[str, Callable[..., Awaitable[dict[str, Any]]]] | None = None,
    ) -> None:
        super().__init__(
            name=f"WorkflowAgent:{workflow_name}",
            description=f"Orchestrates the '{workflow_name}' workflow",
            llm=llm,
            system_prompt=system_prompt or self._default_system_prompt(workflow_name),
        )
        self.workflow_name = workflow_name
        self.critic = critic
        self._executors = action_executors or {}

    @staticmethod
    def _default_system_prompt(workflow_name: str) -> str:
        return (
            f"You are the orchestrator for the '{workflow_name}' workflow in the Company Brain platform.\n"
            "Given trigger data and context retrieved from the company's knowledge base, "
            "produce a CANDIDATE ACTION as a JSON object that describes exactly what should "
            "happen (e.g., issue a refund, create a Jira ticket, send a Slack message).\n\n"
            "Your output MUST be valid JSON with at least these fields:\n"
            '{\n  "action_type": "<type>",\n  "parameters": { ... },\n'
            '  "reasoning": "<why this action is appropriate>"\n}\n\n'
            "Return ONLY the JSON object.  No markdown fences."
        )

    # ── Public API ──────────────────────────────────────────────────────

    async def run(self, input_data: dict[str, Any]) -> AgentResult:
        """Convenience entry‑point matching the BaseAgent interface."""
        result = await self.execute_workflow(
            workflow_config=input_data.get("config", {}),
            trigger_data=input_data.get("trigger", {}),
        )
        return AgentResult(
            success=result.status == "completed",
            output={
                "workflow": result.workflow_name,
                "status": result.status,
                "final_action": result.final_action,
            },
            reasoning=json.dumps(result.critic_verdict.__dict__) if result.critic_verdict else "",
            audit_log=result.audit_trail,
        )

    async def execute_workflow(
        self,
        workflow_config: dict[str, Any],
        trigger_data: dict[str, Any],
        matched_skill: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Full pipeline: retrieve context → generate → critique → execute."""
        audit: list[str] = []
        steps: list[WorkflowStep] = []

        # ── Step 1: Retrieve context (concurrent sub‑queries) ───────────
        audit.append(self._log("Step 1 – retrieving context"))
        context_queries = workflow_config.get("context_queries", [trigger_data.get("summary", "")])
        context_results = await asyncio.gather(
            *[self.get_context(q) for q in context_queries],
            return_exceptions=True,
        )
        merged_context: list[dict[str, Any]] = []
        for res in context_results:
            if isinstance(res, list):
                merged_context.extend(res)

        steps.append(WorkflowStep(name="context_retrieval", status="success", output={"docs_found": len(merged_context)}))
        audit.append(self._log(f"Retrieved {len(merged_context)} context documents"))

        # ── Step 2: Generate candidate action ───────────────────────────
        audit.append(self._log("Step 2 – generating candidate action"))
        
        # Dynamically build the prompt if a skill is provided
        dynamic_system_prompt = self.system_prompt
        if matched_skill:
            audit.append(self._log(f"Applying active skill: {matched_skill.get('name')}"))
            dynamic_system_prompt += (
                f"\n\nCRITICAL: You MUST strictly follow this operational skill definition:\n"
                f"```json\n{json.dumps(matched_skill, indent=2)}\n```\n"
                "Evaluate the 'execution_conditions' for the current step. If they fail, do not proceed."
            )

        user_prompt = (
            "## Trigger Data\n"
            f"```json\n{json.dumps(trigger_data, indent=2)}\n```\n\n"
            "## Retrieved Context\n"
            f"```json\n{json.dumps(merged_context[:20], indent=2, default=str)}\n```\n\n"
            "## Workflow Configuration\n"
            f"```json\n{json.dumps(workflow_config, indent=2)}\n```\n\n"
            "Produce the candidate action JSON."
        )

        llm_response = await self.llm.generate(system_prompt=dynamic_system_prompt, user_prompt=user_prompt)

        try:
            raw = llm_response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            candidate_action = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            logger.error("WorkflowAgent: failed to parse candidate action: %s", llm_response.content[:300])
            steps.append(WorkflowStep(name="generation", status="failed"))
            return WorkflowResult(
                workflow_name=self.workflow_name,
                status="error",
                steps_executed=steps,
                audit_trail=audit,
            )

        steps.append(WorkflowStep(name="generation", status="success", output=candidate_action))
        audit.append(self._log(f"Candidate action type: {candidate_action.get('action_type', '?')}"))

        # ── Step 3: Critic validation ───────────────────────────────────
        audit.append(self._log("Step 3 – critic validation"))
        verdict = await self.critic.critique(
            candidate_action=candidate_action,
            context={"trigger": trigger_data, "docs": merged_context[:10]},
        )
        steps.append(WorkflowStep(
            name="critic_review",
            status="success" if verdict.approved else "rejected",
            output={"approved": verdict.approved, "risk_score": verdict.risk_score, "reasons": verdict.reasons},
        ))
        audit.append(self._log(f"Critic verdict: approved={verdict.approved}, risk={verdict.risk_score}"))

        if not verdict.approved:
            audit.append(self._log("Action REJECTED by critic – escalating to human review"))
            return WorkflowResult(
                workflow_name=self.workflow_name,
                status="pending_review",
                steps_executed=steps,
                critic_verdict=verdict,
                final_action=candidate_action,
                audit_trail=audit,
            )

        # ── Step 4: Execute action ──────────────────────────────────────
        action_type = candidate_action.get("action_type", "")
        executor = self._executors.get(action_type)

        if executor:
            audit.append(self._log(f"Step 4 – executing action '{action_type}'"))
            try:
                exec_result = await executor(candidate_action.get("parameters", {}))
                steps.append(WorkflowStep(name="execution", status="success", output=exec_result))
                audit.append(self._log("Action executed successfully"))
            except Exception as exc:
                logger.exception("WorkflowAgent: action execution failed")
                steps.append(WorkflowStep(name="execution", status="failed", output={"error": str(exc)}))
                return WorkflowResult(
                    workflow_name=self.workflow_name,
                    status="error",
                    steps_executed=steps,
                    critic_verdict=verdict,
                    final_action=candidate_action,
                    audit_trail=audit,
                )
        else:
            audit.append(self._log(f"No executor registered for '{action_type}' – marking as dry‑run"))
            steps.append(WorkflowStep(name="execution", status="skipped", output={"reason": "no executor"}))

        return WorkflowResult(
            workflow_name=self.workflow_name,
            status="completed",
            steps_executed=steps,
            critic_verdict=verdict,
            final_action=candidate_action,
            audit_trail=audit,
        )
