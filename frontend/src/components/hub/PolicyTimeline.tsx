"use client";

import { motion, useReducedMotion } from "motion/react";
import { GitCommitVertical, Plus } from "lucide-react";
import type { PolicyRule } from "@/lib/api";

interface PolicyTimelineProps {
  history: PolicyRule[];
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/**
 * The visible moat: a git-style timeline of invariants the CriticCalibrator has
 * appended to this tenant's policy from human feedback. Each entry is the
 * company's "constitution" gaining a new, permanent rule.
 */
export function PolicyTimeline({ history }: PolicyTimelineProps) {
  const reduce = useReducedMotion();
  const ordered = [...history].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  if (ordered.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No learned invariants yet. They appear here as humans correct the agent.
      </p>
    );
  }

  return (
    <ol className="relative ml-3 border-l border-border">
      {ordered.map((entry, i) => (
        <motion.li
          key={entry.created_at + i}
          initial={reduce ? false : { opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.25, delay: Math.min(i * 0.05, 0.3) }}
          className="mb-6 ml-6"
        >
          <span className="absolute -left-[13px] flex size-6 items-center justify-center rounded-full border border-border bg-card">
            <GitCommitVertical className="size-3.5 text-[var(--accent-emerald)]" />
          </span>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 text-xs font-semibold text-[var(--accent-emerald)]">
              <Plus className="size-3" /> invariant learned
            </span>
            <span className="text-xs text-muted-foreground">{fmtDate(entry.created_at)}</span>
          </div>
          <p className="mt-1.5 rounded-xl border border-border bg-card/50 p-3 font-mono text-sm text-foreground">
            {entry.rule}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            from {entry.feedback_count} human correction{entry.feedback_count === 1 ? "" : "s"} ·{" "}
            {entry.source.replace(/_/g, " ")}
          </p>
        </motion.li>
      ))}
    </ol>
  );
}
