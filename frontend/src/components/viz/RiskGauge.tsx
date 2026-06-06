"use client";

import { motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";
import {
  AUTONOMY_LABELS,
  riskLevelFromProbability,
  severityColor,
} from "@/lib/format";
import type { RiskFactor } from "@/lib/api";

interface RiskGaugeProps {
  probability: number; // 0-1
  confidenceLow: number; // 0-1
  confidenceHigh: number; // 0-1
  threshold: number; // 0-1
  autonomyLevel?: number;
  factors?: RiskFactor[];
  compact?: boolean;
}

/**
 * Probabilistic risk forecast. Shows the calibrated probability of a negative
 * outcome, the 90% confidence band, and the dynamic routing threshold — so the
 * safety decision reads as mathematical, not a binary pass/fail.
 */
export function RiskGauge({
  probability,
  confidenceLow,
  confidenceHigh,
  threshold,
  autonomyLevel,
  factors = [],
  compact = false,
}: RiskGaugeProps) {
  const reduce = useReducedMotion();
  const p = Math.max(0, Math.min(1, probability));
  const lo = Math.max(0, Math.min(1, confidenceLow));
  const hi = Math.max(0, Math.min(1, confidenceHigh));
  const thr = Math.max(0, Math.min(1, threshold));
  const level = riskLevelFromProbability(p);
  const color = severityColor(level);
  const routed = hi >= thr;

  return (
    <div className="w-full">
      <div className="mb-2 flex items-end justify-between">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            P(negative outcome)
          </p>
          <div className="flex items-baseline gap-2">
            <span
              className="text-2xl font-semibold tabular-nums tracking-[-0.02em]"
              style={{ color }}
            >
              {Math.round(p * 100)}%
            </span>
            <span className="text-xs text-muted-foreground">
              ±{Math.round(((hi - lo) / 2) * 100)}% (90% CI)
            </span>
          </div>
        </div>
        {autonomyLevel !== undefined && (
          <div className="text-right">
            <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
              Autonomy
            </span>
            <p className="text-sm font-semibold text-foreground">
              {AUTONOMY_LABELS[autonomyLevel]?.label ?? `L${autonomyLevel}`}
            </p>
          </div>
        )}
      </div>

      {/* Track — recessed frosted trench */}
      <div
        className="relative h-3 w-full overflow-visible rounded-full"
        style={{
          background: "color-mix(in oklab, var(--background) 55%, transparent)",
          boxShadow: "var(--trench)",
        }}
      >
        {/* Confidence band */}
        <div
          className="absolute inset-y-0 rounded-full opacity-25"
          style={{
            left: `${lo * 100}%`,
            width: `${Math.max(0, hi - lo) * 100}%`,
            background: color,
          }}
        />
        {/* Probability fill — gradient with a soft glow */}
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            background: `linear-gradient(90deg, color-mix(in oklab, ${color} 55%, transparent), ${color})`,
            boxShadow: `0 0 12px color-mix(in oklab, ${color} 55%, transparent)`,
          }}
          initial={reduce ? false : { width: 0 }}
          animate={{ width: `${p * 100}%` }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        />
        {/* Probability knob */}
        <motion.div
          className="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background shadow-[var(--shadow-md)]"
          style={{ background: color }}
          initial={reduce ? false : { left: 0 }}
          animate={{ left: `${p * 100}%` }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        />
        {/* Dynamic threshold marker */}
        <div
          className="absolute -top-1.5 bottom-[-6px] w-px bg-foreground/60"
          style={{ left: `${thr * 100}%` }}
        >
          <span className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full border border-border bg-card px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            threshold {Math.round(thr * 100)}%
          </span>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
          )}
          style={{
            color: routed ? "var(--accent-rose)" : "var(--accent-emerald)",
            background: routed
              ? "var(--accent-rose-glow)"
              : "var(--accent-emerald-glow)",
          }}
        >
          <span className="size-1.5 rounded-full" style={{ background: "currentColor" }} />
          {routed ? "Routed to human" : "Within autonomy"}
        </span>
        {!compact && factors.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1.5">
            {factors.slice(0, 3).map((f) => (
              <span
                key={f.label}
                className="rounded-full border border-border bg-secondary/60 px-2 py-0.5 text-[11px] text-secondary-foreground"
              >
                {f.label}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
