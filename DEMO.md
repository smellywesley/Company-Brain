# Company Brain — Live Demo Runbook

This is the exact sequence used to bring the dashboard up with **live backend data**
(not the offline mock fallback) and walk the human-in-the-loop approval flow.

Two paths:
- **Path A** proves the endpoints are correct (no infra beyond Python).
- **Path B** is the visual / video demo (needs Docker for Postgres).

---

## Path A — fast, no infra (proves the endpoints)

```bash
cd backend
python -m pytest tests/test_dashboard_endpoints.py -v
```

Green = the dashboard repo queries are tenant-scoped and return the right shape.
Full suite: `python -m pytest -q` (52 pass; the 1 `presidio_analyzer` failure is
environment-only and passes in CI).

---

## Path B — visual / video (proves the dashboard shows live data)

### 1. Start Postgres (Docker Desktop must be running)

```bash
docker run -d --name cb-pg \
  -e POSTGRES_PASSWORD=change-me-in-production \
  -e POSTGRES_USER=cb_admin \
  -e POSTGRES_DB=companybrain \
  -p 5432:5432 postgres:16-alpine

# wait until ready:
docker exec cb-pg pg_isready -U cb_admin -d companybrain
```

### 2. Backend dependencies

The lean demo only needs these (the dashboard endpoints touch Postgres only;
`sentence-transformers`/`torch` stay lazy and are never loaded):

```bash
cd backend
pip install asyncpg weaviate-client boto3 hvac redis
# or full set: pip install -r requirements.txt
```

### 3. Start the API

`ingestion/` lives at the repo root, so it must be on `PYTHONPATH`.
`AUTH_BYPASS_DEV=1` injects a synthetic admin so the tokenless demo frontend can
reach authenticated endpoints. **Never set this in production.**

PowerShell:
```powershell
$env:PYTHONPATH = "..;."
$env:DATABASE_URL = "postgresql+asyncpg://cb_admin:change-me-in-production@localhost:5432/companybrain"
$env:AUTH_BYPASS_DEV = "1"
$env:FRONTEND_ORIGIN = "http://localhost:3000"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

bash:
```bash
PYTHONPATH="..;." \
DATABASE_URL="postgresql+asyncpg://cb_admin:change-me-in-production@localhost:5432/companybrain" \
AUTH_BYPASS_DEV=1 \
FRONTEND_ORIGIN="http://localhost:3000" \
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Tables auto-create on startup (`init_db()` → `Base.metadata.create_all`). No migration step.
Check: `curl http://localhost:8000/health` → `{"status":"ok","version":"0.2.0"}`.

### 4. Seed demo data

```bash
cd backend
PYTHONPATH="..;." \
DATABASE_URL="postgresql+asyncpg://cb_admin:change-me-in-production@localhost:5432/companybrain" \
python scripts/seed_demo.py
```

Creates the `default` tenant, a "Refund Processing" active skill, and 6 workflow runs
across statuses (completed / pending_review / rejected). Idempotent — safe to re-run.

### 5. Start the frontend

```bash
cd frontend
npm run dev      # http://localhost:3000
```

### 6. Open http://localhost:3000

You should see, **populated from Postgres** (not the mock numbers):
- Top bar: **API Connected** (green).
- **Active Workflows**: 6 runs with real names and critic statuses.
- **Critic Verdicts**: run IDs + risk scores (88 / 8 / 12 / 35 / 55 / 62).
- **Knowledge Stats** counters settle to **6 / 1 / 3 / 0**
  (workflow runs / active skills / pending review / feedback).
- **Recent Activity**: the 6 runs, newest first.

### 7. Human-in-the-loop (the core flow)

1. Click **Approvals** (or go to `/approvals`) — 3 `pending_review` runs.
2. Click **Approve** on one card.
   - The card disappears; the **"N pending"** badge drops (3 → 2).
   - **Today's Summary**: Pending 3→2, Approved 0→1.
   - Backend records it: `curl http://localhost:8000/stats` → `total_feedback` 0 → 1.
   This proves the optimistic UI write hits a **real** DB row via `submitFeedback`.

### 8. Graceful offline fallback (optional, good for the video)

Stop the backend (`Ctrl+C` on uvicorn) and reload `http://localhost:3000`.
The top bar flips to disconnected and the dashboard renders the built-in mock data,
so the UI still looks complete with the backend down. Restart uvicorn to go live again.

---

## How this dashboard learns about company policies

The dashboard is the **read** surface of a closed feedback loop:

1. **Ingestion** pulls docs from Slack / Notion / GitHub → embeddings in Weaviate +
   entities/relations in Neo4j (the knowledge graph).
2. A **WorkflowAgent** reasons over that context and proposes an action.
3. An independent **CriticAgent** scores risk against the tenant's policy
   (`critic_risk_score`, `critic_reasons`) — what you see in Critic Verdicts.
4. Risky actions are held in **Approvals** for a human.
5. When you Approve/Reject, a `FeedbackRecord` is written (the `total_feedback`
   counter you watched move). The **feedback loop** (anomaly check → quorum →
   `SkillUpdater` re-synthesizes the skill, `CriticCalibrator` appends an invariant
   rule to the tenant policy) turns that human judgment into an updated policy/skill.

So every approval is a teaching signal: the next similar workflow is scored against the
policy your decision just shaped. That accumulating, tenant-private policy is the moat.
See `docs/ARCHITECTURE.md` for the full writeup.

---

## Teardown

```bash
# stop frontend + uvicorn (Ctrl+C in their terminals)
docker rm -f cb-pg          # drops the demo database
```
