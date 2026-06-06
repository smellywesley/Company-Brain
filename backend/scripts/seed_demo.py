"""
Seed the database with demo data so every view shows real, compelling content.

Creates the `default` tenant, an active Skill, a set of WorkflowRuns spread over
time (with decision-time context snapshots, critic scores, and reasons), and a
timestamped Critic policy history (the evolving moat). Re-runnable: it clears
prior seed rows (triggered_by == "seed_demo") and reinserts fresh data.

Usage (from backend/ with DATABASE_URL pointing at a running Postgres):
    python scripts/seed_demo.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running as `python scripts/seed_demo.py` from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.db.database import get_db_session, init_db  # noqa: E402
from app.db.models import FeedbackRecord, Skill, Tenant, WorkflowRun  # noqa: E402

logging.basicConfig(level="INFO", format="%(levelname)s | %(message)s")
logger = logging.getLogger("seed_demo")

_SEED_VERSION = "v2"
_NOW = datetime.now(timezone.utc)


def _ctx(sources: list[tuple[str, str, str]], graph_facts: list[str], age_min: int) -> dict:
    """Build a decision-time context snapshot (what the brain retrieved)."""
    return {
        "retrieved_at": (_NOW - timedelta(minutes=age_min)).isoformat(),
        "sources": [
            {"source": s, "title": t, "snippet": sn} for (s, t, sn) in sources
        ],
        "graph_facts": graph_facts,
    }


# Runs, newest first. age_min = minutes before "now" the decision was made.
_RUNS = [
    {
        "workflow_name": "customer_retention",
        "status": "pending_review",
        "critic_approved": None,
        "critic_risk_score": 0.62,
        "critic_reasons": [
            "Retention offer exceeds standard discount band",
            "Cross-source claim requires human confirmation",
        ],
        "rationale": "Account shows churn signal; a 20% win-back offer is within historical save rate.",
        "action": {"action_type": "send_retention_offer", "parameters": {"discount_pct": 20, "account": "Acme Corp"}},
        "trigger": {"account": "Acme Corp", "signal": "No reply in 14 days after renewal quote"},
        "context": _ctx(
            [
                ("salesforce", "Acme Corp — Account", "ARR $48k, renewal in 9 days, sentiment declining"),
                ("slack", "#customer-success", "CSM flagged Acme as at-risk after QBR"),
                ("notion", "Retention Playbook", "Max standard discount is 15% without director sign-off"),
            ],
            ["Acme Corp -[OWNED_BY]-> CSM:dana", "Acme Corp -[HAS]-> Subscription:pro-annual"],
            12,
        ),
    },
    {
        "workflow_name": "refund_automation",
        "status": "pending_review",
        "critic_approved": None,
        "critic_risk_score": 0.55,
        "critic_reasons": ["Amount exceeds $100 threshold", "Refund reason requires validation"],
        "rationale": "Order flagged defective; refund matches charge but exceeds the auto-approve ceiling.",
        "action": {"action_type": "stripe_refund", "parameters": {"amount_cents": 34900, "order_id": "ORD-7291"}},
        "trigger": {"order_id": "ORD-7291", "amount_usd": 349.0, "reason": "Product defective"},
        "context": _ctx(
            [
                ("stripe", "Charge ch_7291", "$349.00 captured 6 days ago, not disputed"),
                ("zendesk", "Ticket 8841", "Customer reports unit dead on arrival, photos attached"),
                ("notion", "Refund Policy", "Refunds over $100 require human approval"),
            ],
            ["ORD-7291 -[BELONGS_TO]-> Customer:globex", "ORD-7291 -[CHARGED_ON]-> Stripe:ch_7291"],
            34,
        ),
    },
    {
        "workflow_name": "ticket_escalation",
        "status": "pending_review",
        "critic_approved": None,
        "critic_risk_score": 0.35,
        "critic_reasons": ["Critical priority requires manager sign-off"],
        "rationale": "P1 ticket from an enterprise account past SLA; escalation is the standard play.",
        "action": {"action_type": "jira_escalate", "parameters": {"assignee": "eng-lead@company.com"}},
        "trigger": {"ticket_id": "TKT-1102", "priority": "critical", "customer": "Acme Corp"},
        "context": _ctx(
            [
                ("jira", "TKT-1102", "Outage on Acme tenant, 2h past response SLA"),
                ("salesforce", "Acme Corp", "Enterprise plan, exec sponsor engaged"),
            ],
            ["TKT-1102 -[AFFECTS]-> Tenant:acme", "Tenant:acme -[TIER]-> enterprise"],
            58,
        ),
    },
    {
        "workflow_name": "refund_automation",
        "status": "completed",
        "critic_approved": True,
        "critic_risk_score": 0.12,
        "critic_reasons": ["Within policy: amount under $100, reason validated"],
        "rationale": "Late delivery, $89 refund under the auto-approve ceiling and within policy.",
        "action": {"action_type": "stripe_refund", "parameters": {"amount_cents": 8900, "order_id": "ORD-4821"}},
        "trigger": {"order_id": "ORD-4821", "amount_usd": 89.0, "reason": "Late delivery"},
        "context": _ctx(
            [
                ("stripe", "Charge ch_4821", "$89.00 captured 3 days ago"),
                ("notion", "Refund Policy", "Auto-approve refunds under $100 with a valid reason"),
            ],
            ["ORD-4821 -[BELONGS_TO]-> Customer:initech"],
            180,
        ),
    },
    {
        "workflow_name": "lead_qualification",
        "status": "completed",
        "critic_approved": True,
        "critic_risk_score": 0.08,
        "critic_reasons": ["Lead matches ICP, no PII exposure"],
        "rationale": "Inbound demo request matches ICP; create CRM lead and route to sales.",
        "action": {"action_type": "create_crm_lead", "parameters": {"company": "Globex", "score": 0.81}},
        "trigger": {"company": "Globex", "source": "inbound_demo_request"},
        "context": _ctx(
            [
                ("hubspot", "Globex", "500 employees, fintech, visited pricing 3x"),
                ("notion", "ICP Definition", "Mid-market fintech is a primary ICP"),
            ],
            ["Globex -[INDUSTRY]-> fintech", "Globex -[SIZE]-> mid-market"],
            240,
        ),
    },
    {
        "workflow_name": "deploy_approval",
        "status": "rejected",
        "critic_approved": False,
        "critic_risk_score": 0.88,
        "critic_reasons": ["Production deploy with no staging validation", "Multiple services affected"],
        "rationale": "Release branch requested straight to prod; no staging run recorded.",
        "action": {"action_type": "k8s_deploy", "parameters": {"cluster": "prod-us-east"}},
        "trigger": {"repo": "company-brain", "branch": "release/v2.1"},
        "context": _ctx(
            [
                ("github", "release/v2.1", "12 commits, touches billing + auth services"),
                ("datadog", "prod-us-east", "Error budget at 40% this week"),
            ],
            ["release/v2.1 -[TOUCHES]-> Service:billing", "release/v2.1 -[TOUCHES]-> Service:auth"],
            300,
        ),
    },
    {
        "workflow_name": "lead_qualification",
        "status": "completed",
        "critic_approved": True,
        "critic_risk_score": 0.18,
        "critic_reasons": ["Lead matches ICP", "Email domain verified"],
        "rationale": "Qualified inbound; ICP match with verified domain.",
        "action": {"action_type": "create_crm_lead", "parameters": {"company": "Soylent", "score": 0.72}},
        "trigger": {"company": "Soylent", "source": "webinar"},
        "context": _ctx(
            [("hubspot", "Soylent", "Attended security webinar, 200 employees")],
            ["Soylent -[INDUSTRY]-> saas"],
            600,
        ),
    },
    {
        "workflow_name": "refund_automation",
        "status": "rejected",
        "critic_approved": False,
        "critic_risk_score": 0.79,
        "critic_reasons": ["Refund amount exceeds original charge", "Possible duplicate request"],
        "rationale": "Requested refund larger than the captured charge; blocked.",
        "action": {"action_type": "stripe_refund", "parameters": {"amount_cents": 50000, "order_id": "ORD-3110"}},
        "trigger": {"order_id": "ORD-3110", "amount_usd": 500.0, "reason": "Changed mind"},
        "context": _ctx(
            [("stripe", "Charge ch_3110", "$300.00 captured — request asks for $500")],
            ["ORD-3110 -[CHARGED_ON]-> Stripe:ch_3110"],
            900,
        ),
    },
    {
        "workflow_name": "ticket_escalation",
        "status": "completed",
        "critic_approved": True,
        "critic_risk_score": 0.22,
        "critic_reasons": ["Within SLA policy for standard escalation"],
        "rationale": "Standard escalation within policy; routed to on-call.",
        "action": {"action_type": "jira_escalate", "parameters": {"assignee": "support-lead@company.com"}},
        "trigger": {"ticket_id": "TKT-0934", "priority": "high"},
        "context": _ctx(
            [("jira", "TKT-0934", "High priority, within SLA window")],
            ["TKT-0934 -[AFFECTS]-> Tenant:initech"],
            1200,
        ),
    },
]

_SKILL_DEF = {
    "name": "Refund Processing",
    "description": "Standard operating procedure for handling customer refund requests.",
    "trigger_keywords": ["refund", "money back", "return"],
    "trigger_conditions": ["topic == refund"],
    "steps": [
        {"step_number": 1, "action_name": "check_policy", "description": "Verify refund eligibility", "required_inputs": ["order_id"]},
        {"step_number": 2, "action_name": "issue_refund", "description": "Process the refund", "required_inputs": ["amount"], "requires_human_approval": True},
    ],
    "guardrails": ["Never refund more than the original charge", "Require approval above $100"],
}

# Timestamped invariants the CriticCalibrator has learned (the visible moat).
_POLICY_HISTORY = [
    {
        "rule": "Reject any subscription refund if the purchase date is > 30 days ago.",
        "source": "human_feedback",
        "created_at": (_NOW - timedelta(days=21)).isoformat(),
        "feedback_count": 3,
    },
    {
        "rule": "Require director sign-off for retention discounts above 15%.",
        "source": "human_feedback",
        "created_at": (_NOW - timedelta(days=12)).isoformat(),
        "feedback_count": 2,
    },
    {
        "rule": "Never deploy to production without a recorded staging validation run.",
        "source": "human_feedback",
        "created_at": (_NOW - timedelta(days=5)).isoformat(),
        "feedback_count": 4,
    },
    {
        "rule": "Block any refund whose amount exceeds the original captured charge.",
        "source": "human_feedback",
        "created_at": (_NOW - timedelta(days=2)).isoformat(),
        "feedback_count": 1,
    },
]

_TENANT_SETTINGS = {
    "seed_version": _SEED_VERSION,
    "critic_rules": [h["rule"] for h in _POLICY_HISTORY],
    "policy_history": _POLICY_HISTORY,
    "accumulated_llm_cost": 4.82,
    "total_input_tokens": 184_300,
    "total_output_tokens": 38_900,
}


async def seed() -> None:
    await init_db()

    async with get_db_session() as session:
        # 1. Default tenant
        result = await session.execute(select(Tenant).where(Tenant.slug == "default"))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(name="Acme Corp", slug="default")
            session.add(tenant)
            await session.flush()
            logger.info("Created default tenant %s", tenant.id)
        else:
            logger.info("Using existing default tenant %s", tenant.id)

        # 2. Refresh tenant settings (policy history / moat + usage)
        tenant.settings = {**(tenant.settings or {}), **_TENANT_SETTINGS}

        # 3. Clear prior seed runs so re-runs produce clean data. Feedback rows
        #    reference runs via FK, so clear demo feedback first.
        await session.execute(
            delete(FeedbackRecord).where(FeedbackRecord.tenant_id == tenant.id)
        )
        await session.execute(
            delete(WorkflowRun).where(
                WorkflowRun.tenant_id == tenant.id,
                WorkflowRun.triggered_by == "seed_demo",
            )
        )

        # 4. Sample active skill (idempotent)
        skill_exists = await session.execute(
            select(Skill).where(Skill.tenant_id == tenant.id, Skill.slug == "refund-processing")
        )
        if skill_exists.scalar_one_or_none() is None:
            session.add(Skill(
                tenant_id=tenant.id,
                slug="refund-processing",
                name="Refund Processing",
                description=_SKILL_DEF["description"],
                version=3,
                status="active",
                risk_level="medium",
                confidence_score=0.87,
                definition=_SKILL_DEF,
                created_by="seed_demo",
            ))
            logger.info("Created sample skill 'Refund Processing'")

        # 5. Workflow runs with decision-time context snapshots
        for r in _RUNS:
            session.add(WorkflowRun(
                tenant_id=tenant.id,
                workflow_name=r["workflow_name"],
                status=r["status"],
                trigger_data=r["trigger"],
                context_used=r["context"],
                candidate_action={**r["action"], "rationale": r["rationale"]},
                final_action=r["action"],
                critic_approved=r["critic_approved"],
                critic_risk_score=r["critic_risk_score"],
                critic_reasons=r["critic_reasons"],
                steps_executed=[
                    {"name": "retrieve", "status": "success"},
                    {"name": "reason", "status": "success"},
                    {"name": "critic_review", "status": "success"},
                ],
                audit_trail=[{
                    "event": "decision",
                    "rationale": r["rationale"],
                    "at": r["context"]["retrieved_at"],
                }],
                triggered_by="seed_demo",
                created_at=datetime.fromisoformat(r["context"]["retrieved_at"]),
            ))
        logger.info("Created %d sample workflow runs", len(_RUNS))

    logger.info("Seed complete (%s). Open the dashboard to see live data.", _SEED_VERSION)


if __name__ == "__main__":
    asyncio.run(seed())
