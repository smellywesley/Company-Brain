# Autonomous Loop State — Company Brain → GaaS (AI-agent governance)

**Read this first on every cycle or fresh session.** This file is the handoff: what the
loop is building, what's done, what's next, what it must never do.

## Scope decision (2026-07-04, user-ratified direction)
GaaS = **AI-agent/LLM action governance only**: runtime enforcement (critic gate +
quarantine), audit-ready reporting (keyed audit chain + Time-Travel snapshots, mapped to
EU AI Act Art. 12/14 + ISO/IEC 42001), SOC 2 as first compliance target. Cloud FinOps and
multicloud posture are **out of scope permanently** unless a paying customer requires them.
Goal: converge on finish lines B (pilot) and C (enterprise) — see
`PILOT_READINESS_GAP_REPORT.md`.

## Cycle protocol (user-specified)
1. Read this file; pick the top `pending` backlog item.
2. Draft a cycle plan (scope, files, tests, verifiable done-criteria — karpathy-guidelines).
3. Dispatch a **critic subagent** to adversarially audit the plan; revise.
4. Dispatch a **builder subagent** (sonnet) to implement; file-disjoint, bounded.
5. Main loop verifies independently: full pytest, lint/build if frontend touched.
6. Commit (focused), push. Update this file (cycle log + statuses).
7. If work can't complete (session limits, blocker): commit what's verified, log the
   handoff under "In-flight", stop cleanly. Next session resumes from here.
8. Loop ends when all autonomous items are done — remaining items are human-gated;
   notify the user, don't spin.

## Non-negotiables (every cycle)
No new pip/npm dependencies (installs get blocked; stdlib/existing deps only). Never
weaken fail-closed semantics. Never claim live verification that didn't happen. No force
push, never touch `main`. Tests must assert behavior, not tautologies. Karpathy: minimal
diff, no speculative abstractions, every changed line traces to the task.

## Backlog (autonomous — loop may execute)
| # | Item | Size | Status |
|---|------|------|--------|
| 1 | **Key the audit chain**: `services/audit/chain.py` uses unkeyed sha256 — a DB-write attacker can forge it; docs/UI claim "HMAC tamper-evident". Key with existing `AUDIT_HMAC_SECRET`, note the audit_logger/chain distinction, tests prove forgery-without-key fails. | S | **done** (b3ab4f0) |
| 2 | Landing page conversion: email/demo-CTA capture, founder note, honest security/roadmap blurb on `/welcome`. No redesign. | M | **done** (76f8ce7) |
| 3 | EU AI Act (Art. 12, 14) + ISO/IEC 42001 mapping doc: each existing mechanism → each requirement, with honest per-row gaps. The audit-ready-reporting story. | M | **done** (19aef17 — critic expanded scope to Art. 9/12/14/26, Art. 15 excluded deliberately) |
| 4 | Policy-as-code: externalize CriticAgent's hardcoded policy block (incl. "$500 max" default) into versioned per-tenant policy definitions; critic composes prompt from them. | L | pending |
| 5 | Governance core extraction: `governance/` package exposing critic + keyed chain + quarantine behind a documented, versioned interface (the GaaS seed; budget limiter stays app-coupled). | L | pending |
| 6 | Slack approval notifications (approvals where work happens; webhook-out only, no new deps). | L | pending |

## Human-gated (loop must NOT attempt — surface, don't fake)
Live full-stack Docker run · real-provider OAuth round-trip · SOC 2 engagement · restore
drill · discovery interviews (templates in `docs/templates/`) · production deploy ·
bigdata.com market analysis (connector unauthenticated).

## Cycle log
| Cycle | Date | Item | Outcome |
|-------|------|------|---------|
| 1 | 2026-07-04 | #1 audit-chain HMAC | Done — critic approved w/ 1 change (secret reuse ruled intentional + documented); builder implemented; 230 passed / 2 skipped; commit b3ab4f0, pushed; CI will run on push. |
| 2 | 2026-07-04 | #2 landing conversion | Done — mailto demo CTA (hero/nav/bottom), founder note, SOC 2 roadmap line. Honesty review caught builder overclaim ("proven in production") → corrected to "proven by tests and live CI runs". Lint+build green, /welcome prerenders. Commit 76f8ce7, pushed. |
| 3 | 2026-07-17 | #3 compliance mapping | Done — docs/COMPLIANCE_MAPPING.md (Art. 9/12/14/26 + ISO 42001, honest-gap column per row, banned-phrase grep clean). Review fix: builder UNDERclaimed chain testing ("only incidentally") — corrected to cite test_differentiators.py forgery tests. Commit 19aef17, pushed. |

## In-flight / handoff notes
None.
