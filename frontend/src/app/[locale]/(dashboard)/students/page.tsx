"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

import { Banner, pa, useWorkspace } from "@/components/profassist/bits";
import {
  Badge,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui";

interface Warning {
  status: string;
  trained: boolean;
  synthetic?: boolean;
  message: string;
  data_needed?: string;
  features?: string[];
  course_code?: string;
  automatic_actions?: boolean;
  threshold?: number;
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
  const slices = parts
    .filter((part) => part.value > 0)
    .map((part) => {
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
        {slices.map((slice) => (
          <path key={slice.name} d={slice.d} fill={slice.color} />
        ))}
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

function bandOf(score: number) {
  if (score >= 0.5) return "high";
  if (score >= 0.25) return "medium";
  return "low";
}

function bandClass(band: string) {
  if (band === "high" || band === "review") return "border-red-500/40 bg-red-500/10 text-red-700";
  if (band === "medium") return "border-yellow-500/40 bg-yellow-500/10 text-yellow-700";
  return "border-emerald-500/40 bg-emerald-500/10 text-emerald-700";
}

export default function StudentsPage() {
  const { course, error: loadError } = useWorkspace();
  const [error, setError] = useState("");
  const [data, setData] = useState<Payload | null>(null);

  useEffect(() => {
    if (!course) return;
    pa<Payload>(`/courses/${course.id}/students`)
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, [course]);

  const warning = data?.early_warning;
  const roster = data?.students || [];
  const scored = (warning?.students || []).filter((row) => row.score != null);
  // A synthetic bundle still produces useful demo scores, so show them with a
  // clear label. A blank score is a data gap, not a low risk.
  const showScores = Boolean(warning?.trained && scored.length > 0);
  const counts = { low: 0, medium: 0, high: 0 };
  if (showScores) {
    for (const row of scored) {
      const band =
        row.band === "review" ? "high" : row.band === "routine" ? "low" : bandOf(Number(row.score));
      if (band === "high") counts.high += 1;
      else if (band === "medium") counts.medium += 1;
      else counts.low += 1;
    }
  }
  const byName = new Map((warning?.students || []).map((row) => [row.display_name, row]));
  const code = data?.course?.code || course?.code || "";
  const title = data?.course?.title || course?.title || "";

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <p className="text-sm text-[#525252]">
        {code ? `Course filter: ${code} ${title}`.trim() : "No course selected yet."}
      </p>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="gap-1" aria-label="AI">
          <Sparkles className="h-3 w-3" aria-hidden="true" />
          AI
        </Badge>
        {warning && !warning.trained && (
          <Badge variant="secondary">Early-warning model not trained</Badge>
        )}
        {warning && warning.trained && warning.synthetic && (
          <Badge variant="secondary">Demo model</Badge>
        )}
      </div>
      {warning && warning.synthetic && showScores && (
        <Banner>
          Synthetic training data; advisory only. The demo marks a score at or above{" "}
          {Math.round((warning.threshold ?? 0.1) * 100)}%. Nothing here changes a student&apos;s
          enrolment, messages, or marks.
        </Banner>
      )}
      {!showScores && warning && <Banner>{warning.message}</Banner>}
      {showScores && <RiskDonut counts={counts} />}
      <h2 className="m-0 text-xl font-normal">Students who may need help</h2>
      {roster.length === 0 ? (
        <p>No roster yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>ID</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Band</TableHead>
              <TableHead>Why</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {roster.map((student) => {
              const row = byName.get(student.display_name);
              const score = row?.score != null ? Number(row.score) : null;
              const band = score == null ? "" : row?.band || bandOf(score);
              const why = score == null || !row ? "" : row.note || (row.factors || []).join(" · ");
              return (
                <TableRow key={student.id}>
                  <TableCell className="py-3">{student.display_name}</TableCell>
                  <TableCell className="py-3">{student.student_number}</TableCell>
                  <TableCell className="py-3">
                    {score == null ? "—" : `${Math.round(score * 100)}%`}
                  </TableCell>
                  <TableCell className="py-3">
                    {band ? (
                      <Badge variant="outline" className={bandClass(band)}>
                        {band}
                      </Badge>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell className="py-3">{why || "—"}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
