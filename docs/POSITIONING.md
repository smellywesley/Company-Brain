# Company Brain (Lore) — Positioning & Product Boundaries

**Canonical.** Every feature, screen, connector, and pitch is measured against this doc. If a change conflicts with it, the change is wrong — not the doc. This exists to stop the product drifting into "AI workforce / agent operating system" territory.

---

## What Company Brain is
Company Brain (brand: **Lore**) is the **governed operating memory and action engine** for a company. It ingests scattered company knowledge into one source-backed memory, answers questions with citations, and safely runs routine operations on that memory — every action proposed, risk-checked by an independent critic, gated by human approval when risky, and written to a tamper-evident audit trail. It detects when knowledge contradicts itself and stops before acting on it.

**One line:** the company's trusted memory plus a governed action loop on top of it.

## What Company Brain is NOT
- ❌ Not an "AI employee platform" or "AI workforce."
- ❌ Not a generic agent operating system / agent runtime — that is **NODE** (below).
- ❌ Not a chatbot or a search box. It acts, with governance; it is not retrieve-and-summarize.
- ❌ Not a no-code rules tool (Zapier/Make). It reasons over company truth, not static triggers.
- ❌ Not a bespoke per-client build — that is the **Services / Custom OS** wrapper (below).

## The three pillars (the differentiated core)
Everything in the product strengthens one of these. Nothing else is core.
1. **Operating Memory** — source-backed company truth. Slack/Notion/GitHub/docs → vector recall + knowledge graph; every answer carries sources, timestamps, owners, confidence.
2. **Governed Action** — retrieve → propose (WorkflowAgent) → validate (independent CriticAgent: risk, policy, tenant, PII) → human approval when risky → execute → HMAC-chained audit. **Auditable action is the wedge.**
3. **Contradiction Handling** — the Contradiction Handshake: when new knowledge conflicts with an active SOP, quarantine the skill, block autonomous execution, route to human reconciliation. The system stops itself.

## The four layers (and which is the product)
1. **Company Brain / Lore — the Product.** Enterprise operating memory + governed action loop. Multi-tenant, versioned, the same engine for every customer. *This is the product.*
2. **AI Employee roles — Packaging layer.** Intake, Support, Finance, Analyst. Role bundles powered by the same engine. **Not new products.**
3. **NODE — Separate platform.** The AI agent operating system / runtime: agent orchestration, agent memory, scheduling, commands, execution infrastructure. **Separate from Company Brain.**
4. **Services / Custom OS — GTM wrapper.** Implementation, onboarding, integrations, managed setup. Sells and deploys Company Brain; **does not redefine it.**

## How "AI Employees" fit (without becoming the product)
An AI Employee is a **role bundle** — a named set of SOPs, executors, and approval policies that the *same engine* runs. It is **"a role Company Brain runs using your company truth, SOPs, approvals, and audit"** — never "autonomous AI staff." Roles inherit the three pillars by construction. If a role needs capability outside the three pillars (generic orchestration, arbitrary tool execution), that capability belongs in **NODE**, not bolted onto Company Brain. Roles to date: **Intake & Qualification, Support & Service, Finance & Admin, Analyst & Reporting.**

## How NODE is separate
NODE owns the generic agent-OS concerns: orchestration, agent memory, scheduling primitives, command execution, runtime infrastructure. Company Brain may run on or integrate with NODE, but **Company Brain owns company truth + governed action + contradiction handling** and nothing in its pitch uses "agent OS" language. If a request is really about agent orchestration/runtime, it is a NODE feature, not a Company Brain feature.

## Product vs Services boundary
- **Product** = config: SOPs, RBAC, connectors, role bundles, policies. Same engine for everyone.
- **Services** = implementation, onboarding, integration work, managed operation. Services *deploy* the product; they must not fork or redefine it. A client ask that cannot be expressed as product config is a Services engagement, not a product feature.

## Naming rules
- Product: **Company Brain** (brand **Lore**). Not "the platform," not "the agent OS."
- Pillars: **Operating Memory · Governed Action · Contradiction Handling.**
- Role bundles: **"AI Employee roles"** / **"roles"** — always "a role Company Brain runs." Never "an AI employee/worker" as a standalone noun replacing a person.
- **NODE** = the separate agent OS/runtime. Company Brain is never called an agent OS.
- Banned for Company Brain: "AI workforce," "autonomous staff/employees," "agent operating system."

## Feature acceptance rules (apply to every feature / PR)
In scope only if it passes ALL of:
1. **Pillar test** — strengthens Operating Memory, Governed Action, or Contradiction Handling.
2. **Governance test** — any action it enables is critic-checked, approval-gated when risky, and audited. No ungoverned autonomous action.
3. **Truth test** — answers/decisions are source-backed (citations, provenance) and tenant-scoped.
4. **Positioning test** — describable without "AI employee/worker" or "agent OS." If it can't be, it belongs in NODE or Services.
5. **Boundary test** — it is product config, not a bespoke client fork (→ Services) and not generic agent runtime (→ NODE).

Fail any rule → reject the feature, or route it to NODE / Services.
