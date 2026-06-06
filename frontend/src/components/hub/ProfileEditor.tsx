"use client";

import { useEffect, useState } from "react";
import { Sparkles, Check } from "lucide-react";
import { toast } from "sonner";
import { api, type CompanyProfile } from "@/lib/api";
import { cn } from "@/lib/utils";

const ACCENTS = ["#6b78e8", "#2563eb", "#0891b2", "#7c3aed", "#0f766e", "#e11d48", "#d97706"];

/** In-place editor for the Company Profile: name, accent, industry, posture. */
export function ProfileEditor() {
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [name, setName] = useState("");
  const [accent, setAccent] = useState(ACCENTS[0]);
  const [posture, setPosture] = useState("balanced");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getProfile()
      .then((p) => {
        setProfile(p);
        setName(p.branding.display_name);
        setAccent(p.branding.accent);
        setPosture(p.risk_posture);
      })
      .catch(() => {});
  }, []);

  // Live-preview the accent on the running app as the user picks.
  useEffect(() => {
    document.documentElement.style.setProperty("--accent-blue", accent);
  }, [accent]);

  const save = async () => {
    setSaving(true);
    try {
      await api.updateProfile({ display_name: name.trim(), accent, risk_posture: posture });
      toast.success("Company profile updated", { description: "Branding + posture applied" });
      setTimeout(() => window.location.reload(), 700);
    } catch {
      toast.error("Could not save — is the backend running?");
      setSaving(false);
    }
  };

  const postures = profile?.catalog.postures ?? [
    { id: "conservative", label: "Conservative", blurb: "" },
    { id: "balanced", label: "Balanced", blurb: "" },
    { id: "aggressive", label: "Aggressive", blurb: "" },
  ];

  return (
    <div className="glass-card lg:col-span-2">
      <div className="mb-4 flex items-center gap-2">
        <Sparkles className="size-4 text-[var(--accent-blue)]" />
        <h3 className="text-sm font-semibold text-foreground">Company Profile</h3>
        <span className="ml-auto text-xs text-muted-foreground">tailors the whole workspace</span>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <label className="text-xs text-muted-foreground">Display name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 h-10 w-full rounded-xl border border-input bg-card/60 px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />

          <label className="mt-4 block text-xs text-muted-foreground">Accent</label>
          <div className="mt-2 flex flex-wrap gap-2">
            {ACCENTS.map((c) => (
              <button
                key={c}
                type="button"
                aria-label={`Accent ${c}`}
                onClick={() => setAccent(c)}
                className={cn(
                  "size-7 rounded-full transition-transform hover:scale-110",
                  accent === c && "ring-2 ring-offset-2 ring-offset-card",
                )}
                style={{ background: c, boxShadow: accent === c ? `0 0 0 2px ${c}` : undefined }}
              />
            ))}
          </div>
        </div>

        <div>
          <label className="text-xs text-muted-foreground">Risk posture</label>
          <div className="mt-1 space-y-2">
            {postures.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setPosture(p.id)}
                className={cn(
                  "flex w-full items-center justify-between rounded-xl border px-3 py-2 text-left text-sm transition-all",
                  posture === p.id
                    ? "border-[var(--accent-blue)] bg-[var(--accent-blue-glow)]"
                    : "border-border bg-card/40 hover:border-[var(--accent-blue)]/50",
                )}
              >
                <span className="font-medium text-foreground">{p.label}</span>
                {posture === p.id && <Check className="size-4 text-[var(--accent-blue)]" />}
              </button>
            ))}
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={save}
        disabled={saving}
        className="btn-glass btn-tint-emerald mt-5 flex h-10 items-center gap-1.5 rounded-xl px-5 text-sm font-semibold disabled:opacity-50"
      >
        <Check className="size-4" /> {saving ? "Saving…" : "Save profile"}
      </button>
    </div>
  );
}
