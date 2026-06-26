# Lore / Company Brain — Deployment Guide (managed stack)

**Stack:** Vercel (frontend) · Railway (API + Celery worker) · Supabase (Postgres) · Upstash (Redis) · Weaviate Cloud (vectors) · Neo4j Aura (graph) · an OIDC provider (Okta/Auth0).

Provision data stores first → API → frontend → **re-audit gate** → go public. All required env vars are documented in `.env.example`.

---

## Step 1 — Generate the two app secrets
The backend **refuses to boot in production** without these. Generate locally:
```
openssl rand -base64 48   # run twice
```
Use the two values for `SKILL_SIGNING_KEY` and `AUDIT_HMAC_SECRET`.

## Step 2 — Supabase (Postgres)
1. supabase.com → **New project**. Region near your users; strong DB password.
2. Settings → Database → **Connection string (URI)**.
3. Capture `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, host, port.
4. Ensure the user can `CREATE TABLE` — schema is applied by Alembic (`alembic upgrade head`, Step 7), not implicit `create_all` (which stays off in prod via `AUTO_CREATE_SCHEMA`).

## Step 3 — Upstash (Redis)
1. upstash.com → **Create Redis database** (matching region).
2. Copy the `rediss://` URL → `CELERY_BROKER_URL`.

## Step 4 — Weaviate Cloud (vectors)
1. console.weaviate.cloud → **Create cluster** (Sandbox is fine to start).
2. Copy the REST endpoint → `WEAVIATE_URL`, and an API key → `WEAVIATE_API_KEY`.

## Step 5 — Neo4j Aura (graph)
1. neo4j.com/product/auradb → **Create AuraDB Free**. **Save the password** (shown once).
2. Capture `NEO4J_URI` (`neo4j+s://…`), `NEO4J_USER` (`neo4j`), `NEO4J_PASSWORD`.

## Step 6 — OIDC provider (auth)
1. Okta or Auth0 → create an application.
2. Capture `OIDC_ISSUER` and `OIDC_AUDIENCE`. **Required in prod:** with `AUTH_BYPASS_DEV` off, an unset `OIDC_ISSUER` makes the API reject *every* authenticated request — you'll lock yourself out and the app will look broken. (Add the Vercel/Railway URLs as allowed origins in Step 9.)

## Step 7 — Backend API (Railway)
1. railway.app → New project → **Deploy from repo**, root `backend/` (it has a Dockerfile).
2. Set env vars (from `.env.example`), critically:
   - `ENVIRONMENT=production`
   - `SKILL_SIGNING_KEY`, `AUDIT_HMAC_SECRET` (Step 1)
   - `AUTH_BYPASS_DEV` → **leave unset**
   - `AUTO_CREATE_SCHEMA=false` (Alembic owns the schema in prod — no implicit DDL at boot)
   - `TRUSTED_PROXY_COUNT=1` (behind Railway's edge)
   - `OIDC_ISSUER`, `OIDC_AUDIENCE`
   - `POSTGRES_*`, `CELERY_BROKER_URL`, `WEAVIATE_URL`/`WEAVIATE_API_KEY`, `NEO4J_*`
   - `LLM_PROVIDER`, `LLM_API_KEY`
   - `BACKEND_URL` = the Railway public URL (set after first deploy, then redeploy)
   - `FRONTEND_ORIGIN` = the Vercel URL (Step 8)
3. **Add a second Railway service** (same image, **same env vars as the API**) for the Celery worker — start command `celery -A app.worker:celery_app worker -l info`, run from `backend/` (use the colon form; the dotted form is ambiguous to Celery's resolver). Without it, ingestion/synthesis tasks enqueue but never run. (Compose users: the `worker` service is already wired in `docker-compose.yml`.)
4. **Run migrations** (Alembic owns the schema). One-off from `backend/` against the prod DB: first time, generate + commit the initial revision —
   `DATABASE_URL=<supabase-url> alembic revision --autogenerate -m "initial schema"`, then on every deploy `DATABASE_URL=<supabase-url> alembic upgrade head`.
5. Confirm `GET https://<railway>/health` → 200.

## Step 8 — Frontend (Vercel)
1. vercel.com → New Project → import repo → **Root Directory = `frontend`** (Next.js auto-detected).
2. Env: `NEXT_PUBLIC_API_URL` = the Railway API URL.
3. Deploy. HTTPS is automatic (required for PWA install + OIDC).

## Step 9 — Wire-up
- API `FRONTEND_ORIGIN` = exact Vercel origin (CORS), then redeploy.
- API `BACKEND_URL` = Railway URL, then redeploy.
- In the OIDC provider, add the Vercel origin + Railway `/oauth/callback` as allowed.

## Step 10 — Re-audit gate (REQUIRED before public)
- **Tenant isolation:** with live Weaviate creds, run
  `WEAVIATE_URL=… WEAVIATE_API_KEY=… python -m pytest tests/test_integration_tenant_isolation.py` → must pass (cross-tenant leak proof).
- **OAuth:** real `/oauth/connect` → callback round-trip via the OIDC provider.
- **Rate limiting:** confirm per-user limiting on authenticated requests.
- No Critical/High remaining.

## Step 11 — Smoke test
- Log in (OIDC) → run an approval → feedback round-trip.
- On a phone: Add to Home Screen → confirm standalone launch + offline shell.

## Rollback
Vercel and Railway retain previous deploys — promote the last good one on failure.

## Post-launch scale follow-ups (P1)
Autoscaling (`desired_count > 1`); per-process `pool_size` vs the managed Postgres connection cap (front with a pooler/PgBouncer); move tasks off public subnets; Terraform remote state if you return to IaC.
