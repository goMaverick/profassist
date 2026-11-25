"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";
import { Badge, Button, Card, Label, Textarea } from "@/components/ui";

interface ModelCard {
  name: string;
  kind: string;
  status: string;
  version: string | null;
  source: string;
  license: string;
  data_needed: string;
  synthetic?: boolean;
  threshold?: number;
  bands?: string[];
  threshold_note?: string;
  note: string;
  features?: string[];
}

interface ModelsView {
  models: ModelCard[];
  mlflow: { reachable: boolean; tracking_uri?: string | null };
  settings: {
    worker_url_set: boolean;
    worker_token_set: boolean;
    worker_host?: string | null;
    env_only: boolean;
  };
}

interface ProbeView {
  configured: boolean;
  reachable: boolean | null;
  status: string;
  probe: boolean;
  token_set: boolean;
  worker_url_set: boolean;
  worker_host?: string | null;
  error?: string;
}

interface ContractView {
  schema_version: string;
  endpoint: string;
  timeout_seconds: number;
  request: Record<string, unknown>;
  response: Record<string, unknown>;
  threshold_note: string;
  license: string;
}

interface AssignmentOption {
  assessment_id: string;
  course_id: string;
  number: string;
  name: string;
}

interface MlJob {
  job_id: string;
  operation?: string;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
  error?: string | null;
  model_version?: string | null;
  snapshot_id?: string | null;
}

interface ModelRelease {
  release_id: string;
  model_name: string;
  model_version: string;
  active: boolean;
  verified: boolean;
  gate_passed: boolean;
  snapshot_id?: string | null;
  created_at?: string | null;
  action?: string;
}

interface DropoutExport {
  export_id: string;
  course_id: string;
  external_export_id?: string | null;
  schema_version?: string;
  cohorts: string[];
  train_cohorts?: string[];
  validation_cohorts?: string[];
  test_cohorts?: string[];
  split?: { train: string[]; validation: string[]; test: string[] };
  row_count: number;
  outcome_count?: number;
  checksum: string;
  created_at?: string | null;
  status: string;
}

interface IdentityMapRow {
  student_key: string;
  moodle_student_id: string;
}

const TONE = {
  ready: "border-transparent bg-emerald-100 text-emerald-800 hover:bg-emerald-100",
  warn: "border-transparent bg-amber-100 text-amber-800 hover:bg-amber-100",
  off: "border-transparent bg-slate-100 text-slate-700 hover:bg-slate-100",
  bad: "border-transparent bg-red-100 text-red-800 hover:bg-red-100",
} as const;

function tone(status: string) {
  if (status === "ready" || status === "configured") return TONE.ready;
  if (status === "not_trained" || status === "not_installed") return TONE.warn;
  return TONE.off;
}

function label(status: string) {
  return status.replaceAll("_", " ");
}

function whyNotReady(card: ModelCard) {
  if (card.name === "student-dropout") {
    if (card.status !== "ready") {
      return "No loadable model bundle is present. The adapter reports not_trained and every student stays unscored.";
    }
    return "The bundle is a synthetic demo. ProfAssist does not import day-35 Moodle activity yet, so no real student is scored.";
  }
  if (card.status !== "configured") {
    return "PLAGIARISM_WORKER_URL is not set. The gateway refuses to score and returns a fixed 503.";
  }
  return "The worker URL is set. Run Test worker to confirm the external service answers /health.";
}

