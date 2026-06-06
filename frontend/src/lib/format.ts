/** Small shared formatting + presentation helpers. */

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(1, Math.floor((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function pct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n)}%`;
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export type Severity = "low" | "medium" | "high" | "unknown";

/** CSS variable for a severity/risk level, used for inline styling. */
export function severityColor(level: string | null | undefined): string {
  switch (level) {
    case "high":
      return "var(--accent-rose)";
    case "medium":
      return "var(--accent-amber)";
    case "low":
      return "var(--accent-emerald)";
    default:
      return "var(--muted-foreground)";
  }
}

export function riskLevelFromProbability(p: number): Severity {
  if (p < 0.33) return "low";
  if (p < 0.66) return "medium";
  return "high";
}

export const AUTONOMY_LABELS: Record<number, { label: string; blurb: string }> = {
  0: { label: "L0 · Manual", blurb: "Human runs every step" },
  1: { label: "L1 · Assisted", blurb: "Agent drafts, human approves" },
  2: { label: "L2 · Conditional", blurb: "Auto within guardrails" },
  3: { label: "L3 · High", blurb: "Auto, human on exception" },
  4: { label: "L4 · Full", blurb: "Fully autonomous" },
};
