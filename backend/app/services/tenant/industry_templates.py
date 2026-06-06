"""
Industry templates + risk posture.

Tailoring a company at onboarding means three things, all derived here:
  - an industry policy pack (starter Critic invariants so the brain is smart on
    day one and then diverges via feedback),
  - default connectors and an accent colour,
  - a risk posture that parameterises the probabilistic forecaster (how high the
    routing threshold sits, the financial auto-approve ceiling, and the maximum
    autonomy level any workflow may reach).

Pure data + pure functions so the onboarding endpoint and the forecaster can
both consume it, and so it is trivially testable.
"""

from __future__ import annotations

from datetime import datetime, timezone


# ── Risk posture → forecaster parameters ─────────────────────────────────────
# threshold_base: centre of the dynamic routing threshold (history still nudges it).
# auto_approve_ceiling_usd: financial actions at/under this can clear without a human.
# max_autonomy_level: cap on the L0-L4 autonomy any workflow may earn.
RISK_POSTURES: dict[str, dict] = {
    "conservative": {
        "label": "Conservative",
        "blurb": "Hold almost everything for a human. Built for regulated work.",
        "threshold_base": 0.35,
        "auto_approve_ceiling_usd": 0,
        "max_autonomy_level": 2,
    },
    "balanced": {
        "label": "Balanced",
        "blurb": "Auto within guardrails, humans on the risky edge.",
        "threshold_base": 0.50,
        "auto_approve_ceiling_usd": 100,
        "max_autonomy_level": 3,
    },
    "aggressive": {
        "label": "Aggressive",
        "blurb": "Maximise autonomy, escalate only clear danger.",
        "threshold_base": 0.65,
        "auto_approve_ceiling_usd": 500,
        "max_autonomy_level": 4,
    },
}

DEFAULT_POSTURE = "balanced"


def posture_params(posture: str | None) -> dict:
    """Return the forecaster parameters for a posture (falls back to balanced)."""
    return RISK_POSTURES.get(posture or DEFAULT_POSTURE, RISK_POSTURES[DEFAULT_POSTURE])


# ── Industry templates ───────────────────────────────────────────────────────
INDUSTRY_TEMPLATES: dict[str, dict] = {
    "fintech": {
        "label": "Fintech / Payments",
        "accent": "#2563eb",
        "suggested_posture": "conservative",
        "connectors": ["slack", "notion", "github"],
        "rules": [
            "Block any refund whose amount exceeds the original captured charge.",
            "Require dual approval for any movement of funds above $100.",
            "Never expose full PAN, SSN, or bank account numbers in any action.",
            "Reject any action lacking a SOC 2 / PCI audit trail entry.",
        ],
    },
    "healthcare": {
        "label": "Healthcare / Life Sciences",
        "accent": "#0891b2",
        "suggested_posture": "conservative",
        "connectors": ["slack", "notion"],
        "rules": [
            "Never include PHI (patient name, MRN, diagnosis) in outbound actions.",
            "Require clinician sign-off before any change to a care record.",
            "Reject any data export without a recorded HIPAA authorization.",
            "Default-deny any cross-system action touching patient identifiers.",
        ],
    },
    "ecommerce": {
        "label": "E-commerce / Retail",
        "accent": "#7c3aed",
        "suggested_posture": "aggressive",
        "connectors": ["slack", "notion", "github"],
        "rules": [
            "Auto-approve refunds under $200 with a valid order and reason.",
            "Reject refunds on orders older than the stated return window.",
            "Flag any discount above 30% for human review.",
            "Block duplicate refunds against the same order id.",
        ],
    },
    "saas": {
        "label": "B2B SaaS",
        "accent": "#0f766e",
        "suggested_posture": "balanced",
        "connectors": ["slack", "notion", "github"],
        "rules": [
            "Require director sign-off for retention discounts above 15%.",
            "Never deploy to production without a recorded staging validation run.",
            "Escalate enterprise-tier tickets past SLA to a manager.",
            "Reject any plan change that bypasses billing reconciliation.",
        ],
    },
}

DEFAULT_INDUSTRY = "saas"


def industry_template(industry: str | None) -> dict:
    """Return the template for an industry (falls back to SaaS)."""
    return INDUSTRY_TEMPLATES.get(industry or DEFAULT_INDUSTRY, INDUSTRY_TEMPLATES[DEFAULT_INDUSTRY])


def build_profile(
    *,
    display_name: str,
    industry: str | None = None,
    risk_posture: str | None = None,
    accent: str | None = None,
) -> dict:
    """Assemble a Company Profile (stored in tenant.settings) from inputs.

    Seeds the industry policy pack into both the flat ``critic_rules`` (consumed
    by the CriticAgent prompt) and the timestamped ``policy_history`` (the moat
    timeline), so a freshly onboarded company has a working, visible policy.
    """
    tmpl = industry_template(industry)
    posture = risk_posture or tmpl["suggested_posture"]
    now = datetime.now(timezone.utc).isoformat()

    rules = list(tmpl["rules"])
    policy_history = [
        {
            "rule": r,
            "source": "industry_template",
            "created_at": now,
            "feedback_count": 0,
        }
        for r in rules
    ]

    return {
        "branding": {
            "display_name": display_name,
            "accent": accent or tmpl["accent"],
            "industry": industry or DEFAULT_INDUSTRY,
            "logo": display_name[:2].upper(),
        },
        "risk_posture": posture,
        "connectors": {c: True for c in tmpl["connectors"]},
        "critic_rules": rules,
        "policy_history": policy_history,
    }
