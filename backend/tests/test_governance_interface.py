"""
Contract test for the versioned governance facade (``app.governance``).

Guards three things that are easy to break silently when the facade wraps
implementations it does not own:

1. ``INTERFACE_VERSION`` is a well-formed semver string.
2. Every re-export IS the same object as its implementation-module original
   (identity, not just equal value) — catches facade drift, e.g. someone
   accidentally re-implementing or wrapping a function instead of
   re-exporting it.
3. ``__all__`` is complete — every intended public name is actually listed,
   so ``from app.governance import *`` and doc tooling see the full surface.

A behavioral smoke test at the bottom proves the facade is wired to the
*real* keyed audit chain, not a stub, mirroring the fake-run pattern in
``test_differentiators.py``.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import app.governance as governance
from app.agents import critic_agent as critic_agent_module
from app.services.audit import chain as chain_module
from app.services.quarantine import lock as lock_module


# ── Version ───────────────────────────────────────────────────────────────────

def test_interface_version_is_semver():
    assert re.match(r"^\d+\.\d+\.\d+$", governance.INTERFACE_VERSION)


# ── Identity: facade re-exports are the real objects, not copies ────────────

def test_reexports_are_identical_to_implementation_objects():
    assert governance.CriticAgent is critic_agent_module.CriticAgent
    assert governance.CriticVerdict is critic_agent_module.CriticVerdict
    assert governance.GENESIS_HASH is chain_module.GENESIS_HASH
    assert governance.build_chain is chain_module.build_chain
    assert governance.build_entry is chain_module.build_entry
    assert governance.digest is chain_module.digest
    assert governance.snapshot_of is chain_module.snapshot_of
    assert governance.verify_chain is chain_module.verify_chain
    assert governance.quarantine_lock is lock_module


# ── __all__ completeness ─────────────────────────────────────────────────────

def test_all_is_complete():
    expected = {
        "INTERFACE_VERSION",
        "CriticAgent",
        "CriticVerdict",
        "GENESIS_HASH",
        "build_chain",
        "build_entry",
        "digest",
        "snapshot_of",
        "verify_chain",
        "quarantine_lock",
    }
    assert set(governance.__all__) == expected


# ── Behavioral smoke: facade wires to the real keyed chain ──────────────────

def _fake_run(rid, name, status, risk, created):
    from datetime import datetime, timezone

    return SimpleNamespace(
        id=rid,
        workflow_name=name,
        status=status,
        critic_risk_score=risk,
        critic_reasons=["reason"],
        critic_approved=(status == "completed"),
        context_used={"sources": []},
        candidate_action={"action_type": name},
        final_action={"action_type": name},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc).replace(minute=created),
    )


def test_facade_build_and_verify_chain_roundtrip():
    runs = [
        _fake_run("11111111-1111-1111-1111-111111111111", "refund", "completed", 0.1, 0),
        _fake_run("22222222-2222-2222-2222-222222222222", "deploy", "rejected", 0.9, 5),
    ]
    chain = governance.build_chain(runs)
    assert governance.verify_chain(chain) is True

    chain[0]["status"] = "tampered"
    assert governance.verify_chain(chain) is False
