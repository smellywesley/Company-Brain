# Backup & Recovery

> **STATUS: WRITTEN BUT NOT DRILLED.** No restore has ever been performed or
> timed against this project. Everything below is a documented plan derived
> from reading `backend/app/db/models.py`, the Alembic migration, and
> Supabase's published capabilities — it is **not** a verified, rehearsed
> runbook. Treat every step as unconfirmed until someone actually runs it.
> **Before relying on this in a real incident, perform an actual restore
> drill against a non-production Supabase project and update this doc with
> real timings and any procedure corrections found.**

## 1. Scope

**Covered:**
- **Postgres (Supabase)** — the 7-table application schema owned by Alembic:
  `tenants`, `skills`, `skill_versions`, `workflow_runs`, `feedback_records`,
  `ingestion_cursors`, and `quarantine_locks`. This is the durable system of
  record for the whole app, including the safety-critical quarantine lock
  (see `backend/app/services/quarantine/lock.py`).
- **Redis (Upstash)** — cache-only. No unique data lives here. It is safe to
  lose or rebuild from empty at any time, with one caveat: it temporarily
  caches quarantine-lock reads. Losing/flushing it does not lose the lock
  itself (Postgres still has it) — a Redis miss just falls through to
  Postgres and the cache self-heals on the next read (`_redis_get` /
  `_pg_get` in `lock.py`).

**Explicitly NOT covered (undocumented gap — flagged, not solved here):**
- **Weaviate Cloud** (vector store) backup/restore.
- **Neo4j Aura** (graph store) backup/restore.

No fake procedures are written for Weaviate or Neo4j below. If you need
those, that work has not started — do not assume any safety net exists for
them today.

## 2. Postgres backup (Supabase)

Two mechanisms, from least to most effort:

### 2a. Supabase built-in daily backups
Supabase automatically takes daily backups on paid plans; retention length
depends on plan tier (check current retention in the dashboard — it varies
and is not fixed here to avoid stating a number that goes stale). To check
or restore from one:
1. Supabase dashboard → your project → **Database → Backups**.
2. Confirm a recent daily backup exists and note its timestamp.
3. Restoring from here is a dashboard-driven action (Supabase handles the
   mechanics) — this gives you an RPO of roughly "up to 24h," not
   sub-daily.

### 2b. Point-In-Time Recovery (PITR) — paid add-on
For sub-daily RPO, Supabase offers WAL-based PITR as a paid add-on:
1. Dashboard → **Database → Backups → Point in Time Recovery**.
2. Enable it if not already on (this is a plan/billing decision, not a code
   change).
3. Once enabled, you can restore to any specific timestamp within the
   configured retention window, not just the last daily snapshot.

Check whether PITR is enabled for this project's Supabase instance before
assuming sub-daily recovery is possible — as of this writing that has not
been verified for this repo's deployment.

### 2c. Manual fallback — `pg_dump` / `pg_restore`
Independent of Supabase's own backup system, you can take a manual logical
backup of the full 7-table schema at any time using the sync connection
string already defined in `docker-compose.yml` (`DATABASE_URL_SYNC`,
plain `postgresql://` — not the `+asyncpg` variant used by the app):

```bash
# Full logical backup (custom format, compressed, restorable with pg_restore)
pg_dump "$DATABASE_URL_SYNC" -Fc -f companybrain_backup_$(date +%Y%m%d_%H%M%S).dump

# Restore into an existing (empty or matching-schema) database
pg_restore --clean --if-exists -d "$DATABASE_URL_SYNC" companybrain_backup_20260704_120000.dump
```

Notes:
- `-Fc` (custom format) is preferred over plain SQL — it's compressed and
  lets `pg_restore` do selective/parallel restores if needed.
- `--clean --if-exists` drops existing objects before recreating them, so
  restoring into a non-empty DB doesn't collide with existing tables.
- Run this against Supabase's connection string in production, or the local
  `DATABASE_URL_SYNC` from `docker-compose.yml` in dev/staging.

