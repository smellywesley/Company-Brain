"""
Tests for CriticAgent verdict validation hardening: the model's own JSON
verdict is untrusted output, so malformed/anomalous fields must fail closed
(REJECT) rather than being coerced or silently accepted.

No live LLM — ``critic.llm.generate`` is monkeypatched, matching the suite's
pure-module convention (see test_contradiction.py).
"""

from __future__ import annotations

from app.agents.critic_agent import CriticAgent
from app.agents.llm_adapter import LLMAdapter, LLMResponse


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_critic() -> CriticAgent:
    return CriticAgent(llm=LLMAdapter(provider="gemini", api_key="test-key"))


async def _critique_with(monkeypatch, content):
    critic = _make_critic()

    async def _respond(*_a, **_k):
        return LLMResponse(content=content)

    monkeypatch.setattr(critic.llm, "generate", _respond)
    return await critic.critique(candidate_action={"action_type": "noop"}, context={})


# ── Anomalous verdict shapes → fail closed ──────────────────────────────────

async def test_top_level_array_rejected(monkeypatch):
    verdict = await _critique_with(monkeypatch, "[1, 2]")
    assert verdict.approved is False
    assert verdict.risk_score == 1.0


async def test_string_approved_rejected(monkeypatch):
    verdict = await _critique_with(monkeypatch, '{"approved": "true", "risk_score": 0.1}')
    assert verdict.approved is False


async def test_int_approved_rejected(monkeypatch):
    verdict = await _critique_with(monkeypatch, '{"approved": 1, "risk_score": 0.1}')
    assert verdict.approved is False


async def test_non_numeric_risk_score_rejected(monkeypatch):
    verdict = await _critique_with(monkeypatch, '{"approved": true, "risk_score": "low"}')
    assert verdict.approved is False
    assert verdict.risk_score == 1.0


async def test_numeric_string_risk_score_rejected(monkeypatch):
    # Deliberate behavior change: numeric strings used to pass via float();
    # now they fail closed instead of being silently coerced.
    verdict = await _critique_with(monkeypatch, '{"approved": true, "risk_score": "0.7"}')
    assert verdict.approved is False


async def test_nan_risk_score_rejected(monkeypatch):
    verdict = await _critique_with(monkeypatch, '{"approved": true, "risk_score": NaN}')
    assert verdict.approved is False


async def test_infinity_risk_score_rejected(monkeypatch):
    verdict = await _critique_with(monkeypatch, '{"approved": true, "risk_score": Infinity}')
    assert verdict.approved is False


# ── Clamping ─────────────────────────────────────────────────────────────────

async def test_risk_score_above_one_clamped(monkeypatch):
    verdict = await _critique_with(
        monkeypatch, '{"approved": true, "risk_score": 1.7, "reasons": ["ok"]}'
    )
    assert verdict.approved is True
    assert verdict.risk_score == 1.0


async def test_risk_score_below_zero_clamped(monkeypatch):
    verdict = await _critique_with(
        monkeypatch, '{"approved": true, "risk_score": -0.3, "reasons": ["ok"]}'
    )
    assert verdict.approved is True
    assert verdict.risk_score == 0.0


async def test_int_risk_score_coerced_to_float(monkeypatch):
    # Guards the bool-before-int isinstance ordering and int -> float coercion.
    verdict = await _critique_with(
        monkeypatch, '{"approved": true, "risk_score": 1, "reasons": ["ok"]}'
    )
    assert verdict.approved is True
    assert verdict.risk_score == 1.0
    assert isinstance(verdict.risk_score, float)


async def test_missing_risk_score_defaults_to_half(monkeypatch):
    verdict = await _critique_with(monkeypatch, '{"approved": true}')
    assert verdict.approved is True
    assert verdict.risk_score == 0.5


# ── Valid passthrough ────────────────────────────────────────────────────────

async def test_valid_approve_passthrough(monkeypatch):
    verdict = await _critique_with(
        monkeypatch,
        '{"approved": true, "risk_score": 0.2, "reasons": ["within policy"],'
        ' "suggested_modifications": {"note": "x"}}',
    )
    assert verdict.approved is True
    assert verdict.risk_score == 0.2
    assert verdict.reasons == ["within policy"]
    assert verdict.suggested_modifications == {"note": "x"}


async def test_valid_reject_passthrough(monkeypatch):
    verdict = await _critique_with(
        monkeypatch, '{"approved": false, "risk_score": 0.9, "reasons": ["PII risk"]}'
    )
    assert verdict.approved is False
    assert verdict.risk_score == 0.9
    assert verdict.reasons == ["PII risk"]


async def test_non_list_reasons_defaults_to_empty(monkeypatch):
    verdict = await _critique_with(
        monkeypatch, '{"approved": true, "risk_score": 0.2, "reasons": "fine"}'
    )
    assert verdict.approved is True
    assert verdict.reasons == []


# ── None content ─────────────────────────────────────────────────────────────

async def test_none_content_rejected(monkeypatch):
    verdict = await _critique_with(monkeypatch, None)
    assert verdict.approved is False
    assert verdict.risk_score == 1.0
