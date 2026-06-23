# CEO Review — Company Brain
**Date:** 2026-06-23  
**Reviewer:** CEO/Advisor lens (solo-founder pre-launch audit)  
**Status:** Pre-EOD deploy decision

---

## Executive Summary

**Ship it today.** Web + installable PWA is the right call — do not pivot to native
mobile for launch. The mobile question is real but the answer is nuanced: the approval
queue and contradiction alerts have genuine mobile urgency; everything else does not.
Wire those two flows for PWA first, native later.

**The product wedge is auditable action, not contradiction detection and not search.**
The contradiction/reconciliation surface is genuinely novel, but it is P1 in the
technical roadmap for a reason — the detector is still title-reading an LLM guess (see
the CEO addendum in TIER4_RECONCILIATION_DESIGN.md). Ship the Approval Queue flow as
the hero. That is the loop that works end-to-end today.

**Cut for EOD:** Reconciliation page (hide from nav or gate behind a "beta" chip),
the Blast Radius visualization, and the Calibration Chart. Keep: Command Center,
Approval Queue, Audit Log, Skills/Connectors hub, Onboarding. Those five screens are
the minimum lovable launch.

---

## 1. Mobile: "Web + PWA today, native later" — Validated with Push-Back

### The verdict: correct strategy, wrong framing

Web + installable PWA is the right call for launch day. The instinct behind the
question — "people are on the move" — is sound, but it needs to be stress-tested
against what "Company Brain on the go" actually means for each use case.

### What the on-the-go use cases actually are

**Genuinely mobile-urgent (time-sensitive, single-tap decisions):**
- Approval Queue notification: an agent has proposed a $349 refund and is blocked
  waiting for a human. This happens during a meeting, off-hours, or on a commute.
  The user needs to see the summary and tap Approve/Reject in under 30 seconds.
  This is a real push-notification + mobile-responsive card interaction.
- Contradiction alert: a PR just merged and quarantined a skill. Knowing this exists
  is useful on a phone. Acting on the full three-pane reconciliation view is not.
- Quick status check: "did the deploy approval go through?" One glance at the
  Command Center stat tiles. Already works on a responsive web page.

**Not genuinely mobile (context-intensive, desktop work):**
- Reviewing and editing a proposed knowledge synthesis (Reconciliation page). You
  need a wide screen and cognitive space. Nobody does this on a phone.
- Audit Log deep-dives — forensic work, desktop only.
- Skills/Connectors configuration — admin task, not on-the-go.
- Onboarding — setup ritual, done once at a desk.

### Why native is the wrong priority now

1. The product has zero users. App Store approval takes days to weeks. Distribution
   friction on native eats launch momentum on a day-of-launch timeline.
2. The core value proposition (autonomous action + human-in-the-loop) needs a
   design partner to validate the workflow before you lock a UI paradigm into
   native code.
3. PWA gives you 80% of what matters (installable, full-screen, push notifications
   via the Web Push API, offline fallback already implemented) with zero app store
   dependency.

### What genuinely matters on mobile vs. what is vanity

| Capability | Matters | Notes |
|---|---|---|
| Push notifications (approval pending, contradiction detected) | Yes — high priority | Not wired yet; this is the P0 mobile gap |
| Responsive approval card (swipe or tap) | Yes | Layout is already `sm:flex-row` — works today |
| Installable to home screen | Yes | PWA manifest missing — 30-minute fix |
| Full reconciliation UI on phone | No | Desktop-primary per spec §5; correct decision |
| Offline audit log | Marginal | Nice, not urgent |
| Native camera / file upload | No | Not in the product |
| Native biometrics for auth | Later | Useful for enterprise, not launch day |

**The single honest mobile gap today:** there is no PWA manifest
(`frontend/public/manifest.json` does not exist) and no service worker. The app
cannot be "installed" from a browser yet. This is a 30-60 minute fix, not a day
of work. Do it before you deploy.

---

## 2. Product Wedge: Who Is the ONE User and What Is the ONE Use Case

### The one user

**The ops-or-eng lead at a 20-150 person B2B SaaS or fintech company** who is drowning
in "what's our policy on X?" interruptions, manually approving every edge-case refund,
and getting burned by out-of-date runbooks after deploys. They have Slack, Notion, and
GitHub. They are not a data scientist. They want fewer fires, not more dashboards.

