"use client";

import { useEffect, useState } from "react";
import { firstCourse, pa, ProfassistError, type Course } from "@/lib/profassist";

export function Banner({ children }: { children: React.ReactNode }) {
  return (
    <p className="border-foreground/15 bg-foreground/[0.03] text-foreground/80 rounded-lg border px-4 py-3 text-sm">
      {children}
    </p>
  );
}

export function useWorkspace() {
  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    firstCourse()
      .then(setCourse)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load the workspace"))
      .finally(() => setLoading(false));
  }, []);

  return { course, error, loading };
}

export async function run<T>(action: () => Promise<T>, setError: (value: string) => void): Promise<T | null> {
  try {
    setError("");
    return await action();
  } catch (err) {
    setError(err instanceof ProfassistError || err instanceof Error ? err.message : "Something went wrong");
    return null;
  }
}

export { pa };
