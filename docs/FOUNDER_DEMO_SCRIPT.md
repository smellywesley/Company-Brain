# Founder Demo Script — Company Brain (~6 minutes talk time)

Setup done beforehand per `DEMO_RUNBOOK.md`. Have three tabs open: `/welcome`, the dashboard,
and a terminal with the stack running.

---

## 0:00 — Opening (30s)

> "Every company's real operating knowledge is scattered — a refund policy in Slack, an
> escalation runbook in Notion, a deploy convention in a PR comment. Tools like Glean answer
> questions about it. Company Brain is different: it ingests that knowledge into one governed
> memory and then **runs the work on it** — with a safety layer strong enough that you can
> let it act."

## 0:30 — Product walkthrough (2 min)

*Dashboard:* "Two loops. Loop A ingests Slack, Notion, GitHub into a source-backed memory.
Loop B does governed work: retrieve context, propose an action, risk-check it, execute or
hold for a human."

*Open a run / Time-Travel dialog:* "Every answer is source-backed — here's exactly what the
brain saw at decision time, down to the snippet, pinned by a content-addressed digest. No
'trust me', you can audit the inputs."

*Approval queue:* "Anything risky lands here. The critic scored this refund 0.55 — over the
$100 policy threshold — so it waits for a human. When I approve or reject, that decision
recalibrates the critic. The policy gets stricter where we've been burned."

## 2:30 — Trust & safety (2 min)

*Reconciliation page:* "This is the part buyers don't expect: the system **stops itself**.
A merged PR changed our onboarding procedure — it now contradicts the approved SOP. Company
Brain quarantined that skill: an independent critic vetoes every action on it until a human
reconciles the conflict. That lock lives in Postgres, not a cache — it survives restarts, and
if the database is unreachable the system fails closed, not open."

*Audit page:* "Every decision is an HMAC-chained audit entry. Change one line, the chain
breaks. This is the artifact you hand a reviewer."

## 4:30 — Architecture credibility (1 min)

> "Under the hood: FastAPI + Celery workers, Postgres, Redis, Weaviate for vector recall,
> Neo4j for the knowledge graph. Multi-tenant from the data model up — every table and every
> vector query is tenant-scoped, and that's regression-tested. Schema is Alembic-managed.
> A GitHub Actions pipeline boots the live stack, applies migrations to real Postgres, proves
> the worker consumes tasks through Redis, and runs the quarantine-lock integration test on
> every push. Per-tenant LLM budgets cap spend before a single token is bought."

## 5:30 — Close (30s)

> "What you saw is controlled-demo ready and CI-validated end to end. Before enterprise
> deployment there are two honest gaps we're closing: native per-tenant sharding in the
> vector store — today it's a centralized, tested tenant filter — and production metrics.
> The wedge is simple: for a regulated buyer, an agent that can prove what it did and why —
> and that stops itself when its own knowledge conflicts — is a different category from a
> chatbot."

---

## Honest caveats (say them if asked, never dodge)

- Tenant isolation is property-filter based today, not native Weaviate multi-tenancy.
- No compliance certifications are held; the audit *mechanisms* are what's real.
- Observability today = structured logs + health probes + optional Sentry; Prometheus/OTel pending.
- Demo data is fictional ("Acme Corp — Demo Workspace"); no customer traction claims.
- LLM answers are source-backed and risk-gated, not hallucination-proof.
