"use client";

import { useEffect, useState } from "react";
import { Banner, pa, useWorkspace } from "@/components/profassist/bits";

interface Warning {
  status: string;
  trained: boolean;
  message: string;
  data_needed?: string;
  features?: string[];
  course_code?: string;
  automatic_actions?: boolean;
  students: Array<{
    display_name: string;
    score: number | null;
    band: string | null;
    factors: string[];
    note: string;
  }>;
}
interface Payload {
  course?: { code: string; title: string };
  students: Array<{ id: string; display_name: string; email: string; student_number: string }>;
  early_warning: Warning;
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
  const warning = data?.early_warning;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <p className="text-sm text-[#525252]">
        Course filter: {data?.course?.code || course.code} {data?.course?.title || course.title}
      </p>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      {!data && !error && <p>Loading the roster…</p>}
      {data && data.students.length === 0 && <p>No students are on this course yet. Sync from Moodle to pull the roster.</p>}
      {warning && (
        <Banner>
          {warning.trained ? warning.message : `Model not trained. ${warning.message}`}
          {warning.data_needed ? ` ${warning.data_needed}` : ""}
        </Banner>
      )}
      {warning?.features && (
        <p className="text-foreground/60 text-xs">
          Upstream features: {warning.features.join(", ")}.
        </p>
      )}
      {data && data.students.length > 0 && (
      <table className="w-full text-left text-sm">
        <thead className="text-foreground/50 border-foreground/10 border-b text-xs tracking-wide uppercase">
          <tr>
            <th className="py-2 font-medium">Name</th>
            <th className="py-2 font-medium">ID</th>
            <th className="py-2 font-medium">Score</th>
            <th className="py-2 font-medium">Band</th>
            <th className="py-2 font-medium">Factors</th>
          </tr>
        </thead>
        <tbody>
          {data?.students.map((student, index) => {
            const row = warning?.students[index];
            return (
              <tr key={student.id} className="border-foreground/10 border-b">
                <td className="py-3">{student.display_name}</td>
                <td className="py-3">{student.student_number}</td>
                <td className="py-3">{row?.score ?? "—"}</td>
                <td className="py-3">{row?.band ?? "not trained"}</td>
                <td className="text-foreground/60 py-3">{row?.factors?.join(", ") || row?.note}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      )}
    </div>
  );
}
