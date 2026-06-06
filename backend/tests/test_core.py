"""
Unit tests for the Company Brain backend.

Tests cover: Pydantic schema validation, skill signing, skill simulation,
anomaly detection, pattern detection, and entity deduplication.
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

import pytest


# ── Skill Schema Tests ──────────────────────────────────────────────────────

class TestSkillSchemas:
    """Test Pydantic validation of SkillDefinition and related schemas."""

    def test_valid_skill_definition(self):
        from app.schemas.skill import SkillDefinition
        skill = SkillDefinition(
            name="Test Skill",
            description="A test skill",
            trigger_keywords=["test"],
            trigger_conditions=["data.type == test"],
            steps=[
                {
                    "step_number": 1,
                    "action_name": "test_action",
                    "description": "Do something",
                    "required_inputs": ["input_a"],
                }
            ],
            guardrails=["Never do X"],
        )
        assert skill.name == "Test Skill"
        assert len(skill.steps) == 1
        assert skill.steps[0].step_number == 1

    def test_step_ordering_validation(self):
        from app.schemas.skill import SkillDefinition
        # Steps out of order should be sorted automatically
        skill = SkillDefinition(
            name="Ordered Skill",
            description="Testing step ordering",
            steps=[
                {"step_number": 2, "action_name": "second", "description": "Step 2"},
                {"step_number": 1, "action_name": "first", "description": "Step 1"},
            ],
        )
        assert skill.steps[0].step_number == 1
        assert skill.steps[1].step_number == 2

    def test_non_sequential_steps_rejected(self):
        from app.schemas.skill import SkillDefinition
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SkillDefinition(
                name="Bad Skill",
                description="Testing bad ordering",
                steps=[
                    {"step_number": 1, "action_name": "first", "description": "Step 1"},
                    {"step_number": 3, "action_name": "third", "description": "Step 3"},
                ],
            )

    def test_empty_steps_rejected(self):
        from app.schemas.skill import SkillDefinition
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SkillDefinition(
                name="No Steps",
                description="No steps defined",
                steps=[],
            )

    def test_short_name_rejected(self):
        from app.schemas.skill import SkillDefinition
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SkillDefinition(
                name="AB",  # Too short (min 3)
                description="Short name",
                steps=[{"step_number": 1, "action_name": "a", "description": "d"}],
            )

    def test_generate_response_risk_validation(self):
        from app.schemas.skill import SkillGenerateResponse, SkillDefinition
        from pydantic import ValidationError

        valid_def = SkillDefinition(
            name="Test Skill",
            description="desc",
            steps=[{"step_number": 1, "action_name": "a", "description": "d"}],
        )
        # Valid risk level
        resp = SkillGenerateResponse(
            definition=valid_def, confidence_score=0.85, risk_level="medium", reasoning="test"
        )
        assert resp.risk_level == "medium"

        # Invalid risk level
        with pytest.raises(ValidationError):
            SkillGenerateResponse(
                definition=valid_def, confidence_score=0.85, risk_level="extreme", reasoning="test"
            )


# ── Skill Signing Tests ─────────────────────────────────────────────────────

class TestSkillSigning:
    """Test HMAC-SHA256 signing and verification."""

    def test_sign_produces_hex_digest(self):
        from app.services.security.skill_signing import SkillSigner
        signer = SkillSigner(signing_key="test-key-1234567890123456")
        definition = {"name": "test", "steps": []}
        sig = signer.sign(definition)
        assert len(sig) == 64  # SHA-256 hex digest length
        assert all(c in "0123456789abcdef" for c in sig)

    def test_verify_valid_signature(self):
        from app.services.security.skill_signing import SkillSigner
        signer = SkillSigner(signing_key="test-key-1234567890123456")
        definition = {"name": "test", "steps": [{"a": 1}]}
        sig = signer.sign(definition)
        assert signer.verify(definition, sig) is True

    def test_verify_tampered_definition(self):
        from app.services.security.skill_signing import SkillSigner
        signer = SkillSigner(signing_key="test-key-1234567890123456")
        definition = {"name": "test", "steps": []}
        sig = signer.sign(definition)
        # Tamper with the definition
        tampered = {"name": "test", "steps": [{"malicious": True}]}
        assert signer.verify(tampered, sig) is False

    def test_deterministic_signing(self):
        from app.services.security.skill_signing import SkillSigner
        signer = SkillSigner(signing_key="test-key-1234567890123456")
        definition = {"b": 2, "a": 1}
        sig1 = signer.sign(definition)
        sig2 = signer.sign(definition)
        assert sig1 == sig2  # Must be deterministic

    def test_no_key_returns_empty(self):
        from app.services.security.skill_signing import SkillSigner
        signer = SkillSigner(signing_key="")
        sig = signer.sign({"name": "test"})
        assert sig == ""


# ── Skill Simulator Tests ───────────────────────────────────────────────────

class TestSkillSimulator:
    """Test deterministic skill simulation against historical data."""

    def test_empty_history_passes(self):
        from app.services.security.skill_simulator import SkillSimulator
        sim = SkillSimulator()
        result = sim.simulate({"steps": [], "guardrails": []}, [])
        assert result.passed is True
        assert result.total_cases == 0

    def test_all_successful_history_passes(self):
        from app.services.security.skill_simulator import SkillSimulator
        sim = SkillSimulator()
        history = [
            {"trigger_data": {"amount": 50}, "final_action": {}, "status": "completed", "critic_approved": True},
            {"trigger_data": {"amount": 99}, "final_action": {}, "status": "completed", "critic_approved": True},
        ]
        result = sim.simulate({"steps": [], "trigger_conditions": [], "guardrails": []}, history)
        assert result.passed is True
        assert result.pass_rate == 1.0

    def test_condition_evaluation(self):
        from app.services.security.skill_simulator import SkillSimulator
        sim = SkillSimulator()
        assert sim._evaluate_condition("amount < 100", {"amount": 50}) is True
        assert sim._evaluate_condition("amount < 100", {"amount": 150}) is False
        assert sim._evaluate_condition("topic == refund", {"topic": "refund"}) is True
        assert sim._evaluate_condition("topic == refund", {"topic": "support"}) is False


# ── Pattern Detector Tests ──────────────────────────────────────────────────

class TestPatternDetector:
    """Test embedding clustering for pattern detection."""

    def test_empty_input(self):
        from app.services.skills_generator.pattern_detector import PatternDetector
        detector = PatternDetector()
        assert detector.detect_clusters([], []) == []

    def test_too_few_documents(self):
        from app.services.skills_generator.pattern_detector import PatternDetector
        detector = PatternDetector(min_cluster_size=3)
        clusters = detector.detect_clusters(
            ["a", "b"],
            [[0.1, 0.2], [0.3, 0.4]],
        )
        assert clusters == []

    def test_detects_similar_documents(self):
        from app.services.skills_generator.pattern_detector import PatternDetector
        detector = PatternDetector(distance_threshold=0.3, min_cluster_size=2)
        # Create 4 near-identical vectors + 1 outlier
        texts = ["refund a", "refund b", "refund c", "refund d", "deploy x"]
        embeddings = [
            [0.9, 0.1, 0.0],
            [0.88, 0.12, 0.01],
            [0.91, 0.09, 0.0],
            [0.87, 0.13, 0.02],
            [0.1, 0.1, 0.9],  # Outlier
        ]
        clusters = detector.detect_clusters(texts, embeddings)
        assert len(clusters) >= 1
        # The refund cluster should have at least the 4 similar docs
        refund_cluster = max(clusters, key=lambda c: len(c.texts))
        assert len(refund_cluster.texts) >= 3


# ── Entity Deduplicator Tests ───────────────────────────────────────────────

class TestEntityDeduplicator:
    """Test entity deduplication heuristics."""

    def test_case_insensitive_match(self):
        from app.services.knowledge_graph.deduplicator import EntityDeduplicator
        dedup = EntityDeduplicator()
        score = dedup._similarity("JavaScript", "javascript")
        assert score == 1.0

    def test_abbreviation_match(self):
        from app.services.knowledge_graph.deduplicator import EntityDeduplicator
        dedup = EntityDeduplicator()
        score = dedup._similarity("JS", "javascript")
        assert score >= 0.9

    def test_substring_match(self):
        from app.services.knowledge_graph.deduplicator import EntityDeduplicator
        dedup = EntityDeduplicator()
        score = dedup._similarity("Company Brain", "Company Brain Platform")
        assert score >= 0.8

    def test_no_match(self):
        from app.services.knowledge_graph.deduplicator import EntityDeduplicator
        dedup = EntityDeduplicator()
        score = dedup._similarity("Python", "React")
        assert score < 0.5

    def test_plural_match(self):
        from app.services.knowledge_graph.deduplicator import EntityDeduplicator
        dedup = EntityDeduplicator()
        score = dedup._similarity("workflows", "workflow")
        assert score >= 0.9


# ── LLM Adapter Tests ───────────────────────────────────────────────────────

class TestLLMAdapter:
    """Test LLM adapter configuration."""

    def test_invalid_provider_raises(self):
        from app.agents.llm_adapter import LLMAdapter
        with pytest.raises(ValueError, match="Unsupported provider"):
            LLMAdapter(provider="invalid", api_key="key")

    def test_cost_estimation(self):
        from app.agents.llm_adapter import LLMAdapter
        adapter = LLMAdapter(provider="openai", api_key="test", model="gpt-4o")
        cost = adapter.estimate_cost({"input_tokens": 1000, "output_tokens": 500})
        assert cost > 0

    def test_default_model_selection(self):
        from app.agents.llm_adapter import LLMAdapter
        gemini = LLMAdapter(provider="gemini", api_key="test")
        assert "gemini" in gemini.model.lower()
        openai = LLMAdapter(provider="openai", api_key="test")
        assert "gpt" in openai.model.lower()


# ── RBAC Tests ──────────────────────────────────────────────────────────────

class TestRBAC:
    """Test role-based access control policy."""

    def test_admin_has_all_permissions(self):
        from app.middleware.rbac import RBACPolicy
        rbac = RBACPolicy()
        assert rbac.check_permission("admin", "read", "any") is True
        assert rbac.check_permission("admin", "write", "any") is True
        assert rbac.check_permission("admin", "execute_workflow", "any") is True

    def test_viewer_read_only(self):
        from app.middleware.rbac import RBACPolicy
        rbac = RBACPolicy()
        assert rbac.check_permission("viewer", "read", "any") is True
        assert rbac.check_permission("viewer", "write", "any") is False

    def test_unknown_role_denied(self):
        from app.middleware.rbac import RBACPolicy
        rbac = RBACPolicy()
        assert rbac.check_permission("hacker", "read", "any") is False
