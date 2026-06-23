# Company Brain — Consolidated EOD Action Plan

_Synthesis of four parallel audits: Security red-team, Production-readiness/scalability, CEO/product, Design+IG. Generated 2026-06-23._

## Verdict

**Deploying the current multi-tenant web app to the public internet today is a NO-GO** — there is a confirmed cross-tenant data leak (the owner's #1 concern). However, a **safe, scoped launch today is achievable**. The blockers cluster into "config" (fast) and "finish the multi-tenancy that's already 90% built" (bounded).

The code itself is in good shape: backend `pytest` = 105 pass / 1 skip / 1 env-only fail; `main.py` boots with 32 routes; frontend `npm run build` passes; WIP (observe/quarantine/reconciliation) is finished, wired, and tested. The gaps are **security correctness** and **deploy plumbing**, not broken features.

---

## Cross-audit convergence (high confidence — multiple agents independently agreed)

| Finding | Agreed by | Status |
|---|---|---|
| No PWA manifest/icons/SW — "installable" claim is not yet true | CEO, Design, Prod | Verified (public/ has only scaffold) |
| `change-me` default secrets + `AUTH_BYPASS_DEV` must not reach prod | Security, Prod | Verified |
| Move off full Terraform/Docker stack → managed HTTPS platform | CEO, Prod | — |
| Reconciliation/quarantine not launch-ready | CEO (cut), Design (iOS prompt breaks), Security (veto suppressible) | Resolve: feature-flag OFF |

---

## P0 — Deploy blockers

### Security (must fix or neutralize before any public exposure)
- **C1 — Cross-tenant leak via `/search`** (`backend/app/main.py:585`). Add `resolve_tenant` + use `TenantIsolatedWeaviateStore`. _Verified directly._
- **C2 — Vectors carry no `tenant_id`** (`ingestion/embedding_pipeline.py`, `worker.py:217`). Tag tenant on every upsert; wire the isolation store. _Verified — must fix with C1._
- **C3 — OAuth IDOR** (`backend/app/routes/oauth.py:53`). Derive tenant/user from the authed session, not query params.
- **C4 — Hardcoded OAuth state secret** (`SKILL_SIGNING_KEY` default). Set a real 32+ char secret.
- **C5 — Forgeable audit chain** (`AUDIT_HMAC_SECRET` default `change-me-in-production`). Set a real secret.
- **H2 — `AUTH_BYPASS_DEV` synthetic admin** — was actually used (committed `audit.jsonl`). Force OFF in prod/CI.
- **H6 — OAuth/webhook routes not auth-exempt + OIDC unconfigured** — app is effectively broken-auth in the shipped stack unless bypass is on. Configure OIDC; exempt webhook/oauth routes.

### Deploy plumbing
- **No frontend prod target** in Terraform; ALB sends `/` to the API.
- **No HTTPS** — ALB has only HTTP :80; blocks OIDC/JWT/credentialed CORS **and** PWA install.
- **DB schema bootstrap** via `create_all` at startup (Alembic unused) — decide deliberately; confirm DDL rights.

### Scope cut (removes risk + matches product call)
- **Feature-flag OFF observe + quarantine + reconciliation** (UI **and** routes). This removes **H1** (prompt-injection on `/observe`) and **H5** (suppressible quarantine veto) from the attack surface, satisfies the CEO "cut" recommendation, and sidesteps Design **P0.2** (`window.prompt()` breaks in iOS PWA). Code is done & tested — keep behind a flag for a later hardened release.

---

## Recommended infra (managed HTTPS, solo-founder-operable)
- **Frontend/PWA →** Vercel (HTTPS out of the box) with `/api/*` proxied to the API.
- **API + Celery worker →** Railway/Render/Fly. (Note: Celery worker is **missing from docker-compose** — tasks enqueue but never run on that stack; Terraform does define it.)
- **Postgres →** Supabase · **Redis →** Upstash · **Vectors →** Weaviate Cloud · **Graph →** Neo4j Aura.
- Drop Kafka (use Celery/Redis) and Vault (use platform secrets) for launch.

## PWA punch-list (~3–6h, only after HTTPS)
`public/manifest.json` (`display: standalone`) · 192/512 icons · `metadata.manifest` + viewport/theme-color in `layout.tsx` · `next-pwa` offline shell · fix mobile nav close button (P0.1) · un-hide "Demo Mode" label on mobile (P0.4).

## P1 — Scalability (before real load, not before first deploy)
`desired_count=1` + no autoscaling (SPOF) · per-process `pool_size=20` will exhaust managed Postgres connections · tasks in public subnets · no Terraform remote state · rate limiter runs before auth & trusts `X-Forwarded-For` (**H3**, recommend fixing in the security pass).

---

## Launch scope (CEO)
Ship 5 screens that form a closed loop: **Command Center · Approval Queue · Audit Log · Skills/Connectors · Onboarding.** Cut for launch: Reconciliation, Blast Radius viz, Calibration Chart. Week-1 highest-ROI mobile bet: **Web Push on the approval queue.**

## Instagram launch (Design)
3-slide carousel **"The Contradiction Handshake"** (problem → quarantine screenshot → brand close) + caption ready in `DESIGN_AND_IG.md`. Asset still to be generated.

---

## Three EOD paths
- **A. Single-tenant private launch today (recommended).** Config fixes + scope cut + PWA + managed HTTPS; deploy invite-only to ONE tenant. With a single tenant, the C1/C2 leak has no second tenant to leak to — risk neutralized by construction. Defer the multi-tenant isolation code + re-audit. Safe and achievable today.
- **B. Full multi-tenant deploy today.** Also land C1/C2/C3/H4 + re-audit `/search`+OAuth before going live. Public-safe, but tight — may slip past EOD and risks rushing security code.
- **C. Don't deploy today.** Fix everything, clean re-audit, deploy in 1–2 days. Safest, misses the deadline.

---

## Progress log

**Decision (2026-06-23): Path C — don't deploy today; fix every Critical/High properly, re-audit, deploy in 1–2 days.**

### Batch 1 — landed & verified (backend `pytest`: 106 passed, 1 pre-existing env-only fail)
- **C1** `/search` is now tenant-scoped (`resolve_tenant` → tenant-filtered search) + no longer leaks exception strings.
- **C2** Weaviate data layer is tenant-aware: `tenant_id` on schema + `DocumentChunk` + upsert; `WeaviateStore.search()` **requires** `tenant_id` and fails closed on empty (footgun removed). `EmbeddingPipeline.run()` now requires a tenant. Broken `TenantIsolatedWeaviateStore` wrapper fixed to call the real API.
- **C3** `/oauth/connect` derives tenant/user from the authed session, not query params (IDOR closed).
- **C4 / C5** OAuth signing key + audit HMAC secret now go through `require_secret()` (`app/services/security/secret_config.py`) — fail closed in production.
- **H2** `AUTH_BYPASS_DEV` is hard-ignored when `ENVIRONMENT=production`.

### Batch 2 — landed & verified (backend `pytest`: 106 passed, 1 pre-existing env-only fail)
- **H1** `AdversarialDetector` wired into the `/observe` OODA path via an injectable `scan` collaborator; untrusted payloads are scanned before any LLM call and rejected fail-closed (incl. scanner errors).
- **H3** rate limiter now registered *before* auth so it runs *after* auth on the request path (per-user keying works); `X-Forwarded-For` only trusted behind a declared `TRUSTED_PROXY_COUNT`, else the real TCP peer is used.
- **H4** tenantless tokens now fail closed (403) in production instead of silently sharing the `default` tenant; default tenant is dev/demo-only.
- **H5** quarantine veto fails *closed* in production when Redis is unavailable (was fail-open and suppressible).
- **H6** OAuth `callback` + `webhooks` added to the auth allowlist (each verifies its own signature/state); `/oauth/connect` stays authenticated.

**All Critical (C1–C5) and High (H1–H6) findings are now fixed in code.**

### Remaining before deploy
- **Live-stack re-audit (task #10) — REQUIRED.** Unit suite stays green but does not exercise live infra. Must verify against real services: the Weaviate `tenant_id` filter (v4 `Filter` API) actually isolates tenants; ingested vectors are tagged; the OAuth connect→callback flow with a real OIDC provider; per-user rate limiting end-to-end.
- `.env.example` + deploy config: document/require `OIDC_ISSUER`, `OIDC_AUDIENCE`, `TRUSTED_PROXY_COUNT`, real `SKILL_SIGNING_KEY` / `AUDIT_HMAC_SECRET`, `AUTH_BYPASS_DEV` unset.
- Medium/Low items (LLM key in URL, token in `localStorage`, CORS-with-credentials, body-mutating sanitizer, dep hygiene, Vault dev mode).
- PWA (task #7), managed HTTPS infra, then deploy (task #8).
