# Company Brain — Demo Checklist

> **Honest caveat:** the full flow below (live stack boot, migrations against real Postgres,
> health probes, worker smoke, quarantine case) has so far only been observed passing inside
> GitHub Actions — the `compose-live` job on runs `28582152408` (commit `03ad931`) and
> `28581789446` (commit `b449ad5`), both green across all 3 jobs (backend, frontend,
> compose-live). The local Docker daemon on this dev machine does not initialize (confirmed
> dead again on repeated attempts), so a live local run has not been observed here. Treat this
> checklist as **run this yourself on a working Docker host before presenting** — do not
> present from CI green alone.

---

## 1. Pre-demo technical checklist

- [ ] Latest CI run on `feature/company-brain-architecture-frontend-polish` is green (backend, frontend, compose-live)
- [ ] `.env` created from `.env.example` (`cp .env.example .env`)
- [ ] Compose stack up: `docker compose up -d --build`
- [ ] Migrations applied: `alembic upgrade head`, then confirm with `alembic current`
- [ ] `GET /health/live` returns 200
- [ ] `GET /health/ready` returns 200 (Postgres `SELECT 1` + Redis ping both pass)
- [ ] Worker smoke passes: `make worker-smoke` (`tasks.ping` echoed back through Redis)
- [ ] Demo seed passes: `make demo-seed` (guarded by `ENABLE_DEMO_SEED=true`; refuses otherwise)
- [ ] Frontend loads at `/welcome` and at `/` (dashboard)
- [ ] Approval queue shows seeded items at `/approvals`
- [ ] Audit trail is visible at `/audit`
- [ ] Contradiction/quarantine case is visible at `/reconciliation`

## 2. Demo narrative checklist

- [ ] Gave the one-line explanation of what Company Brain is
- [ ] Showed a source-backed answer (Time-Travel snapshot dialog with retrieved sources)
- [ ] Showed approval review — approved or rejected one queued item
- [ ] Showed the contradiction/quarantine case (the "Enterprise Onboarding" SOP quarantined over PR #842)
- [ ] Showed the audit trail (HMAC-chained entries)
- [ ] Closed with the honest roadmap statement (what's proven vs. what's still needed for enterprise readiness)

## 3. What NOT to claim

- [ ] **"Enterprise-ready" / "enterprise production readiness"** — say "controlled demo-ready"; enterprise readiness still requires native Weaviate multi-tenancy and production observability, not yet done.
- [ ] **"Native Weaviate multi-tenancy"** — isolation today is a centralized, regression-tested `tenant_id` property filter, not per-tenant shards; describe it exactly that way if isolation comes up.
- [ ] **"Fully compliant" / any held certification (SOC 2, HIPAA, ISO 27001, etc.)** — no certification is held; the audit mechanisms are real, the certifications are not.
- [ ] **"Zero hallucination"** — answers are source-backed and risk-gated, not infallible.
- [ ] **Any real customer traction** — all demo data is fictional, labeled "Acme Corp — Demo Workspace."
