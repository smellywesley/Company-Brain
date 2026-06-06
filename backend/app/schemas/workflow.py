"""
Pydantic models for workflows and critic verdicts in Company Brain.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any


class WorkflowStep(BaseModel):
    """Record of a single step inside a workflow execution."""

    name: str
    status: str = Field(..., description="success | failed | skipped | rejected")
    output: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0


class CriticVerdict(BaseModel):
    """Structured output of the critic agent's evaluation."""

    approved: bool
    reasons: list[str] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    suggested_modifications: dict[str, Any] = Field(default_factory=dict)


class WorkflowConfig(BaseModel):
    """Configuration for a workflow (stored as JSON, shareable between companies)."""

    name: str = Field(..., description="Unique workflow name")
    description: str = ""
    trigger_type: str = Field(default="manual", description="manual | webhook | cron | event")
    context_queries: list[str] = Field(default_factory=list, description="Queries to run against the knowledge base")
    action_type: str = Field(default="", description="Target action executor (e.g. stripe_refund, jira_ticket)")
    llm_system_prompt: str = Field(default="", description="Custom system prompt for the workflow LLM")
    max_retries: int = Field(default=1, ge=0, le=5)
    require_approval: bool = Field(default=True, description="Force human‑in‑the‑loop for all actions")
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowTrigger(BaseModel):
    """Payload that starts a workflow execution."""

    workflow_name: str
    triggered_by: str = "system"
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowResult(BaseModel):
    """Full result of a workflow execution."""

    workflow_name: str
    status: str = Field(..., description="completed | rejected | pending_review | error")
    steps_executed: list[WorkflowStep] = Field(default_factory=list)
    critic_verdict: CriticVerdict | None = None
    final_action: dict[str, Any] = Field(default_factory=dict)
    audit_trail: list[str] = Field(default_factory=list)
