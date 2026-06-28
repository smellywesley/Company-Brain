"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { ServiceWorkerRegister } from "@/components/ServiceWorkerRegister";

// Routes that render full-bleed (no dashboard chrome) — e.g. the marketing
// landing page. Everything else keeps the persistent Sidebar + Header.
const FULL_BLEED_PREFIXES = ["/welcome"];

/**
 * Application shell: persistent glass Sidebar + sticky Header, with the routed
 * page rendered in the main content area. Marketing routes (FULL_BLEED_PREFIXES)
 * skip the chrome so the landing page can own the whole viewport.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "/";
  const fullBleed = FULL_BLEED_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );

  return (
    <TooltipProvider delayDuration={200}>
      {fullBleed ? (
        <div className="min-h-screen">{children}</div>
      ) : (
        <div className="min-h-screen">
          <Sidebar />
          <div className="flex min-h-screen flex-col lg:pl-64">
            <Header />
            <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
              {children}
            </main>
          </div>
        </div>
      )}
      <Toaster position="top-right" closeButton />
      <ServiceWorkerRegister />
    </TooltipProvider>
  );
}
