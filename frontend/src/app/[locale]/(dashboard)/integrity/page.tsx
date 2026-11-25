"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { pa, run, useWorkspaceQuery } from "@/components/profassist/bits";
import type { Hit } from "@/components/profassist/document-viewer";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
} from "@/components/ui";
import { cn } from "@/lib/utils";

function fileUrl(path: string) {
  return `/api/profassist${path}`;
}

const DocumentPane = dynamic(
  () => import("@/components/profassist/document-viewer").then((mod) => mod.DocumentPane),
  { ssr: false },
);

interface CourseOption {
  code: string;
  slug: string;
  title: string;
}
interface AssignmentCard {
  course: string;
  slug: string;
  title: string;
  number: string;
  name: string;
  groups: number;
  flagged_pairs: number;
  highest: number;
  writing_flags: number;
  status: string;
  line: string;
  analysis_sources?: string[];
  course_id?: string;
  assessment_id?: string;
}
interface Overview {
  courses: CourseOption[];
  summary: {
    courses: number;
    assignments: number;
    groups: number;
    review: number;
    concern: number;
  };
  items: AssignmentCard[];
}
interface PairRow {
  left: string;
  right: string;
  percent: number;
  shared: number;
  writing: boolean;
  status: string;
  analysis_source?: string | null;
}
interface Matrix {
  course: string;
  slug: string;
  assignment: string;
  name: string;
  groups: string[];
  matrix: number[][];
  pairs: PairRow[];
}
interface Passage {
  id: string;
  percent: number;
  common: boolean;
  writing: string;
  left: string;
  right: string;
}
interface Run {
  id: string;
  text: string;
  common: boolean;
  ids?: string[];
}
interface ReportSide {
  members: string;
  submitted: string;
}
interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}
interface Match {
  id: string;
  percent: number;
  source: string;
  tag: string;
  quote: string;
  context: string;
  page_left: number;
  page_right: number;
  left_box: Box;
  right_box: Box;
  decision: string;
  left_start?: number | null;
  left_end?: number | null;
  right_start?: number | null;
  right_end?: number | null;
  left_version_id?: string | null;
  right_version_id?: string | null;
  analysis_source?: "worker" | "legacy" | string | null;
}
interface DocSide {
  origin: string;
  view: string;
  original: string;
  filename: string;
}
interface PairDetail {
  course: string;
  slug: string;
  assignment: string;
  course_id?: string | null;
  assessment_id?: string | null;
  left_version_id?: string | null;
  right_version_id?: string | null;
  name: string;
  left: string;
  right: string;
  percent: number;
  status: string;
  left_text: Array<{ runs: Run[] }>;
  right_text: Array<{ runs: Run[] }>;
  left_meta: ReportSide;
  right_meta: ReportSide;
  passages: Passage[];
  matches: Match[];
  decisions: { flagged: number; ok: number; pending: number };
  documents: { left: DocSide; right: DocSide };
  why: string;
}
interface IntegrityJob {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  assignment_id?: string;
  model_version?: string;
  reused?: boolean;
  error?: string | null;
}

export default function IntegrityPage() {
  return (
    <Suspense fallback={<p>Opening integrity…</p>}>
      <IntegrityDrill />
    </Suspense>
  );
}

function statusClass(status: string) {
  if (status === "Clear") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-700";
  if (status === "Review") return "border-blue-500/40 bg-blue-500/10 text-blue-700";
  if (status === "Concern") return "border-red-500/40 bg-red-500/10 text-red-700";
  return "border-border bg-muted text-muted-foreground";
}

function sourceClass(source: string) {
  if (source === "shared") return "border-purple-500/40 bg-purple-500/10 text-purple-700";
  return "border-border bg-muted text-muted-foreground";
}

function decisionClass(decision: string) {
  if (decision === "flag") return "border-red-500/40 bg-red-500/10 text-red-700";
  if (decision === "ok") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-700";
  return "border-border bg-muted text-muted-foreground";
}

function decisionLabel(decision: string) {
  if (decision === "ok") return "OK";
  if (decision === "flag") return "Flagged";
  return "Pending";
}

