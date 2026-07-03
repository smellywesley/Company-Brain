# Company Brain — Knowledge Base (Claude-maintained index)

**Purpose:** a token-cheap reference map of this repo. Read the relevant section below
instead of re-globbing/re-reading files from scratch each session. Not the `/graphify`
tool's output (that package couldn't be run in this environment — see
`IMPLEMENTATION_REPORT.md` history) — this is a hand-built equivalent, same goal
(reduce re-exploration cost), different mechanism (structured markdown, not a graph DB).

**Maintenance:** when a phase of work materially changes structure (new module, new route,
new table, new service dir), update the relevant section here rather than leaving it stale.
Stale-but-labeled beats silently wrong — if unsure a section is current, re-glob that one
subtree rather than trusting this file blindly.

---

## 1. One-liner + positioning

Company Brain: a governed company-memory + action engine. Two loops — **Loop A** (ingest
Slack/Notion/GitHub/Zendesk → PII-redact → chunk → embed → Weaviate + Neo4j) and **Loop B**
(retrieve → WorkflowAgent proposes → CriticAgent risk-checks → human approval if risky →
ActionExecutor → HMAC-chained audit). See `docs/ARCHITECTURE.md` for the full narrative,
`docs/POSITIONING.md` for product-boundary rules, `README.md` for the current readiness tier
(controlled demo-ready — CI green — not enterprise-ready; native Weaviate multi-tenancy and
production observability are open follow-ups).

## 2. Top-level layout

```
backend/           FastAPI (async) + Celery worker/beat + Alembic migrations
frontend/           Next.js 16 (App Router) + React 19 + Tailwind v4 + Framer Motion
ingestion/           Connectors (Slack/Notion/GitHub/Zendesk) + embedding pipeline (Weaviate)
infrastructure/terraform/   AWS ECS (Terraform) — desired_count=1, no autoscaling yet
docs/               ARCHITECTURE, DEPLOY, IMPLEMENTATION_REPORT, DEMO_RUNBOOK, POSITIONING, reviews/
.github/workflows/  ci.yml, deploy.yml (older), release-candidate.yml (Phase 4/5 — CI-proven live stack)
docker-compose.yml       full local/dev stack (9 services)
docker-compose.ci.yml    lean CI stack (postgres, redis, backend, worker — the readiness subset)
Makefile              test / frontend-check / compose-config / compose-up / migrate /
                       health-check / worker-smoke / quarantine-integration / demo-seed
```

## 3. Backend architecture

**Middleware stack** (`backend/app/main.py`, registered bottom-to-top so first-added = innermost):
`InputSanitization → RateLimiter → OIDCAuth → CORS → AuditLog → SecurityHeaders`.

**Agents** (`backend/app/agents/`): `base_agent.py` (interface) · `llm_adapter.py` (unified
async Gemini/OpenAI/Anthropic client, cost estimation, Langfuse tracing, enqueues
`tasks.accumulate_llm_cost`) · `workflow_agent.py` (retrieve+propose) · `critic_agent.py`
(risk/policy pass — checks the quarantine lock **before** any LLM call, unconditional veto if
locked).

**Governed-workflow runner** (`backend/app/services/workflow/runner.py`) — the single
canonical entry point both `POST /workflow/{name}` and the Celery scheduler use. Order: match
SOP → **per-tenant budget gate (blocks before any LLM call if over)** → WorkflowAgent → Critic
→ persist `WorkflowRun` (tamper-evident audit).

**Safety mechanisms (fail-closed by design — do not weaken):**
- **Quarantine lock** (`services/quarantine/lock.py`): Postgres is source of truth
  (`quarantine_locks` table), Redis is a fast-read cache. `acquire`/`release` raise if
  Postgres/asyncpg is unavailable, unless `QUARANTINE_LOCK_ALLOW_REDIS_ONLY_DEV=true` in a
  non-production env (ignored in prod). `expires_at` must be passed as a `datetime` object,
  not an ISO string — asyncpg binds `timestamptz` strictly (a live-CI-only bug, fixed Phase 5).
- **Weaviate tenant isolation** (`ingestion/embedding_pipeline.py` `WeaviateStore.search`):
  property-filter based (single `Document` collection, **required** `tenant_id` arg, empty
  fails closed). Centralized — no route queries Weaviate directly. NOT native multi-tenancy
  (per-tenant shards) — never claim that.
  `services/security/tenant_isolation.py` wraps it (`TenantIsolatedWeaviateStore`) plus
  `TenantIsolatedNeo4jStore` (parameterized Cypher only, no string interpolation).
