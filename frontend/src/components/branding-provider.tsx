"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { api, type CompanyBranding } from "@/lib/api";

const DEFAULT: CompanyBranding = {
  display_name: "Company Brain",
  accent: "#6b78e8",
  industry: null,
  logo: "CB",
};

const BrandingContext = createContext<CompanyBranding>(DEFAULT);

export const useBranding = () => useContext(BrandingContext);

function hexToRgba(hex: string, alpha: number): string {
  const m = hex.replace("#", "");
  const full = m.length === 3 ? m.split("").map((c) => c + c).join("") : m;
  const n = parseInt(full, 16);
  if (Number.isNaN(n)) return `rgba(107,120,232,${alpha})`;
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Fetches the tenant's Company Profile and tailors the running app to it:
 * injects the company accent into the design tokens (so every glow, gauge, and
 * active state is the company's colour) and exposes the brand name + logo.
 * Falls back to the neutral Company Brain identity until loaded.
 */
export function BrandingProvider({ children }: { children: React.ReactNode }) {
  const [branding, setBranding] = useState<CompanyBranding>(DEFAULT);

  useEffect(() => {
    let cancelled = false;
    api
      .getProfile()
      .then((p) => {
        if (cancelled) return;
        setBranding(p.branding);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--accent-blue", branding.accent);
    root.style.setProperty("--accent-blue-glow", hexToRgba(branding.accent, 0.3));
    root.style.setProperty("--ring", branding.accent);
    return () => {
      root.style.removeProperty("--accent-blue");
      root.style.removeProperty("--accent-blue-glow");
      root.style.removeProperty("--ring");
    };
  }, [branding.accent]);

  return <BrandingContext.Provider value={branding}>{children}</BrandingContext.Provider>;
}
