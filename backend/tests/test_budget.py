"""
Per-tenant LLM budget enforcement.

Pure evaluation is tested directly; enforcement and the runner block path use
monkeypatching so no live DB is needed.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.budget import limiter
from app.services.budget.limiter import BudgetExceededError


# ── resolve_budget ────────────────────────────────────────────────────────────

def test_per_tenant_override_wins(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_MONTHLY_BUDGET_USD", "100")
    assert limiter.resolve_budget({"llm_monthly_budget_usd": 25}) == 25.0


def test_env_default_used_when_no_override(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_MONTHLY_BUDGET_USD", "50")
    assert limiter.resolve_budget({}) == 50.0


def test_zero_budget_means_unlimited(monkeypatch):
    monkeypatch.delenv("DEFAULT_LLM_MONTHLY_BUDGET_USD", raising=False)
    assert limiter.resolve_budget({}) == 0.0
    assert limiter.evaluate({})["unlimited"] is True


def test_invalid_override_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_LLM_MONTHLY_BUDGET_USD", "30")
    assert limiter.resolve_budget({"llm_monthly_budget_usd": "not-a-number"}) == 30.0


# ── evaluate ──────────────────────────────────────────────────────────────────

def test_under_budget_not_exceeded():
    s = {"llm_monthly_budget_usd": 10, "accumulated_llm_cost": 4.0, "cost_period_start": limiter.current_period()}
    res = limiter.evaluate(s)
    assert res["exceeded"] is False
    assert res["remaining"] == pytest.approx(6.0)


def test_at_or_over_budget_exceeded():
    s = {"llm_monthly_budget_usd": 10, "accumulated_llm_cost": 10.0, "cost_period_start": limiter.current_period()}
    assert limiter.evaluate(s)["exceeded"] is True
    s["accumulated_llm_cost"] = 12.5
    assert limiter.evaluate(s)["exceeded"] is True


def test_past_month_spend_resets_for_enforcement():
    """A prior-month spend window must not block the new month."""
    s = {"llm_monthly_budget_usd": 10, "accumulated_llm_cost": 999.0, "cost_period_start": "2000-01"}
    res = limiter.evaluate(s)
    assert res["spent"] == 0.0
    assert res["exceeded"] is False


# ── enforce_budget ────────────────────────────────────────────────────────────

async def test_enforce_blocks_when_over(monkeypatch):
    async def _status(_tid):
        return {"exceeded": True, "spent": 12.0, "budget": 10.0}

    monkeypatch.setattr(limiter, "get_budget_status", _status)
    with pytest.raises(BudgetExceededError):
        await limiter.enforce_budget("t1")


async def test_enforce_allows_when_under(monkeypatch):
    async def _status(_tid):
        return {"exceeded": False, "spent": 1.0, "budget": 10.0}

    monkeypatch.setattr(limiter, "get_budget_status", _status)
    await limiter.enforce_budget("t1")  # no raise


async def test_enforce_fails_open_on_infra_error(monkeypatch):
    async def _boom(_tid):
        raise ConnectionError("db down")

    monkeypatch.setattr(limiter, "get_budget_status", _boom)
    await limiter.enforce_budget("t1")  # fail-open: must not raise


def test_error_message_has_no_billing_internals():
    err = BudgetExceededError("t1", spent=123.456, budget=100.0)
    assert "123" not in str(err) and "100" not in str(err)


# ── runner block path ─────────────────────────────────────────────────────────

async def test_runner_returns_blocked_run_when_over_budget(monkeypatch):
    from app.services.workflow import runner

    async def _match(_tid, _trigger):
        return None, None

    async def _over(_tid):
        raise BudgetExceededError(_tid, spent=12.0, budget=10.0)

    monkeypatch.setattr(runner, "_match_skill", _match)
    monkeypatch.setattr("app.services.budget.enforce_budget", _over)

    result = await runner.run_governed_workflow(
        tenant_id=uuid.uuid4(),
        tenant_settings={},
        workflow_name="refund_automation",
        trigger_data={"order_id": "X"},
        config={},
        persist=False,
    )
    assert result["status"] == "blocked"
    assert result["critic"]["approved"] is False
    assert "budget" in result["audit_trail"][0]["event"]
