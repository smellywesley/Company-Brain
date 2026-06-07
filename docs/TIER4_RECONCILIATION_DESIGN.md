# Tier 4 — Knowledge Reconciliation UI: Design Spec

Status: design-approved (plan-design-review, 2026-06-06). Not yet implemented.
Owner: frontend + contradiction backend.

This spec covers the human-facing tier of the redesigned Contradiction Handshake.
It assumes the tiered detection architecture below is the plan of record. Tiers
0-3 are backend and out of scope for this document except where their output
shapes the UI.

---

## 1. Architectural context (the tiered model)

The Contradiction Handshake is no longer a single permanent skill-level lock. It
is a confidence-aware pipeline. The LLM is an accelerator and adjudicator, not
the sole source of intelligence.

```
Tier 0  Deterministic structural checks   (OpenAPI diff, schema diff, route/CLI/config diff)
Tier 1  Retrieval + entity grounding      (does the SOP actually reference the changed entity?)
Tier 2  Rule-based contradiction patterns (route removed AND sop references it, etc.)
Tier 3  Optional LLM adjudication         (ambiguous/medium-confidence cases only)
Tier 4  Human reconciliation             (this document)
```

Evidence accumulates across tiers into a signal set. The decision engine maps
the aggregate to an action:

| Confidence | Source                         | Action            | Lock strength        |
|------------|--------------------------------|-------------------|----------------------|
| Low        | keyword heuristic only         | warn, do NOT block| none (log only)      |
| Medium     | structural / rule-based        | soft quarantine   | TTL-bound            |
| High       | deterministic proof or LLM     | hard quarantine   | TTL optional         |
| Critical   | human-confirmed or failing test| permanent         | until human resolves |

The core invariant: **a candidate conflict is not a confirmed contradiction.**
Only deterministic proof, LLM adjudication, or a human may produce
`safe_to_hard_quarantine: true`. Heuristic-only signals never hard-lock.

---

## 2. Quarantine lock schema (upgrade from the shipped version)

The shipped lock is `quarantine:{tenant_id}:{skill_id}`, no TTL, value =
`{pr_ref, summary, severity, locked_by, locked_at}`. It is replaced by an
artifact-scoped, confidence-aware record:

```
key:  quarantine:{tenant_id}:{skill_id}:{artifact_id}
ttl:  configurable per tenant policy (none only for confirmed/critical)
value:
  artifact_id
  pr_ref
  severity         low | medium | high | critical
  review_status    pending_review | confirmed_conflict | dismissed | expired
  decision_source  heuristic | structural | rule | llm | human
  safe_to_hard_quarantine  bool
  confidence       0.0 - 1.0 (aggregate)
  signals[]        [{type, confidence, detail}]
  evidence         {sop_step, new_reality, referenced_entities[]}
  locked_by
  locked_at
  expires_at       (null for permanent)
```

Backward-compat note: the shipped `CriticAgent` veto gate keys on
`quarantine:{tenant}:{skill}`. The artifact-scoped key is a superset. The gate
must be updated to veto if ANY artifact-scoped lock exists for the skill whose
`review_status` is `pending_review` or `confirmed_conflict` (not `dismissed` or
`expired`). This is a backend change tracked in the task list below.

---

## 3. Tier 4 screen design

### 3.1 Information hierarchy — evidence-first (Decision D2)

The old 3-pane diff led with the proposed fix because every item reaching the UI
was already a confirmed conflict. The tiered model sends items across a
confidence spectrum, so the reviewer's first job is "is this real?" before "is
this fix good?". The screen inverts to lead with evidence.

Reading order, top to bottom:

```
┌─ HEADER ─────────────────────────────────────────────────────────────┐
│  [severity badge]  Skill: "Refund processing"   ·   PR #842           │
│  decision_source: structural+rule   ·   confidence 0.92               │
│  ⏱ expires in 4h 23m   (soft quarantine)   OR   🔒 permanent          │
├─ 1. EVIDENCE  (primary, what the reviewer judges first) ──────────────┤
│  Signals that fired:                                                  │
│   ● api_route_removed            0.95  POST /token deleted in PR      │
│   ● sop_step_references_route    0.90  Step 2 calls POST /token       │
│   ○ keyword_overlap              0.25  "OAuth2" in both               │
│  Referenced entities: /token, bearer_token                            │
├─ 2. THE CONFLICT  (3-pane diff, demoted to second) ──────────────────┤
│   NEW REALITY        │   STALE ARTIFACT      │   PROPOSED FIX         │
│   (PR diff)          │   (SOP step)          │   (synthesized, edit)  │
├─ 3. ACTIONS ─────────────────────────────────────────────────────────┤
│   [Confirm conflict]   [Dismiss]   [Accept synthesis]                 │
└──────────────────────────────────────────────────────────────────────┘
```