- **Per-tenant LLM budget** (`services/budget/limiter.py`): monthly cap from
  `settings.llm_monthly_budget_usd` or `DEFAULT_LLM_MONTHLY_BUDGET_USD` env (0 = unlimited).
  Over-budget fails closed (blocks before LLM call); a DB read error fails **open** (cost
  control must not cause an outage). Rollover owned by the single writer
  `tasks.accumulate_llm_cost` in `worker.py`.
- **Secrets** (`services/security/secret_config.py`): `require_secret()` fails closed in
  production (`ENVIRONMENT=production`) on missing/placeholder/short secrets; ephemeral dev
  secret in local/dev so the stack still boots.

**Contradiction Handshake** (`services/contradiction/`): `detector.py` is a pure, diff-aware
Tier-0 structural gate (extracts changed paths/routes/identifiers from a PR diff, checks SOP
text overlap — no I/O) that decides whether to bother calling the LLM; `synthesizer.py` does
the actual LLM adjudication and fails open (no contradiction) on parse/provider errors. A real
conflict calls `quarantine.acquire_sync(...)`.

**Other services:** `feedback_loop/` (anomaly detection → quorum → skill re-synthesis →
critic calibration — the "moat" that gets stricter over time) · `skills_generator/`
(clusters ingested docs into auto-discovered SOPs) · `knowledge_graph/` (Neo4j entity
extraction + dedup) · `risk/` (blast-radius simulation, probabilistic forecaster) ·
`executors/` (`registry.py` + `crm_calendar.py` + `accounting.py` — the governed
action "final mile", CRM/calendar/accounting via OAuth) · `scheduler/` (pure due-logic for
Celery beat) · `observe/` (`pipeline.py` OODA ingestion, `sentry.py` optional error tracking
— no-op without `SENTRY_DSN`) · `audit/chain.py` (HMAC-SHA256 chained entries, Time-Travel
snapshots) · `tenant/industry_templates.py` (per-industry risk posture defaults).

## 4. Data model (`backend/app/db/models.py`)

