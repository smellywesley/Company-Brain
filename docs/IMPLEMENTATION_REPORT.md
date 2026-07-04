# Implementation Report — Architecture alignment + premium frontend

_Branch: `feature/company-brain-architecture-frontend-polish` (off the full working history on `feat/contradiction-tier0-detection`)._

This report follows the architecture-alignment plan. It is deliberately honest:
it states what already existed, what was changed in this pass, and what remains —
no claim here is stronger than what the code enforces.

## 1. What the repo actually is

- **Backend**: Python / FastAPI (async), SQLAlchemy 2 async + asyncpg, Celery + Redis,
  Weaviate (vector), Neo4j (graph), Alembic. Two loops (ingestion + governed action),
  an independent `CriticAgent`, multi-tenant from the data model up.
- **Frontend**: Next.js 16 (App Router) + React 19, Tailwind v4, `motion` (Framer Motion),
  shadcn on the unified `radix-ui` package, `lucide-react`, `sonner`. Installable PWA.
- **Infra**: Docker Compose (frontend, backend, **worker**, **beat**, weaviate, neo4j,
  postgres, redis, kafka/zookeeper, vault); Terraform for AWS ECS.
- **Deploy target**: managed stack (Vercel + Railway + Supabase + Upstash + Weaviate Cloud
  + Neo4j Aura), documented in `DEPLOY.md`.
- **Tests**: `pytest` (backend), `eslint` + `tsc --noEmit` (frontend). The local dev env is
  lean (no torch/asgiref/presidio/celery-extras), so the full suite runs in CI/Docker;
  locally we verify via `py_compile` + targeted `pytest` for stdlib-only modules.

## 2. Plan vs. reality — what was already done (verified, not re-done)

Much of the plan (written ~3 weeks ago) was already addressed in prior work. Verified
against current code:

| Plan item | Status in code |
|-----------|----------------|
| T1 Celery worker in compose | **Done** — `worker` service + `beat` (scheduler) in `docker-compose.yml` |
| T1 Quarantine lock eviction | **Done** — Redis `--maxmemory-policy noeviction --appendonly yes` |
| T1 Alembic + `create_all` gate | **Done** — `migrations/`, `AUTO_CREATE_SCHEMA` off in prod |
| T0 PII redaction | **Done** — Presidio optional + regex fallback (`ingestion/base_connector.py`) |
| T4 Contradiction detector depth | **Done** — `detector.py` is diff-aware (paths/routes/identifiers), explainable `matched_entities`, not title-only |
| Governed action executors | **Done** — `ExecutorRegistry` + CRM/calendar + accounting executors; runner wires them |
| OAuth connect (Google/HubSpot/QuickBooks) + manual-credential endpoint | **Done** — `routes/oauth.py`, `routes/integrations.py` |
| Scheduler (recurring governed workflows) | **Done** — Celery beat tick → `run_governed_workflow` |

## 3. What was misaligned (and fixed in this pass)

1. **`docs/ARCHITECTURE.md` overclaimed isolation/security** (a trust bug). Reconciled to
   reality:
   - Weaviate: "per-tenant namespaces / cross-tenant 404" → **single collection with a
     mandatory `tenant_id` property filter** (native multi-tenancy is a tracked follow-up).
   - PII: "Presidio redaction" → **Presidio where installed, deterministic regex fallback
     otherwise**.
   - Secrets: "Vault; nothing hardcoded" → **env / platform store + AWS Secrets Manager for
     tenant creds; bundled Vault is dev-mode only, not production-grade**.
   - Kafka: "message bus" → **optional; Celery+Redis is the task path**.
   - Component table updated; worker/beat + readiness probes added.
2. **No split liveness/readiness probes** (only `/health`). Added.

## 4. Backend / security / infra changes (this pass)

- `backend/app/main.py`: added **`GET /health/live`** (liveness) and **`GET /health/ready`**
  (readiness — checks Postgres `SELECT 1` + Redis ping; returns **503** when a required dep
  is down so a load balancer drains the replica without killing it). Legacy `/health` kept.
- `backend/app/services/quarantine/lock.py`: added a public `ping()` that reuses the existing
  process-wide Redis pool (no second connection) for the readiness probe.
- `docs/ARCHITECTURE.md`: honesty reconciliation (above).

## 5. Frontend / UX changes (this pass)

