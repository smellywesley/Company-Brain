# Company Brain — Architecture

## 1. The problem (why it's needed)

Every company's real operating knowledge lives in fragments: a refund policy buried
in a Slack thread, an escalation procedure in a Notion page, a deploy convention in a
GitHub PR comment. New employees take months to absorb it. The same questions get
answered hundreds of times. And the moment someone leaves, a piece of the company's
operating memory leaves with them.

Existing tools answer questions about this knowledge (Glean, Notion AI, Copilot). They
retrieve and summarize. They do not **act**. Asking "what's our refund policy?" still
leaves a human to go execute the refund.

Company Brain closes that gap. It ingests the scattered knowledge, builds a living model
of how the company actually operates, and then runs the operational workflows itself —
retrieve context, reason, propose an action, validate it against policy, and (for
anything risky) hold it for a human to approve before it fires. Every decision is
cryptographically audited.

The wedge is **auditable action**, not search. For regulated buyers (fintech, health,
B2B SaaS with SOC 2 obligations) an agent that can prove, with a tamper-evident chain,
exactly what it did and why is a category of its own.

---

## 2. System overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        FRONTEND  (Next.js)                            │
│   Dashboard · Approval Queue · Demo hero · Settings                   │
│   httpOnly session · SSE live feed                                     │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ HTTPS / REST + SSE
┌───────────────────────────────▼──────────────────────────────────────┐
│                         BACKEND  (FastAPI, async)                     │
│  Middleware stack (outer → inner):                                    │
│  SecurityHeaders → AuditLog → RateLimiter → CORS → OIDCAuth →         │
│  InputSanitization → [route]                                          │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │             MULTI-AGENT ENGINE                                    │ │
│  │  WorkflowAgent ──► CriticAgent ──► ActionExecutor                 │ │
│  │   (orchestrate)    (validate)      (Stripe/Slack/Jira/…)          │ │
│  │        │                                                          │ │
│  │        └──► LLMAdapter (Gemini · OpenAI · Anthropic)              │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  Tenant resolver (JWT claim → Tenant)  ·  RBAC (YAML policy)          │
└──────┬───────────────┬───────────────┬───────────────┬───────────────┘
       │               │               │               │
┌──────▼─────┐  ┌──────▼─────┐  ┌──────▼─────┐  ┌──────▼──────┐
│ PostgreSQL │  │  Weaviate  │  │   Neo4j    │  │   Redis     │
│ tenants,   │  │  vector    │  │ knowledge  │  │ Celery broker│
│ skills,    │  │  search    │  │   graph    │  │ + rate limit │
│ runs,      │  │ (per-tenant│  │ (entities, │  │              │
│ feedback   │  │ namespaces)│  │ relations) │  │              │
└────────────┘  └────────────┘  └────────────┘  └─────────────┘
       ▲                ▲                              │
       │                │                              │
┌──────┴────────────────┴──────────────────────┐  ┌───▼──────────────┐
│         INGESTION PIPELINE                     │  │  CELERY WORKER    │
│  Slack · Notion · GitHub connectors           │  │  ingestion, skill │
│  → PII redaction (Presidio)                    │  │  discovery,       │
│  → chunk → embed (sentence-transformers)       │  │  feedback loop,   │
│  → Weaviate upsert + Neo4j entity extraction   │  │  cost accounting  │
└───────────────────────────────────────────────┘  └──────────────────┘
                                                            ▲
                                          Kafka (message bus, async events)
                                          Vault (secrets) · Langfuse (LLM traces)
```

---

## 3. The two core loops

Company Brain runs on two loops. The first builds memory. The second acts on it.

### Loop A — Ingestion (build the living memory)

```
Slack / Notion / GitHub
        │  connector.fetch_raw()
        ▼
  normalize() → NormalizedDocument
        │
        ▼
  redact_pii()  (Presidio strips names, emails, SSNs before anything is stored)
        │
        ├──► chunk → embed → Weaviate     (semantic recall)
        └──► entity extraction → Neo4j     (who/what/how relationships)
```

Adding a new source is a 3-method connector (`authenticate`, `fetch_raw`, `normalize`)
plus a one-line registry decorator. PII redaction is inherited automatically.

### Loop B — Action (the multi-agent engine)

This is the part competitors don't have. A workflow is not a chatbot turn — it's a
governed pipeline:

```
trigger (event or API call)
        │
        ▼
  ┌──────────────┐  retrieves context across Weaviate + Neo4j
  │ WorkflowAgent│  matches the best learned Skill (SOP) for this trigger
  │ (orchestrator)│  asks the LLM for a CANDIDATE ACTION (structured JSON)
  └──────┬───────┘
         │ candidate action
         ▼
  ┌──────────────┐  independent second pass, temperature 0
  │ CriticAgent  │  checks: PII leakage, RBAC, financial limits, tenant rules
  │ (validator)  │  returns approved? + risk_score + reasons
  └──────┬───────┘
         │
    approved? ──no──► status = pending_review ──► HUMAN APPROVAL QUEUE
         │ yes
         ▼
  ┌──────────────┐  Stripe refund / Slack message / Jira ticket / …
  │ ActionExecutor│  only registered executors run; everything else is dry-run
  └──────┬───────┘
         │
         ▼
  WorkflowRun persisted + HMAC-chained audit entry written