The 3-pane diff from the prior design survives, just relocated under the
evidence. The right pane (PROPOSED FIX) remains editable before acceptance.

### 3.2 Action model

- **Confirm conflict** — reviewer agrees it is real. Sets
  `review_status = confirmed_conflict`, clears TTL (becomes permanent until the
  fix is accepted). Use when the conflict is real but the synthesized fix needs
  more work or another reviewer.
- **Accept synthesis** — applies the (possibly edited) proposed fix to the SOP,
  resolves the conflict, releases the lock. The terminal happy path.
- **Dismiss** — reviewer judges it a false positive. Releases the lock. Capture
  behavior defined in 3.3.

### 3.3 Dismiss as a feedback loop (Decision D3)

Dismiss is not a discard. It is the training signal that makes the heuristic
tier less noisy over time.

Interaction: clicking Dismiss expands the signal list with checkboxes,
pre-checked. The reviewer unchecks the signal(s) that false-fired and confirms.
One tap in the common case (accept the pre-check), no required free text.

On confirm, emit a feedback event the heuristic/rule tiers consume:

```
contradiction_feedback:
  artifact_id, skill_id, tenant_id
  dismissed_signals[]   (the unchecked ones — these false-fired)
  kept_signals[]
  decision_source
  reviewer, ts
```

This closes the loop the architecture critique called for: if
`keyword_overlap 0.25` is dismissed repeatedly while `api_route_removed 0.95`
never is, the tuning layer learns to down-weight keyword overlap.

### 3.4 TTL expiry policy (Decision D4)

A soft (medium-confidence) quarantine carries a TTL. If no human acts before it
elapses: **auto-release, but log loudly.**

- On expiry: `review_status = expired`, lock released, agent may act again.
- Write an `expired_unreviewed` audit record (artifact, skill, signals,
  confidence, expired_at) to a dedicated audit/history view.
- The queue (3.5) sorts by time-to-expiry ascending so about-to-expire items
  float to the top and get human eyes before they lapse.

Rationale: trusting the confidence tier (weak signal should not block forever)
without creating an auditability blind spot. A real-but-low-confidence conflict
can still slip through; the audit trail is the backstop that catches it after
the fact. Escalating-to-hard-lock on expiry was rejected because it lets an
ignored noisy heuristic freeze a workflow, reintroducing the original no-TTL
defect.

### 3.5 Queue / triage view

The confidence-tiered model produces many more (soft) quarantines than the old
single-permanent-lock model, so triage becomes a real surface.

- List of open quarantines across skills/artifacts for the tenant.
- Sort: severity desc, then time-to-expiry asc (urgent-and-expiring first).
- Each row: severity badge, skill, artifact/PR ref, top signal + confidence,
  TTL countdown.
- Do NOT render this as a mosaic of decorative cards. A dense, scannable table
  is correct for an ops triage surface. Cards only if a card IS the interaction.

---

## 4. Interaction state coverage (Pass 2 fix)

| State / surface     | What the reviewer SEES                                              |
|---------------------|--------------------------------------------------------------------|
| Queue: empty        | "No active conflicts. Knowledge is in sync." + link to audit history. Warmth, not a dead end. |
| Queue: loading      | Skeleton rows, not a spinner-on-blank.                              |
| Detail: pending     | Full evidence-first layout, all three actions enabled.             |
| Detail: confirmed   | Permanent badge, TTL hidden, Confirm replaced by "Awaiting fix".   |
| Detail: dismissed   | Read-only, shows which signals were dismissed + by whom + when.    |
| Detail: expired     | Read-only, amber "expired unreviewed" banner, surfaced in audit.   |
| Accept: in-flight   | Optimistic apply with rollback on failure + visible error.         |
| Accept: error       | "Could not apply fix" + the reason + retry; lock stays held.       |
| Redis unavailable   | Banner: "Conflict status temporarily unavailable" — never silently imply "no conflicts". |

