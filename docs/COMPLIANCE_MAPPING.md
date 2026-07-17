# Compliance mapping — how Company Brain's mechanisms support a deployer's obligations. Not a conformity claim.

**Status:** draft, dated 2026-07-17. Reflects the codebase as described in `docs/KNOWLEDGE_BASE.md`
and `docs/PILOT_READINESS_GAP_REPORT.md` as of this date. Re-check both before relying on any row
below — mechanisms and gaps change as the code changes.

## Opening caveats — read before anything else

1. **Applicability is not this document's call.** Whether the EU AI Act applies to a given
   deployment at all, and at what risk tier (minimal, limited, high, unacceptable), is determined
   by the deployer's specific use case, the AI system's role in it, and applicable guidance —
   not by anything Company Brain ships. Nothing below should be read as a statement that the Act
   applies to your deployment, or at what tier.
2. **No certifications exist.** Company Brain holds no certifications of any kind. SOC 2 Type I is
   a roadmap item, not a current state. The product has never run in production — every mechanism
   described in this document has been exercised in local development and/or CI
   (`docs/IMPLEMENTATION_REPORT.md`, `docs/PILOT_READINESS_GAP_REPORT.md`), not against a live
   deployment with real users, real data, or real third-party accounts. Every "supports" in the
   tables below means: **the mechanism exists in code and is test-verified as described in the
   cited tests — nothing more.** It is not a claim of live operation, scale, or effectiveness.
3. **This is not legal advice.** This document is an engineering-to-compliance cross-reference for
   internal use. It does not substitute for a conformity assessment, and no one should rely on it
   as one. Engage qualified counsel before making any regulatory claim about this product.

---

**How to read the tables below:** *Mechanism* names the code behavior; *Where* is the file path
implementing it; *What it supports* states, narrowly, what obligation the mechanism is relevant
to — never that it discharges the obligation; *Honest gap* names the specific, current limitation.
Each section also lists the test files (from `backend/tests/`) that back the "test-verified" claim
for that section's mechanisms, and says plainly where no dedicated test file exists.

## EU AI Act Art. 9 — Risk management system

Art. 9 requires a continuous, iterative risk management process across the AI system's lifecycle:
identifying and evaluating known and foreseeable risks, and taking risk-mitigation measures.

| Mechanism | Where (file path) | What it supports | Honest gap |
|---|---|---|---|
| Blast-radius simulation + probabilistic risk forecaster | `backend/app/services/risk/` | May support a deployer's process for identifying and estimating the downstream impact of a proposed action before it executes | Forecasts are model-generated estimates, not measured outcomes; no live production data has ever fed back into them |
| Human approval queue + autonomy levels + critic verdicts with reasons | `backend/app/services/workflow/runner.py`, `backend/app/agents/critic_agent.py` | Provides a configurable human-review checkpoint that can route higher-risk actions to a person before execution | This is a configurable checkpoint, not a guarantee of oversight — an operator can misconfigure autonomy levels; critic risk scores are LLM-generated and calibration needs accumulated tenant history a new deployment doesn't have |
| Contradiction Handshake / quarantine lock | `backend/app/services/quarantine/lock.py`, `backend/app/services/contradiction/` | Supports fail-closed handling of detected policy conflicts (locks a skill from executing until resolved) | Fail-closed behavior is verified in code and unit tests; the full lock→detect→quarantine path has only been proven live in CI (`release-candidate.yml`), never against a real production incident |
| Feedback loop / learned per-tenant policy + calibration chart | `backend/app/services/feedback_loop/` | May support iterative recalibration of risk thresholds as a tenant accumulates outcomes | Needs a volume of accumulated feedback a new tenant does not have at pilot start; calibration quality before that volume is unproven |

**Verification pointers:** `backend/tests/test_contradiction.py` (critic quarantine veto),
`test_detector.py` / `test_quarantine_lock_semantics.py` / `test_quarantine_api.py` (quarantine
path), `test_feedback_loop.py` (feedback loop). `backend/tests/test_integration_quarantine_lock.py`
exercises the live lock but is skipped unless `QUARANTINE_INTEGRATION=1` is set. No dedicated test
file targets `backend/app/services/risk/` (blast-radius/forecaster) by name in `backend/tests/`.

## EU AI Act Art. 12 — Record-keeping

Art. 12 requires automatic logging of events over the system's lifetime, sufficient to identify
situations that may result in risk and to facilitate post-market monitoring.