```

The **CriticAgent** is the safety core: a separate model pass, deterministic, that can
veto the worker. High-risk or unapproved actions never auto-execute — they route to the
human approval queue in the frontend. That is what makes autonomous action safe enough
to sell to a regulated enterprise.

---

## 4. The moat — skills that learn

A "Skill" is a machine-written Standard Operating Procedure: trigger conditions, steps,
required inputs, guardrails, a risk level. Skills are discovered automatically by
clustering ingested documents and synthesizing the latent procedure, then refined by the
feedback loop:

```
human approves / rejects / corrects an action  (Approval Queue)
        │
        ▼  POST /feedback  → enqueue tasks.process_feedback
  ┌──────────────────┐
  │ FeedbackProcessor│  1. anomaly check  (block poisoning — velocity limits)
  │                  │  2. quorum check   (N independent approvers by risk level)
  │                  │  3. SkillUpdater   → re-synthesize the skill (new version)
  │                  │  4. CriticCalibrator → extract an invariant rule, append it
  │                  │                        to the tenant's CriticAgent policy
  └──────────────────┘
```

Two compounding effects: the **skill** gets better (the SOP is rewritten), and the
**critic** gets stricter (a new permanent rule means the same mistake is caught next
time, before a human ever sees it). Every skill change is an immutable versioned snapshot,
so any update is fully rollback-able.

This is the flywheel: the more a company uses Company Brain, the more it encodes that
company's specific judgment — which is exactly the thing a competitor can't copy, because
it's derived from one customer's private operating history.

---

## 5. Multi-tenancy & security

Every table carries `tenant_id`. Identity flows from the OIDC token:

```
JWT (Okta / OIDC)  ──►  OIDCAuthMiddleware verifies sig + exp + aud + iss
                        extracts tenant claim → request.state.user.tenant
                                  │
                                  ▼
                        resolve_tenant(request, session)
                          - claim present → strict lookup (UUID or slug)
                          - unknown/inactive claim → 403  (never fall through)
                          - no claim → default tenant (dev/demo only)
                                  │
                                  ▼
                        every query filtered by tenant.id
```

Defense layers, each its own middleware:
- **AuthN** — OIDC/JWT, RS256/ES256, JWKS-cached, audience + issuer verified.
- **AuthZ** — YAML RBAC (admin / manager / engineer / viewer), deny by default.
- **Isolation** — tenant-scoped queries; per-tenant Weaviate namespaces; cross-tenant
  access returns 404, not 403 (don't reveal another tenant's data exists).
- **Input** — XSS / SQL-injection detection + HTML stripping before routes see the body.
- **Audit** — every request and every agent action written as an HMAC-SHA256 chained
  JSONL entry; tampering with any line breaks the chain. This is the compliance asset.
- **PII** — Presidio redaction at ingestion, before storage.
- **Secrets** — Vault; nothing hardcoded.
- **Rate limiting** — token bucket per user/IP, thread-safe under concurrency.

---

## 6. How it helps other companies (white-label)

Company Brain is built to be retrofitted onto any organization in hours, not months:

- **Connectors are pluggable.** Slack, Notion, GitHub ship today; Zendesk, Salesforce,
  Confluence, Google Drive are a connector class each. The ingestion + PII + embedding
  path is shared, so a new source is ~100 lines.
- **Workflows are JSON-configurable.** A new operational workflow (refund automation,
  ticket triage, lead qualification, incident response) is a config + a set of action
  executors, not a code fork.
- **RBAC is YAML.** Each customer maps their own roles without touching code.
- **Skills are per-tenant and self-writing.** The platform arrives empty and learns each
  company's specific procedures from that company's own data. No two deployments converge
  to the same brain.
- **Multi-tenant from the data model up.** One deployment serves many companies with hard
  isolation, or it runs single-tenant on-prem for customers who require it.

The result: the same engine becomes a different, custom product for each customer —
because the value lives in the learned skills and calibrated critic, both derived from
that customer's private knowledge.

---

## 7. Why now

Three things became true at once: LLMs got good enough to synthesize procedures from
messy text and produce structured, tool-callable actions; enterprises accumulated their
real knowledge in exactly the SaaS tools these connectors target; and the compliance bar
for "AI that acts" rose sharply. An agent platform that is **auditable by construction**
and **learns one company's judgment** is the product that moment calls for. Search was the
last decade. Governed action is this one.

---

## 8. Component reference

| Layer | Technology | Role |
|-------|-----------|------|
| Frontend | Next.js (App Router, TS) | Dashboard, approval queue, demo, settings |
| API | FastAPI (async) | Routes, middleware stack, agent orchestration |
| Agents | Custom + LLMAdapter | WorkflowAgent, CriticAgent, ActionExecutor |
| LLM | Gemini / OpenAI / Anthropic | Pluggable via one adapter, cost-tracked |
| Relational | PostgreSQL (SQLAlchemy async) | Tenants, skills, versions, runs, feedback |
| Vector | Weaviate | Semantic recall, per-tenant namespaces |
| Graph | Neo4j | Entity + relationship knowledge graph |
| Queue | Celery + Redis | Ingestion, skill discovery, feedback loop |
| Bus | Kafka | Async event distribution |
| Secrets | HashiCorp Vault | Credentials, rotation |
| Observability | Langfuse | Per-call LLM tracing + cost |
| Ingestion | Presidio + sentence-transformers | PII redaction, chunking, embedding |
| Infra | Docker Compose / AWS ECS (Terraform) | Local + cloud deployment |
```