7 tables, all tenant-scoped except the infra-level lock: `Tenant`, `Skill`, `SkillVersion`,
`WorkflowRun`, `FeedbackRecord`, `IngestionCursor`, and **`QuarantineLock`** (keyed by
`tenant_id` string + `skill_id` string, not a tenant FK — it's an infra-level safety table).
Schema owned by **Alembic**, not `create_all` (`backend/migrations/versions/0001_initial_schema.py`
— idempotent: create-if-absent online, full script offline via `--sql`).
`AUTO_CREATE_SCHEMA` env gates `create_all`: on by default in dev, off in prod.

## 5. API surface (`backend/app/main.py` + `routes/`)

Core (`main.py`, no prefix): `GET /health`, `/health/live`, `/health/ready` · `GET /events`
(SSE) · `POST /ingest/{source}` · `POST /observe` · `POST /workflow/{name}` (the governed
loop) · `POST /feedback` · `POST /search` (Weaviate, tenant-scoped) · `GET /connectors`,
`/skills`, `/quarantine`, `POST /quarantine/{skill_id}/release` · dashboard reads: `/workflows`,
`/verdicts`, `/stats`, `/activity`, `/critic/calibration`, `/blast-radius/{run_id}`, `/audit`,
`/audit/{run_id}/snapshot`, `/policy/history` · tenant: `GET/PUT /tenant/profile`,
`POST /onboarding`, `GET /tenant/settings`.

Routers: `oauth.py` (prefix `/oauth`) — `GET /connect/{source}`, `GET /callback/{source}`
(executor OAuth: Google/HubSpot/QuickBooks; refresh-on-401 **not yet wired** — known gap).
`webhooks.py` (prefix `/webhooks`) — `POST /slack`, `POST /github` (HMAC-verified).
`integrations.py` (prefix `/integrations`) — `POST /{provider}/credentials` (manual token
paste), `GET ""` (connected status).

## 6. Frontend (`frontend/src/`)

Next.js App Router. Routes: `/` (dashboard/command center), `/welcome` (marketing landing,
full-bleed, no dashboard chrome — `AppShell.tsx` is pathname-aware), `/approvals` (swipeable
approval queue), `/reconciliation` (contradiction/quarantine cases), `/audit` (HMAC chain +
Time-Travel snapshot dialog), `/connectors`, `/hub` (policy timeline, profile editor),
`/settings`, `/onboarding`, `/offline` (PWA fallback). Shell: `components/shell/`
(AppShell/Header/Sidebar/nav.ts). Viz: `components/viz/` (CalibrationChart, RiskGauge,
BlastRadiusGraph). `lib/api.ts` (typed API client), `lib/sse.ts` (`useEventStream` hook —
connection lifecycle lives inside the effect, `connect` hoisted to avoid TDZ). Stack: `motion`
(Framer Motion), shadcn on unified `radix-ui`, `lucide-react`, `sonner`, installable PWA
(manifest.ts, ServiceWorkerRegister.tsx).

## 7. Tests (`backend/tests/`, 189 passed / 2 skipped as of Phase 5)

Pure/unit (no infra): `test_core.py`, `test_detector.py` (contradiction Tier-0 + quarantine
TTL cache layer, pinned `_asyncpg=None`), `test_contradiction.py` (CriticAgent quarantine
veto), `test_budget.py` (12 cases), `test_quarantine_lock_semantics.py` (8 cases — PG-first
write/cache/fallback/fail-closed), `test_weaviate_tenant_filter.py` (4 cases — mock backend,
filter always carries caller's tenant), `test_worker_smoke.py` (celery app import + `tasks.ping`
eager run), `test_security.py`, `test_security_hardening.py`, `test_tenancy.py`,
`test_scheduler.py`, `test_feedback_loop.py`, `test_executors.py` + `test_crm_calendar_executor.py`
+ `test_accounting_executor.py`, `test_oauth.py`, `test_integrations.py`,
`test_zendesk_connector.py`, `test_dashboard_endpoints.py`, `test_differentiators.py`,
`test_tailoring.py`, `test_observe.py`, `test_quarantine_api.py`, `test_concurrency.py`.

**Live-infra only (skipped unless env flag set):** `test_integration_tenant_isolation.py`
(needs `WEAVIATE_URL`), `test_integration_quarantine_lock.py` (needs
`QUARANTINE_INTEGRATION=1` + real Postgres/Redis) — both proven green in CI
(`release-candidate.yml` `compose-live` job), not locally (Docker daemon unavailable in this
dev environment).

## 8. Infra / CI (Phase 4–5)

`docker-compose.yml`: frontend, backend, worker, beat, weaviate, neo4j, vault (dev-mode
only — **never** documented as production-grade), postgres, redis (`--maxmemory-policy
noeviction --appendonly yes` — safety locks must never be evicted). **No Kafka/ZooKeeper**
(removed Phase 2 — zero producers/consumers existed).
`docker-compose.ci.yml`: lean 4-service subset for CI (postgres/redis/backend/worker — exactly
what `/health/ready` gates on).
`.github/workflows/release-candidate.yml`: `backend` (pytest+compileall) →
`frontend` (npm ci+lint+build) → `compose-live` (boot lean stack, `alembic upgrade head`
against real Postgres, health live/ready, `tasks.ping` enqueue→consume through Redis, live
quarantine integration, `down -v`). **Last known state: all 3 jobs green** (run 28581789446,
commit b449ad5) — see `docs/IMPLEMENTATION_REPORT.md` §7f for the failure→fix history.
Local Docker daemon does not initialize in this dev environment — CI is the only place the
live stack has actually been observed running.

## 9. Demo package

`scripts/seed_demo.py`: refuses unless `ENABLE_DEMO_SEED=true` (verified: exit 2, DB
untouched otherwise). Seeds "Acme Corp — Demo Workspace" tenant, approval-queue runs +
audit trails, critic policy history, and one contradiction case (Enterprise Onboarding SOP
quarantined by a conflicting PR — durable Postgres+Redis lock, best-effort). Run via
`make demo-seed`. Demo flow + talk track: `docs/DEMO_RUNBOOK.md` / `docs/FOUNDER_DEMO_SCRIPT.md`.

## 10. Conventions / gotchas worth remembering

- Every DB table and every Weaviate/Neo4j query takes `tenant_id` — never add a query path
  that skips it.
- `ponytail:` comments mark deliberate simplifications with a named upgrade trigger — read
  them before "fixing" something that looks incomplete.
- Fail-**closed** for safety (quarantine, Weaviate empty-tenant, over-budget), fail-**open**
  for infra blips that aren't safety-relevant (budget DB read error, contradiction synthesizer
  parse error).
- `main` (GitHub remote) is older, unrelated history — never merge into it casually; all work
  lives on `feature/company-brain-architecture-frontend-polish`.
- Docs never claim: native Weaviate multi-tenancy, enterprise production readiness, compliance
  certifications, zero hallucination, or unproven customer traction.

## 11. Known open follow-ups (see IMPLEMENTATION_REPORT.md §8 for the live list)

Native Weaviate multi-tenancy · Prometheus/OTel metrics · API/worker image split +
Terraform autoscaling (`desired_count=1`) · OAuth refresh-on-401 · per-tenant API rate quota
(LLM *budget* is enforced; request-rate isn't yet).
