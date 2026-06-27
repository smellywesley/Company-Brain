"use client";

/**
 * Connectors — where a user links the tools Company Brain reads from and acts on.
 *
 * Three groups: knowledge sources, action providers, and support. OAuth providers
 * use a full-page redirect to the backend (NOT fetch — the backend 302s to the
 * provider and back to ?status=success&source=). Zendesk takes a manual token
 * via POST /integrations/zendesk/credentials, which any provider can fall back to.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Hash,
  FileText,
  GitBranch,
  Calendar,
  Building2,
  Calculator,
  LifeBuoy,
  CheckCircle2,
  CloudOff,
  Loader2,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

interface Provider {
  id: string;
  name: string;
  blurb: string;
  icon: LucideIcon;
  oauth: boolean; // OAuth redirect flow vs. manual credential form
}

const GROUPS: { label: string; providers: Provider[] }[] = [
  {
    label: "Knowledge sources",
    providers: [
      { id: "slack", name: "Slack", blurb: "Messages & channels", icon: Hash, oauth: true },
      { id: "notion", name: "Notion", blurb: "Docs & wikis", icon: FileText, oauth: true },
      { id: "github", name: "GitHub", blurb: "Repos & pull requests", icon: GitBranch, oauth: true },
    ],
  },
  {
    label: "Action providers",
    providers: [
      { id: "google", name: "Google Calendar", blurb: "Scheduling", icon: Calendar, oauth: true },
      { id: "hubspot", name: "HubSpot", blurb: "CRM", icon: Building2, oauth: true },
      { id: "quickbooks", name: "QuickBooks", blurb: "Accounting", icon: Calculator, oauth: true },
    ],
  },
  {
    label: "Support",
    providers: [
      { id: "zendesk", name: "Zendesk", blurb: "Tickets & helpdesk", icon: LifeBuoy, oauth: false },
    ],
  },
];

function ConnectedBadge({ connected }: { connected: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
        connected
          ? "bg-[color-mix(in_oklab,var(--accent-emerald)_14%,transparent)] text-[var(--accent-emerald)]"
          : "bg-secondary text-muted-foreground"
      }`}
    >
      {connected && <CheckCircle2 className="size-3" aria-hidden />}
      {connected ? "Connected" : "Not connected"}
    </span>
  );
}

/** Inline subdomain/email/api_token form for Zendesk (manual credentials). */
function ZendeskForm({ onSaved }: { onSaved: () => void }) {
  const [fields, setFields] = useState({ subdomain: "", email: "", api_token: "" });
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.saveCredentials("zendesk", fields);
      toast.success("Zendesk connected.");
      onSaved();
    } catch (err) {
      toast.error(`Could not save credentials: ${err instanceof Error ? err.message : "unknown error"}`);
    } finally {
      setSaving(false);
    }
  };

  const input =
    "w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-blue)]";

  return (
    <form onSubmit={submit} className="mt-4 space-y-2">
      <input
        required
        value={fields.subdomain}
        onChange={(e) => setFields((f) => ({ ...f, subdomain: e.target.value }))}
        placeholder="subdomain"
        aria-label="Zendesk subdomain"
        className={input}
      />
      <input
        required
        type="email"
        value={fields.email}
        onChange={(e) => setFields((f) => ({ ...f, email: e.target.value }))}
        placeholder="email"
        aria-label="Zendesk email"
        className={input}
      />
      <input
        required
        type="password"
        value={fields.api_token}
        onChange={(e) => setFields((f) => ({ ...f, api_token: e.target.value }))}
        placeholder="api_token"
        aria-label="Zendesk API token"
        className={input}
      />
      <Button type="submit" size="lg" className="w-full" disabled={saving}>
        {saving && <Loader2 className="size-4 animate-spin" aria-hidden />}
        Save credentials
      </Button>
    </form>
  );
}

function ProviderCard({
  provider,
  connected,
  onSaved,
}: {
  provider: Provider;
  connected: boolean;
  onSaved: () => void;
}) {
  const Icon = provider.icon;
  return (
    <div className="glass-card flex flex-col">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-border bg-card/40 text-[var(--accent-blue)]">
          <Icon className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground">{provider.name}</p>
          <p className="text-xs text-muted-foreground">{provider.blurb}</p>
        </div>
        <ConnectedBadge connected={connected} />
      </div>

      {provider.oauth ? (
        <Button
          asChild={!connected}
          variant={connected ? "outline" : "default"}
          size="lg"
          className="mt-4 w-full"
          disabled={connected}
        >
          {connected ? (
            <span>Connected</span>
          ) : (
            // Full-page navigation: the backend 302-redirects to the provider.
            <a href={`${api.oauthBase}/oauth/connect/${provider.id}`}>Connect</a>
          )}
        </Button>
      ) : connected ? (
        <Button variant="outline" size="lg" className="mt-4 w-full" disabled>
          Connected
        </Button>
      ) : (
        <ZendeskForm onSaved={onSaved} />
      )}
    </div>
  );
}

function ConnectorsContent() {
  const [connected, setConnected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [unreachable, setUnreachable] = useState(false);
  const params = useSearchParams();

  const load = useCallback(() => {
    api
      .getIntegrations()
      .then((res) => {
        setConnected(res.connected);
        setUnreachable(false);
      })
      .catch(() => setUnreachable(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Surface the OAuth round-trip result (?status=success&source=slack).
  useEffect(() => {
    if (params.get("status") === "success") {
      const source = params.get("source");
      toast.success(source ? `${source} connected.` : "Connected.");
      load();
    }
  }, [params, load]);

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header>
        <h1 className="text-2xl font-semibold">Connectors</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect the tools Company Brain reads from and acts on. Each one stays
          listed here so you can see what is linked at a glance.
        </p>
      </header>

      {unreachable && (
        <div
          role="alert"
          className="flex items-center gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-300"
        >
          <CloudOff className="h-5 w-5 shrink-0" aria-hidden />
          Connection status temporarily unavailable — the backend could not be reached.
        </div>
      )}

      {GROUPS.map((group) => (
        <section key={group.label} className="space-y-3">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/70">
            {group.label}
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {group.providers.map((p) => (
              <ProviderCard
                key={p.id}
                provider={p}
                connected={!loading && connected.includes(p.id)}
                onSaved={load}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export default function ConnectorsPage() {
  // useSearchParams requires a Suspense boundary in the App Router.
  return (
    <Suspense>
      <ConnectorsContent />
    </Suspense>
  );
}
