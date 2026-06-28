"use client";

/**
 * Company Brain — marketing landing page (full-bleed, no dashboard chrome;
 * AppShell skips its sidebar/header for /welcome).
 *
 * Copy is deliberately honest and aligned to docs/POSITIONING.md: Company Brain
 * is the governed company-memory + action engine — NOT an "AI workforce" or an
 * "agent OS". No fake certifications or compliance logos. Every claim maps to a
 * mechanism that exists in the codebase.
 */

import Link from "next/link";
import { motion, type Variants } from "motion/react";
import {
  Brain,
  ShieldCheck,
  GitMerge,
  Workflow,
  Search,
  Lock,
  FileCheck2,
  Network,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  Database,
  Layers,
  Gauge,
  Headphones,
  Calculator,
  Inbox,
  LineChart,
  type LucideIcon,
} from "lucide-react";

// ── Motion helpers ───────────────────────────────────────────────────────────
const fadeUp: Variants = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0 },
};

function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

const SectionLabel = ({ children }: { children: React.ReactNode }) => (
  <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--accent-blue)]">
    {children}
  </span>
);

// ── Data ─────────────────────────────────────────────────────────────────────
const PILLARS: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: Database,
    title: "Operating memory",
    body: "Slack, Notion, GitHub and docs become one source-backed memory. Every answer carries its sources, timestamps and owners.",
  },
  {
    icon: ShieldCheck,
    title: "Governed action",
    body: "Retrieve → propose → an independent critic checks risk & policy → human approval when risky → execute → tamper-evident audit.",
  },
  {
    icon: GitMerge,
    title: "Contradiction handling",
    body: "When new knowledge conflicts with an active procedure, the skill is quarantined and routed to a human. The system stops itself.",
  },
];

const LOOP: { step: string; icon: LucideIcon; label: string; note: string }[] = [
  { step: "01", icon: Search, label: "Retrieve", note: "Tenant-scoped context from vector + graph memory" },
  { step: "02", icon: Workflow, label: "Propose", note: "WorkflowAgent drafts a structured candidate action" },
  { step: "03", icon: ShieldCheck, label: "Critic", note: "Independent pass: PII, RBAC, limits, policy" },
  { step: "04", icon: CheckCircle2, label: "Approve", note: "Risky actions hold in a human approval queue" },
  { step: "05", icon: Workflow, label: "Execute", note: "Only registered executors fire; rest dry-run" },
  { step: "06", icon: FileCheck2, label: "Audit", note: "HMAC-chained entry — tampering breaks the chain" },
];

const ROLES: { icon: LucideIcon; title: string; body: string }[] = [
  { icon: Inbox, title: "Intake & qualification", body: "Triage inbound, enrich, and route — with the brain's memory and your approval rules." },
  { icon: Headphones, title: "Support & service", body: "Draft and act on tickets from real history; risky replies wait for a human." },
  { icon: Calculator, title: "Finance & admin", body: "High-trust actions (invoices, expenses) always critic-checked and gated." },
  { icon: LineChart, title: "Analyst & reporting", body: "Scheduled, recurring digests and monitors that run governed, on time." },
];

const SECURITY: { icon: LucideIcon; title: string; body: string }[] = [
  { icon: Lock, title: "Tenant isolation", body: "Every table carries tenant_id; queries are tenant-scoped and identity flows from the OIDC token." },
  { icon: FileCheck2, title: "Tamper-evident audit", body: "Each action is an HMAC-SHA256 chained entry — altering any line breaks the chain." },
  { icon: ShieldCheck, title: "Independent critic", body: "A separate, deterministic pass can veto the worker; high-risk actions never auto-execute." },
  { icon: Brain, title: "PII redaction", body: "Presidio at ingestion where installed, with a deterministic regex fallback so PII is scrubbed before storage." },
  { icon: Lock, title: "OIDC + RBAC", body: "JWT auth (sig/exp/aud/iss verified) and deny-by-default YAML roles: admin / manager / engineer / viewer." },
  { icon: GitMerge, title: "Contradiction handshake", body: "Conflicting knowledge quarantines the affected skill until a human reconciles it." },
];

