"""
Governance Core — the versioned facade over Company Brain's three
governance primitives.

This package does not implement anything new. It re-exports the public
surface of three components that already exist elsewhere in the app, so
that anything gating an autonomous action imports one stable module instead
of reaching into three implementation packages directly:

* **CriticAgent** / **CriticVerdict** (``app.agents.critic_agent``) —
  second-pass, fail-closed validation of a candidate action before it can
  execute. Checks the quarantine lock and vetoes unconditionally, before any
  LLM call is made, so a model cannot be talked past an active quarantine.
  Malformed or unparseable LLM verdicts default to reject, not approve.

* **Keyed audit chain** (``app.services.audit.chain``) — builds and verifies
  a chain of audit entries linked by HMAC-SHA256 (keyed by
  ``AUDIT_HMAC_SECRET``), so recomputing a forged link requires the secret,
  not just database write access. This is **tamper-evident, not
  tamper-proof**: a full-DB-access attacker can still rewrite history and
  overwrite the stored chain end-to-end. What the keying buys you is that
  they cannot forge a chain that *verifies*, given only the data — see
  ``chain.py`` for the full threat model.

* **Quarantine lock** (``app.services.quarantine.lock``) — the Contradiction
  Handshake lock the critic checks. PostgreSQL is the source of truth;
  Redis is a fast-read cache only. Outside of local dev with
  ``QUARANTINE_LOCK_ALLOW_REDIS_ONLY_DEV=true`` set, the lock **fails
  closed** (raises) if ``asyncpg`` / Postgres is unavailable — a safety lock
  is never allowed to live in Redis alone in production.

Deliberately excluded: the LLM budget limiter (``app.services.budget``).
It is ORM- and app-coupled by design (reads tenant settings and run history
through the app's own session/repo layer), not a standalone governance
primitive with an independent implementation to re-export. It stays where
it is.

## Versioning

``INTERFACE_VERSION`` follows semver against the names in ``__all__``:

* **major** — a breaking change to the signature or observable semantics of
  anything in ``__all__`` (e.g. ``CriticVerdict`` gains a required field,
  ``verify_chain`` changes what "valid" means).
* **minor** — an additive change (a new re-export, an optional field/kwarg).
* **patch** — an internal fix behind an unchanged interface.

## Portability caveats (read before extracting this as a standalone package)

This is a facade over in-repo modules, not a decoupled library, and saying
otherwise would be dishonest:

* ``CriticAgent`` depends on this app's ``LLMAdapter`` and ``BaseAgent``
  (``app.agents.llm_adapter``, ``app.agents.base_agent``) for its LLM
  transport and result shape.
* The quarantine lock depends on this app's ``secret_config`` (production
  detection) and ``observe.metrics`` (counters) modules.

Neither component has been audited for use outside this codebase. Cutting
this into an installable package standalone is future work, gated on a real
external consumer showing up — not done speculatively here.
"""

from __future__ import annotations

from app.agents.critic_agent import CriticAgent, CriticVerdict
from app.services.audit.chain import (
    GENESIS_HASH,
    build_chain,
    build_entry,
    digest,
    snapshot_of,
    verify_chain,
)
from app.services.quarantine import lock as quarantine_lock

INTERFACE_VERSION = "1.0.0"

__all__ = [
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
]