- **New premium landing page** at `/welcome` (`frontend/src/app/welcome/page.tsx`):
  hero + one-line positioning, problem, how-it-works (the governed loop), trust section with
  a live-styled approval-queue mock panel, use-cases (role bundles), security (mechanisms,
  no fake badges), CTA, footer. Framer Motion (`motion/react`) scroll reveals; on-brand with
  the existing dark/glass tokens. Copy aligned to `docs/POSITIONING.md` — no "AI workforce",
  no unverifiable certifications.
- `frontend/src/components/shell/AppShell.tsx`: made pathname-aware so `/welcome` renders
  full-bleed (no dashboard chrome) while **every existing route keeps its sidebar/header** —
  no routes broken. The app dashboard (`/`) and all sub-pages are unchanged.

## 6. Files changed

- `backend/app/main.py`, `backend/app/services/quarantine/lock.py`
- `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_REPORT.md` (this file)
- `frontend/src/app/welcome/page.tsx` (new), `frontend/src/components/shell/AppShell.tsx`

## 7. Tests / builds run

- `python -m py_compile` on changed backend files — pass.
- `npx tsc --noEmit` + `eslint` on changed frontend files — pass.
- Existing targeted pytest suites (scheduler, executors, oauth, integrations, zendesk) — pass.
- Not run locally (lean env / no daemon): full `pytest`, `next build`, `docker compose up`.
  These run in CI / Docker. `docker compose config` validates the compose file.

## 7b. Phase 2 — production-readiness pass (verified, this pass)

Each item below was implemented AND covered by tests that run in the lean env (no live infra):

1. **Quarantine lock production semantics — hardened.** `lock.py` no longer silently
   degrades to Redis-only. If Postgres/asyncpg is unavailable, `acquire`/`release`
   **fail closed** (raise) unless `QUARANTINE_LOCK_ALLOW_REDIS_ONLY_DEV=true` in a
   non-production env (ignored in production). Reads serve Redis → Postgres fallback →
   repopulate cache; Postgres read errors fail closed. Tests:
   `tests/test_quarantine_lock_semantics.py` (8 cases: PG-first write, cache read, PG
   fallback on cache miss, release clears both, prod fail-closed, dev-no-optin fail-closed,
   dev-optin allowed).
2. **Alembic migration safety — idempotent.** `0001_initial_schema.py` creates each
   table/index only if absent (online) and emits a full fresh-DB script offline (`--sql`).
   Safe against a fresh DB AND an existing `create_all` DB — no `alembic stamp` needed.
   Verified via `alembic upgrade head --sql` (valid DDL incl. `quarantine_locks`).
3. **Kafka + ZooKeeper — removed.** Zero producers/consumers in the codebase. Removed both
   services + volumes from `docker-compose.yml`, the `KAFKA_BROKER` env from backend, the
   Kafka block from `.env.example`, and `kafka-python` from `requirements.txt`. `docker
   compose config` validates; services now: frontend, backend, worker, beat, postgres,
   redis, weaviate, neo4j, vault. Documented in ARCHITECTURE.md ("Why no Kafka").
4. **Per-tenant LLM budget — enforced.** New `app/services/budget/limiter.py`: monthly cap
   from `settings.llm_monthly_budget_usd` or `DEFAULT_LLM_MONTHLY_BUDGET_USD` (0 =
   unlimited). The governed-workflow runner blocks **before any LLM call** when over budget
   and records a `status="blocked"` audited run. Monthly rollover handled by the single
   writer (`tasks.accumulate_llm_cost`). Over-budget fails closed; DB-read error fails open.
   Generic error message (no billing internals). Tests: `tests/test_budget.py` (12 cases).
5. **Weaviate isolation — regression-tested + honest docs.** Isolation remains property-filter
   (single `Document` collection, mandatory required `tenant_id` arg, empty fails closed).
   Added `tests/test_weaviate_tenant_filter.py` (4 cases: filter carries caller's tenant,
   tenant B can't see tenant A rows, empty fails closed without querying, signature requires
   tenant_id). Docs unchanged in claim (already honest) — native MT still a follow-up.
6. **Observability minimum.** Optional Sentry via `SENTRY_DSN` (`app/services/observe/sentry.py`,
   no-op without DSN/sdk). Structured decision logs at the Tier-0 contradiction gate, budget
   blocks, and quarantine ops. `/health/live` + `/health/ready` kept. Prometheus/OTel
   explicitly NOT wired (documented as next step).
7. **DB pool sizing — env-configurable.** `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` (were hardcoded).