// ── Page ─────────────────────────────────────────────────────────────────────
export default function WelcomePage() {
  return (
    <div className="relative min-h-screen overflow-hidden bg-background text-foreground">
      {/* Ambient background motif */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute left-1/2 top-[-10%] h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent-blue)_18%,transparent),transparent)] blur-2xl" />
        <div className="absolute bottom-[-15%] right-[-5%] h-[420px] w-[620px] rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent-emerald)_12%,transparent),transparent)] blur-2xl" />
        <div className="absolute inset-0 bg-[linear-gradient(to_bottom,transparent,var(--background))] opacity-60" />
      </div>

      {/* Nav */}
      <header className="sticky top-0 z-20 border-b border-border/60 bg-background/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <div className="flex items-center gap-2 font-semibold">
            <span className="flex size-8 items-center justify-center rounded-lg border border-border bg-card/60 text-[var(--accent-blue)]">
              <Brain className="size-4" />
            </span>
            Company Brain
          </div>
          <nav className="hidden items-center gap-7 text-sm text-muted-foreground md:flex">
            <a href="#how" className="transition-colors hover:text-foreground">How it works</a>
            <a href="#trust" className="transition-colors hover:text-foreground">Trust</a>
            <a href="#roles" className="transition-colors hover:text-foreground">Use cases</a>
            <a href="#security" className="transition-colors hover:text-foreground">Security</a>
          </nav>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent-blue)] px-3.5 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          >
            Launch app <ArrowRight className="size-4" />
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-5 pb-20 pt-20 text-center sm:pt-28">
        <motion.div initial="hidden" animate="show" variants={fadeUp} transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}>
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card/50 px-3 py-1 text-xs text-muted-foreground">
            <span className="size-1.5 rounded-full bg-[var(--accent-emerald)]" />
            Governed company-memory & action engine
          </span>
          <h1 className="mx-auto mt-6 max-w-4xl text-balance text-4xl font-semibold leading-[1.08] tracking-tight sm:text-6xl">
            Turn scattered company knowledge into a{" "}
            <span className="bg-gradient-to-r from-[var(--accent-blue)] to-[var(--accent-emerald)] bg-clip-text text-transparent">
              governed, auditable
            </span>{" "}
            operating layer.
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-pretty text-base leading-relaxed text-muted-foreground sm:text-lg">
            Company Brain ingests your knowledge into one source-backed memory, then safely
            runs the operational work on it — every action risk-checked by an independent
            critic, gated by human approval when it matters, and written to a tamper-evident
            audit trail.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/"
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent-blue)] px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-[color-mix(in_oklab,var(--accent-blue)_30%,transparent)] transition-opacity hover:opacity-90"
            >
              Open the dashboard <ArrowRight className="size-4" />
            </Link>
            <a
              href="#how"
              className="inline-flex items-center gap-2 rounded-xl border border-border bg-card/40 px-6 py-3 text-sm font-semibold text-foreground transition-colors hover:bg-card/70"
            >
              See how it works
            </a>
          </div>
        </motion.div>

        {/* Pillars */}
        <div className="mt-16 grid gap-4 text-left sm:grid-cols-3">
          {PILLARS.map((p, i) => {
            const Icon = p.icon;
            return (
              <Reveal key={p.title} delay={i * 0.08} className="glass-card">
                <Icon className="size-5 text-[var(--accent-blue)]" />
                <h3 className="mt-3 text-sm font-semibold">{p.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{p.body}</p>
              </Reveal>
            );
          })}
        </div>
      </section>

      {/* Problem */}
      <section className="mx-auto max-w-6xl px-5 py-20">
        <Reveal className="mx-auto max-w-3xl text-center">
          <SectionLabel>The problem</SectionLabel>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            Your real operating knowledge is scattered — and the tools that find it can&apos;t act on it.
          </h2>
          <p className="mt-4 text-muted-foreground">
            Search tools retrieve and summarize. They leave a human to go execute. Meanwhile
            answers drift stale, procedures contradict each other, and ungoverned AI is a
            non-starter for anyone with compliance obligations.
          </p>
        </Reveal>
        <div className="mt-10 grid gap-4 sm:grid-cols-3">
          {[
            { icon: Layers, t: "Fragmented", b: "Policy in Slack, procedure in Notion, conventions in a PR comment. No single source of truth." },
            { icon: AlertTriangle, t: "Stale & conflicting", b: "Knowledge contradicts itself and no one notices until an action goes wrong." },
            { icon: ShieldCheck, t: "Ungoverned", b: "An agent that acts without a paper trail can't be sold to a regulated buyer." },
          ].map((x, i) => {
            const Icon = x.icon;
            return (
              <Reveal key={x.t} delay={i * 0.08} className="glass-card">
                <Icon className="size-5 text-[var(--accent-amber)]" />
                <h3 className="mt-3 text-sm font-semibold">{x.t}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{x.b}</p>
              </Reveal>
            );
          })}
        </div>
      </section>

      {/* How it works — the governed loop */}
      <section id="how" className="mx-auto max-w-6xl px-5 py-20">
        <Reveal className="mx-auto max-w-3xl text-center">
          <SectionLabel>How it works</SectionLabel>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            One governed loop — from question to audited action.
          </h2>
          <p className="mt-4 text-muted-foreground">
            Nothing executes outside this path. The same loop runs whether a person, an API
            call, or a schedule triggers it.
          </p>
        </Reveal>
        <div className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {LOOP.map((s, i) => {
            const Icon = s.icon;
            return (
              <Reveal key={s.step} delay={i * 0.06} className="glass-card relative">
                <span className="absolute right-4 top-4 text-xs font-semibold text-muted-foreground/50">{s.step}</span>
                <Icon className="size-5 text-[var(--accent-blue)]" />
                <h3 className="mt-3 text-sm font-semibold">{s.label}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{s.note}</p>
              </Reveal>
            );
          })}
        </div>
      </section>

      {/* Trust / mock interface panel */}
      <section id="trust" className="mx-auto max-w-6xl px-5 py-20">
        <div className="grid items-center gap-10 lg:grid-cols-2">
          <Reveal>
            <SectionLabel>The wedge is auditable action</SectionLabel>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
              An independent critic stands between intent and execution.
            </h2>
            <p className="mt-4 text-muted-foreground">
              A second, deterministic model pass scores every candidate action for risk and
              policy compliance. Low-risk actions flow through; anything risky waits in a
              human approval queue. Each decision is written to a chained, tamper-evident log
              an auditor can verify line by line.
            </p>
            <ul className="mt-6 space-y-3">
              {[
                "Risk-scored verdicts with explainable reasons",
                "Human approval queue for high-risk actions",
                "Per-tenant learned policy that gets stricter over time",
                "Cryptographically chained audit you can hand to a regulator",
              ].map((t) => (
                <li key={t} className="flex items-start gap-2.5 text-sm">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-[var(--accent-emerald)]" />
                  <span className="text-muted-foreground">{t}</span>
                </li>
              ))}
            </ul>
          </Reveal>

          {/* Mock verdict panel — same visual language as the dashboard */}
          <Reveal delay={0.1}>
            <div className="glass-card">
              <div className="mb-4 flex items-center gap-2">
                <ShieldCheck className="size-4 text-[var(--accent-amber)]" />
                <h3 className="text-sm font-semibold">Approval queue</h3>
                <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="size-1.5 rounded-full bg-[var(--accent-amber)]" /> 2 pending
                </span>
              </div>
              <div className="space-y-3">
                {[
                  { t: "Deploy approval", r: "high", p: 88, s: "No staging validation referenced", c: "var(--accent-amber)" },
                  { t: "Refund · order #7291", r: "low", p: 12, s: "Within policy: under $100", c: "var(--accent-emerald)" },
                  { t: "Invoice · ACME Co", r: "medium", p: 41, s: "Amount above auto-approve limit", c: "var(--accent-blue)" },
                ].map((v) => (
                  <div key={v.t} className="rounded-xl border border-border bg-card/40 p-4">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{v.t}</span>
                      <span
                        className="rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize"
                        style={{ background: `color-mix(in oklab, ${v.c} 16%, transparent)`, color: v.c }}
                      >
                        {v.r} risk
                      </span>
                    </div>
                    <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                      <span>{v.s}</span>
                      <span>P(neg) <span className="font-semibold text-foreground">{v.p}%</span></span>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex items-center gap-2 rounded-lg border border-border bg-card/30 px-3 py-2 text-xs text-muted-foreground">
                <FileCheck2 className="size-3.5 text-[var(--accent-emerald)]" />
                Every decision appended to the HMAC-chained audit trail.
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* Use cases / roles */}
      <section id="roles" className="mx-auto max-w-6xl px-5 py-20">
        <Reveal className="mx-auto max-w-3xl text-center">
          <SectionLabel>Use cases</SectionLabel>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            Role bundles the brain runs — on your truth, SOPs and approvals.
          </h2>
          <p className="mt-4 text-muted-foreground">
            Not autonomous staff. Each role is a set of procedures, executors and approval
            policies the same governed engine runs.
          </p>
        </Reveal>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {ROLES.map((r, i) => {
            const Icon = r.icon;
            return (
              <Reveal key={r.title} delay={i * 0.06} className="glass-card">
                <Icon className="size-5 text-[var(--accent-blue)]" />
                <h3 className="mt-3 text-sm font-semibold">{r.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{r.body}</p>
              </Reveal>
            );
          })}
        </div>
      </section>

      {/* Security */}
      <section id="security" className="mx-auto max-w-6xl px-5 py-20">
        <Reveal className="mx-auto max-w-3xl text-center">
          <SectionLabel>Security & trust</SectionLabel>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            Built for buyers who can&apos;t afford an unsafe answer.
          </h2>
          <p className="mt-4 text-muted-foreground">
            Mechanisms, not badges. Everything below is enforced in code — we don&apos;t claim
            certifications we don&apos;t hold.
          </p>
        </Reveal>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SECURITY.map((s, i) => {
            const Icon = s.icon;
            return (
              <Reveal key={s.title} delay={(i % 3) * 0.06} className="glass-card">
                <Icon className="size-5 text-[var(--accent-emerald)]" />
                <h3 className="mt-3 text-sm font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{s.body}</p>
              </Reveal>
            );
          })}
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-6xl px-5 pb-24 pt-10">
        <Reveal>
          <div className="glass-card relative overflow-hidden text-center">
            <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent-blue)_14%,transparent),transparent)]" />
            <div className="relative py-10">
              <Network className="mx-auto size-7 text-[var(--accent-blue)]" />
              <h2 className="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl">
                See your company&apos;s brain in action.
              </h2>
              <p className="mx-auto mt-3 max-w-xl text-muted-foreground">
                Open the dashboard to explore the live approval queue, critic calibration,
                and audit trail.
              </p>
              <Link
                href="/"
                className="mt-7 inline-flex items-center gap-2 rounded-xl bg-[var(--accent-blue)] px-6 py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90"
              >
                Launch the dashboard <ArrowRight className="size-4" />
              </Link>
            </div>
          </div>
        </Reveal>
      </section>

      {/* Footer */}
      <footer className="border-t border-border/60">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-5 py-8 text-sm text-muted-foreground sm:flex-row">
          <div className="flex items-center gap-2">
            <Brain className="size-4 text-[var(--accent-blue)]" />
            Company Brain
          </div>
          <p className="flex items-center gap-1.5">
            <Gauge className="size-3.5" /> Governed memory & action — auditable by construction.
          </p>
        </div>
      </footer>
    </div>
  );
}
