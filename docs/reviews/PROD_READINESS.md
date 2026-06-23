# Company Brain — Production Readiness Review

**Date:** 2026-06-23
**Branch:** `feat/contradiction-tier0-detection` (uncommitted WIP present)
**Goal assessed:** Deploy the **web app** to production today, ship an installable **PWA**, and make the architecture production-viable and scalable.
**Scope:** Read-only audit. No source code was modified. Tests and the frontend build were executed for real; verbatim output is below.

---

## 1. Current State

### Runtime components (from README, ARCHITECTURE.md, docker-compose, terraform)

| Component | Tech | Where defined | Status |
|---|---|---|---|
| Frontend (web app) | Next.js 16 (App Router, React 19), standalone output | `frontend/`, `frontend/Dockerfile`, compose `frontend` | **Builds clean.** Deployable as a container. **Not in Terraform** (see P0). |
| API | FastAPI / Uvicorn (async) | `backend/app/main.py`, compose `backend`, `ecs.tf` backend task | **Imports & boots clean** (32 routes). |
| Worker | Celery (`app.worker.celery_app`) — feedback loop, ingestion, webhooks, cost accounting | `backend/app/worker.py`, `ecs.tf` worker task | Module is complete and valid. **Missing from docker-compose** (see P1). |
| Relational DB | PostgreSQL (SQLAlchemy async, asyncpg) | compose `postgres`; prod expects Neon (external) | Tables auto-create on startup via `init_db()`. No Alembic migrations run in the deploy path. |
| Vector store | Weaviate | compose `weaviate`; prod expects Weaviate Cloud | External in prod; not provisioned by Terraform. |
| Knowledge graph | Neo4j | compose `neo4j`; prod expects AuraDB | External in prod; not provisioned by Terraform. |
| Cache / broker | Redis (rate limiter + Celery broker + quarantine locks) | compose `redis`; prod expects Upstash | External in prod; not provisioned by Terraform. |
| Message bus | Kafka + ZooKeeper | compose only | Not in Terraform; optional for the web path. |
| Secrets | Vault (compose, **dev mode**) / AWS Secrets Manager (Terraform) | compose `vault`, `secrets.tf` | Prod uses Secrets Manager (good). Vault is dev-mode only. |
| Ingestion | Slack / Notion / GitHub connectors + Presidio + sentence-transformers | `ingestion/` | Present; embedding path imports `weaviate` + sentence-transformers at module load. |

### WIP feature assessment (observe / quarantine / reconciliation)

All three WIP features are **import-clean, fully wired, and tested** — not half-built:

- **`backend/app/services/observe/pipeline.py`** — universal OODA ingestion. Self-contained, deterministic heuristic fallback when no LLM key. Wired into `main.py` `POST /observe`. 6 tests pass.
- **`backend/app/services/quarantine/{lock,service}.py`** — Redis-backed quarantine + read/release service. Wired into `main.py` `GET /quarantine` and `POST /quarantine/{skill_id}/release`. 8 tests pass.
- **`frontend/src/app/reconciliation/page.tsx`** — complete, polished UI (severity badges with text+icon for a11y, offline-unreachable state, optimistic release). Builds and prerenders.
- **Wiring diffs are coherent:** `rbac_policies.yaml` adds the `quarantine` resource to the manager role (matches the `approve_action`/`quarantine` permission the release route requires); `nav.ts` adds the Reconciliation nav entry; `api.ts` adds `getQuarantines()` / `releaseQuarantine()` typed clients consumed by the page.

### Will `main.py` boot?

**Yes — verified.** `import app.main` succeeds and registers **32 routes** (including `/observe`, `/quarantine`, `/quarantine/{id}/release`) once the standard `requirements.txt` deps are present.

Caveat worth knowing: `main.py` imports `SkillMatcher` at module level → `matcher.py` imports `Embedder` at module level → `ingestion/embedding_pipeline.py` does a **top-level `import weaviate`**. So `weaviate-client` (and the sentence-transformers/torch stack it lazily uses) **must be installed for the API process to even import** — it is not as "lazy" as DEMO.md implies. This is satisfied in the Docker image (full `requirements.txt`), so it is **not a prod blocker**, but it does mean the API container must carry the heavy ML deps even though the demo dashboard endpoints never use them. (Optimization opportunity: make the matcher/embedder import lazy so the API can run lean — P2.)

---

## 2. Test / Build Results (verbatim key output)

### Backend — `python -m pytest -q`