Test count: **185 passed, 1 skipped** (was 162). Frontend: `next build` succeeds (all 14
routes prerender); `npm run lint` has 5 pre-existing errors from Next 16's strict
react-hooks rules in files untouched this pass (non-blocking — build is green).

## 7c. Phase 3 — release-candidate validation (this pass)

Goal: get the branch to a clean demo/deployable state. No new product features.

1. **Frontend lint — fixed at the root cause (no suppressions).** All 5 Next 16
   `react-hooks` errors + 1 unused-var warning resolved:
   - `theme-toggle.tsx`: mount flag via `useSyncExternalStore` (SSR-safe) instead of
     `useEffect(setMounted)`.
   - `AnimatedCounter.tsx`: dropped redundant synchronous `setCurrent(0)` (first rAF frame
     sets it).
   - `SnapshotDialog.tsx`: `setLoading(true)` moved into the async loader.
   - `onboarding/page.tsx`: posture default in the industry click handler; removed unused
     `router`/`useRouter`.
   - `lib/sse.ts`: connection lifecycle inside the effect with a hoisted `connect`
     declaration (no self-reference TDZ); dropped `useCallback`/refs.
   Result: **`npm run lint` clean**, **`next build` passes** (all 14 routes prerender).
2. **Worker smoke — added `tasks.ping`** (no DB/LLM/external side effects) + 
   `tests/test_worker_smoke.py` (proves the app imports, the 7 expected tasks register, the
   broker is configured, and `ping` runs eagerly). Live enqueue→consume command documented
   in DEPLOY.md and the task docstring.
3. **Quarantine lock integration test** — `tests/test_integration_quarantine_lock.py`
   (skipped unless `QUARANTINE_INTEGRATION=1` + live PG/Redis): acquire→PG row + Redis cache,
   read from cache, Redis-miss→PG fallback→repopulate, release clears both. Mirrors the
   Weaviate live-test pattern. Unit-level fakes (8 cases) still prove the orchestration.
4. **Compose validated statically** (daemon unavailable in this env — see below). `docker
   compose config` renders all 9 services; Redis confirmed `--maxmemory-policy noeviction
   --appendonly yes`; worker/beat run `celery -A app.worker:celery_app worker|beat`.
5. **Health endpoints** verified via FastAPI `TestClient`: `/health/live`→200;
   `/health/ready`→503 with `{postgres,redis}` errors when deps are absent (correct
   fail-reporting; returns 200 when the stack is up).

**Could NOT run (environment limitation — documented, not faked):**
- `docker compose up -d --build`: the Docker daemon would not initialize in this environment
  (Docker Desktop launched but its Linux engine never became reachable after ~12 min across
  retries). Substitutes run instead: `docker compose config` (full render with a temp
  `.env`), static service/durability checks, and TestClient health probes.
- `alembic upgrade head` against live Postgres: no daemon/PG. Substitute: `alembic upgrade
  head --sql` produces valid DDL for all 7 tables + the version stamp; migration is
  idempotent by construction.

Test count after Phase 3: **189 passed, 2 skipped** (Weaviate + quarantine live-integration
tests skip without infra). `python -m compileall backend/app` clean.

## 7d. Weaviate tenant-isolation — release decision

**Current implementation:** property-filter isolation. A single `Document` collection scoped
by a **mandatory `tenant_id`** on every search, centralized in
`WeaviateStore.search(query_vector, tenant_id, …)`. `tenant_id` is a required argument (cannot
be omitted) and an empty value **fails closed** (returns nothing, never scans all tenants).
The only production call site (`main.py` `/search`) resolves the tenant from the OIDC session
and passes it; no route issues a raw Weaviate query.

**Safe for controlled demo / early pilot:** **Yes.**
- Tenant filter is required and centralized; empty fails closed.
- Regression tests (`test_weaviate_tenant_filter.py`) prove the caller's tenant is always in
  the filter, tenant B cannot see tenant A's rows, and the signature requires `tenant_id`.
- A live cross-tenant leak test (`test_integration_tenant_isolation.py`) gates deploy when
  Weaviate creds are present.
- Docs do not claim native multi-tenancy.

**Not yet complete for regulated enterprise:**
- Native Weaviate multi-tenancy (per-tenant shards) is **not** implemented. Property-filter
  isolation depends on the (now centralized + test-enforced) filter rather than physical
  separation.

**Decision:** Acceptable for controlled demo and early pilot. Native multi-tenancy is
**required before regulated-enterprise GA** and remains the top isolation follow-up.

