"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn, isAppAdmin } from "@/lib/utils";
import { APP_NAME, ROUTES } from "@/lib/constants";
import {
  BookOpen,
  GraduationCap,
  LayoutDashboard,
  PenLine,
  ShieldAlert,
  ShieldCheck,
  Users,
  Building2,
} from "lucide-react";
import { useSidebarStore, useAuthStore } from "@/stores";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui";

const navigation = [
  { label: "Home", href: ROUTES.DASHBOARD, icon: LayoutDashboard },
  { label: "Studio", href: "/studio", icon: BookOpen },
  { label: "Design", href: "/design", icon: BookOpen },
  { label: "Rubric", href: "/rubric", icon: PenLine },
  { label: "Slides", href: "/slides", icon: BookOpen },
  { label: "Grade", href: "/grade", icon: GraduationCap },
  { label: "Integrity", href: "/integrity", icon: ShieldCheck },
  { label: "Students", href: "/students", icon: Users },
  { label: "My style", href: "/style", icon: PenLine },
  { label: "Workspace", href: ROUTES.ORGS, icon: Building2 },
];

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuthStore();

  return (
    <nav className="flex-1 space-y-1 p-4">
      {navigation.map((item) => {
        const isActive = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition-colors",
              "min-h-[44px]",
              isActive
                ? "bg-secondary text-secondary-foreground"
                : "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground",
            )}
          >
            <item.icon className="h-5 w-5" />
            {item.label}
          </Link>
        );
      })}
      {isAppAdmin(user) && (
        <Link
          href={ROUTES.ADMIN}
          onClick={onNavigate}
          className={cn(
            "flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition-colors",
            "min-h-[44px]",
            pathname.startsWith("/admin")
              ? "bg-secondary text-secondary-foreground"
              : "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground",
          )}
        >
          <ShieldAlert className="h-5 w-5" />
          Admin
        </Link>
      )}
    </nav>
  );
}

export function Sidebar() {
  const { isOpen, close } = useSidebarStore();

  return (
    <Sheet open={isOpen} onOpenChange={close}>
      <SheetContent side="left" className="w-72 p-0">
        <SheetHeader className="h-14 px-4">
          <SheetTitle>{APP_NAME}</SheetTitle>
          <SheetClose onClick={close} />
        </SheetHeader>
        <NavLinks onNavigate={close} />
      </SheetContent>
    </Sheet>
  );
}
