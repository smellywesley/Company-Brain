"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { ThemeToggle } from "@/components/theme-toggle";
import { SidebarNav } from "./Sidebar";
import { findNavItem } from "./nav";
import { useApiHealth } from "@/hooks/useApiHealth";

const STATUS_COPY: Record<string, { label: string; dot: string; text: string }> = {
  checking: { label: "Connecting", dot: "bg-[var(--accent-amber)]", text: "text-muted-foreground" },
  online: { label: "API Connected", dot: "bg-[var(--accent-emerald)]", text: "text-foreground" },
  offline: { label: "Demo Mode", dot: "bg-[var(--accent-amber)]", text: "text-muted-foreground" },
};

export function Header() {
  const pathname = usePathname();
  const item = findNavItem(pathname);
  const status = useApiHealth();
  const [open, setOpen] = useState(false);

  const title = item?.label ?? "Company Brain";
  const subtitle = item?.description ?? "";
  const s = STATUS_COPY[status];

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/70 backdrop-blur-xl">
      <div className="flex items-center gap-3 px-4 py-3 sm:px-6 lg:px-8">
        {/* Mobile menu */}
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="rounded-full lg:hidden"
              aria-label="Open navigation"
            >
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 border-sidebar-border bg-sidebar p-0">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <SidebarNav onNavigate={() => setOpen(false)} />
          </SheetContent>
        </Sheet>

        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold tracking-[-0.02em] text-foreground sm:text-xl">
            {title}
          </h1>
          {subtitle && (
            <p className="hidden truncate text-sm text-muted-foreground sm:block">
              {subtitle}
            </p>
          )}
        </div>

        {/* Live status */}
        <div className="flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5">
          <span className={cn("size-2 rounded-full", s.dot, status === "online" && "live-dot")} />
          <span className={cn("text-xs font-medium", s.text)}>{s.label}</span>
        </div>

        <ThemeToggle />
      </div>
    </header>
  );
}
