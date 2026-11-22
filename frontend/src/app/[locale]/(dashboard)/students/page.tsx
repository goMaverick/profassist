"use client";

import { useEffect, useState } from "react";
import { AILabel, Tag } from "@carbon/react";
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

function plainReason(band?: string | null, factors?: string[]) {
  const text = (factors || []).join(" ").toLowerCase();
  if (band === "high" || text.includes("missed")) return "Missed recent logins and some submitted work.";
  if (band === "medium" || text.includes("activity")) return "Activity dropped over the last two weeks.";
  return "Keeping up with logins and submissions.";
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
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <AILabel size="mini" aiText="AI" aria-label="AI" />
        <Tag type="gray">Synthetic, demo only</Tag>
      </div>
      {warning && (
        <div className="pa-bars" aria-label="Risk distribution" style={{ height: 72, alignItems: "flex-end" }}>
          {(["low", "medium", "high"] as const).map((band) => {
            const count = (warning.students || []).filter((item) => item.band === band).length;
            return (
              <div key={band}>
                <div style={{ height: `${Math.max(8, count * 22)}px`, background: band === "high" ? "#da1e28" : band === "medium" ? "#8a3ffc" : "#24a148" }} />
                <span>{band} {count}</span>
              </div>
            );
          })}
        </div>
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
            <th className="py-2 font-medium">Trend</th>
          </tr>
        </thead>
        <tbody>
          {data?.students.map((student, index) => {
            const row = warning?.students[index];
            return (
              <tr key={student.id} className="border-foreground/10 border-b">
                <td className="py-3">{student.display_name}</td>
                <td className="py-3">{student.student_number}</td>
                <td className="py-3">{row?.score == null ? "—" : `${Math.round(Number(row.score) * 100)}%`}</td>
                <td className="py-3">{row?.band ? <Tag type={row.band === "high" ? "red" : row.band === "medium" ? "purple" : "green"} size="sm">{row.band}</Tag> : "—"}</td>
                <td className="py-3">{plainReason(row?.band, row?.factors)}</td>
                <td className="py-3">
                  <span style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 28 }}>
                    {[0.35, 0.5, 0.45, Math.min(1, Number(row?.score ?? 0.2))].map((value, bar) => (
                      <span key={bar} style={{ width: 6, height: `${Math.max(4, value * 28)}px`, background: "#8a3ffc" }} />
                    ))}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      )}
    </div>
  );
}
