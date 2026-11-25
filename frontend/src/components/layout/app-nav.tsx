"use client";

import {
  Activity,
  BadgeCheck,
  Building2,
  ClipboardList,
  Database,
  FileText,
  Layers,
  LayoutDashboard,
  PenLine,
  ShieldAlert,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react";

import { WorkspaceLink } from "@/components/layout/workspace-link";
import { useActiveRoute } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { cn, isAppAdmin } from "@/lib/utils";
import { useAuthStore } from "@/stores";

export type AppNavLeaf = { label: string; href: string; icon: LucideIcon };
export type AppNavGroup = { label?: string; items: AppNavLeaf[] };

/**
 * One source of truth for workspace navigation. The desktop sidebar, the
 * mobile sheet and the search palette all read this.
 */
export const APP_NAV: AppNavGroup[] = [
  { items: [{ label: "Home", href: ROUTES.DASHBOARD, icon: LayoutDashboard }] },
  {
    label: "Design",
    items: [
      { label: "Course Designer", href: "/outline", icon: FileText },
      { label: "Material Designer", href: "/studio", icon: Layers },
      { label: "Assignment Designer", href: "/assignments", icon: ClipboardList },
    ],
  },
  {
    label: "Assess",
    items: [
      { label: "Grading", href: "/grade", icon: BadgeCheck },
      { label: "Integrity", href: "/integrity", icon: ShieldCheck },
    ],
  },
  { label: "Students", items: [{ label: "Students at risk", href: "/students", icon: Users }] },
  {
    label: "Workspace",
    items: [
      { label: "Workspace", href: ROUTES.ORGS, icon: Building2 },
      { label: "Course files", href: ROUTES.KB, icon: Database },
      { label: "Quality", href: "/quality", icon: Activity },
      { label: "My style", href: "/style", icon: PenLine },
    ],
  },
];

export const APP_NAV_ITEMS: AppNavLeaf[] = APP_NAV.flatMap((group) => group.items);

function linkClass(active: boolean) {
  return cn(
    "flex min-h-[40px] items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
    active
      ? "bg-secondary text-secondary-foreground"
      : "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground",
  );
}

export function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const isActive = useActiveRoute();
  const { user } = useAuthStore();

  return (
    <nav aria-label="Workspace" className="flex-1 space-y-6 p-4">
      {APP_NAV.map((group) => (
        <div key={group.label ?? "home"} className="space-y-1">
          {group.label ? (
            <p className="text-muted-foreground px-3 pb-1 font-mono text-[10px] font-semibold tracking-wider uppercase">
              {group.label}
            </p>
          ) : null}
          {group.items.map((item) => (
            <WorkspaceLink
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              aria-current={isActive(item.href) ? "page" : undefined}
              className={linkClass(isActive(item.href))}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {item.label}
            </WorkspaceLink>
          ))}
        </div>
      ))}
      {isAppAdmin(user) ? (
        <WorkspaceLink
          href={ROUTES.ADMIN}
          onClick={onNavigate}
          aria-current={isActive(ROUTES.ADMIN) ? "page" : undefined}
          className={linkClass(isActive(ROUTES.ADMIN))}
        >
          <ShieldAlert className="h-4 w-4 shrink-0" />
          Admin
        </WorkspaceLink>
      ) : null}
    </nav>
  );
}
