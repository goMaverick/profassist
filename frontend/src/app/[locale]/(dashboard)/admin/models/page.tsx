"use client";

import Link from "next/link";
import { useEffect, useId, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, FileText, GraduationCap } from "lucide-react";

import { pa, useWorkspace } from "@/components/profassist/bits";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  Input,
  Label,
  Textarea,
} from "@/components/ui";
import type { Course } from "@/lib/profassist";
import { cn } from "@/lib/utils";
import { useOrgStore } from "@/stores";

type Model = "dropout" | "reuse";
type Step = "data" | "train" | "results";
type ReleaseAction = "approve" | "rollback";

interface Assignment {
  assessment_id: string;
  course_id: string;
  number: string;
  name: string;
}

interface Job {
  job_id: string;
  operation?: string;
  status: string;
  created_at?: string | null;
  error?: string | null;
  model_version?: string | null;
  model_name?: string | null;
  snapshot_id?: string | null;
  release_id?: string | null;
  export_id?: string | null;
  gate_passed?: boolean | null;
  review_count?: number | null;
}

interface Release {
  release_id: string;
  model_name: string;
  model_version: string;
  active: boolean;
  verified: boolean;
  gate_passed: boolean;
}

interface Dataset {
  export_id: string;
  cohorts: string[];
  row_count: number;
  outcome_count: number;
  status: string;
  created_at?: string | null;
  split?: { train?: string[]; validation?: string[]; test?: string[] };
  train_cohorts?: string[];
  validation_cohorts?: string[];
  test_cohorts?: string[];
}

interface Diagnostics {
  models: Array<{
    name: string;
    status: string;
    version: string | null;
    note: string;
    features?: string[];
    license?: string;
  }>;
  mlflow: { reachable: boolean };
  settings: { worker_url_set: boolean; worker_token_set: boolean };
}

const MODELS = {
  dropout: {
    title: "Student withdrawal risk",
    summary: "Identify students who may need early support.",
    training: "ProfAssist follows the groups in your export to train and check the model.",
    metricLabels: {
      recall: "Of students who withdrew, how many the model flagged",
      precision: "Of students flagged, how many withdrew",
    },
    scope: "Approval makes this version available across the organization.",
    icon: GraduationCap,
  },
  reuse: {
    title: "Shared wording in reports",
    summary: "Highlight similar passages for a professor to review.",
    training:
      "ProfAssist trains and checks the model using the saved copy of your reviewed report pairs.",
    metricLabels: {
      recall: "Of known reused passages, how many the model flagged",
      precision: "Of passages flagged, how many were confirmed as reuse",
    },
    scope: "Approval makes this version available for the selected assignment.",
    icon: FileText,
  },
} as const;

const STEPS: Array<{ key: Step; label: string }> = [
  { key: "data", label: "Training data" },
  { key: "train", label: "Train model" },
  { key: "results", label: "Results" },
];

const selectClass =
  "border-input bg-background text-foreground focus-visible:ring-ring h-9 w-full rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:outline-none";
const number = new Intl.NumberFormat(undefined);
const percent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });

function dateLabel(date?: string | null) {
  return date ? new Date(date).toLocaleDateString(undefined, { dateStyle: "medium" }) : "";
}

function activeJob(job?: Job | null) {
  return job?.status === "queued" || job?.status === "running";
}

function eligible(release?: Release) {
  return release?.verified === true && release.gate_passed;
}

function sameVersion(a: Release, b?: Release) {
  return a.model_name === b?.model_name && a.model_version === b.model_version;
}

function datasetName(data: Dataset) {
  return [
    data.cohorts.join(", ") || "Course activity export",
    `${number.format(data.row_count)} records`,
    dateLabel(data.created_at),
  ]
    .filter(Boolean)
    .join(" · ");
}

function datasetSplit(data: Dataset) {
  return {
    train_cohorts: data.train_cohorts ?? data.split?.train ?? [],
    validation_cohorts: data.validation_cohorts ?? data.split?.validation ?? [],
    test_cohorts: data.test_cohorts ?? data.split?.test ?? [],
  };
}

function datasetIssue(data?: Dataset) {
  if (!data) return "Add a dataset for this course to get started.";
  if (data.status !== "validated") return "This dataset still needs to pass the file checks.";
  if (!data.outcome_count)
    return "Add an export with historical course outcomes to train this model.";
  const split = datasetSplit(data);
  if (!split.train_cohorts.length || !split.validation_cohorts.length) {
    return "The export needs separate groups for training and checking the model.";
  }
  return "";
}

async function post<T extends { error?: string | null }>(path: string, body?: FormData | object) {
  const result = await pa<T>(path, {
    method: "POST",
    body: body instanceof FormData ? body : body && JSON.stringify(body),
  });
  if (result.error && !("job_id" in result)) throw new Error(result.error);
  return result;
}