## 3. Restore procedure

1. **Restore Postgres** using whichever method applies:
   - Supabase dashboard restore (daily backup or PITR timestamp), or
   - `pg_restore` from a manual `pg_dump` (Section 2c).
2. **Verify the schema version.** From `backend/`, run:
   ```bash
   DATABASE_URL=<restored-db-url> alembic current
   ```
   Confirm it reports the expected head revision (currently `0001 (head)`
   per `backend/migrations/versions/0001_initial_schema.py`). **If the
   restored backup predates a migration that has since shipped, the schema
   will be behind** — this is a real restore risk: application code may
   expect columns/tables the restored snapshot doesn't have. Run
   `alembic upgrade head` to bring it current before pointing the app at it,
   and check whether that migration also requires a data backfill.
3. **Flush the Redis quarantine cache.** This step is mandatory, not
   optional. After any Postgres restore, Redis may hold entries that
   contradict the just-restored data — e.g. Redis still shows a lock as
   held that was released *after* the backup was taken (so the restore
   brought back a stale "still locked" state that's actually now wrong the
   other direction), or vice versa. Because `get_sync()` in
   `backend/app/services/quarantine/lock.py` checks Redis **first** and
   only falls through to Postgres on a cache miss, a stale Redis entry can
   silently mask the newly-restored Postgres truth. Fix: delete every
   `quarantine:*` key so the next read is forced through to Postgres:
   ```bash
   redis-cli --scan --pattern 'quarantine:*' | xargs -r redis-cli DEL
   # or, if isolation allows a full reset:
   redis-cli FLUSHDB
   ```
   Do this immediately after every Postgres restore, no exceptions.
4. **Spot-check `quarantine_locks` integrity.** Confirm:
   - The `uq_qlock_tenant_skill` unique constraint (one lock per
     tenant+skill) is present and unviolated:
     ```sql
     SELECT tenant_id, skill_id, count(*)
     FROM quarantine_locks
     GROUP BY tenant_id, skill_id
     HAVING count(*) > 1;
     -- expect 0 rows
     ```
   - Permanent locks (`expires_at IS NULL`) survived the restore byte-exact
     — these are human-release-only safety locks, so losing one silently
     re-enables a previously-quarantined skill:
     ```sql
     SELECT tenant_id, skill_id, pr_ref, locked_at
     FROM quarantine_locks
     WHERE expires_at IS NULL;
     ```
     Compare this list against what you expect from before the incident
     (audit logs / `docs/DEMO_RUNBOOK.md`-style records, if any exist for
     the affected tenants).

## 4. Redis

Redis (Upstash) holds no unique data — it is purely a cache. It can be
discarded and rebuilt from empty at any time, including via `FLUSHDB` or by
pointing at a brand-new Upstash instance. This is safe because every reader
falls through to Postgres on a cache miss; this is a design property that is
already true today, not something this doc introduces — see
`_redis_get()` → `_pg_get()` fallback in
`backend/app/services/quarantine/lock.py`. The only operational requirement
is Section 3 step 3: after a *Postgres* restore, flush Redis so it can't
serve a stale answer that predates the restore.

## 5. RTO / RPO

- **RPO:** TBD — depends on which backup tier is active (daily backup vs.
  PITR add-on). Not measured for this project.
- **RTO:** TBD — requires an actual timed drill to measure. No drill has
  been run.

Do not quote either number to anyone (customers, leadership, compliance)
until a real drill produces real timings.

## 6. Status (repeated)

**This document is WRITTEN BUT NOT DRILLED.** No restore has been performed
or timed anywhere in this project's history. Every step above is a plan
based on reading the schema, the Alembic migration, `lock.py`, and
Supabase's published product capabilities — none of it has been rehearsed
against a real Supabase project. Before this runbook is trusted in a real
incident, perform an actual restore drill against a non-production Supabase
project, time each step, and correct this document with what actually
happened.