| Mechanism | Where (file path) | What it supports | Honest gap |
|---|---|---|---|
| Keyed HMAC audit chain + Time-Travel decision snapshots | `backend/app/services/audit/chain.py` | Supports a deployer's record-keeping obligation by producing a tamper-evident, chained log of workflow decisions with point-in-time snapshots | Tamper-**evident**, not tamper-proof — an attacker with write access to the signing key or underlying store could still forge a consistent chain; the full stack has never been verified live outside CI |
| Structured logs + `/metrics` endpoint | `backend/app/services/observe/metrics.py` | Provides structured log output and Prometheus-text-format counters (budget blocks, quarantine acquires/releases, contradictions detected, workflow runs by status) that a deployer could feed into their own record-keeping pipeline | This is stdlib groundwork only — no OpenTelemetry SDK, no configured scraper, no dashboards. It is not an operational monitoring integration; nothing currently ingests or retains these signals outside the running process |
| Governed-workflow runner as single entry point | `backend/app/services/workflow/runner.py` | Ensures every workflow execution path (API and Celery scheduler alike) passes through the same budget-gate → agent → critic → persist sequence, giving record-keeping a single, consistent chokepoint | Centralization is verified by code review and unit tests, not by a live multi-tenant production run |

**Verification pointers:** `backend/tests/test_metrics.py` (the `/metrics` counters),
`test_core.py` and `test_dashboard_endpoints.py` (runner/dashboard read paths). The audit chain
itself is directly tested in `backend/tests/test_differentiators.py`: build/verify round-trip,
tamper detection, and two forgery cases (attacker-style unkeyed recompute, wrong-key recompute)
— both forgeries must fail `verify_chain`.

## EU AI Act Art. 14 — Human oversight

Art. 14 requires that high-risk AI systems be designed to allow effective human oversight,
including the ability for a person to understand, monitor, and intervene in or override the
system's outputs.

| Mechanism | Where (file path) | What it supports | Honest gap |
|---|---|---|---|
| Human approval queue + autonomy levels | `backend/app/services/workflow/runner.py` | Provides a configurable human-review checkpoint before a workflow's action executes, with the tenant able to set the autonomy level that determines when a human is in the loop | This is a checkpoint the deployer configures, not a system-level guarantee of oversight; if autonomy is configured too permissively, a human may never see the action |
| Critic verdicts with reasons | `backend/app/agents/critic_agent.py` | Gives the human reviewer a stated rationale (risk/policy pass with reasons) to support their decision, rather than a bare score | Verdicts and risk scores are LLM-generated; they can be wrong or under-explain the actual risk, and have not been validated against real reviewer outcomes |
| Quarantine lock unconditional veto | `backend/app/services/quarantine/lock.py`, `backend/app/agents/critic_agent.py` | Supports an override path where a locked skill is blocked regardless of critic outcome, giving a human (via the release endpoint) the final say on unlocking it | Checked before any LLM call in code and unit-tested; the live acquire/release cycle under real concurrent load has only run in CI |

**Verification pointers:** `backend/tests/test_contradiction.py` (critic veto logic),
`test_quarantine_lock_semantics.py` (8 cases — PG-first write/cache/fallback/fail-closed),
`test_quarantine_api.py` (release endpoint). Live concurrent-load behavior is only observed in
`release-candidate.yml`'s `compose-live` CI job, never on a real host.

## EU AI Act Art. 26 — Deployer obligations

Art. 26 places obligations on deployers of high-risk AI systems: using the system per its
instructions, assigning competent human oversight, monitoring operation, and keeping logs.

| Mechanism | Where (file path) | What it supports | Honest gap |
|---|---|---|---|
| OIDC authentication + RBAC | `backend/app/middleware/auth.py`, `backend/app/middleware/rbac.py` | Supports a deployer's obligation to restrict system use to authorized, identifiable personnel with defined roles | Access-control logic only; does not itself satisfy competence or training obligations, which remain the deployer's responsibility |
| Tenant scoping (Weaviate property filter) | `ingestion/embedding_pipeline.py` (`WeaviateStore.search`), `backend/app/services/security/tenant_isolation.py` | Supports keeping one deployer's data separated from another's during retrieval | This is a required, centralized property-filter on a single `Document` collection — **not native Weaviate multi-tenancy** (no per-tenant shard boundary). A filter bug anywhere in the query path would be a cross-tenant leak; native multi-tenancy is an open follow-up |
| Per-tenant LLM budget + request-rate caps | `backend/app/services/budget/limiter.py`, `backend/app/middleware/rate_limiter.py` | Supports a deployer's ability to bound and monitor system usage per tenant, per its own operating instructions | The request-rate quota store is in-memory per-process — accurate for a single replica only, not multi-replica-safe; a deployment with more than one backend replica cannot rely on it as a hard cap |
| PII redaction | `ingestion/base_connector.py` | Supports a deployer's data-minimization practice during ingestion, redacting common PII patterns (email, phone, SSN, card) before storage | Presidio (the fuller entity-recognition engine) is optional and only installed in some images; when unavailable, the code degrades to a narrower regex fallback, which will miss PII patterns Presidio would catch |
| Structured logs + `/metrics` | `backend/app/services/observe/metrics.py` | Supports a deployer's monitoring obligation by exposing counters a deployer's own tooling could scrape | Same gap as under Art. 12: no scraper, no dashboard, no alerting is configured out of the box |