Environment note: the machine's global Python (3.11.9) had **no backend deps installed**. I installed only the **lean test set** (fastapi, pydantic, sqlalchemy, PyJWT, pyyaml, httpx, redis, celery, aiosqlite, pytest, pytest-asyncio, weaviate-client, boto3, kafka-python). I deliberately did **not** install `presidio-analyzer`, `sentence-transformers`, or `torch` (huge, and the suite is designed to run without them).

```
.........................................s.............................. [ 67%]
........................F..........                                      [100%]
================================== FAILURES ===================================
_______________ TestPIIRedaction.test_base_connector_redaction ________________
>       from ingestion.base_connector import BaseConnector
E   ModuleNotFoundError: No module named 'presidio_analyzer'
..\ingestion\base_connector.py:15: ModuleNotFoundError
=========================== short test summary info ===========================
FAILED tests/test_security.py::TestPIIRedaction::test_base_connector_redaction
1 failed, 105 passed, 1 skipped, 1 warning in 20.17s
```

**Result: 105 passed, 1 skipped, 1 failed.** The single failure is the **known environment-only `presidio_analyzer` import** that DEMO.md explicitly documents as passing in CI. All WIP tests pass:

```
$ python -m pytest -q tests/test_observe.py tests/test_quarantine_api.py
14 passed, 1 warning in 0.82s
```

Boot check:
```
$ PYTHONPATH="..;." DATABASE_URL="sqlite+aiosqlite:///:memory:" python -c "import app.main; ..."
MAIN IMPORT OK: Company Brain Backend 0.2.0 | routes: 32
```

### Frontend — `npm run build`

```
▲ Next.js 16.2.6 (Turbopack)
✓ Compiled successfully in 2.3s
  Finished TypeScript in 3.8s ...
✓ Generating static pages using 11 workers (10/10) in 631ms
Route (app)
┌ ○ /            ├ ○ /approvals   ├ ○ /audit    ├ ○ /hub
├ ○ /onboarding  ├ ○ /reconciliation  └ ○ /settings   (+ /_not-found)
=== BUILD EXIT: 0 ===
```

**Result: PRODUCTION BUILD PASSES.** TypeScript clean; all 10 routes (incl. the WIP `/reconciliation`) compile and prerender.

### Frontend — `npm run lint`

```
✖ 6 problems (5 errors, 1 warning)
=== LINT EXIT: 1 ===
```

Lint fails, but **every flagged file is pre-existing, none are WIP**: `src/lib/sse.ts` (`connect` used before declaration in reconnect closure), `src/components/theme-toggle.tsx`, `src/app/onboarding/page.tsx`, `src/components/AnimatedCounter.tsx`, `src/components/audit/SnapshotDialog.tsx`. These are `react-hooks` rule violations that **do not block `next build`** (build runs its own typecheck and passed). Not a deploy blocker; flagged as P2 hygiene.

---

## 3. Deploy Blockers — P0 (must fix to deploy the web app today)

1. **The frontend has no production deployment target.** Terraform (`ecs.tf`) provisions only `backend` and `worker` ECS services — there is **no frontend task, service, or ALB target group**, and the ALB forwards `/` straight to the backend on :8000. As written, `terraform apply` does **not** put the web app online. *Fix today:* either (a) deploy the frontend container separately (Vercel / Amplify / a Render/Fly service) — fastest path given `output: "standalone"` and a working Dockerfile; or (b) add an ECS frontend service + a second ALB target group / path rule. Option (a) is the realistic EOD move.

2. **No HTTPS.** The ALB has only an HTTP :80 listener — no ACM certificate, no :443 listener, no HTTP→HTTPS redirect (the SG opens 443 but nothing listens). OIDC/JWT auth, `allow_credentials` CORS, and httpOnly sessions are unsafe over plaintext. *Fix today:* issue an ACM cert, add a 443 listener + redirect (or terminate TLS at the platform in option 1a).

3. **Secrets default to known-weak placeholders.** docker-compose and `.env` fall back to `change-me-in-production`, `change-me-redis`, `neo4j/change-me-now`, Vault `dev-only-token`, Weaviate `change-me`. *Fix today:* confirm real secret values are set in AWS Secrets Manager (Terraform path) / the chosen platform; never ship the fallbacks.

4. **`AUTH_BYPASS_DEV` must be off in prod.** DEMO.md uses `AUTH_BYPASS_DEV=1` to inject a synthetic admin for the tokenless demo. If this leaks into the prod environment, the entire OIDC/RBAC layer is bypassed. *Fix today:* assert it is unset/`0` in the production environment and ideally hard-fail startup if `ENVIRONMENT=production` and the bypass is on.

