"use client";

import { useEffect, useState } from "react";
import { MessageSquare, FileText, GitBranch, Boxes, Plug, ScrollText, type LucideIcon } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { SeverityPill } from "@/components/common/SeverityPill";
import { PolicyTimeline } from "@/components/hub/PolicyTimeline";
import { api, type SkillSummary, type PolicyRule } from "@/lib/api";
import { titleCase } from "@/lib/format";

const CONNECTORS: { id: string; name: string; icon: LucideIcon; detail: string }[] = [
  { id: "slack", name: "Slack", icon: MessageSquare, detail: "Channels, threads, DMs" },
  { id: "notion", name: "Notion", icon: FileText, detail: "Pages, databases, wikis" },
  { id: "github", name: "GitHub", icon: GitBranch, detail: "PRs, issues, READMEs" },
];

const FALLBACK_SKILLS: SkillSummary[] = [
  {
    id: "s1",
    name: "Refund Processing",
    slug: "refund-processing",
    version: 3,
    status: "active",
    risk_level: "medium",
    confidence_score: 0.87,
    created_by: "feedback-loop",
    updated_at: new Date().toISOString(),
  },
];

const FALLBACK_POLICY: PolicyRule[] = [
  { rule: "Reject any subscription refund if the purchase date is > 30 days ago.", source: "human_feedback", created_at: new Date(Date.now() - 21 * 864e5).toISOString(), feedback_count: 3 },
  { rule: "Require director sign-off for retention discounts above 15%.", source: "human_feedback", created_at: new Date(Date.now() - 12 * 864e5).toISOString(), feedback_count: 2 },
  { rule: "Never deploy to production without a recorded staging validation run.", source: "human_feedback", created_at: new Date(Date.now() - 5 * 864e5).toISOString(), feedback_count: 4 },
  { rule: "Block any refund whose amount exceeds the original captured charge.", source: "human_feedback", created_at: new Date(Date.now() - 2 * 864e5).toISOString(), feedback_count: 1 },
];

export default function HubPage() {
  const [connected, setConnected] = useState<string[]>(["slack", "notion", "github"]);
  const [skills, setSkills] = useState<SkillSummary[]>(FALLBACK_SKILLS);
  const [policy, setPolicy] = useState<PolicyRule[]>(FALLBACK_POLICY);

  useEffect(() => {
    api.getTenantSettings().then((r) => setConnected(r.connected_integrations)).catch(() => {});
    api.getSkills().then((r) => r.skills.length && setSkills(r.skills)).catch(() => {});
    api.getPolicyHistory().then((r) => r.policy_history.length && setPolicy(r.policy_history)).catch(() => {});
  }, []);

  return (
    <Tabs defaultValue="connectors" className="space-y-6">
      <TabsList className="bg-card/60">
        <TabsTrigger value="connectors" className="gap-1.5">
          <Plug className="size-3.5" /> Connectors
        </TabsTrigger>
        <TabsTrigger value="skills" className="gap-1.5">
          <Boxes className="size-3.5" /> Skills (SOPs)
        </TabsTrigger>
        <TabsTrigger value="policy" className="gap-1.5">
          <ScrollText className="size-3.5" /> Policy Evolution
        </TabsTrigger>
      </TabsList>

      {/* Connectors */}
      <TabsContent value="connectors" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {CONNECTORS.map((c) => {
          const Icon = c.icon;
          const isOn = connected.includes(c.id);
          return (
            <div key={c.id} className="glass-card glass-card-hover">
              <div className="flex items-start justify-between">
                <span className="flex size-10 items-center justify-center rounded-xl bg-secondary text-foreground">
                  <Icon className="size-5" />
                </span>
                <Switch checked={isOn} aria-label={`Toggle ${c.name}`} />
              </div>
              <h3 className="mt-3 text-base font-semibold text-foreground">{c.name}</h3>
              <p className="text-sm text-muted-foreground">{c.detail}</p>
              <p className="mt-3 text-xs font-medium" style={{ color: isOn ? "var(--accent-emerald)" : "var(--muted-foreground)" }}>
                {isOn ? "● Connected · syncing" : "○ Not connected"}
              </p>
            </div>
          );
        })}
      </TabsContent>

      {/* Skills */}
      <TabsContent value="skills" className="grid gap-4 sm:grid-cols-2">
        {skills.map((s) => (
          <div key={s.id} className="glass-card">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-base font-semibold text-foreground">{titleCase(s.name)}</h3>
                <p className="text-xs text-muted-foreground">
                  v{s.version} · authored by {s.created_by.replace(/_/g, " ")}
                </p>
              </div>
              <SeverityPill level={s.status === "active" ? "low" : "unknown"} label={s.status} />
            </div>
            <div className="mt-4">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Confidence</span>
                <span className="font-semibold text-foreground">{Math.round(s.confidence_score * 100)}%</span>
              </div>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-[var(--accent-emerald)]"
                  style={{ width: `${s.confidence_score * 100}%` }}
                />
              </div>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <SeverityPill level={s.risk_level} label={`${s.risk_level} risk`} />
              <span className="text-xs text-muted-foreground">self-writing SOP</span>
            </div>
          </div>
        ))}
      </TabsContent>

      {/* Policy evolution */}
      <TabsContent value="policy">
        <div className="glass-card">
          <div className="mb-4">
            <h3 className="text-base font-semibold text-foreground">Policy Evolution</h3>
            <p className="text-sm text-muted-foreground">
              Your company&apos;s constitution, version-controlled. Each invariant was
              learned from a human correction and is now permanently enforced by the
              CriticAgent.
            </p>
          </div>
          <PolicyTimeline history={policy} />
        </div>
      </TabsContent>
    </Tabs>
  );
}