**Verification pointers:** `backend/tests/test_security.py`, `test_security_hardening.py`,
`test_tenancy.py` (OIDC/RBAC/tenant paths); `test_weaviate_tenant_filter.py` (mock-backed tenant
filter — 4 cases); `test_budget.py` (12 cases) and `test_tenant_rate_quota.py` (per-tenant rate
bucket); `test_metrics.py`. `backend/tests/test_integration_tenant_isolation.py` targets the live
Weaviate isolation path but is skipped unless `WEAVIATE_URL` is set — per
`docs/PILOT_READINESS_GAP_REPORT.md` §1 it has never actually executed against a live Weaviate in
this project's history. No dedicated test file targets PII redaction
(`ingestion/base_connector.py`) by name in any test suite in this repo.

---

## ISO/IEC 42001

**ISO/IEC 42001 certifies an organization's AI management system (AIMS) — a set of governance
processes, policies, and organizational controls — not a piece of software.** A product cannot be
"42001 compliant" or "42001 certified"; only an organization operating one can pursue
certification, and that requires organizational processes this document does not create.

The mechanisms below may support an organization pursuing 42001 certification by supplying
evidence-generation, logging, and human-oversight-process hooks a certifying auditor might ask an
organization to demonstrate. They do not constitute certification, and using them does not make
Company Brain (or a deployer of it) "42001 compliant."

| Mechanism | Where (file path) | What it supports | Honest gap |
|---|---|---|---|
| Keyed HMAC audit chain + Time-Travel snapshots | `backend/app/services/audit/chain.py` | May support an organization's evidence trail for AIMS audit activities (decision history, point-in-time state) | Tamper-evident, not tamper-proof; no organizational audit has ever exercised this evidence in practice |
| Human approval queue + critic verdicts | `backend/app/services/workflow/runner.py`, `backend/app/agents/critic_agent.py` | May support an organization's documented human-oversight process, one of several controls a 42001 auditor could examine | This is a code-level checkpoint; an AIMS requires the organization to also document roles, training, and escalation procedures around it, which are outside this codebase |
| Contradiction Handshake / quarantine | `backend/app/services/quarantine/lock.py`, `backend/app/services/contradiction/` | May support an organization's incident/nonconformity handling process by providing a fail-closed technical control to point to | Live integration proven in CI only; no organizational incident has ever run through it |
| Feedback loop / calibration | `backend/app/services/feedback_loop/` | May support an organization's continual-improvement evidence (a required AIMS element) | Needs accumulated tenant history a new deployment or new tenant does not have |
| Structured logs + `/metrics` | `backend/app/services/observe/metrics.py` | May support an organization's monitoring-and-measurement evidence | Stdlib groundwork only, not a configured operational monitoring integration |

**Verification pointers:** same test files cited under Art. 9, 12, and 14 above — this section
reuses the same code and does not add new mechanisms, only a different reader (an AIMS auditor
rather than a deployer). No AIMS-specific test exists, or could exist, since 42001 certification
is an organizational-process outcome, not a code outcome.

---

## Explicitly out of scope

- **EU AI Act Art. 15 (accuracy, robustness, and cybersecurity)** is deliberately **not mapped** in
  this document. No penetration test has been performed (see `docs/PILOT_READINESS_GAP_REPORT.md`
  §2), and no live full-stack verification has occurred outside CI. Mapping mechanisms to Art. 15
  without that evidence would overreach what this codebase can currently support.
- **GDPR** is intentionally not mapped in this document. It is a separate exercise with its own
  legal basis, data-subject rights, and processing-record analysis that this compliance mapping
  does not attempt to cover.

---

## Maintenance

This document should be re-checked whenever `docs/KNOWLEDGE_BASE.md` or
`docs/PILOT_READINESS_GAP_REPORT.md` changes in a way that touches a mechanism listed above — a
new test file, a closed gap-report item, a changed file path, or a newly added safety mechanism.
A row that no longer matches those two source documents should be corrected or removed rather than
left stale; an inaccurate "supports" claim in a compliance document is worse than an absent one.
