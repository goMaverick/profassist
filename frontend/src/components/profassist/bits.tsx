"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { pa, ProfassistError, type Course } from "@/lib/profassist";
import { useAuthStore, useOrgStore } from "@/stores";

export function Banner({ children }: { children: React.ReactNode }) {
  return (
    <p className="border-foreground/15 bg-foreground/[0.03] text-foreground/80 rounded-lg border px-4 py-3 text-sm">
      {children}
    </p>
  );
}

export function useWorkspaceQuery<T>(path: string | null, staleTime = 0) {
  const userId = useAuthStore((state) => state.user?.id);
  const orgId = useOrgStore((state) => state.activeOrgId);
  return useQuery({
    queryKey: ["profassist", userId, orgId, path],
    queryFn: ({ signal }) => pa<T>(path!, { signal }),
    enabled: Boolean(userId && path),
    staleTime,
  });
}

export function useWorkspace() {
  const [savedCourseId, setSavedCourseId] = useState<string | null>(null);
  const { data, error, isPending } = useWorkspaceQuery<{ items: Course[] }>("/courses", 30_000);

  useEffect(() => {
    setSavedCourseId(window.sessionStorage.getItem("pa-course") || "");
  }, []);

  const course =
    savedCourseId === null
      ? null
      : (data?.items.find((item) => item.id === savedCourseId) ?? data?.items[0] ?? null);

  return {
    course,
    courses: data?.items ?? [],
    error: error instanceof Error ? error.message : error ? "Could not load the workspace" : "",
    loading: isPending || savedCourseId === null,
  };
}

export async function run<T>(
  action: () => Promise<T>,
  setError: (value: string) => void,
): Promise<T | null> {
  try {
    setError("");
    return await action();
  } catch (err) {
    setError(
      err instanceof ProfassistError || err instanceof Error ? err.message : "Something went wrong",
    );
    return null;
  }
}

export { pa };
