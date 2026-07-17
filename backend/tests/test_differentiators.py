"""
Tests for the standout-feature backends: probabilistic risk forecasting,
blast-radius simulation, and the tamper-evident audit chain with snapshots.

Pure modules — no DB or network — so they run anywhere.
"""

from types import SimpleNamespace

from app.services.risk.forecaster import (
    calibrate_probability,
    calibration_curve,
    confidence_band,
    dynamic_threshold,
    forecast_risk,
)
from app.services.risk.blast_radius import compute_blast_radius
from app.services.audit.chain import (
    build_chain,
    digest,
    snapshot_of,
    verify_chain,
)


# ── Probabilistic risk forecaster ────────────────────────────────────────────

def test_probability_is_monotonic_in_risk():
    assert calibrate_probability(0.1) < calibrate_probability(0.5) < calibrate_probability(0.9)


def test_probability_bounds():
    assert 0.0 <= calibrate_probability(0.0) <= 1.0
    assert 0.0 <= calibrate_probability(1.0) <= 1.0


def test_confidence_band_narrows_with_history():
    p = 0.5
    _, hi_small = confidence_band(p, n_history=2)
    _, hi_large = confidence_band(p, n_history=200)
    small_width = hi_small - p
    large_width = hi_large - p
    assert large_width < small_width  # more evidence -> tighter band


def test_dynamic_threshold_tightens_with_miss_rate():
    clean = dynamic_threshold(n_history=50, miss_rate=0.0)
    messy = dynamic_threshold(n_history=50, miss_rate=0.8)
    assert messy < clean  # more misses -> lower bar -> more caution
    assert 0.25 <= messy <= 0.75 and 0.25 <= clean <= 0.75


def test_high_risk_routes_to_human():
    f = forecast_risk(0.9, n_history=10, miss_rate=0.1, reasons=["Financial limit exceeded"])
    assert f.routed_to_human is True
    assert f.autonomy_level <= 1


def test_low_risk_with_history_earns_autonomy():
    f = forecast_risk(0.05, n_history=40, miss_rate=0.05, reasons=["Within policy"])
    assert f.routed_to_human is False
    assert f.autonomy_level >= 3


def test_factors_derived_from_reasons():
    f = forecast_risk(0.6, reasons=["Amount exceeds $100 threshold", "PII in payload"])
    labels = {fac.label for fac in f.factors}
    assert "Financial limit" in labels
    assert "PII exposure" in labels


def test_calibration_curve_shape():
    points = [(0.1, False), (0.2, False), (0.8, True), (0.9, True), (0.5, True)]
    curve = calibration_curve(points, bins=5)
    assert len(curve) == 5
    assert all("predicted_mid" in b and "observed" in b for b in curve)


# ── Blast radius ─────────────────────────────────────────────────────────────

def test_blast_radius_refund_touches_finance_systems():
    br = compute_blast_radius("refund_automation", trigger_data={}, final_action={})
    systems = {n.system for n in br.nodes}
    assert "Stripe" in {br.origin.system} or br.origin.system == "Payment processor"
    assert "QuickBooks" in systems  # revenue ledger is touched
    summary = br.summary()
    assert summary["systems_touched"] == len(br.nodes)
    assert summary["highest_severity"] in ("low", "medium", "high")


def test_blast_radius_deploy_is_high_severity():
    br = compute_blast_radius("deploy_approval")
    assert br.summary()["highest_severity"] == "high"


def test_blast_radius_unknown_workflow_has_fallback():
    br = compute_blast_radius("totally_unknown_thing")
    assert len(br.nodes) >= 1
    assert br.simulated is True


# ── Audit chain + time-travel snapshot ───────────────────────────────────────

def _run(rid, name, status, risk, ctx, created):
    return SimpleNamespace(
        id=rid,
        workflow_name=name,
        status=status,
        critic_risk_score=risk,
        critic_reasons=["reason"],
        critic_approved=(status == "completed"),
        context_used=ctx,
        candidate_action={"action_type": name},
        final_action={"action_type": name},
        created_at=created,
    )


def _runs():
    from datetime import datetime, timezone

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        _run("11111111-1111-1111-1111-111111111111", "refund", "completed", 0.1, {"sources": [{"x": 1}]}, base),
        _run("22222222-2222-2222-2222-222222222222", "deploy", "rejected", 0.9, {"sources": []}, base.replace(minute=5)),
        _run("33333333-3333-3333-3333-333333333333", "lead", "completed", 0.2, {"sources": [{"y": 2}]}, base.replace(minute=10)),
    ]


def test_chain_builds_and_verifies():
    chain = build_chain(_runs())
    assert len(chain) == 3
    assert verify_chain(chain) is True
    # genesis link
    assert chain[0]["prev_hash"] == "0" * 64
    # forward linkage
    assert chain[1]["prev_hash"] == chain[0]["entry_hash"]
    assert chain[2]["prev_hash"] == chain[1]["entry_hash"]


def test_chain_detects_tampering():
    chain = build_chain(_runs())
    chain[1]["status"] = "completed"  # tamper with a past entry
    assert verify_chain(chain) is False


def test_chain_forgery_with_plain_sha256_is_rejected():
    """A DB-write attacker who tampers a field and recomputes hashes the old
    (unkeyed) way must not produce a chain that verifies — proves the chain
    is now keyed, not plain SHA-256."""
    import hashlib

    chain = build_chain(_runs())
    chain[1]["status"] = "completed"  # tamper

    prev = chain[0]["entry_hash"]
    for entry in chain[1:]:
        entry["prev_hash"] = prev
        core = {k: entry[k] for k in entry if k != "entry_hash"}
        from app.services.audit.chain import _canonical

        entry["entry_hash"] = hashlib.sha256((_canonical(core) + prev).encode("utf-8")).hexdigest()
        prev = entry["entry_hash"]

    assert verify_chain(chain) is False


def test_chain_forgery_with_wrong_key_is_rejected():
    """Recomputing with a guessed/wrong HMAC key must also fail verification."""
    import hashlib
    import hmac

    chain = build_chain(_runs())
    chain[1]["status"] = "completed"  # tamper

    wrong_key = b"attacker-guessed-key-32-bytes-xx"
    prev = chain[0]["entry_hash"]
    for entry in chain[1:]:
        entry["prev_hash"] = prev
        core = {k: entry[k] for k in entry if k != "entry_hash"}
        from app.services.audit.chain import _canonical

        entry["entry_hash"] = hmac.new(wrong_key, (_canonical(core) + prev).encode("utf-8"), hashlib.sha256).hexdigest()
        prev = entry["entry_hash"]

    assert verify_chain(chain) is False


def test_snapshot_digest_is_stable_and_content_addressed():
    runs = _runs()
    snap1 = snapshot_of(runs[0])
    snap2 = snapshot_of(runs[0])
    assert digest(snap1) == digest(snap2)  # deterministic
    # different context -> different digest
    assert digest(snapshot_of(runs[0])) != digest(snapshot_of(runs[2]))


def test_snapshot_carries_decision_time_context():
    snap = snapshot_of(_runs()[0])
    assert "context_used" in snap
    assert snap["critic"]["risk_score"] == 0.1
