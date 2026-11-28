"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { ROUTES } from "@/lib/constants";
import { Button, Spinner } from "@/components/ui";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { isAuthenticated, isLoading, sessionCheckFailed, checkSession } = useAuth();

  useEffect(() => {
    if (!isLoading && !isAuthenticated && !sessionCheckFailed) router.replace(ROUTES.LOGIN);
  }, [isAuthenticated, isLoading, router, sessionCheckFailed]);

  if (!isAuthenticated) {
    if (sessionCheckFailed) {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-3">
          <p role="alert">Could not reach ProfAssist to check your session.</p>
          <Button onClick={() => void checkSession()}>Try again</Button>
        </div>
      );
    }
    if (!isLoading) return null;
    return (
      <div className="flex h-screen items-center justify-center" role="status" aria-live="polite">
        <Spinner className="text-muted-foreground h-6 w-6" />
        <span className="sr-only">Checking authentication...</span>
      </div>
    );
  }

  return <>{children}</>;
}