## 7e. Phase 4 — live infrastructure validation + CI + demo seed (this pass)

Goal: move from "green on static checks" to a repeatable proof that the live stack actually
works. No new product features; no frontend redesign.

1. **Release-candidate CI** — `.github/workflows/release-candidate.yml` (triggers:
   `workflow_dispatch`, `pull_request`, push to the feature branch). Jobs:
   - **backend**: `pytest` + `compileall`.
   - **frontend**: `npm ci` → `npm run lint` → `npm run build`.
   - **compose-live**: boots `docker-compose.ci.yml`, applies migrations to real Postgres
     (`alembic upgrade head` + `current`), checks `/health/live` + `/health/ready` (200 with
     deps live), runs the Celery `tasks.ping` enqueue→consume smoke through Redis, runs the
     `QUARANTINE_INTEGRATION=1` live lock test, then `docker compose down -v`.
2. **Lean CI compose** — `docker-compose.ci.yml` (postgres, redis, backend, worker — the exact
   subset `/health/ready` gates on; Redis keeps `noeviction --appendonly yes`). It is
   **additive**: the full `docker-compose.yml` is untouched. CI secrets are labelled throwaways.
3. **Makefile** — `test`, `frontend-check`, `compose-config`, `compose-up`, `migrate`,
   `health-check`, `worker-smoke`, `quarantine-integration`, `demo-seed` (all call the repo's
   real commands; `COMPOSE` var overrides the stack).
4. **Demo seed hardened + extended** — `scripts/seed_demo.py` now **refuses unless
   `ENABLE_DEMO_SEED=true`** (cannot hit a prod DB by accident), labels the tenant "Acme Corp —
   Demo Workspace", and adds one **contradiction case**: an "Enterprise Onboarding" SOP
   quarantined by a conflicting PR (durable lock via the Postgres+Redis lock module, best-effort).
   The existing refund/retention narrative (which the frontend fallbacks mirror) is preserved.

**Local run results (this pass):** `pytest` 189 passed / 2 skipped · `compileall` clean ·
frontend `lint` clean + `build` passes (14 routes) · `docker compose config` valid for BOTH
`docker-compose.yml` and `docker-compose.ci.yml` · demo-seed guard verified (refuses without
the flag, exit 2, no DB touched).

**Still blocked locally (NOT faked):** `docker compose up`, live `alembic upgrade head`, live
worker enqueue→consume, and the live quarantine integration — the local Docker daemon would not
initialize (Docker Desktop launched but its Linux engine never became reachable). **These are
exactly what the `compose-live` CI job proves** on a runner with a working daemon. Until that job
has a green run, live validation is "pending CI", not "done".

## 7f. Phase 5 — green CI + demo package (this pass)

