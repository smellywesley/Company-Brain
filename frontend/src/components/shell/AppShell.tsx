import type { ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";

/**
 * Application shell: persistent glass Sidebar + sticky Header, with the routed
 * page rendered in the main content area. The sidebar and header persist across
 * navigations (only the page content animates, via app/template.tsx).
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={200}>
      <div className="min-h-screen">
        <Sidebar />
        <div className="flex min-h-screen flex-col lg:pl-64">
          <Header />
          <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            {children}
          </main>
        </div>
      </div>
      <Toaster position="top-right" closeButton />
    </TooltipProvider>
  );
}
