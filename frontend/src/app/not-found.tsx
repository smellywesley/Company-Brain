import Link from "next/link";
import { Compass, ArrowLeft } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="glass-card max-w-md text-center">
        <span className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-[var(--accent-blue-glow)] text-[var(--accent-blue)]">
          <Compass className="size-7" />
        </span>
        <h1 className="mt-4 text-2xl font-semibold tracking-[-0.02em] text-foreground">
          Lost the thread
        </h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          That page is not part of the brain. Let&apos;s get you back to the Command Center.
        </p>
        <Link
          href="/"
          className="btn-glass mt-5 inline-flex h-10 items-center gap-1.5 rounded-xl px-4 text-sm font-medium text-foreground"
        >
          <ArrowLeft className="size-4" /> Back to Command Center
        </Link>
      </div>
    </div>
  );
}
