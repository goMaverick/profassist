"use client";

import { Sparkles } from "lucide-react";

import { Banner, useWorkspace, useWorkspaceQuery } from "@/components/profassist/bits";
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
  model?: string;
  model_version?: string | null;
  batch_id?: string | null;
  cutoff?: string | null;
  data_revision?: string | null;
  students: Array<{
    display_name: string;
    score: number | null;
    band: string | null;
    factors: string[];
    note: string;
    prediction_status?: string;
    eligibility_status?: string;
    model_version?: string | null;
    batch_id?: string | null;
    cutoff?: string | null;
    data_revision?: string | null;
  }>;
}
const factorLabels = {
  active_days_14d: "Active days in the last 14 days",
  active_days_previous_14d: "Active days in the preceding 14 days",
  interactions_14d: "Interactions in the last 14 days",
  interactions_previous_14d: "Interactions in the preceding 14 days",
  resource_views_14d: "Resource views in the last 14 days",
  forum_posts_14d: "Forum posts in the last 14 days",
  late_submissions_to_date: "Late submissions by the cutoff",
  assignments_due_to_date: "Assignments due by the cutoff",
  scores_available_count: "Recorded scores by the cutoff",
  mean_score_pct_to_date: "Average recorded score (%)",
  missed_assignments: "Missed assignments by the cutoff",
  activity_change: "Change in active days across the two periods",
  days_since_last_activity: "Days since last recorded activity",
  no_activity_history: "No recorded activity history",
};

type ScoreFactor = { feature: keyof typeof factorLabels; value: number | null; effect: number };
const factorNumber = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

interface Payload {
  course?: { code: string; title: string };
  students: Array<{
    id: string;
    display_name: string;
    email: string;
    student_number: string;
    dropout_prediction?: {
      probability: number | null;
      risk_band: string | null;
      predicted_at?: string | null;
      model_version?: string | null;
      batch_id?: string | null;
      cutoff_at?: string | null;
      coverage_status?: string | null;
      explanation?: ScoreFactor[] | null;
      status?: string | null;
    } | null;
  }>;
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
  const { data, error, isPending } = useWorkspaceQuery<Payload>(
    course ? `/courses/${course.id}/students` : null,
  );