5. **DB schema relies on `Base.metadata.create_all` at startup; Alembic is unused in the deploy path.** First-boot table creation works, but there is no migration/versioning step in the deploy, and on managed Postgres (Neon) the app role needs DDL rights at startup. *Fix today:* decide deliberately — run `create_all` once against the prod DB (acceptable for a first deploy) or wire `alembic upgrade head` as a release step. Confirm the prod DB URL is reachable and the role can create tables.

---

## 4. Scalability Gaps — P1

1. **No autoscaling; `desired_count = 1` for both services.** No `aws_appautoscaling_target`/`_policy`. Backend is a single Fargate task → a single point of failure with no horizontal scale. *Fix:* set `desired_count >= 2` across the 2 AZs and add CPU/ALB-request-count target-tracking autoscaling.

2. **Celery worker is missing from docker-compose.** Compose enqueues to Redis (feedback re-synthesis, async ingestion, webhook processing, cost accumulation) but runs **no consumer** — those tasks silently never execute on the compose stack. Terraform does define a worker. *Fix:* add a `worker` service to compose running `celery -A app.worker.celery_app worker`. Also add worker autoscaling (queue-depth based) in Terraform.

3. **Backend task is 256 CPU / 512 MB.** The API process imports the sentence-transformers/torch stack at boot (via the matcher→embedder→weaviate chain). 512 MB is too small for that footprint and any real embedding/synthesis work; expect OOM / slow cold starts. *Fix:* bump task size, or split a lean API from a heavy embedding/worker image (ties to the P2 lazy-import fix).

4. **No connection pooling discipline for managed Postgres.** `database.py` hardcodes `pool_size=20, max_overflow=10` per process. With multiple API + worker tasks against Neon (which has low connection ceilings), connections multiply (tasks × 30) and will exhaust the DB. *Fix:* use a pooler (PgBouncer / Neon pooled endpoint) and/or right-size per-process pools.

5. **State stores not provisioned or pinned by IaC.** Postgres/Redis/Weaviate/Neo4j are external (Neon/Upstash/Weaviate Cloud/AuraDB) referenced only via variables. No Terraform-managed RDS/ElastiCache, no version pinning, no backup/PITR config visible. SPOF + drift risk. *Fix:* manage them in IaC (or at least document the managed instances, sizes, and backup policy).

6. **Tasks run in public subnets with `assign_public_ip = true`.** No private subnets, no NAT gateway. Containers are directly internet-addressable. *Fix:* move ECS tasks to private subnets behind NAT; keep only the ALB public.

7. **No Terraform remote state backend.** `main.tf` has no `backend` block → local state, unsafe for team/CI deploys and prone to drift/loss. *Fix:* add S3 + DynamoDB lock backend.

8. **`weaviate:latest` image tag** in compose — non-reproducible builds. Pin a version.

9. **CloudWatch log retention is 7 days** — too short for an audit/compliance product. Raise retention; consider shipping the HMAC audit chain to durable storage.

---

## 5. Nice-to-have — P2

- **Make the matcher/embedder import lazy** so the API can run without the torch/weaviate stack at import time (enables a lean API image and faster cold start; also makes `AUTH_BYPASS_DEV` demo runs lighter).
- **Fix the 5 pre-existing lint errors** (`sse.ts` reconnect closure, `theme-toggle`, `onboarding`, `AnimatedCounter`, `SnapshotDialog`) and gate lint in CI so it cannot regress.
- **Pin all image tags** (Weaviate, and verify others) for reproducibility.
- **Add `/health` readiness vs liveness split** (DB/Redis dependency check on readiness) so ALB does not route to a task whose dependencies are down.
- **Add HSTS/redirect once HTTPS lands** (SecurityHeaders middleware already exists; ensure it emits HSTS only behind TLS).

---

## 6. PWA Punch-list (to ship an installable PWA today)

Current state: **zero PWA infrastructure.** `frontend/public/` contains only the default Next SVGs; there is no web manifest, no service worker, no icons beyond `favicon.ico`, and `layout.tsx` exports no `viewport`/`themeColor`/`manifest` metadata. The app is desktop-dashboard styled (responsive Tailwind utilities are used, e.g. `sm:` breakpoints on the reconciliation page, but mobile layout is unverified).

To make it installable today:

