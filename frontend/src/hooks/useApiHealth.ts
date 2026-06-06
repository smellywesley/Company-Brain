"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

export type ApiHealth = "checking" | "online" | "offline";

/**
 * Polls the backend /health endpoint so the UI can show a live connection
 * indicator. Falls back to "offline" (the UI then renders demo data).
 */
export function useApiHealth(intervalMs = 20_000): ApiHealth {
  const [status, setStatus] = useState<ApiHealth>("checking");

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 4_000);
        const res = await fetch(`${API_BASE}/health`, {
          signal: controller.signal,
          cache: "no-store",
        });
        clearTimeout(timeout);
        if (!cancelled) setStatus(res.ok ? "online" : "offline");
      } catch {
        if (!cancelled) setStatus("offline");
      }
    };

    check();
    const id = setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return status;
}
