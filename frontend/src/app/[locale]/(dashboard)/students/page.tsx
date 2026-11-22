"use client";

import { useEffect, useState } from "react";
import { Banner, pa, useWorkspace } from "@/components/profassist/bits";

interface Payload {
  students: Array<{ id: string; display_name: string; email: string; student_number: string }>;
  early_warning: {
    status: string;
    trained: boolean;
    message: string;
    students: Array<{ display_name: string; risk: string | null; note: string }>;
  };
}

export default function StudentsPage() {
  const { course, error: loadError, loading } = useWorkspace();
  const [error, setError] = useState("");
  const [data, setData] = useState<Payload | null>(null);

  useEffect(() => {
    if (!course) return;
    pa<Payload>(`/courses/${course.id}/students`)
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, [course]);

  if (loading) return <p className="text-sm">Loading the roster…</p>;
  if (!course) return <Banner>{loadError || "No course in this workspace."}</Banner>;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <p className="text-foreground/50 text-xs tracking-[0.18em] uppercase">{course.code}</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Students</h1>
      </div>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      {data && (
        <Banner>
          Model not trained yet. {data.early_warning.message}
        </Banner>
      )}
      <table className="w-full text-left text-sm">
        <thead className="text-foreground/50 border-foreground/10 border-b text-xs tracking-wide uppercase">
          <tr>
            <th className="py-2 font-medium">Name</th>
            <th className="py-2 font-medium">ID</th>
            <th className="py-2 font-medium">Email</th>
            <th className="py-2 font-medium">Risk</th>
          </tr>
        </thead>
        <tbody>
          {data?.students.map((student, index) => (
            <tr key={student.id} className="border-foreground/10 border-b">
              <td className="py-3">{student.display_name}</td>
              <td className="py-3">{student.student_number}</td>
              <td className="py-3">{student.email}</td>
              <td className="text-foreground/60 py-3">{data.early_warning.students[index]?.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