**CI result: ALL THREE JOBS GREEN** — run
[28581789446](https://github.com/smellywesley/Company-Brain/actions/runs/28581789446) on commit
`b449ad5`: `backend` ✓ · `frontend` ✓ · `compose-live` ✓. The live proofs are now **observed**,
not claimed: the stack boots, `alembic upgrade head` applies to real Postgres, `/health/live` and
`/health/ready` return 200 with deps live, `tasks.ping` is enqueued by the backend and consumed
by the worker through Redis, and the quarantine-lock integration passes against real
Postgres + Redis.

The first run ([28563938754](https://github.com/smellywesley/Company-Brain/actions/runs/28563938754))
failed and was debugged from its logs — three root-cause fixes, none of which weakened tests or
fail-closed behavior:

1. **Real product bug (found only by live CI):** `lock.py` passed `expires_at` to asyncpg as an
   ISO string; asyncpg binds `timestamptz` strictly → `DataError`. Fixed to pass a `datetime`.
   Unit fakes could not catch this — exactly why the live job exists.
2. **Env-dependent tests:** the `test_detector.py` TTL tests took the Redis-only path locally
   (no asyncpg) but the real-Postgres path in CI (asyncpg installed) and correctly failed
   closed against a nonexistent DB. They now pin `_asyncpg=None` — they test the Redis-cache
   TTL layer; fail-closed production semantics keep their own dedicated tests.
3. **Audit-chain permission bug:** the backend container logged `PermissionError` on every
   audit write (`logs/` not writable by the non-root user). Dockerfile now creates
   `/app/logs` owned by `appuser`.

**Demo package:** `docs/DEMO_RUNBOOK.md` (setup, 7-minute flow, what-not-to-claim, failure
recovery) and `docs/FOUNDER_DEMO_SCRIPT.md` (~6-minute talk track with honest caveats).
Demo-seed guard re-verified: `ENABLE_DEMO_SEED=false` → refuses, exit 2, DB untouched.

## 7g. Phase 6 — controlled demo execution + pilot-readiness bridge (this pass)

Goal: confirm the docs-only push didn't regress CI, produce the concrete demo-execution
artifacts (checklist, capture plan), and draw an explicit line between "controlled demo-ready"
and "pilot-ready" so neither gets overstated. No new product features; no frontend changes.

**CI re-confirmation:** the caveat that `03ad931` (docs-only) triggered an unawaited CI run was
closed — run [28582152408](https://github.com/smellywesley/Company-Brain/actions/runs/28582152408)
on `03ad931` is **green** (all 3 jobs), same as `b449ad5`'s
[28581789446](https://github.com/smellywesley/Company-Brain/actions/runs/28581789446). Checked
via the **unauthenticated public GitHub REST API only** (`api.github.com/repos/.../actions/runs`,
no auth header) — no stored token was used, printed, retrieved, or modified, per this phase's
explicit constraint.

**Local Docker attempt (Phase 6):** tried again — launched Docker Desktop, polled ~2.5 minutes.
Same result as every prior phase: the daemon never becomes reachable in this dev environment.
Not faked. This means the live demo flow (stack up → seed → UI verification) has still only
been **witnessed via GitHub Actions' `compose-live` job**, never on a developer machine in this
project's history — an explicit, named gap in the new demo checklist rather than a silently
assumed "it works."

**Demo execution artifacts added** (all cross-checked for the 5 non-negotiable phrases —
"enterprise-ready", "native Weaviate multi-tenancy" as done, "fully compliant"/certifications
held, "zero hallucination", unproven customer traction — none found outside "do not claim"
framing):
- `docs/DEMO_CHECKLIST.md` — pre-demo technical checklist, demo narrative checklist, what-not-
  to-claim list, all as literal checkboxes.
- `docs/DEMO_CAPTURE_PLAN.md` — the 7-minute recording beat sheet, an 8-shot screenshot list,
  and the `company-brain-demo-7min.mp4` / `company-brain-screenshots/` /
  `company-brain-demo-notes.md` output convention.
- `docs/PILOT_READINESS_GAP_REPORT.md` — three classified gap lists (must-fix-before-pilot,
  must-fix-before-enterprise, can-wait), each item with a why/done-looks-like note. This is the
  authoritative gap list going forward — README and this report link to it rather than
  restating it, so it doesn't drift out of sync.

**Parallel execution note:** the three doc files above were produced by three subagents
dispatched concurrently (user-requested), each given the same verified ground truth (CI run
IDs/conclusions, confirmed-dead local Docker, exact demo-seed behavior, the 5 non-negotiables)
so they couldn't contradict each other or invent status. All three outputs were read back and
grep-checked post-hoc for forbidden phrasing before being trusted.

**Local static re-verification this pass:** `pytest` 189 passed / 2 skipped · `compileall`
clean · frontend `lint` clean · frontend `build` passes (unchanged route count) · both
`docker compose config` and `docker compose -f docker-compose.ci.yml config` valid.
`make health-check` / `make worker-smoke` remain unrunnable locally (no daemon) — this is the
same, already-documented limitation, not a new one.

## 8. What still remains (honest follow-ups)

The authoritative, classified gap list now lives in
**[`docs/PILOT_READINESS_GAP_REPORT.md`](PILOT_READINESS_GAP_REPORT.md)** (must-fix-before-pilot
/ must-fix-before-enterprise / can-wait) — this section just points there rather than
duplicating it, so the two don't drift out of sync. Highlights: live full-stack verification
(Weaviate+Neo4j) on a real Docker host, a live Weaviate cross-tenant test, and a real OAuth
round-trip gate **pilot**; native Weaviate multi-tenancy, Prometheus/OTel, and API/worker image
split gate **regulated enterprise**.

## 9. Git

- Branch: `feature/company-brain-architecture-frontend-polish`.
- Commits: see `git log` on the branch (architecture-doc reconcile, readiness probes,
  landing page, this report).
- Remote `origin` (`github.com/smellywesley/Company-Brain.git`) `main` is an older
  manual-upload snapshot with **unrelated history**; this branch is pushed **without force**.
  Recommend merging via PR (GitHub can merge unrelated histories) or setting this branch as
  the default — do not force-push over `main`.