This is the person who sees the Approval Queue and says "I want this in my life."

### The one killer use case

**"Approve or reject an AI-proposed action in under 30 seconds, from anywhere, with
a one-sentence explanation of why the agent flagged it."**

That is the Approval Queue. It is the only end-to-end closed loop you have today
where a human interacts with a real decision and the system records a feedback signal
that improves future behavior. Everything else — ingestion, skills discovery, the
knowledge graph — is infrastructure that makes the Approval Queue valuable. The queue
is the product.

### Is contradiction detection the wedge or a distraction?

Contradiction detection is a wedge, but not yet. Right now the detector is an LLM
reading a PR title — an important architectural gap that the CEO addendum already
flagged (C1 in TIER4_RECONCILIATION_DESIGN.md). Shipping the reconciliation UI over a
title-reading detector creates a dangerous positioning problem: you demo a
"contradiction detection system" that fires on noise. One skeptical design partner who
tests it rigorously will dismiss the whole product.

The right sequencing:
- Launch positioning: **"Human-in-the-loop AI operations with a tamper-evident audit
  trail."** Lead with the Approval Queue.
- Week 2-4: Fix the PR diff bug (C-P0-1), add dumb Tier 0 detection (C-P0-2), TTL
  (C-P0-3). Now the contradiction story is real enough to demo.
- Month 2: Lead with contradiction detection as a differentiator once it has a
  design-partner testimonial behind it.

The "search your company's knowledge" framing is a dead end. Glean, Notion AI, and
Microsoft Copilot own that space with massive distribution. Do not compete there.
The moat is auditable, learning, governed action — the flywheel where each human
decision makes the critic smarter.

---

## 3. Ruthless EOD Scope: What Ships vs. What Gets Cut

### The minimum lovable launch — what must ship

| Screen / Feature | Status | Ship? | Reason |
|---|---|---|---|
| Command Center (dashboard) | Working, live data + offline fallback | YES | Hero first impression |
| Approval Queue | Working, swipeable, live + fallback | YES | The product wedge |
| Audit Log | Working, fallback data | YES | The compliance differentiator |
| Skills & Connectors hub | Working, fallback data | YES | Shows the platform is real |
| Onboarding (3-step) | Working | YES | Without it, no one can set up a tenant |
| PWA manifest + install | Not yet built | YES — do this now | 30-min fix; required for PWA claim |
| Push notification (approval pending) | Not built | Defer to Week 1 post-launch | Important but not blocking launch |
| Backend API (FastAPI) deployed | Needs prod infra | YES | Without it, everything runs on mock data |

### What to cut for EOD

**Cut 1: Reconciliation page — hide from nav or mark "coming soon."**

Rationale: the detector underneath it is a PR title reader. Shipping this as a
visible feature sets expectations you cannot currently meet. Remove
`GitPullRequestArrow` from `nav.ts` or wrap the route in a "beta" gate. The page
code is fine; the backend contract is not production-ready (quarantine_records table
does not exist per E4 in the design doc).

**Cut 2: Blast Radius graph (BlastRadiusGraph.tsx) — defer.**

This is a visualization feature fetched per approval card. It adds an API call that
can time out and has no fallback data defined. Remove it from the ApprovalCard or
wrap in a feature flag. The approval flow must be snappy; a stalling blast-radius
fetch degrades it.

**Cut 3: Calibration Chart — defer to Week 2.**

The CalibrationChart is a sophisticated trust visualization (how well the critic's
predicted probabilities match observed outcomes). It is genuinely interesting — but
requires real volume of approved/rejected decisions to be meaningful. With zero
real users, it will show the fallback synthetic curve. Showing a calibration chart
with 10 fake data points to a design partner is worse than not showing it. Hide it
or replace with a simpler "critic risk score" summary until you have real data.

**Do NOT cut:** The offline fallback mode. This is a secret weapon in demos. The
fact that the UI degrades gracefully when the backend is down (confirmed in DEMO.md
§8) is a selling point, not a nice-to-have. Keep it.

**Do NOT cut:** Dark mode. The glassmorphism aesthetic is strong and differentiates
from enterprise tools that look like JIRA. Keep it exactly as is.