---

## 5. Accessibility (Pass 6 fix)

- Severity must NOT be encoded by color alone. Pair each badge with a text label
  (low/medium/high/critical) and a distinct icon. Severity is the primary triage
  signal; colorblind reviewers cannot lose it.
- Confidence bars need a numeric value beside the bar, not bar-only.
- Desktop-primary internal tool; full responsive is out of scope, but the layout
  must not break below ~1024px for reviewers on laptops.
- Keyboard: queue rows navigable and actionable without a mouse; the three
  primary actions reachable by keyboard with visible focus states.

---

## 6. NOT in scope

- Full responsive/mobile design — internal ops tool, desktop-primary. Deferred.
- Comment threads / multi-reviewer discussion — borrowed from the Google Docs
  idea last session, deferred until single-reviewer flow ships.
- Visual mockups — user chose the light audit path (option B). Generate with the
  gstack designer before frontend implementation.
- Tiers 0-3 detector internals — separate backend specs.

## 7. What already exists

- Shipped: `quarantine.lock` (sync+async, fail-open), `CriticAgent` veto gate,
  `ContradictionSynthesizer` (fails open on garbage/provider error),
  GitHub webhook worker wiring. See commit 845237c.
- Prior design decision (last session): 3-pane side-by-side diff over Google
  Docs overlay. Retained, relocated under evidence per D2.
- Frontend stack: Next.js, SSE live feed, existing Approval Queue surface to
  align with.

---

## 8. Implementation Tasks

Synthesized from this review. P1 blocks Tier 4 ship; P2 same-branch; P3 follow-up.

- [ ] **T1 (P1)** — quarantine — Upgrade lock schema to artifact-scoped + confidence fields
  - Surfaced by: section 2 — key is skill-scoped with no TTL/severity/status
  - Files: `backend/app/services/quarantine/lock.py`
  - Verify: unit tests for TTL set/expire, status transitions, artifact-scoped keys
- [ ] **T2 (P1)** — critic — Update veto gate to honor review_status + artifact scope
  - Surfaced by: section 2 backward-compat note — gate must veto only on pending/confirmed, ignore dismissed/expired
  - Files: `backend/app/agents/critic_agent.py`, `backend/tests/test_contradiction.py`
  - Verify: gate vetoes on pending_review, falls through on dismissed/expired
- [ ] **T3 (P1)** — decision-engine — Aggregate signals → confidence → action mapping
  - Surfaced by: section 1 table — candidate vs confirmed separation, safe_to_hard_quarantine
  - Files: new `backend/app/services/contradiction/decision.py`
  - Verify: heuristic-only never produces safe_to_hard_quarantine=true
- [ ] **T4 (P1)** — frontend — Evidence-first reconciliation detail screen
  - Surfaced by: D2 / section 3.1
  - Files: frontend reconciliation route + components
  - Verify: evidence renders above diff; all states from section 4 reachable
- [ ] **T5 (P1)** — frontend+backend — Signal-tagged dismiss + feedback event
  - Surfaced by: D3 / section 3.3
  - Files: dismiss component + `contradiction_feedback` emit/consume path
  - Verify: dismiss emits dismissed_signals[]; tuning layer can read it
- [ ] **T6 (P1)** — backend — TTL expiry → auto-release + expired_unreviewed audit record
  - Surfaced by: D4 / section 3.4
  - Files: expiry sweep (Celery beat) + audit write
  - Verify: expired lock releases AND writes audit record visible in history
- [ ] **T7 (P2)** — frontend — Triage queue, sorted severity desc + TTL asc
  - Surfaced by: section 3.5
  - Files: queue route + table component
  - Verify: about-to-expire items sort to top; table not card-mosaic
- [ ] **T8 (P2)** — frontend — Severity badges: label + icon, not color-only; numeric confidence
  - Surfaced by: Pass 6 / section 5
  - Files: severity badge + confidence bar components
  - Verify: meaning survives grayscale
- [ ] **T9 (P3)** — design — Run /design-consultation to establish DESIGN.md before build
  - Surfaced by: Pass 5 — no design system exists
  - Verify: DESIGN.md committed with tokens for this surface

---

# Eng Review Addendum (plan-eng-review, 2026-06-07)

