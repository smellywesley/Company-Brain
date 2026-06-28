"""
Per-tenant LLM budget enforcement.

A single tenant must not be able to run up an unbounded LLM bill or starve
others. Spend is accumulated per calendar month in ``tenant.settings`` by the
``tasks.accumulate_llm_cost`` Celery task (the single writer, which also handles
the monthly rollover). This module is the *read / enforce* side:

    spent  = tenant.settings["accumulated_llm_cost"]   (current month)
    budget = tenant.settings["llm_monthly_budget_usd"] or env default
    over   = budget > 0 and spent >= budget

Budget resolution (first non-zero wins):
    1. per-tenant override  tenant.settings["llm_monthly_budget_usd"]
    2. env default          DEFAULT_LLM_MONTHLY_BUDGET_USD
    3. 0 / unset            => UNLIMITED (no enforcement)

A budget of 0 means "no cap" so existing tenants are never surprise-blocked;
enforcement is opt-in by configuring a budget.

Failure policy: this is a COST control, not a safety lock. If the budget cannot
be read (DB blip), we **fail open** (allow the call) and log — a transient DB
error must not take the whole product offline. Being *over* a readable budget
fails closed (blocks).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from uuid import UUID

logger = logging.getLogger("company_brain.budget")

_BUDGET_KEY = "llm_monthly_budget_usd"
_SPENT_KEY = "accumulated_llm_cost"
_PERIOD_KEY = "cost_period_start"  # "YYYY-MM" of the current accumulation window


class BudgetExceededError(Exception):
    """Raised when a tenant's LLM spend has reached its monthly budget.

    The message is intentionally generic (no internal billing breakdown) so it
    is safe to surface; structured fields are available for logging/audit.
    """

    def __init__(self, tenant_id: str, spent: float, budget: float) -> None:
        self.tenant_id = tenant_id
        self.spent = spent
        self.budget = budget
        super().__init__("Monthly LLM budget reached for this workspace.")


def current_period() -> str:
    """Current accumulation window key, ``YYYY-MM`` (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def resolve_budget(settings: dict) -> float:
    """Return the effective monthly budget in USD (0 = unlimited)."""
    override = settings.get(_BUDGET_KEY)
    try:
        if override is not None and float(override) > 0:
            return float(override)
    except (TypeError, ValueError):
        logger.warning("Invalid %s in tenant settings: %r", _BUDGET_KEY, override)

    env_default = os.getenv("DEFAULT_LLM_MONTHLY_BUDGET_USD", "0")
    try:
        return max(0.0, float(env_default))
    except ValueError:
        return 0.0


def _spent_this_period(settings: dict) -> float:
    """Spend within the *current* month. If the stored window is a past month,
    treat spend as 0 so a new month starts fresh even before the writer resets
    it (prevents a tenant being permanently blocked across the month boundary)."""
    spent = float(settings.get(_SPENT_KEY, 0.0) or 0.0)
    period = settings.get(_PERIOD_KEY)
    if period and str(period)[:7] != current_period():
        return 0.0
    return spent


def evaluate(settings: dict) -> dict:
    """Pure budget evaluation from a settings dict (no I/O — easy to test)."""
    budget = resolve_budget(settings)
    if budget <= 0:
        return {"unlimited": True, "budget": 0.0, "spent": 0.0, "remaining": None, "exceeded": False}
    spent = _spent_this_period(settings)
    return {
        "unlimited": False,
        "budget": round(budget, 4),
        "spent": round(spent, 6),
        "remaining": round(max(0.0, budget - spent), 6),
        "exceeded": spent >= budget,
    }


async def get_budget_status(tenant_id: str) -> dict:
    """Read the tenant's settings and return its budget status."""
    from app.db.database import get_db_session
    from app.db.models import Tenant

    async with get_db_session() as session:
        tenant = await session.get(Tenant, UUID(str(tenant_id)))
        settings = (tenant.settings if tenant else {}) or {}
    return evaluate(settings)


async def enforce_budget(tenant_id: str) -> None:
    """Raise ``BudgetExceededError`` if the tenant is at/over its monthly budget.

    Fails open on infra errors (logs a warning) — a cost control must not become
    an availability risk.
    """
    if not tenant_id:
        return
    try:
        status = await get_budget_status(tenant_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Budget check failed for tenant %s (%s) — allowing (fail-open)", tenant_id, exc)
        return

    if status.get("exceeded"):
        logger.warning(
            "LLM budget BLOCK tenant=%s spent=%.6f budget=%.4f — refusing LLM call",
            tenant_id, status["spent"], status["budget"],
        )
        raise BudgetExceededError(tenant_id, status["spent"], status["budget"])