---

## 4. Viability Risks (Market / Adoption / Positioning)

### Risk 1: The "AI agent for enterprise" graveyard — HIGH

**The risk:** Every major SaaS vendor is shipping "agentic" features. Salesforce
Agentforce, ServiceNow, HubSpot — all claiming to automate operations. The market is
noisy and buyers are becoming skeptical after seeing agents hallucinate in demos.

**Mitigation:** The differentiator is not "agent" but "auditable agent." The HMAC
audit chain is a real compliance asset. Lead every conversation with "every action has
a cryptographically chained audit trail." That lands differently with a fintech
compliance officer than "AI automation." The onboarding posture picker (conservative /
balanced / aggressive) is also a smart signal — it says "we understand regulated buyers
are paranoid and we built for that."

### Risk 2: Cold start — the brain starts empty — HIGH

**The risk:** Company Brain is only as valuable as its ingested knowledge. A new
customer arrives, connects Slack, and waits. The skill discovery pipeline runs. Nothing
happens for days. They leave.

**Mitigation:** The onboarding seeds 3-4 policy invariants based on industry — this
is the right instinct (fintech gets "dual-control on funds" out of the box). Extend
this: pre-seed one complete Skill per industry (a working Refund Processing SOP for
fintech, a Deploy Safety SOP for SaaS) so the agent can make its first governed action
within an hour of connecting. The demo data (DEMO.md) shows this is achievable. Make
the time-to-first-autonomous-action a metric and target under 60 minutes.

### Risk 3: Positioning confusion — MEDIUM

**The risk:** The README calls it a "knowledge platform," the architecture doc calls
the wedge "auditable action," the onboarding talks about workflows. These are different
framings that will confuse the first 10 prospects.

**Mitigation:** Pick one sentence and make it the tagline everywhere:
"The AI that runs your company's operations — with a human approval queue and a
tamper-evident audit trail." That sentence contains the wedge (AI ops), the safety
story (human approval), and the compliance story (audit trail). Cut "knowledge graph,"
"knowledge map," and "multi-agent architecture" from all external-facing copy. Those
are implementation details, not value propositions.

### Risk 4: Solo-founder bus factor on a complex stack — MEDIUM

**The risk:** The infra footprint is large: Weaviate, Neo4j, Kafka, Redis, Postgres,
Vault, Celery, Langfuse. Each one can fail in a unique way. Solo founders running this
on launch day without on-call infrastructure experience will spend the first week
fighting ops, not talking to customers.

**Mitigation:** For EOD launch, do not use the full Docker Compose stack in
production. Deploy the Next.js frontend to Vercel (zero ops), the FastAPI backend to
Railway or Fly.io (one-command), and use Supabase for Postgres + Upstash for Redis.
Defer Weaviate (use a hosted instance or a free tier), defer Neo4j (the graph is not
needed for the Approval Queue demo), defer Kafka (the Celery worker can use Redis
directly). Strip the stack to: Vercel + Railway + Supabase + Upstash. This is a
weekend of work to rewire but eliminates 90% of launch-day ops risk.

### Risk 5: The detection gap is a trust bomb if exposed — HIGH

**The risk:** This was flagged clearly in the TIER4_RECONCILIATION_DESIGN.md CEO
addendum (C1). The shipped contradiction detector prompts the LLM with a PR title, not
a PR diff. If a design partner pushes a real PR and the detection either misses it or
fires on noise, it destroys trust in the whole platform.

**Mitigation:** Do not show the Reconciliation page in any demo or sales conversation
until C-P0-1 (pass the actual PR diff to the LLM) and C-P0-2 (Tier 0 deterministic
detection) are shipped. This is a P0 engineering task for Week 1 post-launch, not
something to paper over in positioning.

---

## 5. Two-Week Mobile Roadmap: PWA Now to What Next

### Today (EOD, blocking launch)

- Add `frontend/public/manifest.json` with name, icons (192x192, 512x512), `display: standalone`, `theme_color`, `background_color`.
- Add `<link rel="manifest" href="/manifest.json">` to `frontend/src/app/layout.tsx`.
- Confirm the Approval Queue card layout works at 375px (iPhone SE viewport). The
  `sm:flex-row` responsive class is already there; verify no overflow on the action
  buttons.
