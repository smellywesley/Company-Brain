# Prompt for an independent audit (paste into a fresh Claude Chat)

I'm building a product called **Company Brain** and I want a genuinely independent, adversarial audit — not validation. Do not assume anything I describe below will work as intended. Disagree with me wherever the evidence warrants it. I'd rather hear "this doesn't have a market" than a polished list of minor improvements.

## What it is (positioning, as currently stated)

"Company Brain turns scattered company knowledge into a governed, auditable AI operating layer." It ingests company knowledge (Slack, Notion, GitHub, Zendesk) into a source-backed memory, then runs operational workflows on it — not just Q&A. The claimed wedge vs. tools like Glean/Notion AI: those retrieve and summarize; this one *acts*, with a governance layer in between intent and execution.

## How it works (as built)

Two loops:
- **Loop A (ingestion):** connectors pull from Slack/Notion/GitHub/Zendesk → PII redaction (Presidio where installed, regex fallback otherwise) → chunk/embed → Weaviate (vectors) + Neo4j (knowledge graph).
- **Loop B (governed action):** retrieve context → a WorkflowAgent proposes a candidate action → an independent CriticAgent scores risk/policy (deterministic second LLM pass, checks PII/RBAC/financial limits) → risky or unapproved actions route to a human approval queue → only registered executors actually fire (currently: Google Calendar, HubSpot CRM, QuickBooks Online — narrow) → every decision is written to an HMAC-SHA256 chained audit log (tampering breaks the chain).

Two specific safety mechanisms I consider the most differentiated part of the product:
1. **Contradiction Handshake:** when new ingested knowledge (e.g. a merged PR) conflicts with an active procedure/SOP, the system quarantines that skill and vetoes any action on it until a human reconciles the conflict. It notices when its own knowledge is stale/contradictory and stops itself rather than acting on bad information.
2. **Feedback loop / learned policy:** human approve/reject/correct decisions feed back into the critic's policy per tenant, so the guardrails get stricter over time based on that tenant's actual corrections (a calibration chart shows predicted vs. observed risk).

Multi-tenant from the data model up: every table and every vector/graph query is tenant-scoped. Per-tenant LLM budget caps exist (blocks LLM calls before spend when a tenant is over its monthly budget). Rate limiting exists per-user and (newly) per-tenant.

## What's actually proven vs. what's aspirational (be skeptical of self-reported claims like these)

- Backend: FastAPI (async) + Celery workers, Postgres (Alembic-migrated), Redis, Weaviate, Neo4j. 228 automated tests pass. A CI pipeline (GitHub Actions) has been observed green end-to-end multiple times: it boots the live stack, applies migrations to a real Postgres, proves a Celery worker consumes a task through Redis, hits health endpoints, and runs a live safety-lock integration test — all inside CI.
- **This has never been run live on an actual production host or by a real customer.** Only CI has witnessed it live; local developer machines in this project couldn't even get Docker running.
- Frontend: Next.js + React, a marketing landing page, a dashboard, an approval queue, an audit trail viewer, a "contradiction/quarantine" view. No live user has ever used it.
- **Explicitly NOT done / self-acknowledged gaps:** native multi-tenancy in the vector store (today it's a shared collection with a per-query tenant filter, not physically isolated shards) · no compliance certifications of any kind (SOC 2, HIPAA, etc.) — none claimed, none held · no Prometheus/OTel metrics, just structured logs + health checks · OAuth token refresh and the executor list only cover 3 providers, unverified against real accounts · no penetration test · no design partner, no paying customer, no discovery interviews conducted yet. There is a written project gap-report classifying dozens of remaining items into "must fix before pilot" vs "before regulated enterprise" vs "can wait" — assume it is accurate but incomplete (nobody has audited the auditors).
- The team building this is small (effectively one person coordinating AI-assisted development), pre-seed, pre-revenue, pre-customer-contact.

## What I want from you

Take on two personas and be ruthless in both:

1. **As a skeptical potential buyer** (pick a role you think is most plausible — ops lead, compliance officer, engineering lead at a mid-size regulated company) — would you actually adopt this? What would stop you? What's missing that you'd consider a dealbreaker vs. a nice-to-have?
2. **As an investor/future CEO deciding whether to keep funding this** — is the wedge real or crowded? Is "governed action, not just search" actually defensible, or will incumbents (Glean, Microsoft Copilot, ServiceNow, the model labs themselves) bolt this on faster than a small team can build a moat? Is the team trying to do too much at once (ingestion + knowledge graph + agent orchestration + approval workflow + audit/compliance — that's potentially five separate companies)?

Then give me:
- A prioritized, concrete critique list (not vague — I want specific things to fix, in order)
- Your honest read on product-market fit: is this validated, plausible-but-unvalidated, or unlikely to have a market as scoped? What evidence would change your mind?
- If you think the current scope is wrong, tell me what you'd cut and what you'd double down on.
- A concrete, falsifiable way to test the riskiest assumption in the next 30 days — not "build more features," an actual validation experiment with a real customer conversation or artifact.

Do not soften this because I said I built it. Assume I want to find out I'm wrong before a customer or investor does.
