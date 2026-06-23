export const metadata = { title: "Offline · Company Brain" };

export default function OfflinePage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-24 text-center">
      <h1 className="text-xl font-semibold text-foreground">You&apos;re offline</h1>
      <p className="text-sm text-muted-foreground">
        Company Brain can&apos;t reach the network right now. Reconnect and try
        again — your last view is cached.
      </p>
    </div>
  );
}
