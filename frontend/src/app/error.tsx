"use client";

import { useEffect } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface for debugging; a real deployment would forward to an error tracker.
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="glass-card max-w-md text-center">
        <span className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-[var(--accent-rose-glow)] text-[var(--accent-rose)]">
          <AlertTriangle className="size-7" />
        </span>
        <h1 className="mt-4 text-2xl font-semibold tracking-[-0.02em] text-foreground">
          Something broke
        </h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          The view hit an unexpected error. Your data is safe. Try again.
        </p>
        <button
          type="button"
          onClick={reset}
          className="btn-glass mt-5 inline-flex h-10 items-center gap-1.5 rounded-xl px-4 text-sm font-medium text-foreground"
        >
          <RotateCcw className="size-4" /> Try again
        </button>
      </div>
    </div>
  );
}
