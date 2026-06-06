"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "motion/react";
import { Brain } from "lucide-react";
import { cn } from "@/lib/utils";
import { useBranding } from "@/components/branding-provider";
import { NAV_GROUPS, findNavItem } from "./nav";

interface SidebarNavProps {
  /** Called after a nav item is clicked — used to close the mobile sheet. */
  onNavigate?: () => void;
}

/** The navigation content, shared by the desktop sidebar and the mobile sheet. */
export function SidebarNav({ onNavigate }: SidebarNavProps) {
  const pathname = usePathname();
  const active = findNavItem(pathname);
  const branding = useBranding();

  return (
    <nav className="flex h-full flex-col gap-7 px-3 py-5">
      {/* Brand */}
      <Link
        href="/"
        onClick={onNavigate}
        className="flex items-center gap-2.5 px-3 py-1"
      >
        <span
          className="flex size-9 items-center justify-center rounded-xl text-white shadow-[var(--shadow-md)]"
          style={{
            background: "var(--accent-blue)",
            boxShadow: "0 6px 20px var(--accent-blue-glow), var(--glass-sheen)",
          }}
        >
          <Brain className="size-5" />
        </span>
        <span className="flex flex-col leading-tight">
          <span className="truncate text-[15px] font-semibold tracking-[-0.02em] text-foreground">
            {branding.display_name}
          </span>
          <span className="text-[11px] font-medium text-muted-foreground">
            Autonomous Operations
          </span>
        </span>
      </Link>

      <div className="flex flex-1 flex-col gap-6">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="flex flex-col gap-1">
            <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/70">
              {group.label}
            </p>
            {group.items.map((item) => {
              const isActive = active?.href === item.href;
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                    isActive
                      ? "text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {isActive && (
                    <motion.span
                      layoutId="sidebar-active"
                      transition={{ type: "spring", stiffness: 400, damping: 32 }}
                      className="absolute inset-0 -z-10 rounded-xl border border-sidebar-border bg-sidebar-accent"
                    />
                  )}
                  <Icon
                    className={cn(
                      "size-[18px] shrink-0 transition-transform group-hover:scale-110",
                      isActive && "text-[var(--accent-blue)]",
                    )}
                  />
                  {item.label}
                </Link>
              );
            })}
          </div>
        ))}
      </div>

      {/* Footer / system status */}
      <div className="rounded-xl border border-sidebar-border bg-sidebar-accent/50 px-3 py-3">
        <div className="flex items-center gap-2">
          <span className="live-dot size-2 rounded-full bg-[var(--accent-emerald)]" />
          <span className="text-xs font-medium text-foreground">
            Two loops running
          </span>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Ingestion + Action active. Critic vetoes route here.
        </p>
      </div>
    </nav>
  );
}

/** Desktop sidebar: fixed, glassy rail. Hidden below lg (mobile uses a sheet). */
export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-sidebar-border bg-sidebar backdrop-blur-xl lg:block">
      <SidebarNav />
    </aside>
  );
}
