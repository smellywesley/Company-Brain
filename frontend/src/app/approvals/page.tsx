"use client";

import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ShieldCheck, Inbox } from "lucide-react";
import { toast } from "sonner";
import { api, type BlastRadius, type WorkflowRunSummary } from "@/lib/api";
import { ApprovalCard, type Decision } from "@/components/approvals/ApprovalCard";

// Offline fallback so the queue still renders with the backend down.
const FALLBACK: WorkflowRunSummary[] = [
  {
    id: "fallback-1",
    workflow_name: "customer_retention",
    status: "pending_review",
    critic_approved: null,
    critic_risk_score: 0.62,
    critic_risk_level: "medium",
    critic_reasons: [
      "Retention offer exceeds standard discount band",
      "Cross-source claim requires human confirmation",
    ],
    final_action: {
      action_type: "send_retention_offer",
      parameters: { discount_pct: 20, account: "Acme Corp" },
    },
    trigger_data: { account: "Acme Corp", signal: "No reply in 14 days after renewal quote" },
    created_at: new Date(Date.now() - 12 * 60_000).toISOString(),
    forecast: {
      risk_score: 0.62,
      probability: 0.59,
      confidence_low: 0.33,
      confidence_high: 0.86,
      dynamic_threshold: 0.52,
      routed_to_human: true,
      autonomy_level: 1,
      factors: [{ label: "Evidence quality", weight: 0.5 }],
    },
  },
  {
    id: "fallback-2",
    workflow_name: "refund_automation",
    status: "pending_review",
    critic_approved: null,
    critic_risk_score: 0.55,
    critic_risk_level: "medium",
    critic_reasons: ["Amount exceeds $100 threshold", "Refund reason requires validation"],
    final_action: {
      action_type: "stripe_refund",
      parameters: { amount_cents: 34900, order_id: "ORD-7291" },
    },
    trigger_data: { order_id: "ORD-7291", amount_usd: 349.0, reason: "Product defective" },
    created_at: new Date(Date.now() - 34 * 60_000).toISOString(),
    forecast: {
      risk_score: 0.55,
      probability: 0.54,
      confidence_low: 0.3,
      confidence_high: 0.78,
      dynamic_threshold: 0.52,
      routed_to_human: true,
      autonomy_level: 1,
      factors: [{ label: "Financial limit", weight: 0.6 }],
    },
  },
];

export default function ApprovalsPage() {
  const reduce = useReducedMotion();
  const [queue, setQueue] = useState<WorkflowRunSummary[]>(FALLBACK);
  const [blastById, setBlastById] = useState<Record<string, BlastRadius>>({});
  const [exitDir, setExitDir] = useState(0);
  const [approved, setApproved] = useState(0);
  const [rejected, setRejected] = useState(0);
  const [live, setLive] = useState(false);

  // Load the live pending queue.
  useEffect(() => {
    let cancelled = false;
    api
      .getWorkflows("pending_review", 50)
      .then((res) => {
        if (cancelled || res.workflows.length === 0) return;
        setQueue(res.workflows);
        setLive(true);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const front = queue[0];

  // Fetch blast radius for the front card (live runs only).
  useEffect(() => {
    if (!front || !live || blastById[front.id]) return;
    let cancelled = false;
    api
      .getBlastRadius(front.id)
      .then((res) => {
        if (!cancelled) setBlastById((m) => ({ ...m, [front.id]: res.blast_radius }));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [front, live, blastById]);

  const decide = useCallback(
    (decision: Decision, reason?: string) => {
      if (!front) return;
      setExitDir(decision === "approve" ? 1 : decision === "reject" ? -1 : 0);
      if (decision === "approve") setApproved((n) => n + 1);
      if (decision === "reject") setRejected((n) => n + 1);

      toast.success(
        decision === "approve"
          ? "Action approved — executing"
          : decision === "reject"
            ? "Action rejected — blocked"
            : "Correction submitted — critic recalibrated",
        { description: front.workflow_name.replace(/_/g, " ") },
      );

      if (live && !front.id.startsWith("fallback")) {
        api.submitFeedback(front.id, decision, undefined, reason).catch(() => {
          toast.error("Could not reach backend — recorded locally only");
        });
      }
      setQueue((q) => q.slice(1));
    },
    [front, live],
  );

  const exitVariant = reduce
    ? { opacity: 0 }
    : {
        x: exitDir * 480,
        y: exitDir === 0 ? -200 : 0,
        rotate: exitDir * 6,
        opacity: 0,
        transition: { duration: 0.32, ease: [0.16, 1, 0.3, 1] as const },
      };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      {/* Stack */}
      <div>
        {queue.length === 0 ? (
          <div className="glass-card flex flex-col items-center justify-center gap-3 py-20 text-center">
            <span className="flex size-14 items-center justify-center rounded-2xl bg-[var(--accent-emerald-glow)] text-[var(--accent-emerald)]">
              <Inbox className="size-7" />
            </span>
            <h3 className="text-lg font-semibold text-foreground">Queue cleared</h3>
            <p className="max-w-sm text-sm text-muted-foreground">
              Every flagged action has been reviewed. New high-risk actions will land
              here automatically.
            </p>
          </div>
        ) : (
          <div className="relative">
            {/* Peek layers behind the front card */}
            {queue.slice(1, 3).map((it, i) => (
              <div
                key={it.id}
                aria-hidden
                className="glass-card absolute inset-x-0 top-0 origin-top"
                style={{
                  transform: `translateY(${(i + 1) * 14}px) scale(${1 - (i + 1) * 0.03})`,
                  opacity: 1 - (i + 1) * 0.35,
                  zIndex: -1,
                  height: 120,
                }}
              />
            ))}

            <AnimatePresence mode="popLayout" custom={exitDir}>
              <motion.div
                key={front.id}
                layout
                initial={reduce ? false : { opacity: 0, y: 16, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={exitVariant}
                transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
              >
                <ApprovalCard
                  item={front}
                  blast={blastById[front.id]}
                  blastLoading={live && !blastById[front.id]}
                  onDecision={decide}
                />
              </motion.div>
            </AnimatePresence>
          </div>
        )}
      </div>

      {/* Summary */}
      <aside className="space-y-4">
        <div className="glass-card">
          <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            <ShieldCheck className="size-3.5" /> Today
          </p>
          <div className="mt-3 space-y-3">
            <Summary label="Pending review" value={queue.length} color="var(--accent-amber)" />
            <Summary label="Approved" value={approved} color="var(--accent-emerald)" />
            <Summary label="Rejected" value={rejected} color="var(--accent-rose)" />
          </div>
        </div>
        <div className="glass-card">
          <p className="text-sm font-medium text-foreground">How this works</p>
          <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
            The CriticAgent forecasts the probability of a negative outcome. When the
            upper confidence bound crosses the tenant&apos;s dynamic threshold, the action
            lands here. Your decision recalibrates the critic and evolves the policy.
          </p>
        </div>
      </aside>
    </div>
  );
}

function Summary({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className="size-2 rounded-full" style={{ background: color }} />
        {label}
      </span>
      <span className="text-lg font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  );
}
