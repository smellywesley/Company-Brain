"use client";

import type { LucideIcon } from "lucide-react";
import AnimatedCounter from "@/components/AnimatedCounter";
import { cn } from "@/lib/utils";

interface StatTileProps {
  label: string;
  value: number;
  icon: LucideIcon;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  accent?: string; // CSS color for the icon chip
  hint?: string;
  className?: string;
}

/** Compact metric tile used across the Command Center bento grid. */
export function StatTile({
  label,
  value,
  icon: Icon,
  prefix = "",
  suffix = "",
  decimals = 0,
  accent = "var(--accent-blue)",
  hint,
  className,
}: StatTileProps) {
  return (
    <div className={cn("glass-card glass-card-hover", className)}>
      <div className="flex items-start justify-between">
        <span
          className="flex size-9 items-center justify-center rounded-xl"
          style={{ background: `color-mix(in oklab, ${accent} 16%, transparent)`, color: accent }}
        >
          <Icon className="size-[18px]" />
        </span>
        {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
      </div>
      <p className="mt-4 text-3xl font-semibold tabular-nums tracking-[-0.03em] text-foreground">
        <AnimatedCounter target={value} prefix={prefix} suffix={suffix} decimals={decimals} />
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{label}</p>
    </div>
  );
}
