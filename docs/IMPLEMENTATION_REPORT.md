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

## 8. What still remains (honest follow-ups)

These need live infrastructure or are out of scope for the release candidate:

- **Live compose run + live `alembic upgrade head`** — blocked by the local Docker daemon;
  re-run on a host with a working daemon (or in CI) before first deploy.
- **Weaviate native multi-tenancy** (per-tenant shards) — required before regulated-enterprise
  GA (see §7d).
- **Metrics (Prometheus/OpenTelemetry)** — structured logs + optional Sentry are wired; a
  `/metrics` exporter is the documented next step.
- **API/worker image split** + Terraform autoscaling (`desired_count=1` today).
- **Token refresh** for executor OAuth providers (refresh_token stored; refresh-on-401 not
  wired).
- **Per-tenant API rate limits** (per-user rate limiting exists; per-tenant LLM *budget* is
  enforced — a per-tenant request-rate quota is the remaining piece).

## 9. Git

- Branch: `feature/company-brain-architecture-frontend-polish`.
- Commits: see `git log` on the branch (architecture-doc reconcile, readiness probes,
  landing page, this report).
- Remote `origin` (`github.com/smellywesley/Company-Brain.git`) `main` is an older
  manual-upload snapshot with **unrelated history**; this branch is pushed **without force**.
  Recommend merging via PR (GitHub can merge unrelated histories) or setting this branch as
  the default — do not force-push over `main`.