1. **Web App Manifest.** Add `frontend/src/app/manifest.ts` (Next App Router native) or `public/manifest.webmanifest` with: `name`, `short_name`, `start_url: "/"`, `display: "standalone"`, `background_color`, `theme_color` (match the dark theme), and `icons`.
2. **Icons.** Generate `192x192` and `512x512` PNGs (plus a `512` `maskable` icon) and an `apple-touch-icon` (180x180). Place in `public/`. (Only `favicon.ico` exists today.)
3. **Viewport + theme-color metadata.** Add a `viewport` export (`width=device-width, initial-scale=1`) and `themeColor` to `layout.tsx`. Reference the manifest via `metadata.manifest`.
4. **Service worker.** Next 16 has no built-in SW. Either add `next-pwa`/`@ducanh2912/next-pwa`, or hand-write a minimal SW registered from a client component, providing: precache of the app shell, runtime caching for static assets, and a navigation fallback for offline. Note the app already does graceful API-offline fallback (mock data + "disconnected" banner), so an offline **app shell** is the main missing piece.
5. **iOS specifics.** Add `apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style`, and the apple-touch-icon link for installability on iOS Safari.
6. **HTTPS is mandatory for PWA install + service workers** — this is the same requirement as P0 #2. No HTTPS → no installable PWA. Couple the two.
7. **Mobile QA pass.** Verify the AppShell nav, dashboard cards, approvals, and reconciliation pages are usable at ~375px width before claiming "installable + usable."

Estimated effort: manifest + icons + metadata is ~1–2 hours; a basic offline-shell service worker via `next-pwa` is another ~1–2 hours. Achievable today **if** HTTPS is in place.

---

## 7. Recommended EOD Sequence

1. **Lock down config (15 min).** Verify all prod secrets are real (no `change-me*`), confirm `AUTH_BYPASS_DEV` is unset in prod, confirm the prod Postgres/Redis/Weaviate/Neo4j URLs resolve.
2. **Pick the web deploy path (now).** Fastest viable: deploy the Next.js standalone container to a managed platform (Vercel/Amplify/Render/Fly) that gives **HTTPS for free** and set `BACKEND_ORIGIN` so the `/api/*` rewrite proxies to the FastAPI service. This resolves P0 #1 and #2 together. (Alternatively, extend Terraform with a frontend service + ACM 443 listener — more work, less likely to finish today.)
3. **Stand up the API + worker (1–2h).** Build/push the backend image; deploy the backend ECS service (bump memory off 512 MB) and the worker service. Point them at the managed state stores. Run `create_all` (or `alembic upgrade head`) once against prod DB.
4. **Smoke test (30 min).** `GET /health` → `{"status":"ok","version":"0.2.0"}`; exercise `/observe`, `/quarantine`, an approval → feedback (confirm the worker consumes `tasks.process_feedback`).
5. **Ship the PWA layer (2–4h, parallelizable).** Manifest + icons + viewport/theme-color metadata + a `next-pwa` offline shell. Verify installability on Chrome and iOS Safari over the now-HTTPS URL.
6. **Backlog the P1 scalability work** (autoscaling, `desired_count>=2`, worker in compose, private subnets, remote TF state, connection pooler) — none block a first prod deploy of the web app, but all are needed before real traffic/SLA.

---

## Executive Summary

- **Tests:** Backend **105 passed / 1 skipped / 1 failed** — the lone failure is the documented environment-only `presidio_analyzer` import (green in CI). All 14 WIP tests pass. `main.py` imports and registers 32 routes.
- **Build:** Frontend `npm run build` **PASSES** (exit 0), all routes incl. WIP `/reconciliation`. `npm run lint` fails on **5 pre-existing** errors (none in WIP, non-blocking for build).
- **WIP features:** observe / quarantine / reconciliation are **finished, wired, and tested** — not half-built.
- **Deployable today? — QUALIFIED YES for the web app, but NOT via Terraform as-is.** The code is ready; the infra is not. Critical path: (1) deploy the Next.js standalone container to a platform that gives HTTPS, with `/api/*` proxied to the API; (2) deploy backend + worker against the managed state stores with real secrets and `AUTH_BYPASS_DEV` off; (3) run DB table creation once. The blockers are deployment plumbing (no frontend in IaC, no HTTPS, secret/bypass hygiene, schema bootstrap), not application bugs.
- **PWA today? — YES, ~3–6h of work,** but **only after HTTPS is live**. Today there is zero PWA infra (no manifest, SW, or icons); the punch-list above is the complete path.
- **Scalability:** Single-task services with no autoscaling, no frontend/state stores in IaC, public-subnet tasks, per-process DB pools against managed Postgres, and a Celery worker missing from compose. All P1 — fix before real load, not before first deploy.
