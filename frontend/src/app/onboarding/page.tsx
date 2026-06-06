"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Building2,
  Landmark,
  HeartPulse,
  ShoppingBag,
  Boxes,
  Shield,
  Scale,
  Rocket,
  ArrowRight,
  ArrowLeft,
  Check,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const INDUSTRIES: { id: string; label: string; icon: LucideIcon; blurb: string }[] = [
  { id: "fintech", label: "Fintech / Payments", icon: Landmark, blurb: "SOC 2 / PCI invariants, dual-control on funds" },
  { id: "healthcare", label: "Healthcare", icon: HeartPulse, blurb: "PHI protection, clinician sign-off, HIPAA" },
  { id: "ecommerce", label: "E-commerce", icon: ShoppingBag, blurb: "Auto-refunds in policy, chargeback guards" },
  { id: "saas", label: "B2B SaaS", icon: Boxes, blurb: "Retention, deploy safety, SLA escalation" },
];

const POSTURES: { id: string; label: string; icon: LucideIcon; blurb: string }[] = [
  { id: "conservative", label: "Conservative", icon: Shield, blurb: "Hold almost everything for a human" },
  { id: "balanced", label: "Balanced", icon: Scale, blurb: "Auto within guardrails, humans on the edge" },
  { id: "aggressive", label: "Aggressive", icon: Rocket, blurb: "Maximise autonomy, escalate clear danger" },
];

const SUGGESTED: Record<string, string> = {
  fintech: "conservative",
  healthcare: "conservative",
  ecommerce: "aggressive",
  saas: "balanced",
};

export default function OnboardingPage() {
  const router = useRouter();
  const reduce = useReducedMotion();
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [posture, setPosture] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Default the posture to the industry's suggestion when industry changes.
  useEffect(() => {
    if (industry && !posture) setPosture(SUGGESTED[industry] ?? "balanced");
  }, [industry, posture]);

  const canNext = (step === 0 && name.trim()) || (step === 1 && industry) || (step === 2 && posture);

  const finish = async () => {
    setSubmitting(true);
    try {
      const res = await api.onboard({ company_name: name.trim(), industry, risk_posture: posture });
      toast.success(`${res.branding.display_name} is live`, {
        description: `${res.rules_seeded} policy invariants seeded · ${res.risk_posture} posture`,
      });
      // Full reload so the BrandingProvider picks up the new accent + name.
      window.location.href = "/";
    } catch {
      toast.error("Could not complete onboarding — is the backend running?");
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-2xl flex-col justify-center">
      {/* Progress */}
      <div className="mb-6 flex items-center gap-2">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-1 flex-1 rounded-full transition-colors"
            style={{ background: i <= step ? "var(--accent-blue)" : "var(--border)" }}
          />
        ))}
      </div>

      <div className="glass-card min-h-[340px]">
        <AnimatePresence mode="wait" custom={step}>
          <motion.div
            key={step}
            initial={reduce ? false : { opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, x: -24 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          >
            {step === 0 && (
              <div>
                <span className="flex size-12 items-center justify-center rounded-2xl bg-[var(--accent-blue-glow)] text-[var(--accent-blue)]">
                  <Building2 className="size-6" />
                </span>
                <h1 className="mt-4 text-2xl font-semibold tracking-[-0.02em] text-foreground">
                  Name your brain
                </h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  This is the company the brain works for. It brands the whole workspace.
                </p>
                <input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && canNext && setStep(1)}
                  placeholder="Acme Corp"
                  className="mt-5 h-12 w-full rounded-xl border border-input bg-card/60 px-4 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
            )}

            {step === 1 && (
              <div>
                <h1 className="text-2xl font-semibold tracking-[-0.02em] text-foreground">
                  Pick your industry
                </h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  We seed a starter policy pack so the critic is smart on day one.
                </p>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  {INDUSTRIES.map((it) => {
                    const Icon = it.icon;
                    const on = industry === it.id;
                    return (
                      <button
                        key={it.id}
                        type="button"
                        onClick={() => setIndustry(it.id)}
                        className={cn(
                          "flex items-start gap-3 rounded-xl border p-3 text-left transition-all",
                          on ? "border-[var(--accent-blue)] bg-[var(--accent-blue-glow)]" : "border-border bg-card/40 hover:border-[var(--accent-blue)]/50",
                        )}
                      >
                        <Icon className="mt-0.5 size-5 shrink-0 text-[var(--accent-blue)]" />
                        <span>
                          <span className="block text-sm font-semibold text-foreground">{it.label}</span>
                          <span className="block text-xs text-muted-foreground">{it.blurb}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {step === 2 && (
              <div>
                <h1 className="text-2xl font-semibold tracking-[-0.02em] text-foreground">
                  Set your risk posture
                </h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  This tunes the routing threshold and how much the agent may do unattended.
                </p>
                <div className="mt-5 space-y-3">
                  {POSTURES.map((it) => {
                    const Icon = it.icon;
                    const on = posture === it.id;
                    return (
                      <button
                        key={it.id}
                        type="button"
                        onClick={() => setPosture(it.id)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-all",
                          on ? "border-[var(--accent-blue)] bg-[var(--accent-blue-glow)]" : "border-border bg-card/40 hover:border-[var(--accent-blue)]/50",
                        )}
                      >
                        <Icon className="size-5 shrink-0 text-[var(--accent-blue)]" />
                        <span className="flex-1">
                          <span className="block text-sm font-semibold text-foreground">{it.label}</span>
                          <span className="block text-xs text-muted-foreground">{it.blurb}</span>
                        </span>
                        {it.id === SUGGESTED[industry] && (
                          <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
                            suggested
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Nav */}
      <div className="mt-5 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0}
          className="btn-glass flex h-10 items-center gap-1.5 rounded-xl px-4 text-sm font-medium text-muted-foreground disabled:opacity-40"
        >
          <ArrowLeft className="size-4" /> Back
        </button>
        {step < 2 ? (
          <button
            type="button"
            onClick={() => canNext && setStep((s) => s + 1)}
            disabled={!canNext}
            className="btn-glass btn-tint-emerald flex h-10 items-center gap-1.5 rounded-xl px-5 text-sm font-semibold disabled:opacity-40"
          >
            Continue <ArrowRight className="size-4" />
          </button>
        ) : (
          <button
            type="button"
            onClick={finish}
            disabled={!canNext || submitting}
            className="btn-glass btn-tint-emerald flex h-10 items-center gap-1.5 rounded-xl px-5 text-sm font-semibold disabled:opacity-50"
          >
            <Check className="size-4" /> {submitting ? "Tailoring…" : "Launch brain"}
          </button>
        )}
      </div>
    </div>
  );
}
