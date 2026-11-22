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

function RiskDonut({ counts }: { counts: { low: number; medium: number; high: number } }) {
  const parts = [
    { name: "Low", value: counts.low, color: "#24a148" },
    { name: "Medium", value: counts.medium, color: "#f1c21b" },
    { name: "High", value: counts.high, color: "#da1e28" },
  ];
  const total = parts.reduce((sum, part) => sum + part.value, 0) || 1;
  let angle = 0;
  const slices = parts.filter((part) => part.value > 0).map((part) => {
    const sweep = (part.value / total) * 359.99;
    const start = angle;
    angle += sweep;
    const rad = (deg: number) => ((deg - 90) * Math.PI) / 180;
    const x1 = 60 + 42 * Math.cos(rad(start));
    const y1 = 60 + 42 * Math.sin(rad(start));
    const x2 = 60 + 42 * Math.cos(rad(start + sweep));
    const y2 = 60 + 42 * Math.sin(rad(start + sweep));
    const large = sweep > 180 ? 1 : 0;
    return { ...part, d: `M 60 60 L ${x1} ${y1} A 42 42 0 ${large} 1 ${x2} ${y2} Z` };
  });
  return (
    <div style={{ display: "flex", gap: 24, alignItems: "center" }} aria-label="Risk distribution">
      <svg width="120" height="120" viewBox="0 0 120 120">
        {slices.map((slice) => <path key={slice.name} d={slice.d} fill={slice.color} />)}
        <circle cx="60" cy="60" r="24" fill="#f4f4f4" />
      </svg>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
        {parts.map((part) => (
          <li key={part.name} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <i style={{ width: 12, height: 12, background: part.color, display: "inline-block" }} />
            {part.name} {part.value}
          </li>
        ))}
      </ul>
    </div>
  );
}

function bandOf(score: number | null | undefined, given?: string | null) {
  if (score == null) return given || "low";
  if (score >= 0.5) return "high";
  if (score >= 0.25) return "medium";
  return "low";
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

  const warning = data?.early_warning;
  const roster = data?.students?.length
    ? data.students
    : [
        { id: "stu-1", display_name: "Sara Al Maktoum", email: "", student_number: "8881001" },
        { id: "stu-2", display_name: "Omar Haddad", email: "", student_number: "8881002" },
        { id: "stu-3", display_name: "Noor Rahman", email: "", student_number: "8881003" },
        { id: "stu-4", display_name: "Layla Karim", email: "", student_number: "8881004" },
      ];
  const bands = ["low", "high", "high", "low"];

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <p className="text-sm text-[#525252]">
        Course filter: {data?.course?.code || course?.code || "MAAI 903"} {data?.course?.title || course?.title || ""}
      </p>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <AILabel size="mini" aiText="AI" aria-label="AI" />
        <Tag type="gray">Synthetic, demo only</Tag>
      </div>
      <RiskDonut
        counts={{
          low: roster.filter((_, index) => bandOf(warning?.students[index]?.score, bands[index]) === "low").length,
          medium: roster.filter((_, index) => bandOf(warning?.students[index]?.score, bands[index]) === "medium").length,
          high: roster.filter((_, index) => bandOf(warning?.students[index]?.score, bands[index]) === "high").length,
        }}
      />
      <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 400 }}>Students who may need help</h2>
      <table className="w-full text-left text-sm">
        <thead className="text-foreground/50 border-foreground/10 border-b text-xs tracking-wide uppercase">
          <tr>
            <th className="py-2 font-medium">Name</th>
            <th className="py-2 font-medium">ID</th>
            <th className="py-2 font-medium">Score</th>
            <th className="py-2 font-medium">Band</th>
            <th className="py-2 font-medium">Why</th>
            <th className="py-2 font-medium">Trend</th>
          </tr>
        </thead>
        <tbody>
          {roster.map((student, index) => {
            const row = warning?.students[index] || {
              score: [0.16, 0.72, 0.54, 0.14][index] ?? 0.4,
              band: bands[index],
              factors: [],
              note: "",
            };
            return (
              <tr key={student.id} className="border-foreground/10 border-b">
                <td className="py-3">{student.display_name}</td>
                <td className="py-3">{student.student_number}</td>
                <td className="py-3">{row?.score == null ? "—" : `${Math.round(Number(row.score) * 100)}%`}</td>
                <td className="py-3"><Tag type={bandOf(row?.score, row?.band) === "high" ? "red" : bandOf(row?.score, row?.band) === "medium" ? "magenta" : "green"} size="sm">{bandOf(row?.score, row?.band)}</Tag></td>
                <td className="py-3">{plainReason(bandOf(row?.score, row?.band), row?.factors)}</td>
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
    </div>
  );
}
