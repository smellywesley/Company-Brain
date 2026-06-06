"""
Tests for the Contradiction Handshake: the CriticAgent quarantine veto and the
ContradictionSynthesizer report parsing.

No live Redis or LLM — the quarantine lookup and the model call are stubbed, so
these run anywhere (matching the suite's pure-module convention).
"""

from __future__ import annotations

import pytest

from app.agents.critic_agent import CriticAgent
from app.agents.llm_adapter import LLMAdapter, LLMResponse
from app.services.contradiction.synthesizer import ContradictionSynthesizer


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_critic() -> CriticAgent:
    return CriticAgent(llm=LLMAdapter(provider="gemini", api_key="test-key"))


class _StubLLM:
    """Minimal stand-in for LLMAdapter used by the synthesizer tests."""

    def __init__(self, content: str = "", raises: bool = False) -> None:
        self._content = content
        self._raises = raises

    async def generate(self, system_prompt, user_prompt, metadata=None, **_kw):
        if self._raises:
            raise RuntimeError("provider down")
        return LLMResponse(content=self._content)

    async def close(self) -> None:  # pragma: no cover - parity with real adapter
        pass


# ── CriticAgent quarantine veto ──────────────────────────────────────────────

async def test_quarantine_lock_vetoes_action(monkeypatch):
    """A locked SOP is rejected deterministically, before any LLM call."""
    monkeypatch.setattr(
        "app.services.quarantine.lock.get_sync",
        lambda tenant_id, skill_id: {"pr_ref": "PR #842", "summary": "OAuth2 replaced by gRPC tokens"},
    )

    # If the veto fires correctly, the LLM is never consulted. Make it explode
    # if it is, so a regression that skips the gate fails loudly.
    async def _boom(*_a, **_k):
        raise AssertionError("LLM must not be called when the SOP is quarantined")

    critic = _make_critic()
    monkeypatch.setattr(critic.llm, "generate", _boom)

    verdict = await critic.critique(
        candidate_action={"action_type": "refund", "parameters": {"amount": 10}},
        context={"tenant_id": "t1", "skill_id": "s1"},
    )

    assert verdict.approved is False
    assert verdict.risk_score == 1.0
    assert "PR #842" in verdict.reasons[0]
    assert "conflict review" in verdict.reasons[0]


async def test_no_lock_falls_through_to_llm(monkeypatch):
    """With no lock, the critic proceeds to its normal LLM review."""
    monkeypatch.setattr("app.services.quarantine.lock.get_sync", lambda t, s: None)

    critic = _make_critic()

    async def _approve(*_a, **_k):
        return LLMResponse(content='{"approved": true, "risk_score": 0.1, "reasons": ["within policy"]}')

    monkeypatch.setattr(critic.llm, "generate", _approve)

    verdict = await critic.critique(
        candidate_action={"action_type": "refund", "parameters": {"amount": 10}},
        context={"tenant_id": "t1", "skill_id": "s1"},
    )

    assert verdict.approved is True
    assert verdict.risk_score == 0.1


async def test_missing_identity_skips_quarantine(monkeypatch):
    """Without tenant_id/skill_id the gate is skipped and Redis is never touched."""
    def _explode(*_a, **_k):
        raise AssertionError("quarantine must not be queried without identity")

    monkeypatch.setattr("app.services.quarantine.lock.get_sync", _explode)

    critic = _make_critic()

    async def _approve(*_a, **_k):
        return LLMResponse(content='{"approved": true, "risk_score": 0.0, "reasons": []}')

    monkeypatch.setattr(critic.llm, "generate", _approve)

    verdict = await critic.critique(candidate_action={"action_type": "noop"}, context={})
    assert verdict.approved is True


async def test_redis_failure_falls_through(monkeypatch):
    """If the quarantine lookup raises, the critic logs and uses standard review."""
    def _down(*_a, **_k):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr("app.services.quarantine.lock.get_sync", _down)

    critic = _make_critic()

    async def _approve(*_a, **_k):
        return LLMResponse(content='{"approved": true, "risk_score": 0.2, "reasons": ["ok"]}')

    monkeypatch.setattr(critic.llm, "generate", _approve)

    verdict = await critic.critique(
        candidate_action={"action_type": "noop"},
        context={"tenant_id": "t1", "skill_id": "s1"},
    )
    assert verdict.approved is True  # did not crash on infra failure


# ── ContradictionSynthesizer parsing ─────────────────────────────────────────

async def test_synthesizer_detects_real_conflict():
    payload = (
        '{"no_contradiction": false, "affected_skill_id": "s1", "severity": "high",'
        ' "confidence": 0.9, "conflicts": [{"summary": "Replaced OAuth2 /token with'
        ' gRPC token endpoint", "sop_step": "Step 2", "new_reality": "gRPC",'
        ' "referenced_entities": ["/token"]}]}'
    )
    synth = ContradictionSynthesizer(_StubLLM(payload))
    report = await synth.synthesize("PR #842: drop OAuth2", "Step 2: get OAuth2 token", "s1")

    assert report["no_contradiction"] is False
    assert report["severity"] == "high"
    assert report["conflicts"][0]["referenced_entities"] == ["/token"]


async def test_synthesizer_reports_no_conflict():
    synth = ContradictionSynthesizer(_StubLLM('{"no_contradiction": true, "conflicts": []}'))
    report = await synth.synthesize("PR #1: typo fix", "Step 2: get OAuth2 token", "s1")
    assert report["no_contradiction"] is True
    assert report["conflicts"] == []


async def test_synthesizer_fails_open_on_garbage():
    """Malformed model output must NOT quarantine a healthy SOP."""
    synth = ContradictionSynthesizer(_StubLLM("not json at all"))
    report = await synth.synthesize("PR #2", "Step 2", "s1")
    assert report["no_contradiction"] is True
    assert report["affected_skill_id"] == "s1"


async def test_synthesizer_fails_open_on_provider_error():
    synth = ContradictionSynthesizer(_StubLLM(raises=True))
    report = await synth.synthesize("PR #3", "Step 2", "s1")
    assert report["no_contradiction"] is True


async def test_synthesizer_empty_conflicts_overrides_flag():
    """Model claims a conflict but supplies none -> treated as no conflict."""
    synth = ContradictionSynthesizer(_StubLLM('{"no_contradiction": false, "conflicts": []}'))
    report = await synth.synthesize("PR #4", "Step 2", "s1")
    assert report["no_contradiction"] is True
