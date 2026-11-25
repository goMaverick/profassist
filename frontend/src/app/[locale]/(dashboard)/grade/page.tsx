"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  ArrowLeft,
  BookOpen,
  Check,
  ChevronRight,
  FileText,
  Paperclip,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Label,
  Textarea,
} from "@/components/ui";
import { Banner, pa, run, useWorkspaceQuery } from "@/components/profassist/bits";
import type { Box, Hit, MarginNote } from "@/components/profassist/document-viewer";
import { CouncilStage } from "@/components/profassist/council-stage";
import type { GradeStatusPoint } from "./grade-chart";

function fileUrl(path: string) {
  return `/api/profassist${path}`;
}

const DocumentPane = dynamic(
  () => import("@/components/profassist/document-viewer").then((mod) => mod.DocumentPane),
  { ssr: false },
);

const GradeStatusChart = dynamic(
  () => import("./grade-chart").then((mod) => mod.GradeStatusChart),
  { ssr: false },
);

interface CourseRow {
  id: string;
  code: string;
  title: string;
  term: string;
}

interface IntegrityItem {
  course: string;
  slug: string;
  status: string;
  flagged_pairs: number;
  number?: string;
  name?: string;
  title?: string;
}

interface SubmissionRow {
  id: string;
  group_name: string;
  topic: string;
  assessment_id?: string;
  origin?: string;
  files?: number;
  peer_reviews?: number;
  draft_id: string | null;
  draft_status: string | null;
  blind: boolean;
  quarantined: boolean;
  trace_url?: string;
}

interface AssessmentRow {
  id: string;
  title: string;
  status: string;
  kind?: string;
}

interface MoodleStatus {
  mode: string;
  paused: boolean;
  interval_minutes: number;
  next_run: string;
  next_nightly: string;
  last_sync: string;
  last_status: string;
  last_error: string;
}

interface Draft {
  id: string;
  group_name: string;
  status: string;
  blind: boolean;
  blind_revealed: boolean;
  overall_feedback: string;
  professor_levels: Record<string, string>;
  model_view: string;
  one_click: boolean;
  one_click_reason: string;
  trace_url?: string;
  grader_model?: string;
  results: Array<{
    criterion: string;
    feedback: string;
    votes: Array<{ persona: string; level: string | null; quotes: string[] }>;
    judge: {
      level: string | null;
      why: string;
      vote_split: Array<string | null>;
      quotes: string[];
      evidence_status: string;
    };
    debate_rounds?: Array<{ round: number; votes: Array<{ persona: string; level: string }> }>;
    calibrator: { status: string; message: string; applied: boolean };
  }>;
}

function statusLabel(status: string | null) {
  if (status === "draft") return "Draft ready";
  if (status === "approved") return "Approved";
  if (status === "pushed") return "Pushed";
  return status || "Not graded";
}

function compact(value?: string) {
  return (value || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
}

function isGraded(status: string | null) {
  return status === "approved" || status === "pushed";
}

function assessmentBadgeClass(status: string) {
  if (status === "approved" || status === "pushed") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-700";
  }
  if (status === "draft") return "border-purple-500/40 bg-purple-500/10 text-purple-700";
  return "border-border bg-muted text-muted-foreground";
}

function integrityBadgeClass(flagged: number) {
  if (flagged === 0) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-700";
  return "border-amber-500/40 bg-amber-500/10 text-amber-700";
}