- Confirm the Command Center stat tiles stack to 2-column on mobile (already `grid-cols-2`
  in `page.tsx`). Spot-check.

No service worker required at this stage; the offline fallback is a client-side mock
already baked into the React components.

### Week 1 post-launch (push notifications — the real mobile unlock)

The killer mobile use case is: **phone buzzes, one tap to approve.** This requires:
- Register a service worker (`/public/sw.js`) that handles `push` events.
- Subscribe the user's browser to Web Push API (generate VAPID keys, store subscription
  in Postgres per tenant/user, expose `POST /notifications/subscribe`).
- When the backend routes an action to `pending_review`, fire a Web Push notification
  via the subscription.
- Notification payload: workflow name, risk level, one-line reason, deep link to
  `/approvals`.

This is the highest-ROI mobile investment. It turns a passive dashboard into an
active decision assistant. Estimated effort: 2 days for a solo founder who has done
Web Push before; 3-4 days if it's new territory.

### Week 2 (responsive reconciliation triage row, not the full screen)

The full reconciliation 3-pane diff is desktop-only and should stay that way. But the
triage queue — "skill X is quarantined, PR #842, HIGH severity, 4h until auto-release"
— is a perfect mobile-readable notification row. Build a read-only mobile view of the
queue that shows severity badge, skill name, PR ref, and TTL countdown. No editing on
mobile, just awareness. One tap links to the desktop reconciliation screen.

### Month 1 (native mobile — the honest answer on timing)

Native mobile becomes worth building when you have answers to:
- Do users approve actions from their phones or from their desk? (Measure.)
- What's the average session length on mobile PWA? (Measure.)
- Is a design partner asking for biometric auth, offline capability, or native push
  reliability that Web Push can't provide?

If the answers point to mobile being a primary surface, React Native is the right
choice (you have a Next.js/React codebase; the component patterns translate). Start
with the Approval Queue as a standalone native app — not the full platform.

Do not build native before you have these data points. Premature native is 3 months
of velocity lost on a bet you haven't validated.

---

## Decisions Log

| # | Question | Decision |
|---|---|---|
| D1 | Web + PWA vs. native mobile at launch | Web + PWA. Native after first 50 users and mobile usage data. |
| D2 | Product wedge | Approval Queue + audit trail. Contradiction detection is a future differentiator, not the launch story. |
| D3 | Reconciliation page at launch | Hidden from nav or "coming soon." Backend contract (quarantine_records table) doesn't exist; detector is noise. |
| D4 | Blast Radius viz | Cut for launch. Adds API latency to the critical approval flow path. |
| D5 | Calibration Chart | Cut or show only with real data. Synthetic curve is worse than nothing in a demo. |
| D6 | Infra stack for launch | Strip to Vercel + Railway + Supabase + Upstash. Full Docker Compose stack is a solo-founder ops trap. |
| D7 | Mobile P0 today | Add PWA manifest (30 min). That's the line between "installable" and "just a website." |
| D8 | First push notification | Week 1 priority. This is the product changing from pull to push on mobile. |

---

## What Already Exists That Is Stronger Than You Think

- The **offline fallback** with realistic demo data is polished and works. Use it
  in the first demo before wiring real connectors.
- The **onboarding flow** (industry + risk posture picker) is excellent positioning
  work. "Conservative" / "Balanced" / "Aggressive" tells a regulated buyer you
  understand their world before they say a word.
- The **Policy Evolution timeline** (Skills/Connectors hub) is a quiet gem. The idea
  that human feedback becomes a permanent, versioned invariant in the critic is the
  flywheel story in concrete UI. Show this to every investor.
- The **Approval Queue card animation** (swipe left to reject, swipe right to approve)
  is a good mobile-first mental model even on desktop. This is native-feeling behavior
  that validates the PWA approach.

---

*Review conducted against: README.md, DEMO.md, docs/ARCHITECTURE.md,
docs/TIER4_RECONCILIATION_DESIGN.md, and the full frontend source tree
(frontend/src/app/*, frontend/src/components/*, frontend/src/lib/api.ts).
No code was modified — read-only review.*