  const warning = data?.early_warning;
  const roster = data?.students || [];
  const scored = (warning?.students || []).filter((row) => row.score != null);
  const hasPersistedScores = roster.some(
    (student) => student.dropout_prediction?.probability != null,
  );
  // A synthetic bundle still produces useful demo scores, so show them with a
  // clear label. A blank score is a data gap, not a low risk.
  const showScores = hasPersistedScores || Boolean(warning?.trained && scored.length > 0);
  const counts = { low: 0, medium: 0, high: 0 };
  if (showScores) {
    for (const student of roster) {
      const prediction = student.dropout_prediction;
      const row = (warning?.students || []).find(
        (item) => item.display_name === student.display_name,
      );
      const score = prediction?.probability ?? row?.score;
      if (score == null) continue;
      const bandValue = prediction?.risk_band || row?.band;
      const band =
        bandValue === "review"
          ? "high"
          : bandValue === "routine"
            ? "low"
            : bandValue || bandOf(Number(score));
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
      {(error || loadError) && <Banner>{error?.message || loadError}</Banner>}
      {course && isPending && (
        <p className="text-muted-foreground text-sm" role="status">
          Loading student records…
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="gap-1" aria-label="AI">
          <Sparkles className="h-3 w-3" aria-hidden="true" />
          AI
        </Badge>
        {warning && !warning.trained && !hasPersistedScores && (
          <Badge variant="secondary">Early-warning model not trained</Badge>
        )}
        {warning && warning.trained && warning.synthetic && (
          <Badge variant="secondary">Demo model</Badge>
        )}
        {warning?.trained && !warning.synthetic && warning.model_version && (
          <Badge variant="outline">Model version {warning.model_version}</Badge>
        )}
        {warning?.trained &&
          !warning.synthetic &&
          (warning.batch_id || warning.cutoff || warning.data_revision) && (
            <Badge variant="outline">
              {[
                warning.batch_id && `Batch ${warning.batch_id}`,
                warning.cutoff && `Cutoff ${warning.cutoff}`,
                warning.data_revision && `Data ${warning.data_revision}`,
              ]
                .filter(Boolean)
                .join(" · ")}
            </Badge>
          )}
      </div>
      {warning && warning.synthetic && showScores && (
        <Banner>
          Synthetic training data; advisory only. The demo marks a score at or above{" "}
          {Math.round((warning.threshold ?? 0.1) * 100)}%. Nothing here changes a student&apos;s
          enrolment, messages, or marks.
        </Banner>
      )}
      {hasPersistedScores && (
        <Banner>
          Saved scores include their model version, scoring batch, and day-35 cutoff where
          available. They are advisory only and do not change enrolment, messages, or marks.
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
              const prediction = student.dropout_prediction;
              const score =
                prediction?.probability ?? (row?.score != null ? Number(row.score) : null);
              const band = score == null ? "" : prediction?.risk_band || row?.band || bandOf(score);
              const why =
                score == null
                  ? prediction?.coverage_status ||
                    prediction?.status ||
                    row?.eligibility_status ||
                    row?.prediction_status ||
                    row?.note ||
                    "Not scored"
                  : prediction?.coverage_status || row?.note || (row?.factors || []).join(" · ");
              return (
                <TableRow key={student.id}>
                  <TableCell className="py-3">{student.display_name}</TableCell>
                  <TableCell className="py-3">{student.student_number}</TableCell>
                  <TableCell className="py-3">
                    {score == null ? (
                      <span title={row?.note || "No eligible score available"}>
                        {prediction?.status ||
                          prediction?.coverage_status ||
                          row?.eligibility_status ||
                          row?.prediction_status ||
                          "Not scored"}
                      </span>
                    ) : (
                      `${Math.round(score * 100)}%`
                    )}
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
                  <TableCell className="py-3">
                    {prediction && score != null ? (
                      <details>
                        <summary className="cursor-pointer font-medium">Why this score?</summary>
                        {prediction.explanation?.length ? (
                          <>
                            <ul className="mt-2 space-y-1 text-sm">
                              {prediction.explanation.map(({ feature, value, effect }) => (
                                <li key={feature}>
                                  {factorLabels[feature]} ·{" "}
                                  {value == null
                                    ? "Missing at cutoff"
                                    : feature === "no_activity_history"
                                      ? value
                                        ? "Yes"
                                        : "No"
                                      : factorNumber.format(value)}
                                  {" · "}
                                  {effect > 0 ? "Raised score" : "Lowered score"}
                                </li>
                              ))}
                            </ul>
                            <p className="text-muted-foreground mt-2 text-xs">
                              These inputs influenced the model score compared with its training
                              baseline.
                            </p>
                          </>
                        ) : (
                          <p className="text-muted-foreground mt-1 text-sm">
                            Explanation unavailable for this saved score.
                          </p>
                        )}
                      </details>
                    ) : (
                      why || row?.note || "No eligible score available"
                    )}
                    {score != null &&
                      (prediction?.model_version ||
                        prediction?.batch_id ||
                        prediction?.cutoff_at ||
                        prediction?.predicted_at ||
                        row?.model_version ||
                        row?.batch_id ||
                        row?.cutoff) && (
                        <div className="text-muted-foreground mt-1 text-xs">
                          {[
                            (prediction?.model_version || row?.model_version) &&
                              `Model ${prediction?.model_version || row?.model_version}`,
                            (prediction?.batch_id || row?.batch_id) &&
                              `Batch ${prediction?.batch_id || row?.batch_id}`,
                            (prediction?.cutoff_at || row?.cutoff) &&
                              `Cutoff ${prediction?.cutoff_at || row?.cutoff}`,
                            prediction?.predicted_at && `Scored ${prediction.predicted_at}`,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
                      )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
