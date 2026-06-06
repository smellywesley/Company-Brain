"""Tests for per-company tailoring: industry templates, posture, profile build."""

from app.services.tenant.industry_templates import (
    RISK_POSTURES,
    build_profile,
    industry_template,
    posture_params,
)
from app.services.risk.forecaster import forecast_risk


def test_posture_params_fallback():
    assert posture_params(None)["threshold_base"] == RISK_POSTURES["balanced"]["threshold_base"]
    assert posture_params("nonsense")["max_autonomy_level"] == 3


def test_posture_ordering():
    cons = posture_params("conservative")
    agg = posture_params("aggressive")
    assert cons["threshold_base"] < agg["threshold_base"]
    assert cons["max_autonomy_level"] < agg["max_autonomy_level"]
    assert cons["auto_approve_ceiling_usd"] < agg["auto_approve_ceiling_usd"]


def test_industry_template_seeds_rules():
    t = industry_template("fintech")
    assert t["label"].startswith("Fintech")
    assert any("refund" in r.lower() for r in t["rules"])


def test_build_profile_shape():
    p = build_profile(display_name="Acme Corp", industry="ecommerce")
    assert p["branding"]["display_name"] == "Acme Corp"
    assert p["branding"]["logo"] == "AC"
    assert p["risk_posture"] == "aggressive"  # ecommerce suggested
    assert p["connectors"]["slack"] is True
    assert len(p["critic_rules"]) == len(p["policy_history"]) >= 3


def test_posture_changes_routing():
    """Same critic score routes differently under different postures."""
    score = 0.5
    conservative = forecast_risk(score, n_history=20, threshold_base=0.35, max_autonomy=2)
    aggressive = forecast_risk(score, n_history=20, threshold_base=0.65, max_autonomy=4)
    # Conservative has a lower bar -> more likely routed to a human.
    assert conservative.dynamic_threshold < aggressive.dynamic_threshold
    assert conservative.autonomy_level <= 2
