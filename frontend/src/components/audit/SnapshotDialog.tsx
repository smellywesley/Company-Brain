"use client";

import { useEffect, useState } from "react";
import { History, FileText, Network, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, type AuditSnapshot } from "@/lib/api";
import { titleCase } from "@/lib/format";

interface SnapshotDialogProps {
  runId: string | null;
  workflowName: string;
  digest: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Time-Travel state viewer: rewinds to exactly what the brain knew at the
 * decision instant (retrieved sources + memory-graph facts), proven by the
 * content-addressed digest carried in the audit chain.
 */
export function SnapshotDialog({
  runId,
  workflowName,
  digest,
  open,
  onOpenChange,
}: SnapshotDialogProps) {
  const [snapshot, setSnapshot] = useState<AuditSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchedDigest, setFetchedDigest] = useState(digest);

  useEffect(() => {
    if (!open || !runId || runId.startsWith("fallback")) return;
    let cancelled = false;
    // State changes live inside the async loader (not the effect body) so the
    // spinner toggles as part of the fetch lifecycle, not a synchronous render.
    const load = async () => {
      setLoading(true);
      try {
        const res = await api.getAuditSnapshot(runId);
        if (cancelled) return;
        setSnapshot(res.snapshot);
        setFetchedDigest(res.digest);
      } catch {
        // network failure leaves the existing digest; dialog still renders
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [open, runId]);

  const sources = snapshot?.context_used?.sources ?? [];
  const facts = snapshot?.context_used?.graph_facts ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="size-4 text-[var(--accent-blue)]" />
            Time-Travel · {titleCase(workflowName)}
          </DialogTitle>
          <DialogDescription>
            The exact enterprise-memory state at the millisecond this decision was made.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Rewinding state…
          </div>
        ) : (
          <div className="space-y-5">
            <div>
              <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                <FileText className="size-3.5" /> Retrieved sources
              </p>
              <ul className="mt-2 space-y-2">
                {sources.length ? (
                  sources.map((s, i) => (
                    <li key={i} className="rounded-xl border border-border bg-card/50 p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-foreground">{s.title}</span>
                        <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium uppercase text-secondary-foreground">
                          {s.source}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{s.snippet}</p>
                    </li>
                  ))
                ) : (
                  <li className="text-sm text-muted-foreground">No sources recorded.</li>
                )}
              </ul>
            </div>

            {facts.length > 0 && (
              <div>
                <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                  <Network className="size-3.5" /> Memory-graph facts
                </p>
                <ul className="mt-2 space-y-1">
                  {facts.map((f, i) => (
                    <li
                      key={i}
                      className="rounded-lg bg-secondary/60 px-3 py-1.5 font-mono text-xs text-secondary-foreground"
                    >
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="rounded-xl border border-border bg-card/50 p-3">
              <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Snapshot digest (content-addressed)
              </p>
              <p className="mt-1 break-all font-mono text-xs text-[var(--accent-blue)]">
                {fetchedDigest}
              </p>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
