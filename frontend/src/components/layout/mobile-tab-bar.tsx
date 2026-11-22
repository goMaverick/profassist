"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BookOpen,
  GraduationCap,
  LayoutDashboard,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";

interface TabItem {
  label: string;
  href?: string;
  icon: LucideIcon;
  /** When true, treat as active if pathname starts with `href`. */
  startsWith?: boolean;
  onClick?: () => void;
}

export function MobileTabBar() {
  const pathname = usePathname();
  const router = useRouter();

  const stripped = pathname.replace(/^\/[a-z]{2}/, "");

  const items: TabItem[] = [
    { label: "Home", href: ROUTES.DASHBOARD, icon: LayoutDashboard },
    { label: "Studio", href: "/studio", icon: BookOpen, startsWith: true },
    { label: "Grade", href: "/grade", icon: GraduationCap, startsWith: true },
    { label: "Integrity", href: "/integrity", icon: ShieldCheck, startsWith: true },
    { label: "Students", href: "/students", icon: Users, startsWith: true },
  ];

  const isActive = (item: TabItem) => {
    if (!item.href) return false;
    if (item.startsWith) return stripped === item.href || stripped.startsWith(item.href + "/");
    return stripped === item.href;
  };

  return (
    <nav
      role="navigation"
      aria-label="Primary"
      className="border-foreground/10 bg-background/95 supports-[backdrop-filter]:bg-background/85 fixed inset-x-0 bottom-0 z-40 flex items-stretch justify-around border-t pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden"
    >
      {items.map((item) => {
        const active = isActive(item);
        const className = cn(
          "flex flex-1 flex-col items-center justify-center gap-1 py-2.5 text-[10px] font-medium uppercase tracking-wider transition-colors min-h-[56px]",
          active ? "text-foreground" : "text-foreground/55 hover:text-foreground",
        );
        const inner = (
          <>
            <item.icon
              className={cn("h-5 w-5 transition-transform", active && "text-foreground scale-110")}
            />
            <span className="font-mono">{item.label}</span>
            {active && (
              <span aria-hidden className="bg-brand absolute top-0 h-0.5 w-8 rounded-full" />
            )}
          </>
        );
        if (item.onClick) {
          return (
            <button
              key={item.label}
              type="button"
              onClick={item.onClick}
              aria-label={item.label}
              className={cn(className, "relative")}
            >
              {inner}
            </button>
          );
        }
        return (
          <Link
            key={item.label}
            href={item.href!}
            aria-label={item.label}
            aria-current={active ? "page" : undefined}
            className={cn(className, "relative")}
            onClick={(e) => {
              if (item.href === stripped) {
                e.preventDefault();
                router.refresh();
              }
            }}
          >
            {inner}
          </Link>
        );
      })}
    </nav>
  );
}
