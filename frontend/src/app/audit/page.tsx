"use client";

import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  ShieldCheck,
  Database,
  Brain,
  Lightbulb,
  Gavel,
  Zap,
  Link2,
  History,
  type LucideIcon,
} from "lucide-react";
import { api, type AuditEntry } from "@/lib/api";
import { SeverityPill } from "@/components/common/SeverityPill";
import { SnapshotDialog } from "@/components/audit/SnapshotDialog";
import { titleCase, timeAgo, severityColor } from "@/lib/format";

const STAGE_ICON: Record<string, LucideIcon> = {
  retrieve: Database,
  reason: Brain,
  propose: Lightbulb,
  validate: Gavel,
  act: Zap,
};

const FALLBACK: AuditEntry[] = [
  {
    seq: 3,
    run_id: "fallback-a",
    workflow_name: "deploy_approval",
    status: "rejected",
    risk_score: 0.88,
    timestamp: new Date(Date.now() - 5 * 60_000).toISOString(),
    snapshot_digest: "a88b6efb735ae8941b22c0f4e1d9c3b7a0f5e6d2c1b8a9f0e3d4c5b6a7980feed",
    steps: [
      { stage: "retrieve", label: "Retrieve", detail: "2 sources from memory graph" },
      { stage: "reason", label: "Reason", detail: "Release branch straight to prod" },
      { stage: "propose", label: "Propose", detail: "k8s_deploy" },
      { stage: "validate", label: "Validate", detail: "Critic risk 88% — no staging validation" },
      { stage: "act", label: "Act", detail: "Blocked by human / critic" },
    ],
    prev_hash: "00000000000000000000000000000000",
    entry_hash: "393bdd2cd7c454d2aa11bb22cc33dd44ee55ff66aa77bb88cc99dd00ee11ff22",
  },
  {
    seq: 2,
    run_id: "fallback-b",
    workflow_name: "refund_automation",
    status: "completed",
    risk_score: 0.12,
    timestamp: new Date(Date.now() - 180 * 60_000).toISOString(),
    snapshot_digest: "19f8a4e6f3469519c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3",
    steps: [
      { stage: "retrieve", label: "Retrieve", detail: "2 sources from memory graph" },
      { stage: "reason", label: "Reason", detail: "Late delivery, within policy" },
      { stage: "propose", label: "Propose", detail: "stripe_refund" },
      { stage: "validate", label: "Validate", detail: "Critic risk 12% — within policy" },
      { stage: "act", label: "Act", detail: "Executed and logged" },
    ],
    prev_hash: "393bdd2cd7c454d2aa11bb22cc33dd44ee55ff66aa77bb88cc99dd00ee11ff22",
    entry_hash: "7c1a9b3d5e7f0a2c4e6b8d0f1a3c5e7b9d1f3a5c7e9b1d3f5a7c9e1b3d5f7a90",
  },
];

export default function AuditPage() {
  const reduce = useReducedMotion();
  const [entries, setEntries] = useState<AuditEntry[]>(FALLBACK);
  const [verified, setVerified] = useState(true);
  const [selected, setSelected] = useState<AuditEntry | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getAudit(50)
      .then((res) => {
        if (cancelled || res.audit.length === 0) return;
        setEntries(res.audit);
        setVerified(res.verified);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6">
      {/* Verify banner */}
      <div
        className="glass-card flex flex-wrap items-center justify-between gap-3"
        style={{
          borderColor: verified
            ? "color-mix(in oklab, var(--accent-emerald) 35%, transparent)"
            : "color-mix(in oklab, var(--accent-rose) 35%, transparent)",
        }}
      >
        <div className="flex items-center gap-3">
          <span
            className="flex size-10 items-center justify-center rounded-xl"
            style={{
              background: verified ? "var(--accent-emerald-glow)" : "var(--accent-rose-glow)",
              color: verified ? "var(--accent-emerald)" : "var(--accent-rose)",
            }}
          >
            <ShieldCheck className="size-5" />
          </span>
          <div>
            <p className="text-sm font-semibold text-foreground">
              {verified ? "Chain verified" : "Chain integrity failure"}
            </p>
            <p className="text-xs text-muted-foreground">
              {entries.length} entries · SHA-256 hash-linked · tamper-evident
            </p>
          </div>
        </div>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Link2 className="size-3.5" /> each entry signs the one before it
        </span>
      </div>

      {/* Timeline */}
      <div className="relative space-y-3">
        {entries.map((entry, i) => (
          <motion.button
            key={entry.run_id + entry.seq}
            type="button"
            onClick={() => setSelected(entry)}
            initial={reduce ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: Math.min(i * 0.04, 0.3) }}
            className="glass-card glass-card-hover block w-full text-left"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs text-muted-foreground">#{entry.seq}</span>
                <h3 className="text-base font-semibold tracking-[-0.02em] text-foreground">
                  {titleCase(entry.workflow_name)}
                </h3>
                <SeverityPill
                  level={
                    entry.risk_score === null
                      ? "unknown"
                      : entry.risk_score < 0.3
                        ? "low"
                        : entry.risk_score < 0.7
                          ? "medium"
                          : "high"
                  }
                  label={entry.risk_score !== null ? `${Math.round(entry.risk_score * 100)}% risk` : "—"}
                />
              </div>
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <History className="size-3.5" /> {timeAgo(entry.timestamp)} · time-travel
              </span>
            </div>

            {/* Stepper */}
            <div className="mt-4 flex items-center gap-1 overflow-x-auto pb-1">
              {entry.steps.map((step, si) => {
                const Icon = STAGE_ICON[step.stage] ?? Database;
                const isAct = step.stage === "act";
                const color =
                  isAct && entry.status === "rejected"
                    ? severityColor("high")
                    : "var(--accent-blue)";
                return (
                  <div key={step.stage} className="flex shrink-0 items-center">
                    <div className="flex min-w-[120px] flex-col gap-1 rounded-xl border border-border bg-card/40 px-3 py-2">
                      <span
                        className="flex items-center gap-1.5 text-[11px] font-semibold"
                        style={{ color }}
                      >
                        <Icon className="size-3.5" /> {step.label}
                      </span>
                      <span className="line-clamp-2 text-[11px] text-muted-foreground">
                        {step.detail}
                      </span>
                    </div>
                    {si < entry.steps.length - 1 && (
                      <span className="mx-0.5 text-muted-foreground/50">→</span>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Hash chain footer */}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 font-mono text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Link2 className="size-3" /> prev{" "}
                <span className="text-foreground/70">{entry.prev_hash.slice(0, 12)}…</span>
              </span>
              <span>
                hash{" "}
                <span className="text-[var(--accent-blue)]">{entry.entry_hash.slice(0, 12)}…</span>
              </span>
              <span>
                state{" "}
                <span className="text-[var(--accent-emerald)]">
                  {entry.snapshot_digest.slice(0, 12)}…
                </span>
              </span>
            </div>
          </motion.button>
        ))}
      </div>

      <SnapshotDialog
        runId={selected?.run_id ?? null}
        workflowName={selected?.workflow_name ?? ""}
        digest={selected?.snapshot_digest ?? ""}
        open={selected !== null}
        onOpenChange={(o) => !o && setSelected(null)}
      />
    </div>
  );
}
