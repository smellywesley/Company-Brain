"""
Refund Automation Workflow for Company Brain.

End‑to‑end workflow that:
1. Receives a refund request (trigger data with order_id, customer, amount)
2. Retrieves refund policy docs from the knowledge base
3. Pulls transaction history from Stripe (mocked for now)
4. LLM generates a candidate refund action
5. CriticAgent validates policy compliance, PII, and financial limits
6. If approved, executes the refund via Stripe API (mock)
7. Sends notification to Slack

This serves as the reference implementation for building new workflows.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.agents.llm_adapter import LLMAdapter
from app.agents.critic_agent import CriticAgent
from app.agents.workflow_agent import WorkflowAgent

logger = logging.getLogger(__name__)

# ── Refund policy (would be loaded from Notion / vector store in prod) ──────

REFUND_POLICY = """
## Company Refund Policy

1. Refunds under $100: Auto-approved if within 30 days of purchase.
2. Refunds $100–$500: Requires CriticAgent approval. Must include valid reason.
3. Refunds over $500: MUST be escalated to human manager for approval.
4. Digital products: No refunds after 14 days unless product is defective.
5. Subscription refunds: Pro-rated for unused portion only.
6. All refunds must reference a valid order_id and match the original payment method.
7. Maximum 3 refunds per customer per quarter.
8. PII (customer email, card details) must NEVER appear in action logs.
"""

REFUND_SYSTEM_PROMPT = f"""
You are the Refund Automation Agent for Company Brain.

You will receive a refund request with order details and context from the
company's knowledge base. Your job is to determine whether the refund is
valid and produce the action to execute it.

{REFUND_POLICY}

Produce a JSON action with these fields:
{{
  "action_type": "stripe_refund",
  "parameters": {{
    "order_id": "<order_id>",
    "amount_cents": <amount in cents>,
    "reason": "<brief reason>",
    "refund_method": "original_payment_method",
    "notify_customer": true
  }},
  "reasoning": "<why this refund is appropriate based on policy>"
}}

Return ONLY the JSON object.
"""


# ── Mock Stripe executor ───────────────────────────────────────────────────

async def mock_stripe_refund(params: dict[str, Any]) -> dict[str, Any]:
    """Simulate a Stripe refund API call.

    In production, replace with actual ``stripe.Refund.create()`` call.
    """
    order_id = params.get("order_id", "unknown")
    amount_cents = params.get("amount_cents", 0)

    logger.info(
        "MOCK STRIPE: Processing refund for order %s, amount: $%.2f",
        order_id,
        amount_cents / 100,
    )

    # Simulate success
    return {
        "refund_id": f"re_mock_{order_id}",
        "status": "succeeded",
        "amount_cents": amount_cents,
        "order_id": order_id,
        "method": params.get("refund_method", "original_payment_method"),
    }


async def mock_slack_notify(params: dict[str, Any]) -> dict[str, Any]:
    """Simulate sending a Slack notification about the refund."""
    logger.info("MOCK SLACK: Notification sent for refund %s", params.get("order_id", "?"))
    return {"channel": "#refunds", "status": "sent"}


# ── Factory ─────────────────────────────────────────────────────────────────

def create_refund_workflow(
    llm_provider: str | None = None,
    llm_api_key: str | None = None,
    llm_model: str | None = None,
) -> WorkflowAgent:
    """Instantiate a fully-configured Refund Automation WorkflowAgent.

    Uses environment variables as defaults if explicit args are not provided.
    """
    provider = llm_provider or os.getenv("LLM_PROVIDER", "gemini")
    api_key = llm_api_key or os.getenv("LLM_API_KEY", "")
    model = llm_model or os.getenv("LLM_MODEL", "")

    llm = LLMAdapter(
        provider=provider,
        api_key=api_key,
        model=model,
        temperature=0.3,  # Lower temperature for financial decisions
        max_tokens=2048,
    )

    critic = CriticAgent(llm=llm)

    workflow = WorkflowAgent(
        llm=llm,
        critic=critic,
        workflow_name="refund_automation",
        system_prompt=REFUND_SYSTEM_PROMPT,
        action_executors={
            "stripe_refund": mock_stripe_refund,
            "slack_notify": mock_slack_notify,
        },
    )

    logger.info("Refund Automation workflow created (provider=%s, model=%s)", provider, model or "default")
    return workflow


# ── Convenience runner ──────────────────────────────────────────────────────

async def run_refund(
    order_id: str,
    customer_id: str,
    amount_usd: float,
    reason: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """High-level entry point: run the full refund workflow and return the result."""
    workflow = create_refund_workflow()

    trigger_data = {
        "order_id": order_id,
        "customer_id": customer_id,
        "amount_usd": amount_usd,
        "amount_cents": int(amount_usd * 100),
        "reason": reason,
        "summary": f"Refund request for order {order_id}: ${amount_usd:.2f}",
        **extra,
    }

    config = {
        "context_queries": [
            f"refund policy for order {order_id}",
            f"customer {customer_id} refund history",
        ],
    }

    result = await workflow.execute_workflow(
        workflow_config=config,
        trigger_data=trigger_data,
    )

    return {
        "workflow": result.workflow_name,
        "status": result.status,
        "steps": [{"name": s.name, "status": s.status} for s in result.steps_executed],
        "critic_approved": result.critic_verdict.approved if result.critic_verdict else None,
        "critic_risk_score": result.critic_verdict.risk_score if result.critic_verdict else None,
        "critic_reasons": result.critic_verdict.reasons if result.critic_verdict else [],
        "final_action": result.final_action,
        "audit_trail": result.audit_trail,
    }