Full-pipeline eng review. Decisions below supersede section 2's storage
description and the "fail-open" note in section 7. Grounded in the shipped code
at commit 845237c.

## E1. Storage: dual-store with a mandatory consistency contract

Decision: keep Redis (O(1) veto accelerator) + Postgres (source of truth). The
outside voice argued for single-store Postgres; the dual-store was chosen
deliberately, which makes the following contract REQUIRED, not optional. Without
it, dual-store is a silent governance bypass on a safety control.

```
AUTHORITY:   Postgres = source of truth. Redis = non-authoritative accelerator.
VETO READ:   Redis hit (status in {pending_review, confirmed_conflict}) → veto.
             Redis miss | error | corrupt | missing-status → Postgres point-read.
             Unknown is treated as LOCKED (fail-CLOSED). This REVERSES the
             current fail-open behavior at critic_agent.py:142-149.
WRITE ORDER: acquire  → write Postgres row FIRST, then set Redis flag.
             terminal → set Postgres terminal/resolving FIRST, then delete Redis.
REDIS VALUE: {artifact_id, review_status, version} — never a bare boolean
             (a boolean cannot distinguish pending vs confirmed vs stale).
TTL RULE:    Redis flag TTL >= Postgres policy TTL (or Redis no-TTL; the sweep
             is the only deleter), so Redis never expires ahead of the audit row.
RECONCILE:   the expiry sweep also repairs split-brain: for every non-terminal
             Postgres row assert the Redis flag exists; for every terminal row
             assert it is gone.
```

ASCII — the corrected veto hot path:

```
CriticAgent.critique()
   │
   ▼
 Redis GET quarantine:{tenant}:{skill}
   │
   ├── hit, status pending/confirmed ─────────────► VETO (risk=1.0)
   ├── hit, status terminal/stale ────────────────► (should not happen; reconcile)
   └── miss | error | corrupt
          │
          ▼
        Postgres: SELECT 1 FROM quarantine_records
          WHERE tenant_id=? AND skill_id=?
            AND review_status IN ('pending_review','confirmed_conflict') LIMIT 1
          │
          ├── row exists ─────────────────────────► VETO (fail-CLOSED)
          └── no row ─────────────────────────────► proceed to LLM critique
```

## E2. Decision engine (dedicated module)

`backend/app/services/contradiction/decision.py`, a pure function:
`decide(signals[], decision_source, tenant_config) -> {action, lock_strength,
ttl, safe_to_hard_quarantine}`. Explicit policy table:

```
confidence band   source                     action          lock        TTL
low               heuristic only             warn            none        n/a   (NEVER hard-lock)
medium            structural / rule          soft_quarantine TTL-bound   tenant.ttl_medium
high              deterministic proof | llm  hard_quarantine TTL ceiling tenant.ttl_high
critical          human | failing test       permanent       no TTL      none
```

Invariant enforced in ONE place: `decision_source == "heuristic"` can never
yield `safe_to_hard_quarantine=true`. The webhook worker calls this and acts;
it never maps severity itself. LLM-reported `severity` is an input signal, not
the lock strength.

## E3. Per-tenant config (typed reader)

`Tenant.settings` JSONB parsed into a typed config with validated safe defaults:
`financial_limit`, `ttl_medium`, `ttl_high`, `hard_lock_policy`. A missing TTL
must never resolve to 0 (instant release) or none (permanent). Replaces the
hardcoded `$500` at critic_agent.py:73. Do NOT write quarantine policy into
`Tenant.settings` from a hot path — `accumulate_llm_cost` already does an
unguarded read-modify-write on that column (lost-update bug); keep policy
read-only there or move it to its own column.

## E4. Postgres schema (new, P1 blocker — does not exist today)

```
quarantine_records(
  id, tenant_id FK, skill_id FK,
  artifact_id  -- deterministic: hash(tenant, skill, pr_number, merge_sha)
  pr_ref, severity, review_status, decision_source,
  safe_to_hard_quarantine bool, confidence float,
  signals jsonb, evidence jsonb,
  expires_at nullable, created_at, updated_at, resolved_by, resolved_at,
  UNIQUE(artifact_id),
  PARTIAL INDEX (tenant_id, expires_at) WHERE review_status='pending_review'
)
```
Plus an append-only audit trail for terminal/expired events (reuse the existing
audit pattern). The `expired_unreviewed` record (section 3.4) lives here.

