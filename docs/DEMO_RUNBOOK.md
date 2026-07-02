# Company Brain — Controlled Demo Runbook

## Positioning (use this language)

> Company Brain is a shipped internal knowledge retrieval product for teams. This demo shows
> source-backed answers, approval review, contradiction detection, and auditability. It is
> controlled-demo ready after the release-candidate CI passes. It is not yet enterprise-ready
> because native Weaviate multi-tenancy and production observability are still follow-ups.

Everything in the demo is **fictional demo data** ("Acme Corp — Demo Workspace", tagged
`seed_demo`). No real customers, no compliance certifications, no live financial actions.

---

## Setup (one time, ~10 minutes)

Prereqs: Docker with a working daemon, Node 20+, Python 3.11+.

```bash
# 1. Checkout
git clone https://github.com/smellywesley/Company-Brain.git
cd Company-Brain
git checkout feature/company-brain-architecture-frontend-polish

# 2. Environment (placeholders are fine for a local demo)
cp .env.example .env

# 3. Start the stack
#    Full stack (frontend + weaviate + neo4j + vault):
docker compose up -d --build
#    OR the lean subset (backend/worker/postgres/redis only — enough for API-side demo):
docker compose -f docker-compose.ci.yml up -d --build

# 4. Apply migrations (Alembic owns the schema)
make migrate            # = docker compose exec -T backend alembic upgrade head + current

# 5. Seed the demo data (guarded — refuses without the flag)
make demo-seed          # = exec -e ENABLE_DEMO_SEED=true backend python scripts/seed_demo.py

# 6. Verify health + worker before anyone is watching
make health-check       # /health/live and /health/ready must both return 200
make worker-smoke       # enqueues tasks.ping; the worker must echo it back

# 7. Frontend
#    Full stack: open http://localhost:3000/welcome
#    (Lean CI stack has no frontend container — run `cd frontend && npm ci && npm run dev`
#     and open http://localhost:3000/welcome)
```

If you use the lean stack, drive the Make targets with
`COMPOSE="docker compose -f docker-compose.ci.yml"`.

**Reset between demos:** `docker compose down -v` then repeat steps 3–6 (seed is
deterministic and re-runnable; it clears prior `seed_demo` rows first).

---

## The 7-minute flow

1. **Open `/welcome`** — the landing page. One sentence: *"Company Brain turns scattered
   company knowledge into a governed, auditable operating layer — it retrieves, proposes,
   risk-checks, and only acts with an audit trail."*
2. **Enter the dashboard** (`/`) — point at the two loops: Ingestion Health (Loop A, the
   memory) and Recent Actions (Loop B, the governed work). Note the Critic Calibration chart:
   the critic's risk forecasts vs. what humans actually decided.
3. **Source-backed answer** — open a recent run's detail / the audit Time-Travel dialog:
   every answer carries the exact sources (Slack/Notion/Stripe snippets) and memory-graph
   facts the brain saw at decision time, pinned by a content-addressed digest.
4. **Approval queue** (`/approvals`) — the heart of governance. Walk one card: the proposed
   action, the critic's risk score and reasons, the blast radius. Approve or reject one —
   the decision feeds back into the critic's learned policy.
5. **Contradiction / quarantine case** (`/reconciliation`) — the seeded "Enterprise
   Onboarding" SOP is quarantined because PR #842 conflicts with it. The point: *the system
   stops itself* — the CriticAgent vetoes any action on that SOP until a human reconciles.
6. **Audit trail** (`/audit`) — HMAC-chained entries; altering any line breaks the chain.
   This is the artifact you hand a reviewer.
7. **Health & ops** — `curl localhost:8000/health/ready` live on screen (200 with deps up),
   and `make worker-smoke` to show the queue is real.
8. **Close with the honest roadmap** — what's proven (CI-validated live stack, migrations,
   worker, quarantine on real Postgres/Redis) and what's next (native Weaviate
   multi-tenancy, Prometheus/OTel, autoscaling) before enterprise deployment.

---

## What NOT to claim

- Do **not** claim native Weaviate multi-tenancy — isolation is a centralized, regression-tested
  `tenant_id` property filter; per-tenant shards are a roadmap item.
- Do **not** claim enterprise production readiness.
- Do **not** claim any compliance certification (SOC 2, HIPAA, ISO...). The audit mechanisms
  are real; certifications are not held.
- Do **not** claim zero hallucination — claims are source-backed and risk-gated, not infallible.
- Do **not** claim customer traction that does not exist.

## If something breaks mid-demo

- `docker compose ps` — anything unhealthy? `docker compose logs backend --tail=50`.
- Readiness 503 → Postgres or Redis is down; restart the stack.
- Frontend renders with fallback demo data even if the backend is down — the queue and
  dashboard stay presentable; say "this is the offline fallback view" honestly.