function Status({
  title,
  children,
  kind = "default",
}: {
  title: string;
  children?: ReactNode;
  kind?: "default" | "success" | "warning" | "destructive";
}) {
  return (
    <Alert
      role={kind === "destructive" ? "alert" : "status"}
      variant={kind}
      className="rounded-lg px-3 py-2.5"
    >
      <AlertTitle className="font-sans text-sm">{title}</AlertTitle>
      {children && <AlertDescription>{children}</AlertDescription>}
    </Alert>
  );
}

function Details({
  label,
  children,
  onOpen,
}: {
  label: string;
  children: ReactNode;
  onOpen?: () => void;
}) {
  return (
    <details
      className="border-border rounded-lg border px-3 py-2.5"
      onToggle={(event) => {
        if (event.currentTarget.open) onOpen?.();
      }}
    >
      <summary className="cursor-pointer text-sm font-medium">{label}</summary>
      <div className="mt-3 space-y-3">{children}</div>
    </details>
  );
}

export default function ModelsPage() {
  const { course: workspaceCourse, courses, loading, error } = useWorkspace();
  const [courseId, setCourseId] = useState("");
  const course = courses.find((item) => item.id === courseId) ?? workspaceCourse;
  const orgId = useOrgStore((state) => state.activeOrgId);
  return (
    <div className="max-w-5xl space-y-5">
      {course ? (
        <ModelChooser
          key={orgId}
          course={course}
          orgId={orgId}
          courseControl={
            courses.length > 1 ? (
              <label className="flex max-w-full items-center gap-2 text-sm">
                Course
                <select
                  className={cn(selectClass, "min-w-0")}
                  value={course.id}
                  onChange={(event) => setCourseId(event.target.value)}
                >
                  {courses.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.code}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <Badge variant="outline" title={course.title}>
                Course {course.code}
              </Badge>
            )
          }
        />
      ) : (
        <Status
          title={loading ? "Loading the current course…" : "Choose a course"}
          kind={error ? "destructive" : "default"}
        >
          {error ||
            (!loading && (
              <Link href="/dashboard" className="underline">
                Open the workspace to select a course
              </Link>
            ))}
        </Status>
      )}
      <DiagnosticsPanel key={orgId} orgId={orgId} />
    </div>
  );
}

function ModelChooser({
  course,
  orgId,
  courseControl,
}: {
  course: Course;
  orgId: string | null;
  courseControl: ReactNode;
}) {
  const [model, setModel] = useState<Model>("dropout");
  const [assignmentId, setAssignmentId] = useState("");
  const assignments = useQuery({
    queryKey: ["model-assignments", orgId, course.id, course.code],
    queryFn: async ({ signal }) => {
      const response = await pa<{ items: Assignment[] }>(
        `/integrity/overview?course=${encodeURIComponent(course.code)}`,
        { signal },
      );
      return response.items.filter((item) => item.assessment_id && item.course_id === course.id);
    },
    enabled: model === "reuse",
  });
  const assignment =
    assignments.data?.find((item) => item.assessment_id === assignmentId) ?? assignments.data?.[0];
  return (
    <div className="space-y-4">
      <fieldset className="min-w-0">
        <legend className="sr-only">Choose a model</legend>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-medium" aria-hidden="true">
            Choose a model
          </h2>
          {courseControl}
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {(["dropout", "reuse"] as const).map((value) => {
            const { title, summary, icon: Icon } = MODELS[value];
            return (
              <Label
                key={value}
                className={cn(
                  "border-border bg-card hover:bg-accent/50 flex cursor-pointer items-start gap-3 rounded-lg border p-3",
                  model === value && "border-brand/50 bg-brand/[0.06]",
                )}
              >
                <input
                  type="radio"
                  name="model-purpose"
                  className="accent-primary mt-0.5 shrink-0"
                  checked={model === value}
                  onChange={() => setModel(value)}
                />
                <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
                <span className="space-y-1">
                  <span className="block font-semibold">{title}</span>
                  <span className="text-muted-foreground block text-xs font-normal">{summary}</span>
                </span>
              </Label>
            );
          })}
        </div>
      </fieldset>
      <ModelWorkflow
        key={`${course.id}:${model}:${assignment?.assessment_id ?? ""}`}
        model={model}
        orgId={orgId}
        course={course}
        assignment={assignment}
        assignments={assignments.data ?? []}
        loadingAssignments={assignments.isPending}
        assignmentError={assignments.error?.message}
        onAssignment={setAssignmentId}
      />
    </div>
  );
}