## E5. Idempotency + state machine completeness

- Webhook redelivery: `process_github_webhook_event` has no dedupe. Record
  processed `(delivery_id or pr_number+merge_sha)` and no-op on replay.
- `artifact_id` must be deterministic (above) so acquire is an idempotent upsert.
- Define the missing transition explicitly: `dismissed → pending_review`
  (re-quarantine) is allowed ONLY on a NEW signal/sha, never on an identical
  replay. A wrong dismiss must be re-openable; a replay must not silently
  un-dismiss.

## E6. Performance

- Decision: tier-gate the LLM once Tier 0-1 grounding exists; parallelize the
  per-skill calls now with bounded concurrency (semaphore, respects provider
  rate limits). Replaces the serial loop at worker.py:70-95 (~50s/merge).

## E7. Test coverage (regression — mandatory, iron rule)

The 9 existing tests encode the old permanent-lock contract and will stay green
while behavior changes. Required new/updated tests:

1. veto fires on pending_review AND confirmed_conflict
2. veto does NOT fire on dismissed / expired
3. veto fail-CLOSED: Redis miss/error/corrupt → Postgres fallback vetoes
   (UPDATE the existing `test_redis_failure_falls_through` — its premise inverts)
4. decision engine: every confidence band; heuristic-only never hard-locks
5. missing TTL config → safe default, never 0 or none
6. TTL expiry sweep: releases AND writes expired_unreviewed audit; idempotent
   (FOR UPDATE SKIP LOCKED), and confirmed (no-TTL) never auto-expires
7. dismiss emits contradiction_feedback with dismissed_signals[]
8. artifact-scoping: 2 PRs lock same skill; release one, the other holds
9. dual-store reconciliation repairs a split-brain row
10. webhook redelivery is a no-op; dismissed→pending only on new sha

## E8. Failure modes (critical gaps if unaddressed)

| Codepath | Failure | Test | Error handling | Silent? |
|----------|---------|------|----------------|---------|
| veto on Redis miss | split-brain fail-open → action on locked skill | E7.3 | E1 Postgres fallback | was SILENT — now closed |
| acquire crash mid-write | Redis flag with no PG row (un-auditable) | E7.9 | E1 write order + reconcile | closed |
| sweep down | Redis TTL expires before audit row written | E7.6 | E1 TTL rule (Redis ≥ PG) | closed |
| webhook redelivery | duplicate lock / un-dismiss | E7.10 | E5 dedupe | closed |
| tenant unresolved (2nd tenant) | handshake silently no-ops | — | E10 require explicit mapping | SILENT — fix in E10 |

## E9. Build order (dependency lanes)

```
Lane A (backend safety core, sequential — shared quarantine module):
  E4 migration → E1 dual-store contract + lock.py → E2 decision engine
  → E2-into-worker (replace severity mapping) → E7 tests
Lane B (backend, parallel to A after E4):
  E6 parallelize handshake ; E5 idempotency ; E3 tenant config reader
Lane C (frontend, after Lane A lands the record shape):
  T4 detail screen → T5 dismiss → T7 queue → T8 badges
Lane D (independent): T9 /design-consultation
Detection (separate plan, blocks nothing here): Tier 0-2 PR-diff ingestion.
```

## E10. Other accepted fixes
- Require explicit owner→tenant mapping; error loudly on miss instead of the
  single-tenant guess (worker.py:319-324). Prevents silent handshake no-op.
- Store ALL conflicts in the record, not just `conflicts[0]` (worker.py:87).
- Remove dead `_DEFAULT_POLICY` (critic_agent.py:41-65).

## NOT in scope (eng review)
- Tier 0-2 structural detection (PR-diff ingestion, OpenAPI/schema diffing,
  rule engine) — large, no foundation in the code yet, its own plan.
