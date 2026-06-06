"use client";

import { useState } from "react";
import { AlertTriangle, Check, Pencil, X, Database, Zap } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { RiskGauge } from "@/components/viz/RiskGauge";
import { BlastRadiusGraph } from "@/components/viz/BlastRadiusGraph";
import { SeverityPill } from "@/components/common/SeverityPill";
import { titleCase, timeAgo } from "@/lib/format";
import type { BlastRadius, WorkflowRunSummary } from "@/lib/api";

export type Decision = "approve" | "reject" | "modify";

interface ApprovalCardProps {
  item: WorkflowRunSummary;
  blast?: BlastRadius;
  blastLoading?: boolean;
  onDecision: (decision: Decision, reason?: string) => void;
}

function actionSummary(action: Record<string, unknown>): string {
  const type = (action.action_type as string) || "action";
  const params = (action.parameters as Record<string, unknown>) || {};
  const parts = Object.entries(params)
    .slice(0, 3)
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${String(v)}`);
  return parts.length ? `${titleCase(type)} — ${parts.join(", ")}` : titleCase(type);
}

export function ApprovalCard({ item, blast, blastLoading, onDecision }: ApprovalCardProps) {
  const [modifying, setModifying] = useState(false);
  const [reason, setReason] = useState("");
  const forecast = item.forecast;
  const triggerEntries = Object.entries(item.trigger_data || {}).slice(0, 4);

  return (
    <div className="glass-strong rounded-[var(--radius-2xl)] p-6 sm:p-7">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold tracking-[-0.02em] text-foreground">
            {titleCase(item.workflow_name)}
          </h3>
          <p className="text-xs text-muted-foreground">{timeAgo(item.created_at)}</p>
        </div>
        <SeverityPill level={item.critic_risk_level} />
      </div>

      {/* Proposed action */}
      <div className="mt-5 rounded-xl border border-border bg-card/50 p-4">
        <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
          <Zap className="size-3.5" /> Proposed action
        </p>
        <p className="mt-1 text-sm font-medium text-foreground">
          {actionSummary(item.final_action)}
        </p>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        {/* Left: context + critic warning + risk */}
        <div className="space-y-5">
          {triggerEntries.length > 0 && (
            <div>
              <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                <Database className="size-3.5" /> Context retrieved
              </p>
              <dl className="mt-2 space-y-1">
                {triggerEntries.map(([k, v]) => (
                  <div key={k} className="flex gap-2 text-sm">
                    <dt className="shrink-0 capitalize text-muted-foreground">
                      {k.replace(/_/g, " ")}:
                    </dt>
                    <dd className="text-foreground">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {item.critic_reasons.length > 0 && (
            <div
              className="rounded-xl border p-3"
              style={{
                borderColor: "color-mix(in oklab, var(--accent-amber) 35%, transparent)",
                background: "color-mix(in oklab, var(--accent-amber) 8%, transparent)",
              }}
            >
              <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--accent-amber)]">
                <AlertTriangle className="size-3.5" /> Critic flagged
              </p>
              <ul className="mt-1.5 space-y-1">
                {item.critic_reasons.map((r) => (
                  <li key={r} className="text-sm text-foreground">
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {forecast && (
            <RiskGauge
              probability={forecast.probability}
              confidenceLow={forecast.confidence_low}
              confidenceHigh={forecast.confidence_high}
              threshold={forecast.dynamic_threshold}
              autonomyLevel={forecast.autonomy_level}
              factors={forecast.factors}
            />
          )}
        </div>

        {/* Right: blast radius (recessed) */}
        <div className="trench p-3">
          <div className="mb-1 flex items-center justify-between">
            <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
              Blast radius
            </p>
            {blast && (
              <SeverityPill
                level={blast.summary.highest_severity}
                label={`${blast.summary.systems_touched} systems`}
              />
            )}
          </div>
          {blastLoading || !blast ? (
            <div className="flex flex-col items-center gap-3 py-8">
              <Skeleton className="size-40 rounded-full" />
              <Skeleton className="h-3 w-32" />
            </div>
          ) : (
            <BlastRadiusGraph data={blast} size={300} />
          )}
        </div>
      </div>

      {/* Modify reason */}
      {modifying && (
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Describe the correction the agent should learn from…"
          rows={2}
          className="mt-4 w-full resize-none rounded-xl border border-input bg-card/60 p-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
        />
      )}

      {/* Actions — structural frosted, colour as glow not fill */}
      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onDecision("approve")}
          className="btn-glass btn-tint-emerald flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl px-4 text-sm font-semibold"
        >
          <Check className="size-4" /> Approve
        </button>
        <button
          type="button"
          onClick={() => onDecision("reject")}
          className="btn-glass btn-tint-rose flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl px-4 text-sm font-semibold"
        >
          <X className="size-4" /> Reject
        </button>
        <button
          type="button"
          onClick={() => {
            if (modifying) {
              onDecision("modify", reason || undefined);
            } else {
              setModifying(true);
            }
          }}
          className="btn-glass flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl px-4 text-sm font-medium text-muted-foreground"
        >
          <Pencil className="size-4" /> {modifying ? "Submit correction" : "Modify"}
        </button>
      </div>
    </div>
  );
}
