# Pilot Readiness Gap Report

This report bridges three states: **controlled demo-ready** (proven true today by CI —
see `docs/IMPLEMENTATION_REPORT.md` and GitHub Actions runs `28582152408` (commit
`03ad931`) and `28581789446` (commit `b449ad5`), both green across backend, frontend,
and compose-live jobs), **pilot-ready** (safe to hand to one real but small/friendly
customer, not yet a regulated enterprise), and **enterprise-ready** (safe for a
regulated enterprise deployment).

Nothing in this document should be read as already done just because it is described
in specific, checklist detail below. A specific description of a gap is not evidence
of progress on closing it — it exists so the gap is falsifiable and someone can verify
it directly, rather than relying on a vague assurance that things are "basically fine."

---

## 1. Must fix before controlled pilot

A pilot customer will touch the full stack, real third-party accounts, and real
production secrets — none of which CI has exercised yet. CI has only proven the lean
`docker-compose.ci.yml` subset (postgres, redis, backend, worker) inside GitHub
Actions; the full stack and live external integrations remain unverified.

- [ ] Verify full `docker-compose.yml` (including Weaviate + Neo4j) boots live on a real Docker host — why: only the lean CI subset has ever been proven live; Weaviate and Neo4j have never been started together with the rest of the stack outside of code review. Done = a real machine (not CI) brings up every service in `docker-compose.yml`, all health checks pass, and the app functions end to end against it.
- [ ] Run the live Weaviate cross-tenant isolation test against a real Weaviate instance — why: `test_integration_tenant_isolation.py` exists but is `pytest.mark.skipif`-gated on `WEAVIATE_URL` and has never actually executed against a live Weaviate in this project's history; today's isolation is property-filter based in a single `Document` collection, not native multi-tenancy. Done = the test runs (not skipped) against a live Weaviate instance and passes, with the run logged.
- [ ] Complete an OAuth round-trip against at least one real provider account (Google Calendar, HubSpot, or QuickBooks) — why: `backend/app/routes/oauth.py` has only been unit-tested with mocks (`test_oauth.py`); no real provider has ever authorized, returned a token, and had that token used for a real API call. Done = one live authorize -> callback -> token-use cycle completes successfully against a real account.
- [ ] Review the production environment for secret placeholders — why: `docker-compose.yml`'s `change-me-*` password fallbacks are for local/dev convenience only, and there is no automated CI check yet that a production env has zero placeholder secrets; `secret_config.py` fails closed in production but only for missing/short/placeholder values it's told to check. Done = a manual (or scripted) audit confirms every secret in the target production environment is a real, non-placeholder value, with the audit method recorded.
- [ ] Validate managed Postgres/Redis (e.g. Supabase, Railway/Upstash pooling) live against this app — why: `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` in `backend/app/db/database.py` are env-configurable but have never been exercised against a real pooler (PgBouncer/Supabase pooler); connection-limit behavior under the app's actual pool config is unverified. Done = the app runs a realistic load against a managed Postgres/Redis instance with no connection-pool exhaustion or unexpected drops.
- [ ] Write and drill a backup/recovery runbook — why: no backup/recovery runbook exists yet for Postgres (point-in-time recovery) or for the `quarantine_locks` table specifically, which is safety-critical. Done = a written runbook exists and at least one restore drill (including a `quarantine_locks` restore) has been performed and its outcome recorded.

## 2. Must fix before regulated enterprise deployment

These are gaps that a friendly pilot customer can tolerate but a regulated enterprise
buyer will not — they concern isolation guarantees, observability at scale, security
posture, and infrastructure resilience beyond a single-instance pilot.

- [ ] Implement native Weaviate multi-tenancy (per-tenant shards) — why: today's isolation is a required, centralized `tenant_id` property filter in `WeaviateStore.search()` (`ingestion/embedding_pipeline.py`), regression-tested with mocks (`test_weaviate_tenant_filter.py`), but it is not native multi-tenancy and has no per-tenant shard boundary. Done = each tenant's vectors live in an isolated native Weaviate tenant/shard, not just a filtered query.
- [ ] Add Prometheus/OpenTelemetry metrics — why: current observability is structured logs plus `/health/live` and `/health/ready`, which is not sufficient for enterprise-scale operations and SLAs. Done = Prometheus (or OTel-compatible) metrics are emitted for key request, worker, and queue paths and are scrapeable/queryable.
- [ ] Verify Sentry end-to-end in production — why: `backend/app/services/observe/sentry.py` is a no-op unless `SENTRY_DSN` is set, and no DSN has ever been configured and tested end-to-end; there is no evidence an error has ever been captured and triaged through Sentry from this app. Done = a real DSN is configured in production, a real error is captured, and it is triaged in the Sentry project.
- [ ] Split API and worker Docker images — why: backend and worker currently share the same Dockerfile/image, so the API image carries the full (heavier) worker/ML dependency stack unnecessarily. Done = two distinct images exist, with the API image excluding worker-only dependencies.
- [ ] Configure Terraform autoscaling — why: `infrastructure/terraform/` provisions ECS Fargate with `desired_count=1`, a single point of failure with no autoscaling. Done = autoscaling policy (e.g. target tracking on CPU/requests) is defined in Terraform and validated to scale out and back in.
- [ ] Implement per-tenant API request-rate quota — why: per-tenant LLM budget is enforced (`backend/app/services/budget/limiter.py`, blocking governed workflow runs before any LLM call when over monthly budget), but only per-user rate limiting exists for general API requests (`backend/app/middleware/rate_limiter.py`) — there is no per-tenant request-rate quota. Done = a per-tenant request-rate limit exists and is enforced independently of per-user limits and LLM budget.
- [ ] Wire OAuth refresh-on-401 — why: `refresh_token` is stored today but never used; a 401 from a provider currently has no automated recovery path. Done = a 401 from a connected provider triggers a refresh-token exchange and retry, verified against at least one real provider.
- [ ] Commission a formal third-party security review / penetration test — why: no formal third-party security review or pentest has been performed on this codebase to date. Done = an external firm completes a review/pentest and findings are triaged and addressed or explicitly risk-accepted.

## 3. Can wait (explicitly out of near-term scope)

Per `docs/ARCHITECTURE.md` and `docs/POSITIONING.md`, these are intentionally deferred
and not part of near-term pilot or enterprise readiness work.

- [ ] Slack bot — not part of current product surface; revisit only if pilot/enterprise customers explicitly require it.
- [ ] Browser extension — not part of current product surface.
- [ ] Expanded public API surface — current API surface is intentionally scoped; broader third-party API exposure is deferred.
- [ ] "Agentic OS" framing — the product is explicitly not positioned as an autonomous agent workforce (see `docs/POSITIONING.md`); no work should reframe it this way.
- [ ] Large frontend redesign beyond what already exists — incremental polish only; no ground-up redesign planned near-term.