- Single-store migration — considered (outside voice #9), rejected in favor of
  dual-store + consistency contract per user decision A1-REVISED.

## What already exists (corrected)
- Shipped lock is fail-OPEN; E1 changes it to fail-CLOSED via Postgres fallback.
- No `quarantine_records` table exists — E4 is net-new.
- `Tenant.settings` JSONB exists (models.py:62) but has a lost-update RMW bug in
  `accumulate_llm_cost` — do not co-locate writable policy there.

---

# CEO Review Addendum (plan-ceo-review, 2026-06-07) — RE-SEQUENCE, plan of record

This addendum SUPERSEDES the build order in E9. A second independent reviewer
made the decisive strategic catch and the user accepted it (decision D5).

## C1. The core finding: detection is the product; enforcement was being gold-plated

The shipped detector is structurally blind. [synthesizer.py:46](backend/app/services/contradiction/synthesizer.py)
prompts the model as if it receives "a unified code diff," but
[worker.py:43](backend/app/worker.py) only passes the PR title + body. The one
live signal is an LLM vibe-reading a PR title. Hardening enforcement (dual-store,
fail-closed, confidence tiering, audit) around that manufactures false confidence
— for a regulated buyer, an airtight audit trail over a title-guess is worse than
none. The two plans were mislabeled: detection is P0, enforcement hardening is P1.

## C2. Re-sequenced plan of record (supersedes E9)

**P0 — prove the wedge (build now):**
- **C-P0-1** Fix the prompt/diff bug: actually fetch and pass the PR diff. GitHub
  already includes it in the webhook payload / one API call away. (synthesizer +
  worker.py:43)
- **C-P0-2** Dumb-but-real Tier 0 detection: parse the PR diff, flag SOPs whose
  text references a file/route/symbol the diff touches. Deterministic, auditable,
  beats the title-reader immediately.
- **C-P0-3** Add TTL to the shipped lock (lock.py) — cheap kill of the live
  no-TTL permanent-brick hazard. Do this regardless of everything else.
- **C-P0-4** Minimal lock + veto + bare reconciliation screen: enough for a
  design-partner demo ("merge a PR that deletes POST /token → system detects SOP
  step 2 still calls it → quarantines → agent vetoed, with a one-line
  deterministic explanation").

**P1 — enforcement hardening (the reviewed 17-task plan, pull AFTER a design
partner reacts):** dual-store consistency contract (E1), full decision-engine
table (E2), fail-closed flip (E1 — do NOT flip until a trustworthy detector
exists; failing closed on a noise detector over-blocks on infra hiccups while
missing real breaks), confidence tiering, reconciliation UI polish, observability
(D4 metrics), canary rollout (D3). These are correct and stay on the shelf as a
ready P1; a real signal schema from Tier 0 should shape E4's persisted model
rather than the current guessed `signals[]` shape.

## C3. What changed from the eng-review addendum
- E9 build order is DEFERRED to P1. Do not start Lane A (dual-store) now.
- E4's rich persisted signal schema: keep `signals`/`evidence` as opaque JSONB
  for now; let Tier 0 define the structured shape (outside-voice #4, accepted).
- The fail-closed flip (E1) is explicitly gated on a trustworthy detector.
- TTL fix (C-P0-3) is the only piece of the enforcement plan pulled into P0.

## C4. Strategy decisions log
| # | Decision | Choice |
|---|----------|--------|
| D1 | Approach under deferred detection | A: safety + thin stub (later overturned by D5) |
| D2 | Review mode | HOLD SCOPE |
| D3 | Fail-closed rollout | Feature-flag canary-then-ramp (now P1) |
| D4 | Observability | Core metrics + sweep alert (now P1) |
| D5 | **Re-sequence** | **Detection-first; enforcement → P1** |

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | RE-SEQUENCED | HOLD mode; D5 detection-first reversal |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | not run (codex not installed) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | ISSUES_OPEN | 12 issues, 1 critical gap |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | ISSUES_OPEN | score 4/10 → 8/10, 3 decisions |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not run |

- **CROSS-MODEL:** Two independent challenges ran. #1 (eng) challenged dual-store storage; user upheld dual-store (A1-REVISED). #2 (CEO) challenged the whole sequencing; user ACCEPTED the detection-first re-sequence (D5). The eng/design enforcement plan is now P1, not P0.
- **UNRESOLVED:** 0 decisions left open.
- **CRITICAL GAP:** 1 — the shipped veto is fail-OPEN; the cheap TTL fix (C-P0-3) is pulled into P0; the full fail-closed flip is gated on a trustworthy detector (P1).
- **VERDICT:** CEO + ENG + DESIGN reviewed. Plan of record is the CEO Review Addendum (detection-first). P0 = prove the wedge (Tier 0 detection + diff fix + TTL + demo); P1 = the reviewed enforcement plan. Re-run `/review` on the diff once P0 lands.
