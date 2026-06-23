"""Tests for the universal OODA ingestion pipeline (core graph engine)."""

import pytest

from app.services.observe.pipeline import (
    heuristic_triplets,
    observe,
    _raw_text,
)


def test_heuristic_extracts_triplet():
    triplets = heuristic_triplets("Stripe refunded Order ORD-7291 today.", "Shopify")
    assert triplets
    t = triplets[0]
    assert t["subject"] and t["predicate"] == "refunded" and t["object"]


def test_heuristic_always_returns_something():
    triplets = heuristic_triplets("lorem ipsum nothing structured", "Bloomberg")
    assert len(triplets) == 1
    assert triplets[0]["attributes"]["low_signal"] is True


def test_raw_text_flattens_nested_payload():
    text = _raw_text({"data": {"order": {"id": "ORD-1", "amount": 349}}})
    assert "ORD-1" in text and "349" in text


@pytest.mark.asyncio
async def test_escape_hatch_no_contradiction():
    """No stale artifact -> no conflict, no quarantine, triplets still emitted."""
    out = await observe(
        tenant_id="t1",
        source_platform="Shopify",
        industry_vertical="ecommerce",
        raw_payload={"data": "Stripe refunded Order ORD-9 for the customer."},
    )
    assert out["has_contradiction"] is False
    assert out["conflicts"] == []
    assert out["quarantine_locked"] is False
    assert out["extracted_triplets"]
    assert 0.0 <= out["confidence_score"] <= 1.0


@pytest.mark.asyncio
async def test_quarantine_preflight_hard_rejects():
    """A locked skill halts ingestion with a hard-reject contract."""
    def fake_lock(tenant_id, skill_id):
        return {"pr_ref": "PR-42", "summary": "refund policy under review"}

    out = await observe(
        tenant_id="t1",
        source_platform="Stripe",
        industry_vertical="fintech",
        raw_payload={"data": "Stripe refunded Order ORD-9."},
        skill_id="refund-processing",
        quarantine_get=fake_lock,
    )
    assert out["has_contradiction"] is True
    assert out["quarantine_locked"] is True
    assert "HARD REJECT" in out["quarantine_summary"]
    assert "PR-42" in out["quarantine_summary"]
    assert out["extracted_triplets"] == []  # halted before extraction


@pytest.mark.asyncio
async def test_unlocked_skill_proceeds():
    def fake_unlocked(tenant_id, skill_id):
        return None

    out = await observe(
        tenant_id="t1",
        source_platform="GitHub",
        industry_vertical="tmt",
        raw_payload={"data": "Engineer deployed Service billing to prod."},
        skill_id="deploy",
        quarantine_get=fake_unlocked,
    )
    assert out["quarantine_locked"] is False
    assert out["extracted_triplets"]


@pytest.mark.asyncio
async def test_contradiction_synthesis_maps_conflicts():
    async def fake_synth(*, new_reality, stale_artifact, skill_id, tenant_id=None):
        return {
            "no_contradiction": False,
            "severity": "high",
            "conflicts": [
                {
                    "stale_reference": "SOP: refund within 30 days",
                    "new_reality": "refund requested at 45 days",
                    "severity": "high",
                    "affected_entities": ["Order ORD-9", "Refund Policy"],
                }
            ],
        }

    out = await observe(
        tenant_id="t1",
        source_platform="Stripe",
        industry_vertical="fintech",
        raw_payload={"data": "Refund requested 45 days after purchase."},
        skill_id="refund-processing",
        stale_artifact="Refunds allowed within 30 days.",
        synthesize=fake_synth,
    )
    assert out["has_contradiction"] is True
    assert len(out["conflicts"]) == 1
    c = out["conflicts"][0]
    assert c["severity"] == "HIGH"
    assert "Order ORD-9" in c["blast_radius_nodes"]
