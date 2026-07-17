"""
Tests for the CriticAgent's YAML-backed base policy (critic_policy.yaml).

Covers: policy loads into the system prompt with its version stamped,
tenant-specific learned rules are still appended unchanged, construction
fails closed when the policy file is missing/corrupt, and the runner
stamps ``policy_version`` into the run's audit trail.
"""

from __future__ import annotations

import uuid

import pytest

from app.agents.critic_agent import CriticAgent
from app.agents.llm_adapter import LLMAdapter


def _make_critic(**kwargs) -> CriticAgent:
    return CriticAgent(llm=LLMAdapter(provider="gemini", api_key="test-key"), **kwargs)


# ── Policy loads into the prompt ─────────────────────────────────────────────

def test_policy_loads_and_prompt_contains_base_rules_and_version():
    critic = _make_critic()
    assert critic.policy_version == 1
    assert "BASE POLICY (v1)" in critic.system_prompt
    assert "No PII leakage" in critic.system_prompt
    assert "Financial limit" in critic.system_prompt


def test_tenant_rules_still_appended():
    critic = _make_critic(tenant_rules=["x"])
    assert "TENANT-SPECIFIC LEARNED RULES" in critic.system_prompt
    assert "- x" in critic.system_prompt
    # Base policy must still be present alongside the learned rules.
    assert "BASE POLICY (v1)" in critic.system_prompt


# ── Fail closed ───────────────────────────────────────────────────────────────

def test_fails_closed_when_policy_file_missing(monkeypatch, tmp_path):
    from app.agents import critic_agent

    monkeypatch.setattr(critic_agent, "_POLICY_PATH", tmp_path / "does_not_exist.yaml")
    critic_agent._load_policy.cache_clear()
    try:
        with pytest.raises(FileNotFoundError):
            _make_critic()
    finally:
        critic_agent._load_policy.cache_clear()


def test_fails_closed_when_policy_missing_rules(monkeypatch, tmp_path):
    from app.agents import critic_agent

    bad_policy = tmp_path / "bad.yaml"
    bad_policy.write_text("version: 1\nrules: []\n", encoding="utf-8")
    monkeypatch.setattr(critic_agent, "_POLICY_PATH", bad_policy)
    critic_agent._load_policy.cache_clear()
    try:
        with pytest.raises(ValueError):
            _make_critic()
    finally:
        critic_agent._load_policy.cache_clear()


# ── Runner stamps policy_version into the audit trail ────────────────────────

async def test_runner_stamps_policy_version(monkeypatch):
    from app.agents.workflow_agent import WorkflowResult
    from app.services.workflow import runner

    class _DummyLLM:
        def estimate_cost(self, _usage):
            return 0.0

        async def close(self):
            pass

    class _FakeCritic:
        def __init__(self, llm, tenant_rules=None):
            self.policy_version = 1

    class _FakeWorkflowAgent:
        def __init__(self, llm, critic, workflow_name, action_executors=None):
            self.workflow_name = workflow_name

        async def execute_workflow(self, workflow_config, trigger_data, matched_skill=None):
            return WorkflowResult(
                workflow_name=self.workflow_name,
                status="completed",
                audit_trail=["did work"],
            )

    async def _match(_tid, _trigger):
        return None, None

    async def _budget_ok(_tid):
        return None

    monkeypatch.setattr(runner, "_match_skill", _match)
    monkeypatch.setattr(runner, "_get_llm", lambda: _DummyLLM())
    monkeypatch.setattr("app.services.budget.enforce_budget", _budget_ok)
    monkeypatch.setattr("app.agents.critic_agent.CriticAgent", _FakeCritic)
    monkeypatch.setattr("app.agents.workflow_agent.WorkflowAgent", _FakeWorkflowAgent)
    monkeypatch.setattr("app.services.executors.registry.load_executors", lambda: {})

    result = await runner.run_governed_workflow(
        tenant_id=uuid.uuid4(),
        tenant_settings={},
        workflow_name="test_wf",
        trigger_data={},
        config={},
        persist=False,
    )

    assert result["audit_trail"] == ["did work", "policy_version=1"]