export default function ModelsPage() {
  const { course } = useWorkspace();
  const [view, setView] = useState<ModelsView | null>(null);
  const [contract, setContract] = useState<ContractView | null>(null);
  const [probe, setProbe] = useState<ProbeView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [assignments, setAssignments] = useState<AssignmentOption[]>([]);
  const [assessmentId, setAssessmentId] = useState("");
  const [jobs, setJobs] = useState<MlJob[]>([]);
  const [releases, setReleases] = useState<ModelRelease[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [releaseReason, setReleaseReason] = useState("");
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const hasActiveJobs = jobs.some((job) => job.status === "queued" || job.status === "running");
  const [snapshotsFile, setSnapshotsFile] = useState<File | null>(null);
  const [manifestFile, setManifestFile] = useState<File | null>(null);
  const [outcomesFile, setOutcomesFile] = useState<File | null>(null);
  const [dropoutExports, setDropoutExports] = useState<DropoutExport[]>([]);
  const [dropoutExportId, setDropoutExportId] = useState("");
  const [identityMapText, setIdentityMapText] = useState("");
  const [dropoutJobs, setDropoutJobs] = useState<MlJob[]>([]);
  const [dropoutReleases, setDropoutReleases] = useState<ModelRelease[]>([]);
  const [dropoutReleaseReason, setDropoutReleaseReason] = useState("");
  const hasActiveDropoutJobs = dropoutJobs.some(
    (job) => job.status === "queued" || job.status === "running",
  );
  const hasActiveDropoutRelease = dropoutReleases.some(
    (release) => release.active && release.verified && release.gate_passed,
  );

  useEffect(() => {
    Promise.all([
      pa<ModelsView>("/admin/ml/models"),
      pa<ContractView>("/admin/ml/plagiarism/contract").catch(() => null),
    ])
      .then(([data, details]) => {
        setView(data);
        setContract(details);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not load the ML control room"),
      );
  }, []);

  useEffect(() => {
    if (!course) return;
    pa<{ items: AssignmentOption[] }>(
      `/integrity/overview?course=${encodeURIComponent(course.code)}`,
    )
      .then((data) => {
        const rows = data.items.map((item) => ({
          assessment_id: item.assessment_id,
          course_id: item.course_id,
          number: item.number,
          name: item.name,
        }));
        setAssignments(rows);
        setAssessmentId((current) =>
          rows.some((item) => item.assessment_id === current)
            ? current
            : rows[0]?.assessment_id || "",
        );
      })
      .catch(() => setAssignments([]));
  }, [course]);

  useEffect(() => {
    if (!course || !assessmentId) {
      setJobs([]);
      setReleases([]);
      return;
    }
    let stopped = false;
    const query = `course_id=${encodeURIComponent(course.id)}&assessment_id=${encodeURIComponent(assessmentId)}`;
    Promise.all([
      pa<{ items: MlJob[] }>(`/admin/ml/jobs?${query}`),
      pa<{ items: ModelRelease[] }>(`/admin/ml/releases?model_kind=plagiarism&${query}`),
    ])
      .then(([jobData, releaseData]) => {
        if (!stopped) {
          setJobs(jobData.items || []);
          setReleases(releaseData.items || []);
        }
      })
      .catch((err: unknown) => {
        if (!stopped)
          setError(err instanceof Error ? err.message : "Could not load model workflow");
      });
    return () => {
      stopped = true;
    };
  }, [course, assessmentId]);

  useEffect(() => {
    if (!course || !assessmentId || !hasActiveJobs) return;
    let stopped = false;
    const query = `course_id=${encodeURIComponent(course.id)}&assessment_id=${encodeURIComponent(assessmentId)}`;
    const timer = window.setInterval(() => {
      Promise.all([
        pa<{ items: MlJob[] }>(`/admin/ml/jobs?${query}`),
        pa<{ items: ModelRelease[] }>(`/admin/ml/releases?model_kind=plagiarism&${query}`),
      ])
        .then(([jobData, releaseData]) => {
          if (!stopped) {
            setJobs(jobData.items || []);
            setReleases(releaseData.items || []);
          }
        })
        .catch(() => undefined);
    }, 2500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [course, assessmentId, hasActiveJobs]);

  useEffect(() => {
    if (!course) return;
    const query = `course_id=${encodeURIComponent(course.id)}`;
    Promise.all([
      pa<{ items: DropoutExport[] }>(`/admin/ml/dropout/exports?${query}`),
      pa<{ items: MlJob[] }>(`/admin/ml/dropout/jobs?${query}`),
      pa<{ items: ModelRelease[] }>("/admin/ml/dropout/releases"),
    ])
      .then(([exportData, jobData, releaseData]) => {
        const exported = exportData.items || [];
        const dropout = (jobData.items || []).filter((job) =>
          job.operation?.startsWith("dropout-"),
        );
        setDropoutExports(exported);
        setDropoutJobs(dropout);
        setDropoutReleases(releaseData.items || []);
        setDropoutExportId((current) => current || exported[0]?.export_id || "");
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not load dropout model workflow"),
      );
  }, [course]);

  useEffect(() => {
    if (!course || !hasActiveDropoutJobs) return;
    let stopped = false;
    const query = `course_id=${encodeURIComponent(course.id)}`;
    const timer = window.setInterval(() => {
      Promise.all([
        pa<{ items: MlJob[] }>(`/admin/ml/dropout/jobs?${query}`),
        pa<{ items: ModelRelease[] }>("/admin/ml/dropout/releases"),
      ])
        .then(([jobData, releaseData]) => {
          if (!stopped) {
            setDropoutJobs(
              (jobData.items || []).filter((job) => job.operation?.startsWith("dropout-")),
            );
            setDropoutReleases(releaseData.items || []);
          }
        })
        .catch(() => undefined);
    }, 2500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [course, hasActiveDropoutJobs]);

  const selectedSnapshotJob = jobs.find(
    (job) => job.snapshot_id === snapshotId && job.operation === "plagiarism-snapshot",
  );
  const snapshotReady = selectedSnapshotJob?.status === "completed";

  async function testWorker() {
    setBusy(true);
    setProbe(null);
    const result = await run(
      () => pa<ProbeView>("/admin/ml/plagiarism/probe", { method: "POST" }),
      setError,
    );
    if (result) setProbe(result);
    setBusy(false);
  }

  async function startWorkflow(path: string, body: Record<string, string>) {
    setWorkflowBusy(true);
    const result = await run(
      () => pa<MlJob>(path, { method: "POST", body: JSON.stringify(body) }),
      setError,
    );
    if (result) {
      if (result.error) {
        setError(result.error);
        setWorkflowBusy(false);
        return;
      }
      if (result.snapshot_id) setSnapshotId(result.snapshot_id);
      if (course && assessmentId) {
        const query = `course_id=${encodeURIComponent(course.id)}&assessment_id=${encodeURIComponent(assessmentId)}`;
        const [jobData, releaseData] = await Promise.all([
          pa<{ items: MlJob[] }>(`/admin/ml/jobs?${query}`),
          pa<{ items: ModelRelease[] }>(`/admin/ml/releases?model_kind=plagiarism&${query}`),
        ]);
        setJobs(jobData.items || []);
        setReleases(releaseData.items || []);
      }
    }
    setWorkflowBusy(false);
  }

  async function releaseAction(releaseId: string, action: "approve" | "rollback") {
    if (!releaseReason.trim()) {
      setError("Add a reason before changing the active model release.");
      return;
    }
    setWorkflowBusy(true);
    const result = await run(
      () =>
        pa<ModelRelease>(`/admin/ml/releases/${releaseId}/${action}`, {
          method: "POST",
          body: JSON.stringify({ reason: releaseReason.trim() }),
        }),
      setError,
    );
    if (result && course && assessmentId) {
      const query = `course_id=${encodeURIComponent(course.id)}&assessment_id=${encodeURIComponent(assessmentId)}`;
      const data = await pa<{ items: ModelRelease[] }>(
        `/admin/ml/releases?model_kind=plagiarism&${query}`,
      );
      setReleases(data.items || []);
      setReleaseReason("");
    }
    setWorkflowBusy(false);
  }

  async function uploadDropoutExport() {
    if (!course || !snapshotsFile || !manifestFile) {
      setError("Choose the snapshot CSV and its manifest JSON first.");
      return;
    }
    const form = new FormData();
    form.append("course_id", course.id);
    form.append("snapshots_file", snapshotsFile);
    form.append("manifest_file", manifestFile);
    if (outcomesFile) form.append("outcomes_file", outcomesFile);
    setWorkflowBusy(true);
    const result = await run(
      () =>
        pa<DropoutExport & { error?: string }>("/admin/ml/dropout/exports", {
          method: "POST",
          body: form,
        }),
      setError,
    );
    if (result?.error) setError(result.error);
    if (result && !result.error) {
      setDropoutExportId(result.export_id);
      const [exportData, jobData, releaseData] = await Promise.all([
        pa<{ items: DropoutExport[] }>(
          `/admin/ml/dropout/exports?course_id=${encodeURIComponent(course.id)}`,
        ),
        pa<{ items: MlJob[] }>(`/admin/ml/dropout/jobs?course_id=${encodeURIComponent(course.id)}`),
        pa<{ items: ModelRelease[] }>("/admin/ml/dropout/releases"),
      ]);
      setDropoutExports(exportData.items || []);
      setDropoutJobs((jobData.items || []).filter((job) => job.operation?.startsWith("dropout-")));
      setDropoutReleases(releaseData.items || []);
    }
    setWorkflowBusy(false);
  }

  async function startDropoutJob(operation: "score" | "train" | "monitor") {
    if (!dropoutExportId) {
      setError("Choose a validated day-35 export first.");
      return;
    }
    let body: Record<string, unknown> = { export_id: dropoutExportId };
    if (operation === "score") {
      let identityMap: IdentityMapRow[];
      try {
        identityMap = JSON.parse(identityMapText) as IdentityMapRow[];
        if (
          !Array.isArray(identityMap) ||
          identityMap.some((row) => !row.student_key || !row.moodle_student_id)
        ) {
          throw new Error("Each mapping needs a student_key and moodle_student_id.");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Enter a valid JSON identity map.");
        return;
      }
      body = { ...body, identity_map: identityMap };
    }
    if (operation === "train") {
      const selected = dropoutExports.find((item) => item.export_id === dropoutExportId);
      const split = selected?.split;
      const train = selected?.train_cohorts || split?.train;
      const validation = selected?.validation_cohorts || split?.validation;
      const test = selected?.test_cohorts || split?.test;
      if (!train?.length || !validation?.length || !test?.length) {
        setError(
          "The selected manifest does not report its train, validation, and test cohort split.",
        );
        return;
      }
      body = { ...body, train_cohorts: train, validation_cohorts: validation, test_cohorts: test };
    }
    setWorkflowBusy(true);
    const result = await run(
      () =>
        pa<MlJob & { error?: string }>(`/admin/ml/dropout/${operation}`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      setError,
    );
    if (result?.error) setError(result.error);
    if (result && !result.error && course) {
      const [jobData, releaseData] = await Promise.all([
        pa<{ items: MlJob[] }>(`/admin/ml/dropout/jobs?course_id=${encodeURIComponent(course.id)}`),
        pa<{ items: ModelRelease[] }>("/admin/ml/dropout/releases"),
      ]);
      setDropoutJobs((jobData.items || []).filter((job) => job.operation?.startsWith("dropout-")));
      setDropoutReleases(releaseData.items || []);
    }
    setWorkflowBusy(false);
  }

  async function dropoutReleaseAction(releaseId: string, action: "approve" | "rollback") {
    if (!dropoutReleaseReason.trim()) {
      setError("Add a reason before changing the active dropout release.");
      return;
    }
    setWorkflowBusy(true);
    const result = await run(
      () =>
        pa<ModelRelease>(`/admin/ml/dropout/releases/${releaseId}/${action}`, {
          method: "POST",
          body: JSON.stringify({ reason: dropoutReleaseReason.trim() }),
        }),
      setError,
    );
    if (result) {
      const data = await pa<{ items: ModelRelease[] }>("/admin/ml/dropout/releases");
      setDropoutReleases(data.items || []);
      setDropoutReleaseReason("");
    }
    setWorkflowBusy(false);
  }

  if (!view && !error) return <p className="text-sm">Loading ML control room...</p>;
  if (!view) return <Banner>{error}</Banner>;

  const dropout = view.models.find((card) => card.name === "student-dropout");
  const reuse = view.models.find((card) => card.name === "passage-reuse");
  const features = dropout?.features ?? [];
  const workerHost = view.settings.worker_host;

  return (
    <div className="flex max-w-5xl flex-col gap-3 text-sm">
      {error && <Banner>{error}</Banner>}

      <div className="grid gap-3 md:grid-cols-2">
        <Card className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-medium">Student dropout</h2>
              <p className="text-foreground/60 text-xs">
                Course-withdrawal early warning. Advisory only: it never enrols, messages, or grades
                a student.
              </p>
            </div>
            <Badge variant="outline" className={tone(dropout?.status ?? "not_trained")}>
              {label(dropout?.status ?? "not_trained")}
            </Badge>
          </div>

          <dl className="mt-3 grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-foreground/60">Synthetic</dt>
            <dd>
              {dropout?.synthetic
                ? "Yes - demo artifact, not real student data"
                : "No synthetic flag reported"}
            </dd>
            <dt className="text-foreground/60">Threshold</dt>
            <dd>
              {dropout?.threshold !== undefined ? dropout.threshold : "not set"}
              <span className="text-foreground/50"> (the bundle owns this value)</span>
            </dd>
            <dt className="text-foreground/60">Features</dt>
            <dd>
              {features.length || 14} required
              <details className="mt-1">
                <summary className="text-foreground/60 cursor-pointer">Show feature names</summary>
                <ul className="mt-1 grid gap-0.5 pl-4">
                  {features.map((feature) => (
                    <li key={feature}>
                      <code className="text-[11px]">{feature}</code>
                    </li>
                  ))}
                </ul>
              </details>
            </dd>

            <dt className="text-foreground/60">Data needed</dt>
            <dd>{dropout?.data_needed}</dd>
            <dt className="text-foreground/60">License</dt>
            <dd>{dropout?.license}</dd>
            <dt className="text-foreground/60">Version</dt>
            <dd>{dropout?.version ?? "not reported"}</dd>
          </dl>

          <p className="text-foreground/60 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs">
            <strong className="text-foreground">Why not production-ready:</strong>{" "}
            {dropout ? whyNotReady(dropout) : "The gateway did not return a dropout card."}
          </p>

          <div className="mt-3 flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/students">At-risk students</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/integrations/moodle">Moodle import</Link>
            </Button>
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-medium">Passage reuse / plagiarism</h2>
              <p className="text-foreground/60 text-xs">
                Integrity signal from an external worker. The worker owns the model, threshold, and
                matching.
              </p>
            </div>
            <Badge variant="outline" className={tone(reuse?.status ?? "not_installed")}>
              {label(reuse?.status ?? "not_installed")}
            </Badge>
          </div>

          <dl className="mt-3 grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-foreground/60">Worker URL</dt>
            <dd>
              {view.settings.worker_url_set ? (
                <>
                  set
                  {workerHost ? (
                    <>
                      {" | "}
                      <code className="text-[11px]">{workerHost}</code>
                    </>
                  ) : (
                    <span className="text-foreground/50"> | host hidden</span>
                  )}
                </>
              ) : (
                "not set"
              )}
            </dd>
            <dt className="text-foreground/60">Token</dt>
            <dd>{view.settings.worker_token_set ? "set, hidden" : "not set"}</dd>
            <dt className="text-foreground/60">Threshold</dt>
            <dd>{reuse?.threshold_note ?? "not reported"}</dd>

            <dt className="text-foreground/60">Data needed</dt>
            <dd>{reuse?.data_needed}</dd>
            <dt className="text-foreground/60">License</dt>
            <dd>{reuse?.license}</dd>
            <dt className="text-foreground/60">Version</dt>
            <dd>{reuse?.version ?? "not reported"}</dd>
          </dl>

          <p className="text-foreground/60 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs">
            <strong className="text-foreground">Why not production-ready:</strong>{" "}
            {reuse ? whyNotReady(reuse) : "The gateway did not return a passage-reuse card."}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void testWorker()}>
              {busy ? "Testing..." : "Test worker"}
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/integrity">Open integrity</Link>
            </Button>
            <span className="text-foreground/50 text-xs">3-second /health timeout</span>
          </div>

          {probe && (
            <div
              className={`mt-3 rounded-lg border px-2.5 py-2 text-xs ${
                probe.reachable ? TONE.ready : TONE.bad
              }`}
            >
              <strong>{probe.reachable ? "Worker reachable" : "Worker not reachable"}</strong>
              <span className="ml-2">
                configured {String(probe.configured)} | reachable {String(probe.reachable)}
                {probe.worker_host ? ` | host ${probe.worker_host}` : ""}
              </span>
              <p className="mt-1">{probe.error ?? `Status: ${label(probe.status)}.`}</p>
            </div>
          )}
        </Card>
      </div>

      <Card className="p-3">
        <p className="text-foreground/70 text-xs">
          <strong className="text-foreground">
            No pass/fail model exists in the upstream repo.
          </strong>{" "}
          Dropout predicts withdrawal; plagiarism predicts text reuse.
        </p>
      </Card>

      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-medium">Student dropout exports and jobs</h2>
            <p className="text-foreground/60 mt-1 text-xs">
              Upload a validated day-35 export, score current students with an explicit identity
              map, or train and monitor using the immutable manifest split.
            </p>
          </div>
          <Badge variant="outline">{course?.code || "No course selected"}</Badge>
        </div>

        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <label className="grid gap-1 text-xs">
            <span className="text-foreground/60">Day-35 snapshots CSV</span>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setSnapshotsFile(event.target.files?.[0] || null)}
            />
          </label>
          <label className="grid gap-1 text-xs">
            <span className="text-foreground/60">Export manifest JSON</span>
            <input
              type="file"
              accept=".json,application/json"
              onChange={(event) => setManifestFile(event.target.files?.[0] || null)}
            />
          </label>
          <label className="grid gap-1 text-xs">
            <span className="text-foreground/60">Historical outcomes CSV (training only)</span>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setOutcomesFile(event.target.files?.[0] || null)}
            />
          </label>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={workflowBusy || !course || !snapshotsFile || !manifestFile}
            onClick={() => void uploadDropoutExport()}
          >
            Validate and upload export
          </Button>
          <label className="grid gap-1 text-xs">
            <span className="text-foreground/60">Validated export</span>
            <select
              className="bg-background h-9 min-w-72 rounded-md border px-2 text-sm"
              value={dropoutExportId}
              onChange={(event) => setDropoutExportId(event.target.value)}
              disabled={!dropoutExports.length}
            >
              {dropoutExports.length ? (
                dropoutExports.map((item) => (
                  <option key={item.export_id} value={item.export_id}>
                    {item.status} · {item.row_count} rows ·{" "}
                    {item.cohorts?.join(", ") || "cohorts unavailable"}
                  </option>
                ))
              ) : (
                <option value="">No validated exports</option>
              )}
            </select>
          </label>
          {(() => {
            const selected = dropoutExports.find((item) => item.export_id === dropoutExportId);
            return selected ? (
              <span className="text-foreground/50 text-xs">
                {selected.outcome_count != null ? `${selected.outcome_count} outcomes · ` : ""}
                SHA-256 <code>{selected.checksum}</code>
              </span>
            ) : null;
          })()}
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="grid gap-1 text-xs">
            <Label htmlFor="dropout-identity-map" className="text-foreground/60">
              Current student identity map (JSON)
            </Label>
            <Textarea
              id="dropout-identity-map"
              rows={4}
              value={identityMapText}
              onChange={(event) => setIdentityMapText(event.target.value)}
              placeholder={
                '[{"student_key":"pseudonym-from-export","moodle_student_id":"current-Moodle-ID"}]'
              }
            />
            <span className="text-foreground/50">
              Sent with the score request to join eligible export rows to this course&apos;s roster;
              it is not included in the training export.
            </span>
          </div>
          <div className="flex flex-wrap content-start items-start gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={
                workflowBusy ||
                !dropoutExportId ||
                !identityMapText.trim() ||
                !hasActiveDropoutRelease
              }
              onClick={() => void startDropoutJob("score")}
            >
              Score current students
            </Button>
            <Button
              size="sm"
              disabled={workflowBusy || !dropoutExportId}
              onClick={() => void startDropoutJob("train")}
            >
              Train dropout candidate
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={workflowBusy || !dropoutExportId || !hasActiveDropoutRelease}
              onClick={() => void startDropoutJob("monitor")}
            >
              Monitor active release
            </Button>
          </div>
        </div>
        {!hasActiveDropoutRelease && (
          <p className="text-foreground/50 mt-2 text-xs">
            Scoring and monitoring stay disabled until an approved, verified dropout release passes
            its gate.
          </p>
        )}

        {dropoutExports.length > 0 &&
          dropoutExportId &&
          (() => {
            const selected = dropoutExports.find((item) => item.export_id === dropoutExportId);
            const train = selected?.train_cohorts || selected?.split?.train || [];
            const validation = selected?.validation_cohorts || selected?.split?.validation || [];
            const test = selected?.test_cohorts || selected?.split?.test || [];
            return (
              <p className="text-foreground/50 mt-2 text-xs">
                Training split from the manifest: train [{train.join(", ")}], validation [
                {validation.join(", ")}], test [{test.join(", ")}]. The exact arrays are sent
                unchanged.
              </p>
            );
          })()}

        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <section>
            <h3 className="text-sm font-medium">Dropout jobs</h3>
            {dropoutJobs.length ? (
              <ul className="mt-2 grid gap-2">
                {dropoutJobs.map((job) => (
                  <li key={job.job_id} className="rounded-md border p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className={tone(job.status)}>
                        {label(job.status)}
                      </Badge>
                      <span>{label(job.operation || "dropout job")}</span>
                      {job.model_version && <code>{job.model_version}</code>}
                    </div>
                    {job.error && <p className="mt-1 text-red-700">{job.error}</p>}
                    <code className="text-foreground/50">{job.job_id}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-foreground/50 mt-2 text-xs">No dropout jobs yet.</p>
            )}
          </section>
          <section>
            <h3 className="text-sm font-medium">Organization-wide dropout releases</h3>
            {dropoutReleases.length ? (
              <ul className="mt-2 grid gap-2">
                {dropoutReleases.map((release) => (
                  <li key={release.release_id} className="rounded-md border p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <strong>
                        {release.model_name} · {release.model_version}
                      </strong>
                      {release.active && (
                        <Badge variant="outline" className={TONE.ready}>
                          active
                        </Badge>
                      )}
                      <Badge
                        variant="outline"
                        className={release.verified && release.gate_passed ? TONE.ready : TONE.warn}
                      >
                        {release.verified && release.gate_passed
                          ? "verified · gate passed"
                          : "not eligible"}
                      </Badge>
                    </div>
                    {!release.active && release.verified && release.gate_passed && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={workflowBusy}
                          onClick={() => void dropoutReleaseAction(release.release_id, "approve")}
                        >
                          Approve candidate
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={workflowBusy}
                          onClick={() => void dropoutReleaseAction(release.release_id, "rollback")}
                        >
                          Restore this version
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-foreground/50 mt-2 text-xs">
                No dropout releases have been registered.
              </p>
            )}
            <label className="mt-3 grid gap-1 text-xs">
              <span className="text-foreground/60">Release decision reason</span>
              <input
                className="bg-background h-9 rounded-md border px-2"
                value={dropoutReleaseReason}
                onChange={(event) => setDropoutReleaseReason(event.target.value)}
                placeholder="Why is this version being activated or restored?"
              />
            </label>
          </section>
        </div>
      </Card>

      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-medium">Plagiarism training and releases</h2>
            <p className="text-foreground/60 mt-1 text-xs">
              Review report pairs in Integrity, freeze a complete reviewed snapshot, train a
              candidate, then approve or roll back a verified release.
            </p>
          </div>
          <Badge variant="outline">{course?.code || "No course selected"}</Badge>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="grid gap-1 text-xs">
            <span className="text-foreground/60">Assignment</span>
            <select
              className="bg-background h-9 min-w-64 rounded-md border px-2 text-sm"
              value={assessmentId}
              onChange={(event) => {
                setAssessmentId(event.target.value);
                setSnapshotId("");
              }}
              disabled={!assignments.length}
            >
              {assignments.length ? (
                assignments.map((item) => (
                  <option key={item.assessment_id} value={item.assessment_id}>
                    Assignment {item.number} · {item.name}
                  </option>
                ))
              ) : (
                <option value="">No submitted assignments</option>
              )}
            </select>
          </label>
          <Button
            variant="outline"
            size="sm"
            disabled={workflowBusy || !course || !assessmentId}
            onClick={() =>
              void startWorkflow("/admin/ml/plagiarism/snapshot", {
                course_id: course!.id,
                assessment_id: assessmentId,
              })
            }
          >
            Freeze reviewed snapshot
          </Button>
          <Button
            size="sm"
            disabled={workflowBusy || !snapshotId || !snapshotReady}
            onClick={() =>
              void startWorkflow("/admin/ml/plagiarism/train", { snapshot_id: snapshotId })
            }
          >
            Train candidate
          </Button>
        </div>
        {snapshotId && (
          <p className="text-foreground/60 mt-2 text-xs">
            Snapshot: <code>{snapshotId}</code> ·{" "}
            {snapshotReady ? "ready for training" : "waiting for snapshot job"}
          </p>
        )}
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <section>
            <h3 className="text-sm font-medium">Jobs</h3>
            {jobs.length ? (
              <ul className="mt-2 grid gap-2">
                {jobs.map((job) => (
                  <li key={job.job_id} className="rounded-md border p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className={tone(job.status)}>
                        {label(job.status)}
                      </Badge>
                      <span>{label(job.operation || "model job")}</span>
                      {job.model_version && <code>{job.model_version}</code>}
                      {job.snapshot_id && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setSnapshotId(job.snapshot_id || "")}
                        >
                          Use snapshot
                        </Button>
                      )}
                    </div>
                    {job.error && <p className="mt-1 text-red-700">{job.error}</p>}
                    <code className="text-foreground/50">{job.job_id}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-foreground/50 mt-2 text-xs">No training jobs yet.</p>
            )}
          </section>
          <section>
            <h3 className="text-sm font-medium">Releases</h3>
            {releases.length ? (
              <ul className="mt-2 grid gap-2">
                {releases.map((release) => (
                  <li key={release.release_id} className="rounded-md border p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <strong>
                        {release.model_name} · {release.model_version}
                      </strong>
                      {release.active && (
                        <Badge variant="outline" className={TONE.ready}>
                          active
                        </Badge>
                      )}
                      <Badge
                        variant="outline"
                        className={release.verified && release.gate_passed ? TONE.ready : TONE.warn}
                      >
                        {release.verified && release.gate_passed
                          ? "verified · gate passed"
                          : "not eligible"}
                      </Badge>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {!release.active && release.verified && release.gate_passed && (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={workflowBusy}
                            onClick={() => void releaseAction(release.release_id, "approve")}
                          >
                            Approve candidate
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={workflowBusy}
                            onClick={() => void releaseAction(release.release_id, "rollback")}
                          >
                            Restore this version
                          </Button>
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-foreground/50 mt-2 text-xs">No releases for this assignment.</p>
            )}
            <label className="mt-3 grid gap-1 text-xs">
              <span className="text-foreground/60">Decision reason</span>
              <input
                className="bg-background h-9 rounded-md border px-2"
                value={releaseReason}
                onChange={(event) => setReleaseReason(event.target.value)}
                placeholder="Why is this version being activated or restored?"
              />
            </label>
          </section>
        </div>
      </Card>

      <Card className="p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-medium">MLflow registry</h2>
            <Badge variant="outline" className={view.mlflow.reachable ? TONE.ready : TONE.warn}>
              {view.mlflow.reachable ? "reachable" : "unreachable"}
            </Badge>
            <code className="text-foreground/60 text-xs">
              {view.mlflow.tracking_uri || "tracking URI not set"}
            </code>
          </div>
          <Link className="text-xs underline" href="/admin/ai">
            AI settings
          </Link>
        </div>
        {!view.mlflow.reachable && (
          <p className="text-foreground/60 mt-2 text-xs">
            Restart hint: start it with <code>docker compose up -d mlflow</code>, or set{" "}
            <code>MLFLOW_TRACKING_URI</code> and restart the API.
          </p>
        )}
      </Card>

      {contract && (
        <Card className="p-3">
          <details>
            <summary className="cursor-pointer text-sm font-medium">
              Worker JSON contract (v{contract.schema_version})
            </summary>
            <p className="text-foreground/60 mt-2 text-xs">
              Static from docs/ml.md. It contains no secrets and no worker URL.
            </p>
            <pre className="bg-foreground/[0.03] mt-2 overflow-x-auto rounded-lg p-3 text-xs">
              {JSON.stringify(contract, null, 2)}
            </pre>
          </details>
        </Card>
      )}
    </div>
  );
}