function tally(rows: SubmissionRow[]): GradeStatusPoint[] {
  let notGraded = 0;
  let draft = 0;
  let approved = 0;
  let pushed = 0;
  for (const row of rows) {
    if (row.draft_status === "draft") draft += 1;
    else if (row.draft_status === "approved") approved += 1;
    else if (row.draft_status === "pushed") pushed += 1;
    else notGraded += 1;
  }
  return [
    { status: "Not graded", count: notGraded },
    { status: "Draft", count: draft },
    { status: "Approved", count: approved },
    { status: "Pushed", count: pushed },
  ];
}
function GroupCard({
  row,
  busy,
  revision,
  onRun,
  onReview,
}: {
  row: SubmissionRow;
  busy: boolean;
  revision: number;
  onRun: (row: SubmissionRow) => void;
  onReview: (row: SubmissionRow) => void;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pov, setPov] = useState<"loading" | "ready" | "empty" | "error">(
    row.draft_id ? "loading" : "empty",
  );
  const [files, setFiles] = useState<string[] | null>(null);
  const [filesError, setFilesError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setFiles(null);
    setFilesError("");
    pa<{ files?: Array<{ filename: string }> }>(`/submissions/${row.id}`)
      .then((data) => {
        if (cancelled) return;
        setFiles((data.files || []).map((item) => item.filename));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFilesError(err instanceof Error ? err.message : "Could not load attachments.");
      });
    return () => {
      cancelled = true;
    };
  }, [row.id]);

  useEffect(() => {
    let cancelled = false;
    if (!row.draft_id) {
      setDraft(null);
      setPov("empty");
      return () => {
        cancelled = true;
      };
    }
    setPov("loading");
    pa<Draft>(`/drafts/${row.draft_id}`)
      .then((next) => {
        if (cancelled) return;
        setDraft(next);
        setPov(next.results?.length || next.overall_feedback ? "ready" : "empty");
      })
      .catch(() => {
        if (cancelled) return;
        setDraft(null);
        setPov("error");
      });
    return () => {
      cancelled = true;
    };
  }, [row.draft_id, revision]);
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">{row.group_name}</h3>
          <p className="pa-meta">{row.topic || "No topic recorded."}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge
            variant="outline"
            className={
              row.draft_status === "draft"
                ? "border-purple-500/40 bg-purple-500/10 text-purple-700"
                : isGraded(row.draft_status)
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700"
                  : "border-border bg-muted text-muted-foreground"
            }
          >
            {statusLabel(row.draft_status)}
          </Badge>
          {row.blind && <Badge variant="outline">Blind</Badge>}
          {row.quarantined && <Badge variant="destructive">Quarantined</Badge>}
        </div>
      </div>
      <p className="pa-meta">
        {row.files ?? 0} file{(row.files ?? 0) === 1 ? "" : "s"} · {row.peer_reviews ?? 0} peer
        review{(row.peer_reviews ?? 0) === 1 ? "" : "s"}
      </p>
      <div className="mt-3 space-y-1">
        <p className="pa-step-kicker">ProfAssist POV</p>
        {pov === "loading" && (
          <p className="pa-meta" aria-busy="true">
            {"Reading the council draft\u2026"}
          </p>
        )}
        {pov === "empty" && <p className="pa-meta">{"Not graded yet \u2014 run the council"}</p>}
        {pov === "error" && (
          <p className="pa-meta" role="alert">
            Could not load the council draft.
          </p>
        )}{" "}
        {pov === "ready" && draft && (
          <Fragment>
            {draft.overall_feedback && <p className="text-sm">{draft.overall_feedback}</p>}
            {draft.results.length > 0 && (
              <ul className="space-y-1">
                {draft.results.map((item) => (
                  <li
                    key={item.criterion}
                    className="flex items-center justify-between gap-2 text-sm"
                  >
                    <span>{item.criterion}</span>
                    <Badge variant="outline">{item.judge?.level || "no band"}</Badge>
                  </li>
                ))}
              </ul>
            )}
            {draft.results.length === 0 && (
              <p className="pa-meta">No criterion levels stored yet.</p>
            )}
          </Fragment>
        )}
      </div>
      <div className="mt-3 space-y-1">
        <p className="pa-step-kicker">
          <Paperclip className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />
          Attachments
        </p>
        {!files && !filesError && (
          <p className="pa-meta" aria-busy="true">
            {"Loading attachments\u2026"}
          </p>
        )}
        {filesError && (
          <p className="pa-meta" role="alert">
            {filesError}
          </p>
        )}
        {files && files.length === 0 && <p className="pa-meta">No files attached.</p>}
        {files && files.length > 0 && (
          <ul className="space-y-0.5 text-sm">
            {files.map((name) => (
              <li key={name} className="flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="truncate">{name}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" disabled={busy} onClick={() => onRun(row)}>
          Run council
        </Button>
        <Button size="sm" variant="outline" onClick={() => onReview(row)}>
          Review results
        </Button>
      </div>
    </Card>
  );
}

type Stage = "courses" | "assignments" | "dashboard";

export default function GradePage() {
  const uploadRef = useRef<HTMLInputElement>(null);
  const {
    data: home,
    isPending: homeLoading,
    error: homeLoadError,
  } = useWorkspaceQuery<{ courses: CourseRow[] }>("/home");
  const courses = home?.courses ?? [];
  const homeError = homeLoadError?.message;
  const onlyCourseId = courses.length === 1 ? courses[0]?.id : undefined;
  const [stage, setStage] = useState<Stage>("courses");
  const [courseId, setCourseId] = useState("");
  const [assessmentId, setAssessmentId] = useState("");
  const { data: integrityOverview, error: integrityLoadError } = useWorkspaceQuery<{
    items: IntegrityItem[];
  }>(courseId ? "/integrity/overview?course=all" : null);
  const integrity = integrityOverview?.items ?? [];
  const integrityError = integrityLoadError?.message;
  const [error, setError] = useState("");
  const [rows, setRows] = useState<SubmissionRow[]>([]);
  const [assessments, setAssessments] = useState<AssessmentRow[]>([]);
  const [moodle, setMoodle] = useState<MoodleStatus | null>(null);
  const [approving, setApproving] = useState("");
  const [feedbackFor, setFeedbackFor] = useState("");
  const [sent, setSent] = useState("");
  const [council, setCouncil] = useState<Draft | null>(null);
  const [grading, setGrading] = useState(false);
  const [whyId, setWhyId] = useState("");
  const [councilAnimating, setCouncilAnimating] = useState(false);
  const [povRevision, setPovRevision] = useState(0);

  const loadQueue = useCallback(async (id: string) => {
    const queue = await pa<{
      course: { last_sync_status?: string };
      assessment: { status: string; criteria: unknown[] } | null;
      assessments?: AssessmentRow[];
      submissions: SubmissionRow[];
    }>(`/courses/${id}/grade`);
    setRows(queue.submissions);
    setAssessments(queue.assessments || []);
    const panel = await pa<MoodleStatus>("/moodle/status");
    setMoodle(panel);
  }, []);

  useEffect(() => {
    if (!onlyCourseId) return;
    setCourseId(onlyCourseId);
    setStage("assignments");
  }, [onlyCourseId]);

  const course = courses.find((item) => item.id === courseId) || null;

  useEffect(() => {
    if (!course) return;
    loadQueue(course.id).catch((err: unknown) =>
      setError(err instanceof Error ? err.message : "Load failed"),
    );
  }, [course, loadQueue]);

  useEffect(() => {
    if (!homeLoading && stage !== "courses" && !course) setStage("courses");
  }, [homeLoading, stage, course]);

  useEffect(() => {
    if (!feedbackFor) return;
    document
      .getElementById("feedback-desk")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [feedbackFor]);

  function chooseCourse(next: CourseRow) {
    if (next.id === courseId) {
      void loadQueue(next.id).catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Load failed"),
      );
    } else {
      setRows([]);
      setAssessments([]);
    }
    setCourseId(next.id);
    setAssessmentId("");
    setStage("assignments");
    setError("");
    setFeedbackFor("");
    setCouncil(null);
  }

  function backToCourses() {
    setStage("courses");
    setAssessmentId("");
    setFeedbackFor("");
  }

  function openAssignment(id: string) {
    setAssessmentId(id);
    setStage("dashboard");
    setError("");
    setFeedbackFor("");
    setCouncil(null);
  }

  function backToAssignments() {
    setStage("assignments");
    setAssessmentId("");
    setFeedbackFor("");
  }

  function reviewResults(row: SubmissionRow) {
    setSent("");
    setFeedbackFor(row.group_name);
  }

  async function approve(id: string) {
    if (!id || !course || approving) return;
    setApproving(id);
    try {
      const next = await run(
        () => pa<Draft>(`/drafts/${id}/approve`, { method: "POST" }),
        setError,
      );
      if (next) await loadQueue(course.id);
    } finally {
      setApproving("");
    }
  }

  async function runCouncil(target?: SubmissionRow) {
    if (target?.quarantined) {
      setError("A quarantined file stays out of the council.");
      return;
    }
    const readable = (item: SubmissionRow) => !item.quarantined;
    const visible = (item: SubmissionRow) => readable(item) && item.group_name !== "Group B";
    const pool = assessmentId
      ? rows.some((item) => item.assessment_id === assessmentId)
        ? rows.filter((item) => item.assessment_id === assessmentId)
        : rows.filter((item) => !item.assessment_id || item.assessment_id === "None")
      : rows;
    const row =
      target ||
      pool.find((item) => item.group_name === feedbackFor && visible(item)) ||
      pool.find(visible) ||
      pool.find((item) => item.group_name === feedbackFor && readable(item)) ||
      pool.find(readable);
    if (!row) {
      setError("There is no submission the council can read yet. A quarantined file stays out.");
      return;
    }
    setGrading(true);
    setCouncilAnimating(true);
    try {
      const next = await run(
        () => pa<Draft>(`/submissions/${row.id}/grade`, { method: "POST" }),
        setError,
      );
      if (next) {
        setCouncil(next);
        setPovRevision((value) => value + 1);
        if (course) await loadQueue(course.id);
      }
    } finally {
      setGrading(false);
    }
  }

  const assessment = assessments.find((item) => item.id === assessmentId) || null;
  const legacyRows = rows.filter((item) => !item.assessment_id || item.assessment_id === "None");
  const assignmentRows = assessmentId
    ? rows.some((item) => item.assessment_id === assessmentId)
      ? rows.filter((item) => item.assessment_id === assessmentId)
      : legacyRows
    : rows;
  const graded = assignmentRows.filter((item) => isGraded(item.draft_status)).length;
  const awaiting = assignmentRows.filter((item) => item.draft_status === "draft").length;
  const chartData = tally(assignmentRows);
  const courseIntegrity = course
    ? integrity.filter(
        (item) =>
          compact(item.slug) === compact(course.code) ||
          compact(item.course) === compact(course.code),
      )
    : [];
  const integrityFlags = courseIntegrity.reduce((sum, item) => sum + (item.flagged_pairs || 0), 0);
  const integrityCases = courseIntegrity.filter((item) => (item.flagged_pairs || 0) > 0);
  const integritySlug = courseIntegrity[0]?.slug || course?.code || "";
  const uploadAssessment = assessments.find((item) => item.id === assessmentId) || assessments[0];
  if (homeLoading) {
    return (
      <p className="text-sm" aria-busy="true">
        Loading the grading workspace...
      </p>
    );
  }

  if (courses.length === 0) {
    return <Banner>{homeError || "No courses in this workspace yet."}</Banner>;
  }

  return (
    <div className="pa-dash">
      {stage === "courses" && (
        <section aria-label="Courses" className="space-y-3">
          <div className="pa-page-head">
            <h1 style={{ margin: 0, fontSize: "1.75rem", fontWeight: 400 }}>Grade</h1>
            <p>
              Pick a course, choose an assignment, then review the council draft for each group.
            </p>
          </div>
          {homeError && <p role="alert">{homeError}</p>}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {courses.map((item) => (
              <Card key={item.id} className="p-0">
                <button
                  type="button"
                  className="flex w-full items-start justify-between gap-3 p-4 text-left"
                  onClick={() => chooseCourse(item)}
                >
                  <span className="min-w-0 space-y-1">
                    <span className="block text-base font-semibold">{item.code}</span>
                    <span className="block text-sm">{item.title}</span>
                    <span className="pa-meta block">{item.term || "Term open"}</span>
                  </span>
                  <ChevronRight className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
                </button>
              </Card>
            ))}
          </div>
        </section>
      )}

      {stage === "assignments" && course && (
        <section aria-label="Assignments" className="space-y-3">
          <button
            type="button"
            className="pa-why inline-flex items-center gap-1"
            onClick={backToCourses}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to courses
          </button>
          <div className="pa-page-head">
            <p className="pa-crumb">Courses / {course.code}</p>
            <h1 style={{ margin: 0, fontSize: "1.75rem", fontWeight: 400 }}>
              {course.code} - {course.title}
            </h1>
            <p>
              {course.term || "Term open"} - {rows.length} submission
              {rows.length === 1 ? "" : "s"} in this course
            </p>
          </div>
          {error && <p role="alert">{error}</p>}
          {assessments.length === 0 && <Banner>No assignments in this course yet.</Banner>}
          <div className="grid gap-3 md:grid-cols-2">
            {assessments.map((item) => {
              const scoped = rows.filter((row) => row.assessment_id === item.id);
              const done = scoped.filter((row) => isGraded(row.draft_status)).length;
              const waiting = scoped.filter((row) => row.draft_status === "draft").length;
              return (
                <Card key={item.id} className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <button
                      type="button"
                      className="min-w-0 text-left"
                      onClick={() => openAssignment(item.id)}
                    >
                      <span className="block text-base font-semibold">{item.title}</span>
                      <span className="pa-meta block">
                        {scoped.length} submission{scoped.length === 1 ? "" : "s"} - {done} graded -{" "}
                        {waiting} awaiting
                      </span>
                    </button>
                    <div className="flex shrink-0 items-center gap-2">
                      <Badge variant="outline" className={assessmentBadgeClass(item.status)}>
                        {item.status}
                      </Badge>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Open ${item.title}`}
                        onClick={() => openAssignment(item.id)}
                      >
                        <ChevronRight aria-hidden="true" />
                      </Button>
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>
        </section>
      )}
      {stage === "dashboard" && course && (
        <section aria-label="Assignment dashboard" className="space-y-5">
          <button
            type="button"
            className="pa-why inline-flex items-center gap-1"
            onClick={backToAssignments}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to assignments
          </button>

          <div className="pa-page-head">
            <p className="pa-crumb">
              {course.code} / {assessment?.title || "Assignment"}
            </p>
            <h1 style={{ margin: 0, fontSize: "1.75rem", fontWeight: 400 }}>
              {assessment?.title || "Assignment"}
            </h1>
            <p>
              {course.title} - {course.term || "Term open"}
              {assessment ? ` - ${assessment.status}` : ""}
            </p>
          </div>

          {error && <p role="alert">{error}</p>}

          <div className="pa-kpi-row">
            <Card className="p-4">
              <p className="pa-step-kicker">Submissions</p>
              <strong className="text-[2rem] font-normal">{assignmentRows.length}</strong>
            </Card>
            <Card className="p-4">
              <p className="pa-step-kicker">Graded</p>
              <strong className="text-[2rem] font-normal">{graded}</strong>
            </Card>
            <Card className="p-4">
              <p className="pa-step-kicker">Awaiting review</p>
              <strong className="text-[2rem] font-normal">{awaiting}</strong>
            </Card>
            <Card className="p-4">
              <p className="pa-step-kicker">Integrity flags</p>
              <strong className="text-[2rem] font-normal">{integrityFlags}</strong>
            </Card>
          </div>

          <div className="pa-chart-row">
            <Card className="p-4">
              <p className="pa-step-kicker">Group status</p>
              <div style={{ height: 240 }}>
                <GradeStatusChart data={chartData} />
              </div>
            </Card>
            <Card className="p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="pa-step-kicker">Integrity</p>
                <Badge variant="outline" className={integrityBadgeClass(integrityFlags)}>
                  {integrityFlags === 0 ? "Clear" : `${integrityFlags} flagged`}
                </Badge>
              </div>
              {integrityError ? (
                <p className="pa-meta" role="alert">
                  {integrityError}
                </p>
              ) : integrityCases.length === 0 ? (
                <p className="pa-meta">No copying cases</p>
              ) : (
                <ul className="mt-2 space-y-1.5 text-sm">
                  {integrityCases.map((item) => (
                    <li
                      key={`${item.slug}-${item.number || item.title || "course"}-${item.name || ""}`}
                      className="flex items-start justify-between gap-3"
                    >
                      <span>
                        {item.number ? `Assignment ${item.number}` : item.title || item.course}
                        {item.name ? ` - ${item.name}` : ""}
                      </span>
                      <span className="pa-meta shrink-0">
                        {item.flagged_pairs} pair{item.flagged_pairs === 1 ? "" : "s"} -{" "}
                        {item.status}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <Button asChild variant="outline" size="sm" className="mt-3">
                <Link href={`/integrity?course=${encodeURIComponent(integritySlug)}`}>
                  Open integrity review
                  <ChevronRight aria-hidden="true" />
                </Link>
              </Button>
            </Card>
          </div>

          <div>
            <h2 style={{ margin: "0 0 8px", fontSize: "1.25rem", fontWeight: 400 }}>Groups</h2>
            {assignmentRows.length === 0 && (
              <p>No submissions for this assignment yet. Sync from Moodle or upload a zip.</p>
            )}
            <div className="grid gap-3 lg:grid-cols-2">
              {assignmentRows.map((row) => (
                <GroupCard
                  key={row.id}
                  row={row}
                  busy={grading}
                  revision={povRevision}
                  onRun={(item) => void runCouncil(item)}
                  onReview={reviewResults}
                />
              ))}
            </div>
          </div>
          <section id="council-result" className="pa-panel">
            <h2 style={{ marginTop: 0, fontWeight: 400 }}>Council</h2>
            <p className="pa-meta">
              {council?.grader_model
                ? `Graders: ${council.grader_model}`
                : "Graders: Offline drafter"}
            </p>
            <Button disabled={grading} onClick={() => void runCouncil()}>
              {grading ? "The council is reading..." : "Run the council"}
            </Button>
            {(grading || councilAnimating) && (
              <CouncilStage scene="grade" onDone={() => setCouncilAnimating(false)} />
            )}
            {council && (
              <div className="pa-council-list">
                {council.results.map((row) => {
                  const levels = (row.votes || []).map((vote) => vote.level).filter(Boolean);
                  const agree = levels.length === 3 && new Set(levels).size === 1;
                  const open = whyId === row.criterion;
                  return (
                    <div className="pa-council-row" key={row.criterion}>
                      <div className="pa-council-main">
                        <span>{row.criterion}</span>
                        <strong>{row.judge?.level || "no band"}</strong>
                        <span
                          className={agree ? "pa-votes is-agree" : "pa-votes is-split"}
                          aria-label={agree ? "Graders agree" : "Graders split"}
                        >
                          <i />
                          <i />
                          <i />
                        </span>
                        <button
                          type="button"
                          className="pa-why"
                          onClick={() => setWhyId(open ? "" : row.criterion)}
                        >
                          {open ? "Hide why" : "Why"}
                        </button>
                      </div>
                      {open && <p className="pa-meta">{row.judge?.why}</p>}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
          {feedbackFor ? (
            <div id="feedback-desk">
              <FeedbackDesk
                group={feedbackFor}
                courseCode={course.code}
                sent={sent}
                moodleMode={moodle?.mode || ""}
                onClose={() => setFeedbackFor("")}
                onApprove={() => {
                  const row =
                    assignmentRows.find((item) => item.group_name === feedbackFor) ||
                    rows.find((item) => item.group_name === feedbackFor);
                  if (row?.draft_id) void approve(row.draft_id);
                }}
                onSend={() => {
                  void run(
                    () =>
                      pa<{ message: string; note?: string; mode?: string }>("/grade/send", {
                        method: "POST",
                        body: JSON.stringify({ group: feedbackFor, course: course.code }),
                      }),
                    setError,
                  ).then((result) => {
                    if (!result) return;
                    setSent(
                      result.mode === "fake" ? result.note || result.message : result.message,
                    );
                    void loadQueue(course.id);
                  });
                }}
              />
            </div>
          ) : (
            <section aria-label="Results queue" className="space-y-3">
              <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 400 }}>Results queue</h2>
              {assignmentRows.length === 0 && (
                <p>No submissions yet. Sync from Moodle or upload a zip.</p>
              )}
              {assignmentRows.map((row) => (
                <article key={row.id} className="pa-panel">
                  <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 400 }}>
                    {row.group_name}
                  </h2>
                  <p style={{ margin: "4px 0 8px", color: "#525252" }}>
                    {row.topic || "No topic recorded."}
                  </p>
                  <p style={{ margin: "8px 0", color: "#525252" }}>
                    {row.files ?? 0} file{(row.files ?? 0) === 1 ? "" : "s"} -{" "}
                    {row.peer_reviews ?? 0} peer review
                    {(row.peer_reviews ?? 0) === 1 ? "" : "s"}
                  </p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <Badge
                      variant="outline"
                      className={
                        row.draft_status === "draft"
                          ? "border-purple-200 bg-purple-100 text-purple-800"
                          : isGraded(row.draft_status)
                            ? "border-emerald-200 bg-emerald-100 text-emerald-800"
                            : "border-border bg-muted text-muted-foreground"
                      }
                    >
                      {statusLabel(row.draft_status)}
                    </Badge>
                    {row.blind && <Badge variant="outline">Blind</Badge>}
                    {row.quarantined && <Badge variant="destructive">Quarantined</Badge>}
                  </div>
                  <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    {row.draft_id && row.draft_status === "draft" && (
                      <Button
                        disabled={approving === row.draft_id}
                        onClick={() => void approve(row.draft_id as string)}
                      >
                        {approving === row.draft_id ? "Approving..." : "Approve"}
                      </Button>
                    )}
                    <Button variant="secondary" onClick={() => reviewResults(row)}>
                      Change
                    </Button>
                    <Button variant="outline" onClick={() => reviewResults(row)}>
                      Give feedback
                    </Button>
                  </div>
                </article>
              ))}
              <details>
                <summary>Get more submissions</summary>
                <div className="pa-sync-strip">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={async () => {
                      const result = await run(
                        () => pa<{ last_sync_status?: string }>("/moodle/sync", { method: "POST" }),
                        setError,
                      );
                      if (result) await loadQueue(course.id);
                    }}
                  >
                    Sync from Moodle
                  </Button>
                  <input
                    ref={uploadRef}
                    type="file"
                    accept=".zip"
                    className="hidden"
                    aria-hidden="true"
                    tabIndex={-1}
                    onChange={async (event) => {
                      const file = event.target.files?.[0];
                      event.target.value = "";
                      if (!file || !uploadAssessment) return;
                      const body = new FormData();
                      body.append("file", file);
                      body.append("assessment_id", uploadAssessment.id);
                      const ok = await run(
                        () =>
                          pa(`/courses/${course.id}/submissions/upload`, {
                            method: "POST",
                            body,
                          }),
                        setError,
                      );
                      if (ok) await loadQueue(course.id);
                    }}
                  />
                  <Button variant="outline" size="sm" onClick={() => uploadRef.current?.click()}>
                    <Upload />
                    Upload a zip
                  </Button>
                </div>
              </details>
            </section>
          )}
        </section>
      )}
    </div>
  );
}

interface Band {
  name: string;
  low: number;
  high: number;
  points: number;
}
interface Grader {
  name: string;
  band: string;
  reason: string;
}
interface Criterion {
  id: string;
  name: string;
  weight: number;
  band: string;
  score: number;
  short: string;
  reason: string;
  evidence: string;
  agreed: boolean;
  page: number;
  box: Box;
  bands: Band[];
  graders: Grader[];
}
interface AiGrade {
  rubric: string;
  source: string;
  total: number;
  out_of: number;
  letter: string;
  confidence: "High" | "Medium" | "Low";
  council: Array<{ name: string; initials: string; color: string }>;
  criteria: Criterion[];
}
interface FeedbackNotes {
  group: string;
  comments: MarginNote[];
  rubric: Array<{ criterion: string; comment: string }>;
  overall: string;
  bank: string[];
  overrides?: Record<string, string>;
  ai_grade?: AiGrade;
  document: { origin: string; view: string; original: string };
}

function letterOf(score: number) {
  if (score >= 85) return "A";
  if (score >= 75) return "B";
  if (score >= 65) return "C";
  if (score >= 50) return "D";
  return "F";
}

function FeedbackDesk({
  group,
  courseCode,
  sent,
  moodleMode,
  onClose,
  onApprove,
  onSend,
}: {
  group: string;
  courseCode: string;
  sent: string;
  moodleMode: string;
  onClose: () => void;
  onApprove: () => void;
  onSend: () => void;
}) {
  const [notes, setNotes] = useState<FeedbackNotes | null>(null);
  const [notesError, setNotesError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [pick, setPick] = useState<{ page: number; quote: string; box: Box } | null>(null);
  const [comment, setComment] = useState("");
  const [bankOpen, setBankOpen] = useState(false);
  const [openRow, setOpenRow] = useState("");
  const [howOpen, setHowOpen] = useState(false);
  const [docOpen, setDocOpen] = useState(false);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [why, setWhy] = useState("");
  const [rubricOpen, setRubricOpen] = useState(false);
  const [activeHit, setActiveHit] = useState("");
  const [step, setStep] = useState(0);
  const [focus, setFocus] = useState<"overall" | number>("overall");
  const [fresh, setFresh] = useState("");

  useEffect(() => {
    let cancelled = false;
    setNotesError("");
    pa<FeedbackNotes>(
      `/grade/feedback?group=${encodeURIComponent(group)}&course=${encodeURIComponent(courseCode)}`,
    )
      .then((data) => {
        if (cancelled) return;
        setNotes(data);
        setOverrides(data.overrides || {});
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setNotes(null);
        setNotesError(err instanceof Error ? err.message : "Could not load this group's feedback.");
      });
    return () => {
      cancelled = true;
    };
  }, [group, courseCode, attempt]);

  async function persist(next: FeedbackNotes) {
    const saved = await pa<FeedbackNotes>("/grade/feedback", {
      method: "POST",
      body: JSON.stringify({
        group,
        course: courseCode,
        comments: next.comments,
        rubric: next.rubric,
        overall: next.overall,
        bank: next.bank,
        overrides: next.overrides || {},
      }),
    });
    setNotes(saved);
  }

  function insert(text: string) {
    if (!notes) return;
    if (focus === "overall") {
      const next = { ...notes, overall: `${notes.overall} ${text}`.trim() };
      setNotes(next);
      void persist(next);
      return;
    }
    const rubric = notes.rubric.map((row, index) =>
      index === focus ? { ...row, comment: `${row.comment} ${text}`.trim() } : row,
    );
    const next = { ...notes, rubric };
    setNotes(next);
    void persist(next);
  }

  if (!notes) {
    return (
      <section className="pa-panel" aria-label="Feedback">
        <h2 style={{ marginTop: 0, fontWeight: 400 }}>Feedback for {group}</h2>
        {notesError ? (
          <>
            <p role="alert" className="pa-meta">
              {notesError}
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <Button variant="secondary" onClick={() => setAttempt((count) => count + 1)}>
                Retry
              </Button>
              <Button variant="ghost" onClick={onClose}>
                Back to the queue
              </Button>
            </div>
          </>
        ) : (
          <p className="pa-meta" aria-busy="true">
            Loading this group’s feedback…
          </p>
        )}
      </section>
    );
  }
  const grade = notes.ai_grade;
  const criteria = grade?.criteria || [];
  const sendsToMoodle = moodleMode === "real";

  function chosenBand(row: Criterion) {
    return overrides[row.id] || row.band;
  }

  function chosenScore(row: Criterion) {
    const name = chosenBand(row);
    if (name === row.band) return row.score;
    return row.bands.find((band) => band.name === name)?.points ?? row.score;
  }

  const total = criteria.reduce((sum, row) => sum + chosenScore(row), 0) || grade?.total || 0;
  const letter = letterOf(total);
  const hits: Hit[] = [...criteria]
    .filter((row) => row.box)
    .sort((a, b) => a.page - b.page || a.box.y - b.box.y || a.box.x - b.box.x)
    .map((row, index) => ({
      id: row.id,
      n: index + 1,
      page: row.page,
      box: row.box,
      tone: "shared" as const,
    }));
  const evidenceNumber = new Map(hits.map((hit) => [hit.id, hit.n]));
  const checks = criteria.filter((row) => !row.agreed && !accepted[row.id]).length;

  function choose(row: Criterion, band: string) {
    if (!notes) return;
    const next = { ...overrides, [row.id]: band };
    setOverrides(next);
    setStep(1);
    void persist({ ...notes, overrides: next });
  }

  return (
    <section className="pa-feedback" aria-label="Feedback">
      <div className={docOpen ? "pa-doc-wrap is-open" : "pa-doc-wrap"}>
        <Button className="pa-doc-close" variant="ghost" onClick={() => setDocOpen(false)}>
          Close submission
        </Button>
        <DocumentPane
          url={fileUrl(notes.document.view)}
          title={group}
          kind={notes.document.origin === "docx" ? "docx" : "pdf"}
          downloadUrl={fileUrl(notes.document.original)}
          notes={notes.comments}
          hits={hits}
          activeId={activeHit}
          allowSelection
          onSelectText={(chosen) => {
            setPick(chosen);
            setComment("");
          }}
          onEditNote={(id, text) => {
            const next = {
              ...notes,
              comments: notes.comments.map((item) => (item.id === id ? { ...item, text } : item)),
            };
            setNotes(next);
          }}
          onDeleteNote={(id) => {
            const next = { ...notes, comments: notes.comments.filter((item) => item.id !== id) };
            setNotes(next);
            void persist(next);
          }}
        />
      </div>
      <aside className="pa-panel pa-grade-panel">
        <Button className="pa-view-sub" variant="outline" onClick={() => setDocOpen(true)}>
          View submission
        </Button>
        <p className="pa-grade-banner">
          The AI suggested a grade using your rubric. Check it and approve.
        </p>
        <p className="pa-grade-total">
          {total} / {grade?.out_of || 100} ({letter})
        </p>
        {checks > 0 && (
          <span className="pa-check-tag">
            Check {checks} row{checks === 1 ? "" : "s"}
          </span>
        )}
        <button type="button" className="pa-why" onClick={() => setHowOpen(true)}>
          How was this made?
        </button>
        <table className="pa-rubric">
          <thead>
            <tr>
              <th>Criterion</th>
              <th>AI score</th>
              <th>Reason</th>
              <th>
                <span className="pa-sr">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {criteria.map((row, index) => {
              const band = chosenBand(row);
              const changed = band !== row.band;
              const needs = !row.agreed && !accepted[row.id];
              const open = openRow === row.id;
              return (
                <Fragment key={row.id}>
                  <tr id={`criterion-${row.id}`}>
                    <td>
                      {needs && <i className="pa-dot" aria-hidden="true" />}
                      {row.name}
                    </td>
                    <td>
                      {chosenScore(row)}/{row.weight} {band}
                    </td>
                    <td>{row.short || row.reason}</td>
                    <td className="pa-row-actions">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="This row is fine"
                        onClick={() => {
                          setAccepted((current) => ({ ...current, [row.id]: true }));
                          setOpenRow("");
                        }}
                      >
                        <Check />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={open ? "Close this row" : "Change this row"}
                        onClick={() => setOpenRow(open ? "" : row.id)}
                      >
                        <Pencil />
                      </Button>
                    </td>
                  </tr>
                  {open && (
                    <tr className="pa-rubric-edit">
                      <td colSpan={4}>
                        <div className="pa-bands" role="group" aria-label={row.name}>
                          {row.bands.map((item) => (
                            <button
                              key={item.name}
                              type="button"
                              className={band === item.name ? "is-on" : ""}
                              aria-pressed={band === item.name}
                              onClick={() => choose(row, item.name)}
                            >
                              <strong>{item.name}</strong>
                              <span>
                                {item.low}-{item.high}
                              </span>
                              {band === item.name && (
                                <em>{changed ? "Changed by you" : "AI picked"}</em>
                              )}
                            </button>
                          ))}
                        </div>
                        <div className="pa-row-links">
                          <button
                            type="button"
                            className="pa-why"
                            onClick={() => setActiveHit(row.id)}
                          >
                            Evidence {evidenceNumber.get(row.id)}
                          </button>
                          <button
                            type="button"
                            className="pa-why"
                            onClick={() => setWhy((current) => (current === row.id ? "" : row.id))}
                          >
                            {why === row.id ? "Hide why" : "Why?"}
                          </button>
                        </div>
                        {why === row.id && (
                          <div className="pa-why-body">
                            {row.graders.map((person) => (
                              <p key={person.name}>
                                <strong>{person.name}</strong> chose {person.band}. {person.reason}
                              </p>
                            ))}
                            <p>
                              {row.agreed
                                ? "The three graders agreed."
                                : "The three graders did not agree. Please check this row."}
                            </p>
                          </div>
                        )}
                        <Label htmlFor={`rubric-${index}`} className="mt-2 inline-block">
                          Your comment
                        </Label>
                        <Textarea
                          id={`rubric-${index}`}
                          value={notes.rubric[index]?.comment || ""}
                          onFocus={() => setFocus(index)}
                          onBlur={() => void persist(notes)}
                          onChange={(event) => {
                            const rubric = notes.rubric.map((item, itemIndex) =>
                              itemIndex === index ? { ...item, comment: event.target.value } : item,
                            );
                            setNotes({ ...notes, rubric });
                          }}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        <Label htmlFor="overall-feedback">Feedback to students</Label>
        <Textarea
          id="overall-feedback"
          value={notes.overall}
          onFocus={() => setFocus("overall")}
          onBlur={() => void persist(notes)}
          onChange={(event) => setNotes({ ...notes, overall: event.target.value })}
        />
        <button type="button" className="pa-why" onClick={() => setBankOpen((open) => !open)}>
          {bankOpen ? "Hide comment bank" : "Comment bank"}
        </button>
        {bankOpen && (
          <ul className="pa-bank">
            {notes.bank.map((item) => (
              <li key={item}>
                <Badge variant="secondary">{item}</Badge>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Insert"
                  onClick={() => insert(item)}
                >
                  <Plus />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Remove"
                  onClick={() =>
                    void persist({ ...notes, bank: notes.bank.filter((row) => row !== item) })
                  }
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
        {bankOpen && (
          <>
            <Label htmlFor="bank-new">Add a reusable comment</Label>
            <Textarea
              id="bank-new"
              value={fresh}
              onChange={(event) => setFresh(event.target.value)}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (!fresh.trim()) return;
                const next = { ...notes, bank: [...notes.bank, fresh.trim()] };
                setFresh("");
                void persist(next);
              }}
            >
              Save to bank
            </Button>
          </>
        )}
        <Label htmlFor="margin-comment">Margin comment</Label>
        <Textarea
          id="margin-comment"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
        />
        {pick ? (
          <p className="pa-meta">
            Anchored to page {pick.page}: “
            {pick.quote.length > 120 ? `${pick.quote.slice(0, 120)}…` : pick.quote}”
          </p>
        ) : (
          <p className="pa-meta">Select text in the submission to anchor a margin comment.</p>
        )}
        <Button
          variant="outline"
          disabled={!pick || !comment.trim()}
          onClick={() => {
            if (!pick || !comment.trim()) return;
            const next = {
              ...notes,
              comments: [
                ...notes.comments,
                {
                  id: `you-${Date.now()}`,
                  page: pick.page,
                  box: pick.box,
                  quote: pick.quote,
                  text: comment.trim(),
                },
              ],
            };
            setComment("");
            setPick(null);
            setNotes(next);
            setDocOpen(true);
            void persist(next);
          }}
        >
          Add margin comment
        </Button>
        <div className="pa-grade-bar">
          <Button variant="secondary" onClick={() => void persist(notes)}>
            Save draft
          </Button>
          <Button
            onClick={() => {
              setStep(2);
              onApprove();
            }}
          >
            Approve grade
          </Button>
          <Button
            onClick={() => {
              setStep(3);
              onSend();
            }}
          >
            {sendsToMoodle ? "Send to Moodle" : "Record approval locally"}
          </Button>
        </div>
        {moodleMode === "fake" && (
          <p className="pa-meta">
            Moodle is not connected in this workspace. This records the approval in ProfAssist only;
            nothing is sent to Moodle.
          </p>
        )}
        {sent && <p className="pa-grade-banner">{sent}</p>}
        {howOpen && (
          <div className="pa-drawer" role="dialog" aria-label="How was this made?">
            <div className="pa-drawer-card">
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <h2 className="pa-section">How was this made?</h2>
                <Button variant="ghost" size="sm" onClick={() => setHowOpen(false)}>
                  Close
                </Button>
              </div>
              <ol className="pa-made">
                {[
                  { icon: BookOpen, label: "You set the rubric", link: true },
                  { icon: FileText, label: "AI read the submission" },
                  {
                    icon: Sparkles,
                    label: "AI filled each rubric row with a band, score, reason and evidence",
                  },
                  { icon: Check, label: "You check, change and approve" },
                ].map((item, index) => {
                  const Icon = item.icon;
                  const current = step < 2 ? index === 3 : false;
                  return (
                    <li key={item.label} className={current ? "is-now" : "is-done"}>
                      <span className="pa-made-num">{index + 1}</span>
                      <span>
                        <Icon size={16} />
                        {item.link ? (
                          <button
                            type="button"
                            className="pa-why"
                            onClick={() => setRubricOpen(true)}
                          >
                            {item.label}
                          </button>
                        ) : (
                          item.label
                        )}
                      </span>
                    </li>
                  );
                })}
              </ol>
              {grade && (
                <>
                  <Badge variant="outline" className="border-blue-200 bg-blue-100 text-blue-800">
                    {grade.confidence} confidence
                  </Badge>
                  <p>Drafted by AI council: 3 graders + chair, using the {grade.rubric}.</p>
                  <div className="pa-council">
                    {grade.council.map((person) => (
                      <span
                        key={person.name}
                        title={person.name}
                        style={{ background: person.color }}
                      >
                        {person.initials}
                      </span>
                    ))}
                  </div>
                  <ol className="pa-steps">
                    {[
                      "AI drafted",
                      "You reviewed",
                      "Approved",
                      sendsToMoodle ? "Sent to Moodle" : "Recorded locally",
                    ].map((label, index) => (
                      <li
                        key={label}
                        className={index === step ? "is-now" : index < step ? "is-done" : ""}
                      >
                        {label}
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </div>
          </div>
        )}
        <Dialog open={rubricOpen} onOpenChange={setRubricOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{grade?.rubric || "Rubric"}</DialogTitle>
              <DialogDescription>
                This rubric comes from {grade?.source}. Each row is worth the points shown.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-1 text-sm">
              {criteria.map((row) => (
                <p key={row.id}>
                  <strong>{row.name}</strong> ({row.weight} points):{" "}
                  {row.bands.map((band) => `${band.name} ${band.low}-${band.high}`).join(", ")}.
                </p>
              ))}
            </div>
          </DialogContent>
        </Dialog>
      </aside>
    </section>
  );
}
