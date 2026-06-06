"use client";

import { useEffect, useState } from "react";
import { motion } from "motion/react";
import {
  Activity,
  Workflow,
  ShieldAlert,
  Boxes,
  DollarSign,
  Gauge,
  MessageSquare,
  FileText,
  GitBranch,
  CheckCircle2,
} from "lucide-react";
import {
  api,
  type StatsResponse,
  type ActivityItem,
  type VerdictSummary,
  type CalibrationResponse,
} from "@/lib/api";
import { StatTile } from "@/components/common/StatTile";
import { SeverityPill } from "@/components/common/SeverityPill";
import { CalibrationChart } from "@/components/viz/CalibrationChart";
import { AUTONOMY_LABELS, timeAgo, titleCase } from "@/lib/format";

const FALLBACK_STATS: StatsResponse["stats"] = {
  total_workflow_runs: 9,
  pending_review: 3,
  total_feedback: 6,
  total_skills: 1,
  active_skills: 1,
  accumulated_cost_usd: 4.82,
  total_tokens: 223200,
};

const FALLBACK_ACTIVITY: ActivityItem[] = [
  { id: "a", type: "workflow", title: "Refund automation — completed", description: "Within policy: under $100", timestamp: new Date(Date.now() - 12 * 60000).toISOString() },
  { id: "b", type: "system", title: "Deploy approval — rejected", description: "No staging validation", timestamp: new Date(Date.now() - 38 * 60000).toISOString() },
  { id: "c", type: "workflow", title: "Lead qualification — completed", description: "Matches ICP", timestamp: new Date(Date.now() - 64 * 60000).toISOString() },
];

const FALLBACK_VERDICTS: VerdictSummary[] = [
  { id: "v1", title: "deploy approval · b96613dd", verdict: "rejected", risk_score: 88, risk_level: "high", reasons: [], probability: 79, autonomy_level: 0 },
  { id: "v2", title: "refund automation · d08c0d4e", verdict: "approved", risk_score: 12, risk_level: "low", reasons: [], probability: 24, autonomy_level: 4 },
  { id: "v3", title: "ticket escalation · 34da2b9e", verdict: "needs-review", risk_score: 35, risk_level: "medium", reasons: [], probability: 42, autonomy_level: 2 },
];

const FALLBACK_CAL: CalibrationResponse["calibration"] = {
  curve: [
    { bin_low: 0, bin_high: 0.2, predicted_mid: 0.1, observed: 0.05, count: 2 },
    { bin_low: 0.2, bin_high: 0.4, predicted_mid: 0.3, observed: 0.0, count: 4 },
    { bin_low: 0.4, bin_high: 0.6, predicted_mid: 0.5, observed: 0.5, count: 1 },
    { bin_low: 0.6, bin_high: 0.8, predicted_mid: 0.7, observed: 1.0, count: 2 },
    { bin_low: 0.8, bin_high: 1, predicted_mid: 0.9, observed: 1.0, count: 1 },
  ],
  samples: 10,
  mean_abs_error: 0.08,
};

const INGESTION = [
  { name: "Slack", icon: MessageSquare, status: "Synced", detail: "1,204 messages" },
  { name: "Notion", icon: FileText, status: "Synced", detail: "318 pages" },
  { name: "GitHub", icon: GitBranch, status: "Synced", detail: "92 PRs" },
];

