"""
Cryptographic Audit Chain with Time-Travel State.

Builds a tamper-evident chain over workflow decisions. Each entry:

  - captures the full retrieve -> reason -> propose -> validate -> act trace,
  - embeds a content-addressed digest of the *decision-time state* (the exact
    context / memory subgraph the brain used at that millisecond), and
  - links to the previous entry via a keyed HMAC-SHA256, so altering any past
    entry breaks every hash after it.

The chain link (``entry_hash``) is HMAC-SHA256, not plain SHA-256: forging or
recomputing it requires the secret key, which an attacker with only DB write
access does not have. (``digest()`` / ``snapshot_of()`` stay unkeyed plain
SHA-256 — that's content addressing for the decision-time snapshot, not a
tamper-evidence claim.)

This deliberately reuses ``AUDIT_HMAC_SECRET`` — the same secret used by the
request-level JSONL audit middleware in ``app/middleware/audit_logger.py``.
Both are the audit trust domain for a single operator; split into a
dedicated ``AUDIT_CHAIN_HMAC_SECRET`` only if a compliance requirement
demands independent rotation of the two chains.

In dev, with no env var set, ``require_secret`` returns an ephemeral
per-process secret (see ``secret_config.py``). That's fine here because the
chain is always rebuilt and verified fresh from DB rows within one request —
there's no persisted chain or cross-process verification that a restart
could break.

This turns the audit log from a text receipt into a provable record of both
what the AI did and what it knew when it did it (the "time-travel" property).
Pure and deterministic for testability.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import json
from typing import Any

from app.services.security.secret_config import require_secret

GENESIS_HASH = "0" * 64


@functools.cache
def _key() -> bytes:
    """Lazily-resolved, process-cached HMAC key for the audit chain.

    Lazy so importing this module stays side-effect-free, and cached so the
    dev "unset secret" warning logs once per process, not once per entry.
    """
    return require_secret("AUDIT_HMAC_SECRET", min_length=32).encode()


def _canonical(obj: Any) -> str:
    """Stable JSON encoding so the same logical content always hashes the same."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest(obj: Any) -> str:
    """SHA-256 hex digest of an arbitrary JSON-serialisable object."""
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def snapshot_of(run: Any) -> dict:
    """The decision-time state snapshot for a run: what the brain knew.

    Pulls the context that was actually used (sources, retrieved memory, graph
    facts) plus the critic inputs. ``context_used`` is persisted on the run, so
    this is a faithful rewind, not a reconstruction.
    """
    context = getattr(run, "context_used", None) or {}
    return {
        "captured_for_run": str(getattr(run, "id", "")),
        "workflow": getattr(run, "workflow_name", ""),
        "context_used": context,
        "candidate_action": getattr(run, "candidate_action", None) or {},
        "critic": {
            "risk_score": getattr(run, "critic_risk_score", None),
            "reasons": getattr(run, "critic_reasons", None) or [],
            "approved": getattr(run, "critic_approved", None),
        },
    }


def _steps_for(run: Any) -> list[dict]:
    """Derive the retrieve -> reason -> propose -> validate -> act stages."""
    context = getattr(run, "context_used", None) or {}
    sources = context.get("sources") or context.get("documents") or []
    candidate = getattr(run, "candidate_action", None) or {}
    final = getattr(run, "final_action", None) or {}
    risk = getattr(run, "critic_risk_score", None)
    reasons = getattr(run, "critic_reasons", None) or []
    status = getattr(run, "status", "")

    return [
        {
            "stage": "retrieve",
            "label": "Retrieve",
            "detail": f"{len(sources)} source(s) from memory graph"
            if sources
            else "Context pulled from memory graph",
        },
        {
            "stage": "reason",
            "label": "Reason",
            "detail": (candidate.get("rationale") if isinstance(candidate, dict) else None)
            or "WorkflowAgent synthesised a candidate action",
        },
        {
            "stage": "propose",
            "label": "Propose",
            "detail": (candidate.get("action_type") if isinstance(candidate, dict) else None)
            or (final.get("action_type") if isinstance(final, dict) else None)
            or "Candidate action",
        },
        {
            "stage": "validate",
            "label": "Validate",
            "detail": (f"Critic risk {round(risk * 100)}% — {reasons[0]}" if (risk is not None and reasons) else (f"Critic risk {round(risk * 100)}%" if risk is not None else "Critic review")),
        },
        {
            "stage": "act",
            "label": "Act",
            "detail": {
                "completed": "Executed and logged",
                "rejected": "Blocked by human / critic",
                "pending_review": "Held for human approval",
            }.get(status, status or "Recorded"),
        },
    ]


def build_entry(run: Any, seq: int, prev_hash: str) -> dict:
    """Build one chained audit entry for a run, linked to ``prev_hash``."""
    snap = snapshot_of(run)
    snapshot_digest = digest(snap)
    created = getattr(run, "created_at", None)
    core = {
        "seq": seq,
        "run_id": str(getattr(run, "id", "")),
        "workflow_name": getattr(run, "workflow_name", ""),
        "status": getattr(run, "status", ""),
        "risk_score": getattr(run, "critic_risk_score", None),
        "timestamp": created.isoformat() if created else None,
        "snapshot_digest": snapshot_digest,
        "steps": _steps_for(run),
        "prev_hash": prev_hash,
    }
    entry_hash = hmac.new(_key(), (_canonical(core) + prev_hash).encode("utf-8"), hashlib.sha256).hexdigest()
    return {**core, "entry_hash": entry_hash}


def build_chain(runs: list[Any]) -> list[dict]:
    """Build the full chain (oldest -> newest) so prev_hash links read forward."""
    ordered = sorted(
        runs,
        key=lambda r: (getattr(r, "created_at", None) or 0, str(getattr(r, "id", ""))),
    )
    chain: list[dict] = []
    prev = GENESIS_HASH
    for i, run in enumerate(ordered):
        entry = build_entry(run, seq=i + 1, prev_hash=prev)
        chain.append(entry)
        prev = entry["entry_hash"]
    return chain


def verify_chain(chain: list[dict]) -> bool:
    """Recompute every hash link; return False if any entry was tampered with."""
    prev = GENESIS_HASH
    for entry in chain:
        if entry.get("prev_hash") != prev:
            return False
        core = {k: entry[k] for k in entry if k != "entry_hash"}
        recomputed = hmac.new(_key(), (_canonical(core) + prev).encode("utf-8"), hashlib.sha256).hexdigest()
        if recomputed != entry.get("entry_hash"):
            return False
        prev = entry["entry_hash"]
    return True
