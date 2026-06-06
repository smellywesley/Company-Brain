import {
  LayoutDashboard,
  ShieldCheck,
  ScrollText,
  Boxes,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Short description used for tooltips / page subtitles. */
  description: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Platform",
    items: [
      {
        label: "Command Center",
        href: "/",
        icon: LayoutDashboard,
        description:
          "Real-time ingestion health and a live feed of autonomous actions.",
      },
      {
        label: "Approval Queue",
        href: "/approvals",
        icon: ShieldCheck,
        description:
          "Review actions the CriticAgent flagged before they execute.",
      },
      {
        label: "Audit Log",
        href: "/audit",
        icon: ScrollText,
        description:
          "Cryptographically chained record of every retrieve → act decision.",
      },
      {
        label: "Skills & Connectors",
        href: "/hub",
        icon: Boxes,
        description:
          "Manage data connectors and the self-writing operating procedures.",
      },
    ],
  },
  {
    label: "System",
    items: [
      {
        label: "Settings",
        href: "/settings",
        icon: Settings,
        description: "Workspace, security, and model configuration.",
      },
    ],
  },
];

/** Flattened lookup for resolving the active item / page title from a path. */
export const ALL_NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

export function findNavItem(pathname: string): NavItem | undefined {
  // Exact match first, then the longest prefix match (so nested routes resolve).
  const exact = ALL_NAV_ITEMS.find((i) => i.href === pathname);
  if (exact) return exact;
  return ALL_NAV_ITEMS.filter((i) => i.href !== "/" && pathname.startsWith(i.href)).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];
}
