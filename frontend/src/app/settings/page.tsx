"use client";

import { useEffect, useState } from "react";
import { Building2, CreditCard, Plug, Palette, ShieldCheck } from "lucide-react";
import AnimatedCounter from "@/components/AnimatedCounter";
import { SeverityPill } from "@/components/common/SeverityPill";
import { ThemeToggle } from "@/components/theme-toggle";
import { ProfileEditor } from "@/components/hub/ProfileEditor";
import { api, type TenantSettingsResponse } from "@/lib/api";

const FALLBACK: TenantSettingsResponse = {
  tenant_id: "1a007831-2891-4763-999e-b01c6b76d168",
  name: "Acme Corp",
  slug: "default",
  plan: "enterprise",
  billing: {
    accumulated_cost_usd: 4.82,
    total_input_tokens: 184300,
    total_output_tokens: 38900,
    total_tokens: 223200,
  },
  connected_integrations: ["slack", "notion", "github"],
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<TenantSettingsResponse>(FALLBACK);

  useEffect(() => {
    api.getTenantSettings().then(setSettings).catch(() => {});
  }, []);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ProfileEditor />

      {/* Tenant */}
      <div className="glass-card">
        <div className="mb-4 flex items-center gap-2">
          <Building2 className="size-4 text-[var(--accent-blue)]" />
          <h3 className="text-sm font-semibold text-foreground">Workspace</h3>
          <span className="ml-auto rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold uppercase text-secondary-foreground">
            {settings.plan}
          </span>
        </div>
        <dl className="space-y-3 text-sm">
          <Row label="Organization" value={settings.name} />
          <Row label="Slug" value={settings.slug} mono />
          <Row label="Tenant ID" value={settings.tenant_id} mono />
        </dl>
      </div>

      {/* Billing */}
      <div className="glass-card">
        <div className="mb-4 flex items-center gap-2">
          <CreditCard className="size-4 text-[var(--accent-emerald)]" />
          <h3 className="text-sm font-semibold text-foreground">LLM Usage</h3>
        </div>
        <p className="text-3xl font-semibold tracking-[-0.03em] text-foreground">
          <AnimatedCounter target={settings.billing.accumulated_cost_usd} prefix="$" decimals={2} />
          <span className="ml-1 text-sm font-normal text-muted-foreground">USD</span>
        </p>
        <div className="mt-4 grid grid-cols-2 gap-4">
          <Row label="Input tokens" value={settings.billing.total_input_tokens.toLocaleString()} />
          <Row label="Output tokens" value={settings.billing.total_output_tokens.toLocaleString()} />
        </div>
      </div>

      {/* Integrations */}
      <div className="glass-card lg:col-span-2">
        <div className="mb-4 flex items-center gap-2">
          <Plug className="size-4 text-[var(--accent-blue)]" />
          <h3 className="text-sm font-semibold text-foreground">Integrations</h3>
          <span className="ml-auto text-xs text-muted-foreground">OAuth 2.0</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          {["slack", "notion", "github"].map((id) => {
            const on = settings.connected_integrations.includes(id);
            return (
              <div key={id} className="flex items-center justify-between rounded-xl border border-border bg-card/40 p-3">
                <span className="text-sm font-medium capitalize text-foreground">{id}</span>
                <SeverityPill level={on ? "low" : "unknown"} label={on ? "connected" : "linked"} />
              </div>
            );
          })}
        </div>
      </div>

      {/* Security */}
      <div className="glass-card">
        <div className="mb-4 flex items-center gap-2">
          <ShieldCheck className="size-4 text-[var(--accent-emerald)]" />
          <h3 className="text-sm font-semibold text-foreground">Security</h3>
        </div>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li>• OIDC / JWT auth (RS256 · JWKS cached)</li>
          <li>• RBAC: admin · manager · engineer · viewer</li>
          <li>• Tamper-evident audit chain (SHA-256)</li>
          <li>• PII redaction on ingestion (Presidio)</li>
        </ul>
      </div>

      {/* Appearance */}
      <div className="glass-card">
        <div className="mb-4 flex items-center gap-2">
          <Palette className="size-4 text-[var(--accent-blue)]" />
          <h3 className="text-sm font-semibold text-foreground">Appearance</h3>
        </div>
        <div className="flex items-center justify-between rounded-xl border border-border bg-card/40 p-3">
          <div>
            <p className="text-sm font-medium text-foreground">Theme</p>
            <p className="text-xs text-muted-foreground">Switch between light and dark</p>
          </div>
          <ThemeToggle />
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={mono ? "font-mono text-xs text-foreground" : "text-sm font-medium text-foreground"}>
        {value}
      </dd>
    </div>
  );
}