function ModelWorkflow({
  model,
  orgId,
  course,
  assignment,
  assignments,
  loadingAssignments,
  assignmentError,
  onAssignment,
}: {
  model: Model;
  orgId: string | null;
  course: Course;
  assignment?: Assignment;
  assignments: Assignment[];
  loadingAssignments: boolean;
  assignmentError?: string;
  onAssignment: (id: string) => void;
}) {
  const dropout = model === "dropout";
  const settings = MODELS[model];
  const cache = useQueryClient();
  const [step, setStep] = useState<Step>("data");
  const [dataId, setDataId] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [startedId, setStartedId] = useState("");
  const [resultId, setResultId] = useState("");
  const [identityMap, setIdentityMap] = useState("");
  const encodedCourse = encodeURIComponent(course.id);
  const scope = `course_id=${encodedCourse}&assessment_id=${encodeURIComponent(assignment?.assessment_id ?? "")}`;
  const jobsKey = ["models", orgId, "jobs", model, course.id, assignment?.assessment_id] as const;
  const releaseCourseId = dropout ? null : course.id;
  const releaseAssignmentId = dropout ? null : assignment?.assessment_id;
  const releasesKey = useMemo(
    () => ["models", orgId, "releases", model, releaseCourseId, releaseAssignmentId] as const,
    [orgId, model, releaseCourseId, releaseAssignmentId],
  );
  const exportsKey = ["models", orgId, "exports", course.id] as const;
  const jobs = useQuery({
    queryKey: jobsKey,
    enabled: dropout || Boolean(assignment),
    queryFn: async ({ signal }) => {
      const url = dropout
        ? `/admin/ml/dropout/jobs?course_id=${encodedCourse}`
        : `/admin/ml/jobs?${scope}`;
      const result = await pa<{ items: Job[] }>(url, { signal });
      return result.items.filter((job) =>
        job.operation?.startsWith(dropout ? "dropout-" : "plagiarism-"),
      );
    },
    refetchInterval: (query) => (query.state.data?.some(activeJob) ? 2500 : false),
  });
  const releases = useQuery({
    queryKey: releasesKey,
    enabled: dropout || Boolean(assignment),
    queryFn: async ({ signal }) => {
      const url = dropout
        ? "/admin/ml/dropout/releases"
        : `/admin/ml/releases?model_kind=plagiarism&${scope}`;
      return (await pa<{ items: Release[] }>(url, { signal })).items;
    },
    refetchInterval: jobs.data?.some(activeJob) ? 2500 : false,
  });
  const datasets = useQuery({
    queryKey: exportsKey,
    enabled: dropout,
    queryFn: async ({ signal }) =>
      (
        await pa<{ items: Dataset[] }>(`/admin/ml/dropout/exports?course_id=${encodedCourse}`, {
          signal,
        })
      ).items,
  });
  const rows = jobs.data ?? [];
  const releaseRows = releases.data ?? [];
  const activeRelease = releaseRows.find((release) => release.active && eligible(release));
  const versions = releaseRows.filter((release, index) =>
    sameVersion(release, activeRelease)
      ? release.release_id === activeRelease?.release_id
      : releaseRows.findIndex((candidate) => sameVersion(candidate, release)) === index,
  );
  const trainingRuns = rows.filter(
    (job) => job.operation === (dropout ? "dropout-train" : "plagiarism-train"),
  );
  const preparing = rows.find((job) => job.operation === "plagiarism-snapshot" && activeJob(job));
  const currentlyTraining = trainingRuns.find(activeJob);
  const snapshots = rows.filter(
    (job) => job.operation === "plagiarism-snapshot" && job.snapshot_id,
  );
  const snapshot = snapshots.find((job) => job.snapshot_id === dataId) ?? snapshots[0];
  const saved = datasets.data ?? [];
  const dataset =
    saved.find((item) => item.export_id === dataId) ??
    saved.find((item) => !datasetIssue(item)) ??
    saved[0];
  const problem = datasetIssue(dataset);
  const ready = dropout ? !problem : snapshot?.status === "completed";
  const result = trainingRuns.find((job) => job.job_id === resultId) ?? trainingRuns[0];
  const candidate =
    result?.status === "completed" && result.gate_passed === true
      ? (releaseRows.find((release) => release.release_id === result.release_id) ??
        (dropout && result.model_name && result.model_version
          ? releaseRows.find(
              (release) =>
                release.model_name === result.model_name &&
                release.model_version === result.model_version,
            )
          : undefined))
      : undefined;
  const resultRelease =
    candidate && sameVersion(candidate, activeRelease) ? activeRelease : candidate;
  const resultDataset = saved.find((item) => item.export_id === result?.export_id);
  const started = trainingRuns.find((job) => job.job_id === startedId);
  const metrics = useQuery({
    queryKey: ["models", orgId, "metrics", result?.job_id],
    enabled: step === "results" && result?.status === "completed",
    queryFn: ({ signal }) =>
      pa<Partial<Record<"precision" | "recall", number>>>(
        `/admin/ml/jobs/${result!.job_id}/metrics`,
        { signal },
      ),
    retry: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!started || activeJob(started)) return;
    setResultId(started.job_id);
    if (step === "train") setStep("results");
    setStartedId("");
    void cache.invalidateQueries({ queryKey: releasesKey });
  }, [started, step, cache, releasesKey]);

  function go(next: Step) {
    setStep(next);
    setError("");
    setMessage("");
  }

  async function work(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function rememberJob(job: Job, operation: string) {
    cache.setQueryData<Job[]>(jobsKey, (old = []) => {
      const existing = old.find((row) => row.job_id === job.job_id);
      const updated = { ...existing, ...job, operation: job.operation || operation };
      return [updated, ...old.filter((row) => row.job_id !== job.job_id)];
    });
    void cache.invalidateQueries({ queryKey: jobsKey });
    void cache.invalidateQueries({ queryKey: releasesKey });
  }

  async function addDataset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const outcomes = form.get("outcomes_file");
    if (outcomes instanceof File && !outcomes.name) form.delete("outcomes_file");
    form.set("course_id", course.id);
    await work(async () => {
      const added = await post<Dataset & { error?: string }>("/admin/ml/dropout/exports", form);
      cache.setQueryData<Dataset[]>(exportsKey, (old = []) => [
        added,
        ...old.filter((entry) => entry.export_id !== added.export_id),
      ]);
      setDataId(added.export_id);
      setUploadOpen(false);
      void cache.invalidateQueries({ queryKey: exportsKey });
    });
  }

  async function prepare() {
    if (!assignment || preparing) return;
    await work(async () => {
      const job = await post<Job>("/admin/ml/plagiarism/snapshot", {
        course_id: course.id,
        assessment_id: assignment.assessment_id,
      });
      rememberJob(job, "plagiarism-snapshot");
      if (job.snapshot_id) setDataId(job.snapshot_id);
    });
  }

  async function train() {
    if (!ready || currentlyTraining) return;
    await work(async () => {
      const job =
        dropout && dataset
          ? await post<Job>("/admin/ml/dropout/train", {
              export_id: dataset.export_id,
              ...datasetSplit(dataset),
            })
          : await post<Job>("/admin/ml/plagiarism/train", { snapshot_id: snapshot?.snapshot_id });
      rememberJob(job, dropout ? "dropout-train" : "plagiarism-train");
      setStartedId(job.job_id);
    });
  }

  async function changeRelease(release: Release, action: ReleaseAction, reason: string) {
    await work(async () => {
      const base = dropout ? "/admin/ml/dropout/releases" : "/admin/ml/releases";
      await post<{ error?: string }>(`${base}/${release.release_id}/${action}`, { reason });
      await cache.invalidateQueries({ queryKey: releasesKey });
      setMessage(
        action === "approve" ? "Model approved for use." : "Previous model version restored.",
      );
    });
  }

  async function runDropoutOperation(operation: "score" | "monitor") {
    if (!dataset || !activeRelease) return;
    await work(async () => {
      const body: Record<string, unknown> = { export_id: dataset.export_id };
      if (operation === "score") {
        let parsed: unknown;
        try {
          parsed = JSON.parse(identityMap);
        } catch {
          throw new Error("Enter a valid JSON student identity map.");
        }
        if (
          !Array.isArray(parsed) ||
          !parsed.length ||
          parsed.some(
            (row) =>
              !row ||
              typeof row.student_key !== "string" ||
              !row.student_key.trim() ||
              typeof row.moodle_student_id !== "string" ||
              !row.moodle_student_id.trim(),
          )
        ) {
          throw new Error("Each row needs a student key and a Moodle student ID.");
        }
        body.identity_map = parsed;
      }
      const job = await post<Job>(`/admin/ml/dropout/${operation}`, body);
      rememberJob(job, `dropout-${operation}`);
      setMessage(
        job.error ||
          (operation === "score" ? "Student scoring requested." : "Model monitoring requested."),
      );
    });
  }

  const mainError =
    error ||
    jobs.error?.message ||
    releases.error?.message ||
    (dropout ? datasets.error?.message : assignmentError);
  return (
    <div className="space-y-3">
      {mainError && (
        <Status title="Action needed" kind="destructive">
          {mainError}
        </Status>
      )}
      {message && <Status title={message} kind="success" />}
      <Card className="border-border overflow-hidden">
        <nav
          aria-label="Model workflow"
          className="border-border bg-muted/40 grid grid-cols-3 border-b"
        >
          {STEPS.map(({ key, label }, index) => (
            <Button
              key={key}
              type="button"
              variant="ghost"
              aria-current={key === step ? "step" : undefined}
              className={cn(
                "h-auto min-h-11 gap-2 rounded-none border-b-2 border-transparent px-2 py-2 whitespace-normal",
                key === step && "border-brand bg-card",
              )}
              onClick={() => go(key)}
              disabled={key === "train" && !ready && !currentlyTraining}
            >
              <span
                aria-hidden="true"
                className="bg-muted grid size-5 shrink-0 place-items-center rounded-full text-xs"
              >
                {index + 1}
              </span>
              {label}
            </Button>
          ))}
        </nav>
        <section className="space-y-4 p-4 sm:p-5">
          {step === "data" && (
            <>
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Choose training data</h2>
                <p className="text-muted-foreground text-sm">
                  {dropout
                    ? "Use past student activity and known course outcomes."
                    : "Use report pairs already reviewed in Integrity."}
                </p>
              </div>
              {dropout ? (
                <>
                  <label className="grid max-w-lg gap-1.5 text-sm font-medium">
                    Saved dataset
                    <select
                      className={selectClass}
                      value={dataset?.export_id ?? ""}
                      disabled={!saved.length}
                      onChange={(event) => setDataId(event.target.value)}
                    >
                      {saved.length ? (
                        saved.map((item) => (
                          <option key={item.export_id} value={item.export_id}>
                            {datasetName(item)}
                          </option>
                        ))
                      ) : (
                        <option value="">
                          {datasets.isPending ? "Loading datasets…" : "No saved datasets"}
                        </option>
                      )}
                    </select>
                  </label>
                  {datasets.isPending ? (
                    <Status title="Loading training data…" />
                  ) : ready && dataset ? (
                    <Status title="Ready to train" kind="success">
                      {number.format(dataset.outcome_count)} student outcomes included.
                    </Status>
                  ) : (
                    <Status title="More data needed" kind="warning">
                      {problem}
                    </Status>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    aria-expanded={uploadOpen}
                    aria-controls="model-add-dataset"
                    onClick={() => setUploadOpen((open) => !open)}
                  >
                    {uploadOpen ? "Close dataset form" : "Add a dataset"}
                  </Button>
                  {uploadOpen && (
                    <form
                      id="model-add-dataset"
                      onSubmit={addDataset}
                      className="border-border space-y-3 rounded-lg border p-3"
                    >
                      <p className="text-muted-foreground text-sm">
                        Choose the files from the same export. Historical outcomes are required for
                        training.
                      </p>
                      <div className="grid gap-3 lg:grid-cols-3">
                        <UploadField
                          name="snapshots_file"
                          label="Student activity (CSV)"
                          description="Activity through day 35."
                          accept=".csv,text/csv"
                          required
                        />
                        <UploadField
                          name="outcomes_file"
                          label="Course outcomes (CSV)"
                          description="Required for training."
                          accept=".csv,text/csv"
                        />
                        <UploadField
                          name="manifest_file"
                          label="Export information (JSON)"
                          description="The manifest supplied with the export."
                          accept=".json,application/json"
                          required
                        />
                      </div>
                      <Button type="submit" size="sm" disabled={busy}>
                        Check and add dataset
                      </Button>
                    </form>
                  )}
                </>
              ) : (
                <>
                  <label className="grid max-w-lg gap-1.5 text-sm font-medium">
                    Assignment
                    <select
                      className={selectClass}
                      value={assignment?.assessment_id ?? ""}
                      disabled={!assignments.length}
                      onChange={(event) => onAssignment(event.target.value)}
                    >
                      {assignments.length ? (
                        assignments.map((item) => (
                          <option key={item.assessment_id} value={item.assessment_id}>
                            Assignment {item.number} · {item.name}
                          </option>
                        ))
                      ) : (
                        <option value="">
                          {loadingAssignments ? "Loading assignments…" : "No submitted assignments"}
                        </option>
                      )}
                    </select>
                  </label>
                  {snapshots.length > 1 && (
                    <label className="grid max-w-lg gap-1.5 text-sm font-medium">
                      Saved copy of report reviews
                      <select
                        className={selectClass}
                        value={snapshot?.snapshot_id ?? ""}
                        onChange={(event) => setDataId(event.target.value)}
                      >
                        {snapshots.map((item) => (
                          <option key={item.job_id} value={item.snapshot_id ?? ""}>
                            {dateLabel(item.created_at) || "Saved copy"} · {statusLabel(item)}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {preparing ? (
                    <Status title="Preparing training data">
                      ProfAssist is checking and saving the reviewed report pairs.
                    </Status>
                  ) : ready ? (
                    <Status title="Ready to train" kind="success">
                      {snapshot?.review_count
                        ? `${number.format(snapshot.review_count)} reviewed report pairs in the saved copy.`
                        : "A checked copy of the report reviews is available."}
                    </Status>
                  ) : snapshot?.status === "failed" ? (
                    <Status title="Training data could not be prepared" kind="warning">
                      {snapshot.error || "Check the report reviews and try again."}
                    </Status>
                  ) : (
                    <Status
                      title={
                        assignment && jobs.isPending
                          ? "Checking saved training data…"
                          : assignment
                            ? "Prepare the reviewed reports"
                            : "Select an assignment"
                      }
                    >
                      {assignment &&
                        "Save a complete pair review in Integrity, then prepare a copy for training."}
                    </Status>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!assignment || busy || Boolean(preparing) || jobs.isLoading}
                      onClick={() => void prepare()}
                    >
                      {ready ? "Prepare from latest reviews" : "Prepare training data"}
                    </Button>
                    <Button asChild variant="ghost" size="sm">
                      <Link
                        href={
                          assignment
                            ? `/integrity?course=${encodeURIComponent(course.code)}&assignment=${encodeURIComponent(assignment.number)}`
                            : "/integrity"
                        }
                      >
                        Open Integrity reviews
                      </Link>
                    </Button>
                  </div>
                </>
              )}
              <div className="border-border flex flex-wrap justify-between gap-2 border-t pt-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setResultId("");
                    go("results");
                  }}
                >
                  See latest results
                </Button>
                <Button onClick={() => go("train")} disabled={!ready || Boolean(preparing)}>
                  Continue to training
                  <ArrowRight aria-hidden="true" />
                </Button>
              </div>
            </>
          )}
          {step === "train" && (
            <>
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Train a new version</h2>
                <p className="text-muted-foreground text-sm">{settings.training}</p>
              </div>
              {currentlyTraining ? (
                <Status
                  title={
                    currentlyTraining.status === "queued"
                      ? "Training queued"
                      : "Training in progress"
                  }
                >
                  Results will appear here when training and checks finish.
                </Status>
              ) : (
                <Status
                  title={ready ? "Ready to start" : "More data needed"}
                  kind={ready ? "success" : "warning"}
                >
                  {dropout && dataset ? datasetName(dataset) : assignment?.name}
                </Status>
              )}
              <div className="border-border flex flex-wrap justify-between gap-2 border-t pt-3">
                <Button variant="outline" onClick={() => go("data")}>
                  <ArrowLeft aria-hidden="true" /> Back to training data
                </Button>
                <Button
                  disabled={!ready || busy || Boolean(currentlyTraining) || Boolean(preparing)}
                  onClick={() => void train()}
                >
                  {currentlyTraining ? "Training…" : busy ? "Starting…" : "Start training"}
                </Button>
              </div>
            </>
          )}
          {step === "results" && (
            <>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h2 className="text-lg font-semibold tracking-tight">Training results</h2>
                  <p className="text-muted-foreground text-sm">
                    {resultDataset
                      ? datasetName(resultDataset)
                      : dropout
                        ? course.code
                        : assignment?.name}
                  </p>
                </div>
                {activeRelease && (
                  <Badge variant="outline">In use · Version {activeRelease.model_version}</Badge>
                )}
              </div>
              {trainingRuns.length > 1 && (
                <label className="grid max-w-lg gap-1.5 text-sm font-medium">
                  Training run
                  <select
                    className={selectClass}
                    value={result?.job_id ?? ""}
                    onChange={(event) => setResultId(event.target.value)}
                  >
                    {!result && <option value="">Choose a run</option>}
                    {trainingRuns.map((job) => (
                      <option key={job.job_id} value={job.job_id}>
                        {dateLabel(job.created_at) || "Training run"} · {statusLabel(job)}
                        {job.status === "completed" && job.model_version
                          ? ` · Version ${job.model_version}`
                          : ""}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {!result ? (
                <Status
                  title={
                    currentlyTraining
                      ? "Training in progress"
                      : jobs.isLoading
                        ? "Loading training results…"
                        : "No training results yet"
                  }
                >
                  {currentlyTraining
                    ? "Results will appear after the required checks finish."
                    : !jobs.isLoading &&
                      "Choose training data and start training to see a result here."}
                </Status>
              ) : result.status === "completed" ? (
                <>
                  <Status
                    title={
                      resultRelease?.active
                        ? "Approved and in use"
                        : result.gate_passed === false
                          ? "Required checks did not pass"
                          : eligible(resultRelease)
                            ? "Ready for approval"
                            : "Training complete"
                    }
                    kind={
                      result.gate_passed === false
                        ? "warning"
                        : eligible(resultRelease)
                          ? "success"
                          : "default"
                    }
                  >
                    {result.gate_passed === false
                      ? "This version cannot be approved. Review the results or try another dataset."
                      : eligible(resultRelease)
                        ? "This version passed the required checks."
                        : "Approval is available after release verification."}
                  </Status>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {(["recall", "precision"] as const).map((key) => {
                      const value = metrics.data?.[key];
                      if (typeof value !== "number") return null;
                      return (
                        <div
                          key={key}
                          className="border-border bg-muted/35 rounded-lg border px-3 py-2"
                        >
                          <p className="text-lg font-semibold">{percent.format(value)}</p>
                          <p className="text-muted-foreground text-xs">
                            {settings.metricLabels[key]}.
                          </p>
                        </div>
                      );
                    })}
                  </div>
                  <p className="text-muted-foreground text-xs">
                    {metrics.isFetching
                      ? "Loading validation results…"
                      : metrics.data && Object.keys(metrics.data).length
                        ? "Measured on examples held apart for validation."
                        : "Detailed validation metrics are unavailable for this run."}
                  </p>
                  {resultRelease && eligible(resultRelease) && !resultRelease.active && (
                    <ReleaseForm
                      key={resultRelease.release_id}
                      scope={settings.scope}
                      busy={busy}
                      onSubmit={(reason) => changeRelease(resultRelease, "approve", reason)}
                    />
                  )}
                </>
              ) : result.status === "failed" ? (
                <Status title="Training could not finish" kind="warning">
                  {result.error || "Check the training data and try again."}
                </Status>
              ) : (
                <Status title={statusLabel(result)}>
                  Results will appear after the required checks finish.
                </Status>
              )}
              <div className="border-border flex flex-wrap justify-between gap-2 border-t pt-3">
                <Button variant="outline" onClick={() => go("data")}>
                  Choose training data
                </Button>
                {activeRelease && (
                  <Button asChild variant="outline">
                    <Link href={dropout ? "/students" : "/integrity"}>
                      {dropout ? "Open Students at risk" : "Open Integrity"}
                    </Link>
                  </Button>
                )}
              </div>
            </>
          )}
        </section>
      </Card>
      <Details label="Run history and model versions">
        {rows.length ? (
          <ul className="divide-border divide-y text-sm">
            {rows.map((job) => (
              <li
                key={job.job_id}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <div>
                  <strong>{operationLabel(job.operation)}</strong>
                  <span className="text-muted-foreground ml-2 text-xs">
                    {dateLabel(job.created_at)}
                  </span>
                  {job.error && <p className="text-destructive text-xs">{job.error}</p>}
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{statusLabel(job)}</Badge>
                  {trainingRuns.includes(job) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setResultId(job.job_id);
                        go("results");
                      }}
                    >
                      View run
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">No activity for this selection.</p>
        )}
        {versions.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-medium">
              {dropout ? "Organization-wide versions" : "Assignment versions"}
            </h3>
            {versions.map((release) => (
              <div
                className="border-border space-y-2 rounded-md border p-2"
                key={release.release_id}
              >
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span>Version {release.model_version}</span>
                  <Badge variant="outline">
                    {release.active
                      ? "In use"
                      : eligible(release)
                        ? "Available for approval"
                        : "Unavailable"}
                  </Badge>
                </div>
                {!release.active && eligible(release) && (
                  <ReleaseForm
                    scope={settings.scope}
                    busy={busy}
                    allowRestore
                    onSubmit={(reason, action) => changeRelease(release, action, reason)}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </Details>
      {dropout && (
        <Details label="Score students or monitor the active model">
          <p className="text-muted-foreground text-sm">
            {activeRelease
              ? "Use the dataset selected above. Scoring also requires the student identity map."
              : "Approve a verified version before scoring students or monitoring its performance."}
          </p>
          <Label htmlFor="model-identity-map">Student identity map (JSON)</Label>
          <Textarea
            id="model-identity-map"
            value={identityMap}
            onChange={(event) => setIdentityMap(event.target.value)}
            placeholder='[{"student_key":"export-key","moodle_student_id":"student-id"}]'
          />
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={busy || !activeRelease || !dataset || !identityMap.trim()}
              onClick={() => void runDropoutOperation("score")}
            >
              Score current students
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || !activeRelease || !dataset}
              onClick={() => void runDropoutOperation("monitor")}
            >
              Monitor active model
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link href="/admin/integrations/moodle">Moodle import</Link>
            </Button>
          </div>
        </Details>
      )}
    </div>
  );
}

function UploadField({
  name,
  label,
  description,
  accept,
  required,
}: {
  name: string;
  label: string;
  description: string;
  accept: string;
  required?: boolean;
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <Label htmlFor={name}>{label}</Label>
      <Input
        id={name}
        name={name}
        type="file"
        accept={accept}
        required={required}
        aria-describedby={`${name}-help`}
      />
      <p id={`${name}-help`} className="text-muted-foreground text-xs">
        {description}
      </p>
    </div>
  );
}

function ReleaseForm({
  scope,
  busy,
  allowRestore,
  onSubmit,
}: {
  scope: string;
  busy: boolean;
  allowRestore?: boolean;
  onSubmit: (reason: string, action: ReleaseAction) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const reasonId = useId();
  return (
    <Details label={allowRestore ? "Change the active version" : "Approve for use"}>
      <p className="text-muted-foreground text-sm">{scope}</p>
      <div className="grid max-w-lg gap-1.5">
        <Label htmlFor={reasonId}>Reason for this decision</Label>
        <Input
          id={reasonId}
          value={reason}
          maxLength={2000}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={busy || !reason.trim()}
          onClick={() => void onSubmit(reason.trim(), "approve")}
        >
          Approve version
        </Button>
        {allowRestore && (
          <Button
            variant="outline"
            size="sm"
            disabled={busy || !reason.trim()}
            onClick={() => void onSubmit(reason.trim(), "rollback")}
          >
            Restore this version
          </Button>
        )}
      </div>
    </Details>
  );
}

function operationLabel(operation?: string) {
  switch (operation) {
    case "plagiarism-snapshot":
      return "Prepare reviewed reports";
    case "dropout-train":
    case "plagiarism-train":
      return "Train model";
    case "dropout-score":
      return "Score students";
    case "dropout-monitor":
      return "Monitor model";
    default:
      return "Check reports";
  }
}

function statusLabel(job: Job) {
  switch (job.status) {
    case "queued":
      return "Queued";
    case "running":
      return "In progress";
    case "completed":
      return job.gate_passed === false ? "Checks did not pass" : "Complete";
    case "failed":
      return "Needs attention";
    default:
      return job.status;
  }
}

function DiagnosticsPanel({ orgId }: { orgId: string | null }) {
  const [open, setOpen] = useState(false);
  const [showContract, setShowContract] = useState(false);
  const [probe, setProbe] = useState("");
  const [checking, setChecking] = useState(false);
  const details = useQuery({
    queryKey: ["models", orgId, "diagnostics"],
    queryFn: ({ signal }) => pa<Diagnostics>("/admin/ml/models", { signal }),
    enabled: open,
  });
  const contract = useQuery({
    queryKey: ["models", orgId, "contract"],
    queryFn: ({ signal }) => pa<object>("/admin/ml/plagiarism/contract", { signal }),
    enabled: showContract,
  });

  async function testWorker() {
    setChecking(true);
    try {
      const response = await pa<{ reachable: boolean | null; error?: string }>(
        "/admin/ml/plagiarism/probe",
        { method: "POST" },
      );
      setProbe(
        response.reachable
          ? "Training service reachable."
          : response.error || "Training service unavailable.",
      );
    } catch (cause) {
      setProbe(cause instanceof Error ? cause.message : "Could not check the training service.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <Details label="Technical details for admins" onOpen={() => setOpen(true)}>
      {details.isFetching && (
        <p className="text-muted-foreground text-sm">Loading service status…</p>
      )}
      {details.error && (
        <p role="alert" className="text-destructive text-sm">
          {details.error.message}
        </p>
      )}
      {details.data && (
        <ul className="text-muted-foreground space-y-1 text-sm">
          <li>Model registry {details.data.mlflow.reachable ? "available" : "unavailable"}</li>
          <li>
            Training service{" "}
            {details.data.settings.worker_url_set ? "configured" : "not configured"} · Access token{" "}
            {details.data.settings.worker_token_set ? "set" : "not set"}
          </li>
          {details.data.models.map((item) => (
            <li key={item.name}>
              <details>
                <summary className="cursor-pointer">
                  {item.name} ·{" "}
                  {item.version ? `Version ${item.version}` : item.status.replaceAll("_", " ")}
                </summary>
                {item.note && <p>{item.note}</p>}
                {item.license && <p>License {item.license}</p>}
                {item.features?.length ? <p>Input fields {item.features.join(", ")}</p> : null}
              </details>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" disabled={checking} onClick={() => void testWorker()}>
          {checking ? "Checking…" : "Check training service"}
        </Button>
        <Button asChild variant="ghost" size="sm">
          <Link href="/admin/ai">AI settings</Link>
        </Button>
      </div>
      {probe && (
        <p role="status" className="text-muted-foreground text-sm">
          {probe}
        </p>
      )}
      <Details label="Worker API contract" onOpen={() => setShowContract(true)}>
        {contract.isFetching && <p className="text-muted-foreground text-sm">Loading contract…</p>}
        {contract.error && (
          <p role="alert" className="text-destructive text-sm">
            {contract.error.message}
          </p>
        )}
        {contract.data && (
          <pre className="bg-muted overflow-auto rounded-md p-3 text-xs">
            {JSON.stringify(contract.data, null, 2)}
          </pre>
        )}
      </Details>
    </Details>
  );
}
