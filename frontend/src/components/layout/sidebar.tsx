"use client";

import { NavLinks } from "@/components/layout/app-nav";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui";
import { APP_NAME } from "@/lib/constants";
import { useSidebarStore } from "@/stores";

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
