"use client";

/**
 * Knowledge Reconciliation — the human tier of the Contradiction Handshake.
 *
 * Lists skills quarantined because a merged PR contradicts their SOP.
 * Evidence leads (PR ref, conflict summary, severity); actions come second:
 * Dismiss (false positive — releases the lock) or Accept (synthesis applied).
 * See docs/TIER4_RECONCILIATION_DESIGN.md for the full design decisions.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertOctagon,
  AlertTriangle,
  CircleAlert,
  Info,
  CheckCircle2,
  CloudOff,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { api, type QuarantineEntry } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

// Text label + icon per severity — never color alone (a11y decision, spec §5).
const SEVERITY_BADGE: Record<string, { icon: LucideIcon; className: string }> = {
  critical: { icon: AlertOctagon, className: "border-red-500/40 bg-red-500/10 text-red-400" },
  high: { icon: AlertTriangle, className: "border-orange-500/40 bg-orange-500/10 text-orange-400" },
  medium: { icon: CircleAlert, className: "border-amber-500/40 bg-amber-500/10 text-amber-300" },
  low: { icon: Info, className: "border-sky-500/40 bg-sky-500/10 text-sky-300" },
};

function SeverityBadge({ severity }: { severity: string }) {
  const { icon: Icon, className } = SEVERITY_BADGE[severity] ?? SEVERITY_BADGE.medium;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium uppercase tracking-wide ${className}`}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {severity}
    </span>
  );
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "";
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function ReconciliationPage() {
  const [entries, setEntries] = useState<QuarantineEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [unreachable, setUnreachable] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [pending, setPending] = useState<
    { entry: QuarantineEntry; resolution: "dismiss" | "accept" } | null
  >(null);
  const [reason, setReason] = useState("");

  const load = useCallback(() => {
    api
      .getQuarantines()
      .then((res) => {
        const sorted = [...res.quarantines].sort(
          (a, b) =>
            (SEVERITY_ORDER[a.lock.severity] ?? 9) - (SEVERITY_ORDER[b.lock.severity] ?? 9) ||
            a.lock.locked_at.localeCompare(b.lock.locked_at),
        );
        setEntries(sorted);
        setUnreachable(false);
      })
      .catch(() => setUnreachable(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const confirmResolve = useCallback(async () => {
    if (!pending) return;
    const { entry, resolution } = pending;
    setBusy(entry.skill_id);
    try {
      await api.releaseQuarantine(entry.skill_id, resolution, reason.trim());
      setEntries((prev) => prev.filter((e) => e.skill_id !== entry.skill_id));
      toast.success(
        resolution === "dismiss"
          ? `Dismissed — "${entry.skill_name}" is unblocked.`
          : `Synthesis accepted — "${entry.skill_name}" is unblocked.`,
      );
      setPending(null);
    } catch (err) {
      toast.error(`Could not release the lock: ${err instanceof Error ? err.message : "unknown error"}`);
    } finally {
      setBusy(null);
    }
  }, [pending, reason]);

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Knowledge Reconciliation</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Merged PRs that contradict an active operating procedure. Each quarantined
          skill is blocked from autonomous action until you resolve the conflict.
        </p>
      </header>

      {/* Never imply "no conflicts" when status is simply unknown (spec §4). */}
      {unreachable && (
        <div
          role="alert"
          className="flex items-center gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-300"
        >
          <CloudOff className="h-5 w-5 shrink-0" aria-hidden />
          Conflict status temporarily unavailable — the backend could not be reached.
          Quarantines may still be active.
        </div>
      )}

      {loading ? (
        <div className="space-y-2" aria-busy>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-lg border border-border/40 bg-muted/20" />
          ))}
        </div>
      ) : !unreachable && entries.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-border/40 py-16 text-center">
          <CheckCircle2 className="h-10 w-10 text-emerald-400" aria-hidden />
          <p className="font-medium">No active conflicts. Knowledge is in sync.</p>
          <p className="text-sm text-muted-foreground">
            When a merged PR contradicts a procedure, it appears here for review.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-border/40 rounded-lg border border-border/40">
          {entries.map((entry) => (
            <li key={entry.skill_id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start">
              {/* Evidence first (spec §3.1): what fired, from where, how bad. */}
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={entry.lock.severity} />
                  <span className="font-medium">{entry.skill_name}</span>
                  <span className="text-xs text-muted-foreground">
                    {entry.lock.pr_ref}
                    {entry.lock.locked_at ? ` · ${timeAgo(entry.lock.locked_at)}` : ""}
                    {entry.lock.ttl_seconds === null ? " · permanent until resolved" : " · auto-releases in 24h if unreviewed"}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground">{entry.lock.summary}</p>
              </div>

              <div className="flex shrink-0 gap-2">
                <button
                  onClick={() => {
                    setReason("");
                    setPending({ entry, resolution: "dismiss" });
                  }}
                  disabled={busy === entry.skill_id}
                  className="inline-flex h-11 items-center justify-center rounded-md border border-border px-4 text-sm hover:bg-muted/40 disabled:opacity-50"
                >
                  Dismiss
                </button>
                <button
                  onClick={() => {
                    setReason("");
                    setPending({ entry, resolution: "accept" });
                  }}
                  disabled={busy === entry.skill_id}
                  className="inline-flex h-11 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                >
                  Accept synthesis
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={pending !== null}
        onOpenChange={(o) => {
          if (!o) setPending(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {pending?.resolution === "dismiss" ? "Dismiss as false positive" : "Accept synthesis"}
            </DialogTitle>
            <DialogDescription>
              {pending?.resolution === "dismiss"
                ? "Releases the lock and records this as a false positive."
                : "Applies the synthesized resolution and releases the lock."}{" "}
              Add an optional reason for the audit log.
            </DialogDescription>
          </DialogHeader>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            maxLength={2000}
            autoFocus
            placeholder="Optional reason (recorded in the audit trail)…"
            className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-blue)]"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setPending(null)} disabled={busy !== null}>
              Cancel
            </Button>
            <Button onClick={confirmResolve} disabled={busy !== null}>
              {pending?.resolution === "dismiss" ? "Dismiss" : "Accept synthesis"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