export default function CommandCenter() {
  const [stats, setStats] = useState(FALLBACK_STATS);
  const [activity, setActivity] = useState(FALLBACK_ACTIVITY);
  const [verdicts, setVerdicts] = useState(FALLBACK_VERDICTS);
  const [calibration, setCalibration] = useState(FALLBACK_CAL);

  useEffect(() => {
    api.getStats().then((r) => setStats(r.stats)).catch(() => {});
    api.getActivity(8).then((r) => r.activity.length && setActivity(r.activity)).catch(() => {});
    api.getVerdicts(6).then((r) => r.verdicts.length && setVerdicts(r.verdicts)).catch(() => {});
    api.getCalibration().then((r) => setCalibration(r.calibration)).catch(() => {});
  }, []);

  return (
    <div className="space-y-6">
      {/* Stat row */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatTile label="Workflow runs" value={stats.total_workflow_runs} icon={Workflow} accent="var(--accent-blue)" />
        <StatTile label="Pending review" value={stats.pending_review} icon={ShieldAlert} accent="var(--accent-amber)" hint="needs you" />
        <StatTile label="Active skills" value={stats.active_skills} icon={Boxes} accent="var(--accent-emerald)" />
        <StatTile label="LLM cost" value={stats.accumulated_cost_usd} icon={DollarSign} accent="var(--accent-blue)" prefix="$" decimals={2} />
      </div>

      {/* Bento */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Ingestion health (Loop A) */}
        <motion.div className="glass-card lg:col-span-1" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
          <div className="mb-4 flex items-center gap-2">
            <Activity className="size-4 text-[var(--accent-emerald)]" />
            <h3 className="text-sm font-semibold text-foreground">Ingestion Health</h3>
            <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="live-dot size-1.5 rounded-full bg-[var(--accent-emerald)]" /> Loop A
            </span>
          </div>
          <div className="space-y-2.5">
            {INGESTION.map((s) => {
              const Icon = s.icon;
              return (
                <div key={s.name} className="flex items-center gap-3 rounded-xl border border-border bg-card/40 p-3">
                  <Icon className="size-4 text-muted-foreground" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-foreground">{s.name}</p>
                    <p className="text-xs text-muted-foreground">{s.detail}</p>
                  </div>
                  <span className="flex items-center gap-1 text-xs font-medium text-[var(--accent-emerald)]">
                    <CheckCircle2 className="size-3.5" /> {s.status}
                  </span>
                </div>
              );
            })}
          </div>
        </motion.div>

        {/* Calibration curve — the trust chart */}
        <motion.div className="glass-card lg:col-span-1" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: 0.05 }}>
          <div className="mb-2 flex items-center gap-2">
            <Gauge className="size-4 text-[var(--accent-blue)]" />
            <h3 className="text-sm font-semibold text-foreground">Critic Calibration</h3>
          </div>
          <CalibrationChart curve={calibration.curve} meanAbsError={calibration.mean_abs_error} samples={calibration.samples} size={236} />
        </motion.div>

        {/* Recent autonomous actions (Loop B) */}
        <motion.div className="glass-card lg:col-span-1" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: 0.1 }}>
          <div className="mb-4 flex items-center gap-2">
            <Workflow className="size-4 text-[var(--accent-blue)]" />
            <h3 className="text-sm font-semibold text-foreground">Recent Actions</h3>
            <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="live-dot size-1.5 rounded-full bg-[var(--accent-blue)]" /> Loop B
            </span>
          </div>
          <div className="space-y-3">
            {activity.slice(0, 6).map((a) => (
              <div key={a.id} className="flex gap-3">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-[var(--accent-blue)]" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-foreground">{a.title}</p>
                  <p className="truncate text-xs text-muted-foreground">{a.description} · {timeAgo(a.timestamp)}</p>
                </div>
              </div>
            ))}
          </div>
        </motion.div>

        {/* Critic verdicts with autonomy */}
        <motion.div className="glass-card lg:col-span-3" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: 0.15 }}>
          <div className="mb-4 flex items-center gap-2">
            <ShieldAlert className="size-4 text-[var(--accent-amber)]" />
            <h3 className="text-sm font-semibold text-foreground">Critic Verdicts &amp; Autonomy</h3>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {verdicts.map((v) => (
              <div key={v.id} className="rounded-xl border border-border bg-card/40 p-4">
                <div className="flex items-center justify-between">
                  <span className="truncate text-sm font-medium text-foreground">{titleCase(v.title.split(" · ")[0])}</span>
                  <SeverityPill level={v.risk_level} />
                </div>
                <div className="mt-3 flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">
                    P(neg) <span className="font-semibold text-foreground">{v.probability ?? v.risk_score}%</span>
                  </span>
                  {v.autonomy_level !== undefined && (
                    <span className="rounded-full bg-secondary px-2 py-0.5 font-medium text-secondary-foreground">
                      {AUTONOMY_LABELS[v.autonomy_level]?.label ?? `L${v.autonomy_level}`}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
