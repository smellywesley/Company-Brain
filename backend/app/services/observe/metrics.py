"""
Stdlib-only counters exposed in the Prometheus text exposition format.

This is deliberately NOT a Prometheus/OpenTelemetry integration — no client
library, no OTel SDK, no scraper configured, no histograms. It is groundwork:
a tiny thread-safe in-memory counter registry whose ``/metrics`` rendering a
real Prometheus instance COULD scrape later. Counters are per-process and
reset on restart (normal Prometheus counter semantics; the API process and
each Celery worker keep separate registries).

The exposition format is a documented plain-text format
(https://prometheus.io/docs/instrumenting/exposition_formats/) — hand-rolling
it avoids adding a new external dependency, which matters in this repo.
"""

from __future__ import annotations

import threading

_HELP = {
    "company_brain_budget_blocks_total": "Governed runs refused before any LLM call because the tenant hit its monthly budget.",
    "company_brain_quarantine_acquires_total": "Quarantine locks placed (Contradiction Handshake).",
    "company_brain_quarantine_releases_total": "Quarantine locks released by human reconciliation.",
    "company_brain_contradictions_detected_total": "Confirmed contradictions that quarantined a skill.",
    "company_brain_workflow_runs_total": "Governed workflow runs by final status.",
}

_lock = threading.Lock()
# key: (name, frozenset of label items) -> int
_counters: dict[tuple[str, frozenset], int] = {}


def inc(name: str, labels: dict[str, str] | None = None, amount: int = 1) -> None:
    """Increment a counter. Never raises — metrics must not break the caller."""
    try:
        key = (name, frozenset((labels or {}).items()))
        with _lock:
            _counters[key] = _counters.get(key, 0) + amount
    except Exception:  # noqa: BLE001 — observability is never worth an outage
        pass


def reset() -> None:
    """Clear all counters (test isolation only)."""
    with _lock:
        _counters.clear()


def _label_str(labels: frozenset) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels))
    return "{" + inner + "}"


def render() -> str:
    """Full registry in Prometheus text exposition format."""
    with _lock:
        snapshot = dict(_counters)

    lines: list[str] = []
    for name in sorted({n for n, _ in snapshot}):
        help_text = _HELP.get(name, name.replace("_", " "))
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        for (n, labels), value in sorted(snapshot.items(), key=lambda kv: (kv[0][0], sorted(kv[0][1]))):
            if n == name:
                lines.append(f"{name}{_label_str(labels)} {value}")
    return "\n".join(lines) + ("\n" if lines else "")
