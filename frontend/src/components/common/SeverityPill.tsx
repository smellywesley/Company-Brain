import { cn } from "@/lib/utils";
import { severityColor } from "@/lib/format";

interface SeverityPillProps {
  level: string; // low | medium | high | unknown
  label?: string;
  className?: string;
}

/** A small status pill tinted by severity, used for risk levels and verdicts. */
export function SeverityPill({ level, label, className }: SeverityPillProps) {
  const color = severityColor(level);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize",
        className,
      )}
      style={{
        color,
        background: `color-mix(in oklab, ${color} 14%, transparent)`,
      }}
    >
      <span className="size-1.5 rounded-full" style={{ background: color }} />
      {label ?? level}
    </span>
  );
}
