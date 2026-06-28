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

## 8. What still remains (honest follow-ups)

These need live infrastructure to implement and verify safely, so they are **not** claimed
as done:

- **Weaviate native multi-tenancy** (per-tenant shards) — current isolation is property-filter
  level; verifying a rewrite needs a live Weaviate. (`test_integration_tenant_isolation.py`
  exists for the property-filter behavior.)
- **Quarantine lock source-of-truth in Postgres** — currently Redis with `noeviction` + AOF
  (eviction-safe), but not yet Postgres-backed.
- **Observability**: structured logging exists; metrics (Prometheus/OTel) and Sentry are not
  wired — readiness/liveness probes added this pass.
- **Per-tenant LLM budgets / rate caps** — cost is tracked (`accumulated_llm_cost`); hard
  budget enforcement is not yet implemented.
- **API/worker image split** + Terraform autoscaling (`desired_count=1` today).
- **Token refresh** for executor OAuth providers (refresh_token stored; refresh-on-401 not
  wired).
- **Kafka/Zookeeper** can be dropped from the launch compose (Celery+Redis carries the work).

## 9. Git

- Branch: `feature/company-brain-architecture-frontend-polish`.
- Commits: see `git log` on the branch (architecture-doc reconcile, readiness probes,
  landing page, this report).
- Remote `origin` (`github.com/smellywesley/Company-Brain.git`) `main` is an older
  manual-upload snapshot with **unrelated history**; this branch is pushed **without force**.
  Recommend merging via PR (GitHub can merge unrelated histories) or setting this branch as
  the default — do not force-push over `main`.