function analysisSourceLabel(source?: string | null) {
  if (source === "worker") return "worker model";
  if (source === "legacy-record") return "legacy stored result";
  if (source === "legacy-heuristic" || source === "legacy") return "legacy heuristic";
  return "source unreported";
}

function heat(percent: number) {
  if (percent >= 100) return "#e0e0e0";
  if (percent >= 75) return "#ffd7d9";
  if (percent >= 40) return "#d0e2ff";
  return "#defbe6";
}

function hitsFor(visible: Array<Match & { n: number }>, side: "left" | "right"): Hit[] {
  return visible
    .map((row): Hit => ({
      id: row.id,
      n: row.n,
      page: side === "left" ? row.page_left : row.page_right,
      box: side === "left" ? row.left_box : row.right_box,
      tone: row.source === "readings" ? "readings" : row.source === "brief" ? "brief" : "shared",
    }))
    .filter(({ box, page }) => page > 0 && box.w > 0 && box.h > 0);
}

function SubmissionPane({
  group,
  meta,
  paragraphs,
  matches,
  activeId,
}: {
  group: string;
  meta: ReportSide;
  paragraphs: Array<{ runs: Run[] }>;
  matches: Array<Match & { n: number }>;
  activeId?: string;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const byId = useMemo(() => new Map(matches.map((match) => [match.id, match])), [matches]);

  useEffect(() => {
    const scroll = frame.current;
    const target = scroll?.querySelector("[data-active-match]");
    if (!scroll || !target) return;
    scroll.scrollTop +=
      target.getBoundingClientRect().top -
      scroll.getBoundingClientRect().top -
      scroll.clientHeight / 3;
  }, [activeId]);

  return (
    <section className="pa-doc pa-integrity-reader" aria-label={`Group ${group} report`}>
      <header className="pa-doc-head border-border border-b pb-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">Group {group}</h3>
          {meta.members && <p className="text-muted-foreground text-xs">{meta.members}</p>}
        </div>
        {meta.submitted && (
          <span className="text-muted-foreground text-xs">Submitted {meta.submitted}</span>
        )}
      </header>
      <div
        className="pa-doc-scroll"
        ref={frame}
        role="region"
        aria-label={`Group ${group} full text`}
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- The report must be scrollable with the keyboard.
        tabIndex={0}
      >
        <div className="pa-integrity-text">
          {paragraphs.map((paragraph, index) => (
            <p key={index}>
              {paragraph.runs.map((run, runIndex) => {
                const related = (run.ids ?? [run.id]).flatMap((id) => byId.get(id) ?? []);
                if (!related.length) return <span key={runIndex}>{run.text}</span>;
                const selected = related.some((match) => match.id === activeId);
                const shared = related.some((match) => match.source === "shared");
                return (
                  <mark
                    key={runIndex}
                    className={shared ? "pa-integrity-highlight" : "pa-integrity-common"}
                    data-active-match={selected ? "" : undefined}
                  >
                    <span className="sr-only">
                      {related.map((match) => `Match ${match.n}`).join(", ")}.{" "}
                    </span>
                    {run.text}
                  </mark>
                );
              })}
            </p>
          ))}
        </div>
      </div>
    </section>
  );
}

function IntegrityDrill() {
  const router = useRouter();
  const params = useSearchParams();
  const course = params.get("course") || "all";
  const assignment = params.get("assignment") || "";
  const pair = params.get("pair") || "";
  const {
    data: overview,
    error: overviewError,
    refetch: refreshOverview,
  } = useWorkspaceQuery<Overview>(
    !assignment ? `/integrity/overview?course=${encodeURIComponent(course)}` : null,
  );
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const pairKey = JSON.stringify([course, assignment, pair]);
  const [loadedPair, setLoadedPair] = useState<{ key: string; detail: PairDetail } | null>(null);
  const detail = loadedPair?.key === pairKey ? loadedPair.detail : null;
  const [sort, setSort] = useState<"percent" | "shared">("percent");
  const [why, setWhy] = useState(false);
  const [note, setNote] = useState("");
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  const [strongOnly, setStrongOnly] = useState(false);
  const [hideCommon, setHideCommon] = useState(false);
  const [selection, setSelection] = useState<{ key: string; id: string } | null>(null);
  const matchToolbar = useRef<HTMLDivElement>(null);
  const [savingMatch, setSavingMatch] = useState(false);
  const [job, setJob] = useState<IntegrityJob | null>(null);
  const [scanning, setScanning] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (!assignment) {
      setMatrix(null);
      return;
    }
    pa<Matrix>(`/integrity/matrix?course=${encodeURIComponent(course)}&number=${assignment}`)
      .then(setMatrix)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not open that assignment"),
      );
  }, [course, assignment, refresh]);

  useEffect(() => {
    if (!assignment || !pair) return;
    let cancelled = false;
    const [left, right] = pair.split("-");
    pa<PairDetail>(
      `/integrity/pair?course=${encodeURIComponent(course)}&number=${assignment}&left=${left}&right=${right}`,
    )
      .then((data) => {
        if (!cancelled) setLoadedPair({ key: pairKey, detail: data });
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not open that pair");
      });
    return () => {
      cancelled = true;
    };
  }, [course, assignment, pair, pairKey, refresh]);

  useEffect(() => {
    if (!job?.job_id || job.status === "completed" || job.status === "failed") return;
    let stopped = false;
    const poll = async () => {
      try {
        const status = await pa<IntegrityJob>(`/integrity/jobs/${job.job_id}`);
        if (stopped) return;
        setJob((current) => ({
          ...current,
          ...status,
          model_version: status.model_version || current?.model_version,
        }));
        if (status.status === "completed") {
          setRefresh((value) => value + 1);
          if (!assignment) void refreshOverview();
        }
      } catch (err) {
        if (!stopped) setError(err instanceof Error ? err.message : "Could not check scan status");
      }
    };
    const timer = window.setInterval(() => void poll(), 2000);
    void poll();
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [job?.job_id, job?.status, assignment, refreshOverview]);

  const visible = useMemo(() => {
    const rows = (detail?.matches || []).filter((item) => {
      if (strongOnly && item.percent < 80) return false;
      if (hideCommon && item.source !== "shared") return false;
      return true;
    });
    return rows.map((item, index) => ({ ...item, n: index + 1 }));
  }, [detail, strongOnly, hideCommon]);
  const active =
    visible.find((match) => selection?.key === pairKey && match.id === selection.id) ?? visible[0];
  const previousMatch = active && visible[active.n - 2];
  const nextMatch = active && visible[active.n];

  function selectMatch(id: string) {
    setSelection({ key: pairKey, id });
  }

  const pairs = useMemo(() => {
    const rows = matrix?.pairs ? [...matrix.pairs] : [];
    rows.sort((a, b) => (sort === "shared" ? b.shared - a.shared : b.percent - a.percent));
    return rows;
  }, [matrix, sort]);

  function go(next: { course?: string; assignment?: string; pair?: string }) {
    const query = new URLSearchParams();
    const chosen = next.course ?? course;
    if (chosen && chosen !== "all") query.set("course", chosen);
    if (next.assignment) query.set("assignment", next.assignment);
    if (next.pair) query.set("pair", next.pair);
    router.push(`/integrity${query.toString() ? `?${query}` : ""}`);
  }

  async function decide(matchId: string, action: "ok" | "flag") {
    if (!detail || savingMatch) return;
    setSavingMatch(true);
    const result = await run(
      () =>
        pa<{ matches: Match[]; decisions: PairDetail["decisions"]; message: string }>(
          "/integrity/match",
          {
            method: "POST",
            body: JSON.stringify({
              course: detail.slug,
              number: detail.assignment,
              left: detail.left,
              right: detail.right,
              match_id: matchId,
              action,
            }),
          },
        ),
      setError,
    );
    setSavingMatch(false);
    if (!result) return;
    setLoadedPair((current) =>
      current?.key === pairKey
        ? {
            ...current,
            detail: { ...current.detail, matches: result.matches, decisions: result.decisions },
          }
        : current,
    );
    setSaved(result.message);
  }

  async function act(action: "ok" | "flag" | "note") {
    if (!detail) return;
    let recordedForTraining = false;
    if (action === "ok" || action === "flag") {
      const versionedMatches = detail.matches.filter(
        (match) =>
          match.decision === "flag" &&
          typeof match.left_start === "number" &&
          typeof match.left_end === "number" &&
          typeof match.right_start === "number" &&
          typeof match.right_end === "number",
      );
      const span = (match: Match) => ({
        left_start: match.left_start as number,
        left_end: match.left_end as number,
        right_start: match.right_start as number,
        right_end: match.right_end as number,
      });
      if (
        !detail.course_id ||
        !detail.assessment_id ||
        !detail.left_version_id ||
        !detail.right_version_id
      ) {
        setError(
          "This pair has no immutable report versions yet, so it cannot be included in a training review.",
        );
        return;
      }
      if (action === "flag" && versionedMatches.length === 0) {
        setError(
          "Mark at least one versioned passage as Flagged before saving this pair as reuse.",
        );
        return;
      }
      const review = await run(
        () =>
          pa<{ saved: boolean; error?: string }>("/integrity/reviews", {
            method: "POST",
            body: JSON.stringify({
              course_id: detail.course_id,
              assessment_id: detail.assessment_id,
              left_version_id: detail.left_version_id,
              right_version_id: detail.right_version_id,
              decision: action,
              spans: action === "flag" ? versionedMatches.map(span) : [],
              note,
            }),
          }),
        setError,
      );
      if (!review) return;
      if (!review.saved) {
        setError(review.error || "The versioned review could not be saved.");
        return;
      }
      recordedForTraining = true;
    }
    const result = await run(
      () =>
        pa<{ message: string }>("/integrity/pair", {
          method: "POST",
          body: JSON.stringify({
            course: detail.slug,
            number: detail.assignment,
            left: detail.left,
            right: detail.right,
            action,
            note,
          }),
        }),
      setError,
    );
    if (result) {
      setSaved(
        recordedForTraining
          ? `${result.message} Versioned pair review saved for training.`
          : result.message,
      );
    }
  }

  async function startScan(item: AssignmentCard) {
    if (!item.course_id || !item.assessment_id) {
      setError("This assignment is missing the identifiers needed to start a verified scan.");
      return;
    }
    setError("");
    setScanning(item.assessment_id);
    const result = await run(
      () =>
        pa<IntegrityJob & { error?: string }>(`/courses/${item.course_id}/integrity/jobs`, {
          method: "POST",
          body: JSON.stringify({ assessment_id: item.assessment_id }),
        }),
      setError,
    );
    setScanning("");
    if (result?.error) {
      setError(result.error);
      return;
    }
    if (result) setJob(result);
  }

  const courseItems = [
    { code: "All courses", slug: "all", title: "" },
    ...(overview?.courses || []),
  ];

  return (
    <div className="pa-dash">
      <nav className="pa-crumb" aria-label="Integrity">
        <button
          type="button"
          className="pa-why"
          onClick={() => go({ course, assignment: "", pair: "" })}
        >
          Course
        </button>
        {assignment && (
          <>
            {" / "}
            <button
              type="button"
              className="pa-why"
              onClick={() => go({ course, assignment, pair: "" })}
            >
              Assignment {assignment}
            </button>
          </>
        )}
        {detail && (
          <>
            {" "}
            / Group {detail.left} and Group {detail.right}
          </>
        )}
      </nav>
      {(error || overviewError) && (
        <Alert variant="destructive">
          <AlertTitle>Integrity</AlertTitle>
          <AlertDescription>{error || overviewError?.message}</AlertDescription>
        </Alert>
      )}
      {!assignment && (
        <>
          <div className="max-w-xs space-y-1.5">
            <Label htmlFor="integrity-course">Course</Label>
            <Select
              value={courseItems.some((item) => item.slug === course) ? course : "all"}
              onValueChange={(value) => go({ course: value })}
            >
              <SelectTrigger id="integrity-course">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {courseItems.map((item) => (
                  <SelectItem key={item.slug} value={item.slug}>
                    {item.slug === "all" ? "All courses" : `${item.code} · ${item.title}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {overview && (
            <div className="pa-kpi-row">
              <Card className="p-4">
                <p className="pa-step-kicker">Assignments</p>
                <strong className="text-[2rem]">{overview.summary.assignments}</strong>
              </Card>
              <Card className="p-4">
                <p className="pa-step-kicker">Groups</p>
                <strong className="text-[2rem]">{overview.summary.groups}</strong>
              </Card>
              <Card className="p-4">
                <p className="pa-step-kicker">Needs a look</p>
                <strong className="text-[2rem]">{overview.summary.review}</strong>
              </Card>
              <Card className="p-4">
                <p className="pa-step-kicker">Concern</p>
                <strong className="text-[2rem]">{overview.summary.concern}</strong>
              </Card>
            </div>
          )}
          {overview && overview.items.length === 0 && (
            <p>No submissions yet. Sync Moodle or upload a submission.</p>
          )}
          <div className="grid gap-3">
            {(overview?.items || []).map((item) => (
              <div key={`${item.slug}-${item.number}`} className="pa-panel pa-integrity-row">
                <button
                  type="button"
                  className="pa-integrity-main text-left"
                  onClick={() => go({ course: item.slug, assignment: item.number })}
                >
                  <strong>
                    {item.course} · Assignment {item.number}
                  </strong>
                  <span> {item.name}</span>
                  <span className="pa-integrity-meta">{item.line}</span>
                  {item.analysis_sources?.length ? (
                    <span className="text-muted-foreground text-xs">
                      Signals:{" "}
                      {[...new Set(item.analysis_sources)]
                        .map((source) => analysisSourceLabel(source))
                        .join(" · ")}
                    </span>
                  ) : null}
                  <span className="pa-integrity-bar">
                    <span className="pa-mini-meter" aria-hidden="true">
                      <span style={{ width: `${item.highest}%`, background: heat(item.highest) }} />
                    </span>
                    Highest {item.highest}%
                  </span>
                </button>
                <span className="pa-integrity-side">
                  <Badge variant="outline" className={statusClass(item.status)}>
                    {item.status}
                  </Badge>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={
                      scanning === item.assessment_id ||
                      (job != null && job.status !== "completed" && job.status !== "failed")
                    }
                    onClick={() => void startScan(item)}
                  >
                    {scanning === item.assessment_id ? "Starting…" : "Scan reports"}
                  </Button>
                  <button
                    type="button"
                    className="pa-why"
                    aria-label={`Open assignment ${item.number}`}
                    onClick={() => go({ course: item.slug, assignment: item.number })}
                  >
                    <ChevronRight className="h-5 w-5" aria-hidden="true" />
                  </button>
                </span>
              </div>
            ))}
          </div>
          {job && (
            <Alert variant={job.status === "failed" ? "destructive" : "default"}>
              <AlertTitle>Report scan {job.status}</AlertTitle>
              <AlertDescription>
                {job.error ||
                  `Job ${job.job_id}${job.model_version ? ` · model ${job.model_version}` : ""}${job.reused ? " · reused existing job" : ""}`}
              </AlertDescription>
            </Alert>
          )}
        </>
      )}
      {assignment && !pair && matrix && (
        <>
          <h2 className="m-0 font-normal">
            {matrix.course} · Assignment {matrix.assignment} {matrix.name}
          </h2>
          <div className="pa-legend" aria-label="Colour key">
            <span>
              <i style={{ background: "#defbe6" }} /> Under 40%, clear
            </span>
            <span>
              <i style={{ background: "#d0e2ff" }} /> 40% to 74%, review
            </span>
            <span>
              <i style={{ background: "#ffd7d9" }} /> 75% or more, concern
            </span>
          </div>
          <table className="pa-matrix" aria-label="Similarity between groups">
            <thead>
              <tr>
                <th />
                {matrix.groups.map((group) => (
                  <th key={group}>Group {group}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.groups.map((left, row) => (
                <tr key={left}>
                  <th>Group {left}</th>
                  {matrix.groups.map((right, column) => {
                    const percent = matrix.matrix[row]?.[column] ?? 0;
                    return (
                      <td
                        key={right}
                        style={{ background: left === right ? "#e0e0e0" : heat(percent) }}
                      >
                        {left === right ? (
                          "—"
                        ) : (
                          <button
                            type="button"
                            className="pa-why"
                            onClick={() =>
                              go({ course: matrix.slug, assignment, pair: `${left}-${right}` })
                            }
                          >
                            {percent}%
                          </button>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <table className="pa-matrix">
            <thead>
              <tr>
                <th>Pair</th>
                <th>
                  <button type="button" className="pa-why" onClick={() => setSort("percent")}>
                    Similar
                  </button>
                </th>
                <th>
                  <button type="button" className="pa-why" onClick={() => setSort("shared")}>
                    Shared passages
                  </button>
                </th>
                <th>AI flag</th>
                <th>Status</th>
                <th>Signal source</th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((item) => (
                <tr
                  key={`${item.left}-${item.right}`}
                  onClick={() =>
                    go({ course: matrix.slug, assignment, pair: `${item.left}-${item.right}` })
                  }
                  style={{ cursor: "pointer" }}
                >
                  <td>
                    Group {item.left} vs Group {item.right}
                  </td>
                  <td>{item.percent}%</td>
                  <td>{item.shared}</td>
                  <td>{item.writing ? "Yes" : "No"}</td>
                  <td>
                    <Badge variant="outline" className={statusClass(item.status)}>
                      {item.status}
                    </Badge>
                  </td>
                  <td className="text-muted-foreground text-xs">
                    {analysisSourceLabel(item.analysis_source)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {detail && (
        <>
          <section aria-labelledby="integrity-pair-title" className="space-y-3">
            <div>
              <h2 id="integrity-pair-title" className="text-xl font-semibold tracking-tight">
                Group {detail.left} vs Group {detail.right}
              </h2>
              <p className="text-muted-foreground mt-1 text-sm">
                {detail.course} · Assignment {detail.assignment} · {detail.name}
              </p>
              <div className="text-muted-foreground mt-2 flex flex-wrap items-center gap-2 text-sm">
                <Badge variant="outline" className={statusClass(detail.status)}>
                  {detail.status}
                </Badge>
                <span>{detail.percent}% similar</span>
                <span>
                  {detail.decisions.flagged} flagged, {detail.decisions.ok} OK,{" "}
                  {detail.decisions.pending} pending
                </span>
              </div>
            </div>
            <div
              ref={matchToolbar}
              tabIndex={-1}
              className="bg-card border-border flex scroll-mt-16 flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2"
            >
              <div
                aria-live="polite"
                className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm"
              >
                {active ? (
                  <>
                    <span
                      className={cn(
                        "font-medium",
                        active.source === "shared" && "text-destructive",
                      )}
                    >
                      Match {active.n} of {visible.length}
                    </span>
                    {(["left", "right"] as const).map((side) => {
                      const box = active[`${side}_box`];
                      return detail.documents[side].view && box.w > 0 && box.h > 0 ? (
                        <span key={side} className="text-muted-foreground text-xs">
                          Group {detail[side]} p. {active[`page_${side}`]}
                        </span>
                      ) : null;
                    })}
                  </>
                ) : (
                  <span className="text-muted-foreground">No matching passages in this view.</span>
                )}
              </div>
              {active && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!previousMatch}
                    onClick={() => previousMatch && selectMatch(previousMatch.id)}
                  >
                    <ChevronLeft aria-hidden="true" /> Previous
                  </Button>
                  <Button
                    size="sm"
                    disabled={!nextMatch}
                    onClick={() => nextMatch && selectMatch(nextMatch.id)}
                  >
                    Next <ChevronRight aria-hidden="true" />
                  </Button>
                </div>
              )}
            </div>
            <div className="pa-integrity-reports" key={pairKey}>
              {(["left", "right"] as const).map((side) => {
                const document = detail.documents[side];
                return document.view ? (
                  <DocumentPane
                    key={`${side}:${document.view}`}
                    url={fileUrl(document.view)}
                    title={`Group ${detail[side]}`}
                    filename={document.filename}
                    kind={document.origin === "docx" ? "docx" : "pdf"}
                    downloadUrl={document.original ? fileUrl(document.original) : undefined}
                    hits={hitsFor(visible, side)}
                    activeId={active?.id}
                    comparison
                  />
                ) : (
                  <SubmissionPane
                    key={side}
                    group={detail[side]}
                    meta={detail[`${side}_meta`]}
                    paragraphs={detail[`${side}_text`]}
                    matches={visible}
                    activeId={active?.id}
                  />
                );
              })}
            </div>
            {active && (
              <div className="bg-card border-border flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2">
                <div aria-live="polite" className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">Match {active.n}</span>
                  <Badge variant="outline" className={decisionClass(active.decision)}>
                    {decisionLabel(active.decision)}
                  </Badge>
                  <Badge variant="outline" className={sourceClass(active.source)}>
                    {active.tag}
                  </Badge>
                  <span className="text-muted-foreground text-xs">{active.percent}% similar</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={savingMatch}
                    aria-pressed={active.decision === "ok"}
                    onClick={() => void decide(active.id, "ok")}
                  >
                    Mark OK
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    disabled={savingMatch}
                    aria-pressed={active.decision === "flag"}
                    onClick={() => void decide(active.id, "flag")}
                  >
                    Flag for follow-up
                  </Button>
                </div>
              </div>
            )}
            <details className="bg-card border-border rounded-lg border p-3">
              <summary className="cursor-pointer text-sm font-medium">
                Passage list and filters
              </summary>
              <div className="my-3 flex flex-wrap gap-2">
                <Button
                  variant={strongOnly ? "default" : "outline"}
                  size="sm"
                  aria-pressed={strongOnly}
                  onClick={() => setStrongOnly((on) => !on)}
                >
                  Strong only
                </Button>
                <Button
                  variant={hideCommon ? "default" : "outline"}
                  size="sm"
                  aria-pressed={hideCommon}
                  onClick={() => setHideCommon((on) => !on)}
                >
                  Hide brief and readings
                </Button>
              </div>
              {visible.length > 0 && (
                <Table aria-label="Matches">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Match</TableHead>
                      <TableHead>Similarity</TableHead>
                      <TableHead>Quote</TableHead>
                      <TableHead>Source</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {visible.map((item) => (
                      <TableRow
                        key={item.id}
                        className={cn(item.id === active?.id && "bg-primary/5")}
                      >
                        <TableCell>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            aria-current={item.id === active?.id ? "true" : undefined}
                            onClick={() => {
                              selectMatch(item.id);
                              matchToolbar.current?.focus();
                            }}
                          >
                            Match {item.n}
                          </Button>
                        </TableCell>
                        <TableCell>{item.percent}%</TableCell>
                        <TableCell>
                          <span className="pa-quote">{item.quote}</span>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={sourceClass(item.source)}>
                            {item.tag}
                          </Badge>
                          <p className="text-muted-foreground text-xs">
                            {analysisSourceLabel(item.analysis_source)}
                          </p>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={decisionClass(item.decision)}>
                            {decisionLabel(item.decision)}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </details>
          </section>
          <button
            type="button"
            className="pa-why"
            style={{ display: "block", margin: "12px 0", textAlign: "left" }}
            onClick={() => setWhy((open) => !open)}
          >
            {why ? "Hide why" : "Why?"}
          </button>
          {why && (
            <p id="integrity-why" className="pa-why-body">
              {detail.why}
            </p>
          )}
          <div className="border-border/70 mt-4 rounded-lg border p-3">
            <p className="text-muted-foreground mb-2 text-xs">
              Save a complete pair review for training. Flag the specific reused passages above
              before recording a reuse decision.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => act("ok")}>Save reviewed as distinct reports</Button>
              <Button variant="destructive" onClick={() => act("flag")}>
                Save reviewed as report reuse
              </Button>
            </div>
          </div>
          <div className="mt-4 space-y-1.5">
            <Label htmlFor="integrity-note">Add a note</Label>
            <Textarea
              id="integrity-note"
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
          <div className="mt-2">
            <Button variant="outline" onClick={() => act("note")}>
              Save note
            </Button>
          </div>
          {saved && <p>{saved}</p>}
        </>
      )}
    </div>
  );
}
