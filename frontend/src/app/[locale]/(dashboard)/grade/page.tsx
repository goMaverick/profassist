"use client";

import { useEffect, useState } from "react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";
import { CouncilStage } from "@/components/profassist/council-stage";

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
  results: Array<{
    criterion: string;
    feedback: string;
    votes: Array<{ persona: string; level: string | null; quotes: string[] }>;
    judge: { level: string | null; why: string; vote_split: Array<string | null>; quotes: string[]; evidence_status: string };
    debate_rounds?: Array<{ round: number; votes: Array<{ persona: string; level: string }> }>;
    calibrator: { status: string; message: string; applied: boolean };
  }>;
}

const LEVELS = ["beginning", "developing", "proficient", "advanced"];

export default function GradePage() {
  const { course, error: loadError, loading } = useWorkspace();
  const [error, setError] = useState("");
  const [rows, setRows] = useState<SubmissionRow[]>([]);
  const [assessments, setAssessments] = useState<AssessmentRow[]>([]);
  const [syncStatus, setSyncStatus] = useState("");
  const [moodle, setMoodle] = useState<{
    mode: string;
    paused: boolean;
    interval_minutes: number;
    next_run: string;
    next_nightly: string;
    last_sync: string;
    last_status: string;
    last_error: string;
  } | null>(null);
  const [files, setFiles] = useState<Array<{ filename: string; extracted_text: string }>>([]);
  const [peers, setPeers] = useState<Array<{ reviewer?: string; text?: string }>>([]);
  const [rubricReady, setRubricReady] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [raw, setRaw] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [feedback, setFeedback] = useState("");
  const [levels, setLevels] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function loadQueue(courseId: string) {
    const queue = await pa<{
      course: { last_sync_status?: string };
      assessment: { status: string; criteria: unknown[] } | null;
      assessments?: AssessmentRow[];
      submissions: SubmissionRow[];
    }>(`/courses/${courseId}/grade`);
    setRows(queue.submissions);
    setAssessments(queue.assessments || []);
    setSyncStatus(queue.course?.last_sync_status || "");
    const panel = await pa<NonNullable<typeof moodle>>("/moodle/status");
    setMoodle(panel);
    setRubricReady((queue.assessments || []).some((item) => item.status === "approved") || (queue.assessment?.status === "approved" && (queue.assessment.criteria?.length ?? 0) > 0));
  }

  useEffect(() => {
    if (course) loadQueue(course.id).catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, [course]);

  async function openRow(row: SubmissionRow) {
    setSelected(row.id);
    const submission = await pa<{
      raw_text: string;
      files?: Array<{ filename: string; extracted_text: string }>;
      peer_reviews?: Array<{ reviewer?: string; text?: string }>;
    }>(`/submissions/${row.id}`);
    setRaw(submission.raw_text);
    setFiles(submission.files || []);
    setPeers(submission.peer_reviews || []);
    if (row.draft_id) {
      const next = await pa<Draft>(`/drafts/${row.draft_id}`);
      setDraft(next);
      setFeedback(next.overall_feedback);
      setLevels(next.professor_levels || {});
    } else {
      setDraft(null);
      setFeedback("");
      setLevels({});
    }
  }

  if (loading) return <p className="text-sm">Loading the queue…</p>;
  if (!course) return <Banner>{loadError || "No course in this workspace."}</Banner>;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <p className="text-foreground/50 text-xs tracking-[0.18em] uppercase">{course.code}</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Review and grade</h1>
        <p className="text-foreground/70 mt-2 max-w-2xl text-sm">
          Three graders quote the submission. A judge keeps only quotes that are really there and explains the level.
          The calibrator is not trained, so nothing is a one-click accept.
        </p>
      </div>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      <div className="flex flex-wrap items-center gap-2">
        <button
          className="bg-foreground text-background rounded-lg px-3 py-2 text-sm"
          onClick={async () => {
            const result = await run(() => pa<{ last_sync_status?: string }>("/moodle/sync", { method: "POST" }), setError);
            if (result) {
              setSyncStatus(result.last_sync_status || "Synced.");
              await loadQueue(course.id);
            }
          }}
        >
          Sync now
        </button>
        {moodle && (
          <p className="text-foreground/60 text-sm">
            {moodle.mode} mode · every {moodle.interval_minutes} min
            {moodle.paused ? " · paused" : ""} · next run {moodle.next_run || "paused"} · nightly {moodle.next_nightly || "off"}
            {moodle.last_sync ? ` · last ${moodle.last_status} ${moodle.last_sync}` : ""}
            {moodle.last_error ? ` · ${moodle.last_error}` : ""}
          </p>
        )}
        {syncStatus && <p className="text-foreground/60 text-sm">{syncStatus}</p>}
        {assessments.filter((item) => item.status === "approved").map((item) => (
          <button
            key={item.id}
            className="rounded-lg border px-3 py-2 text-sm"
            onClick={async () => {
              setBusy(true);
              const result = await run(
                () => pa<{ graded: number; skipped: number }>(`/assessments/${item.id}/grade-batch`, { method: "POST" }),
                setError,
              );
              if (result) await loadQueue(course.id);
              setBusy(false);
            }}
          >
            Batch grade {item.title}
          </button>
        ))}
        <label className="text-sm">
          Upload a zip of submissions
          <input
            className="mt-1 block"
            type="file"
            accept=".zip"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              const target = assessments[0];
              if (!file || !target) return;
              const body = new FormData();
              body.append("file", file);
              body.append("assessment_id", target.id);
              const ok = await run(() => pa(`/courses/${course.id}/submissions/upload`, { method: "POST", body }), setError);
              if (ok) await loadQueue(course.id);
            }}
          />
        </label>
      </div>
      {!rubricReady && (
        <Banner>Approve a rubric on the assignment before the council can mark.</Banner>
      )}
      <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
        <ul className="flex flex-col gap-2">
          {rows.map((row) => (
            <li key={row.id}>
              <button
                className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${selected === row.id ? "border-foreground" : "border-foreground/10"}`}
                onClick={() => openRow(row).catch((err: unknown) => setError(err instanceof Error ? err.message : "Open failed"))}
              >
                <span className="font-medium">{row.group_name}</span>
                <span className="text-foreground/50 mt-1 block">
                  {row.draft_status || "not graded"}
                  {row.blind ? " · blind sample" : ""}
                  {row.files ? ` · ${row.files} files` : ""}
                  {row.peer_reviews ? ` · ${row.peer_reviews} peer reviews` : ""}
                  {row.origin === "upload" ? " · uploaded" : ""}
                </span>
              </button>
              {row.trace_url && (
                <a className="mt-1 block px-1 text-xs underline" href={row.trace_url} target="_blank" rel="noreferrer">
                  View agent trail
                </a>
              )}
            </li>
          ))}
        </ul>
        {selected && (
          <div className="flex flex-col gap-4">
            <pre className="border-foreground/10 max-h-64 overflow-auto rounded-lg border p-3 text-xs whitespace-pre-wrap">{raw}</pre>
            {files.length > 0 && (
              <div className="text-sm">
                <p className="font-medium">Attachments</p>
                {files.map((file) => (
                  <p key={file.filename} className="text-foreground/70 mt-1">
                    {file.filename}: {file.extracted_text.slice(0, 180)}
                  </p>
                ))}
              </div>
            )}
            {peers.length > 0 && (
              <div className="text-sm">
                <p className="font-medium">Peer reviews (not the grade)</p>
                {peers.map((review, index) => (
                  <p key={`${review.reviewer}-${index}`} className="text-foreground/70 mt-1">
                    {review.reviewer}: {review.text}
                  </p>
                ))}
              </div>
            )}
            {busy && <CouncilStage scene="grade" />}
            <button
              className="bg-foreground text-background w-fit rounded-lg px-3 py-2 text-sm disabled:opacity-50"
              disabled={busy || !rubricReady}
              onClick={async () => {
                setBusy(true);
                const next = await run(() => pa<Draft>(`/submissions/${selected}/grade`, { method: "POST" }), setError);
                if (next) {
                  setDraft(next);
                  setFeedback(next.overall_feedback);
                  setLevels(next.professor_levels || {});
                  await loadQueue(course.id);
                }
                setBusy(false);
              }}
            >
              {busy ? "Council is reading…" : "Run grading council"}
            </button>
            {draft && (
              <div className="flex flex-col gap-4">
                <Banner>{draft.one_click_reason}</Banner>
                {draft.blind && !draft.blind_revealed && (
                  <Banner>
                    Blind sample. Choose a level from the quotes before you reveal the council.
                    <button
                      className="ml-2 underline"
                      onClick={async () => {
                        const next = await run(() => pa<Draft>(`/drafts/${draft.id}/reveal`, { method: "POST" }), setError);
                        if (next) setDraft(next);
                      }}
                    >
                      Reveal council level
                    </button>
                  </Banner>
                )}
                {draft.results.map((result) => (
                  <article key={result.criterion} className="border-foreground/10 rounded-lg border p-3 text-sm">
                    <h3 className="font-medium">{result.criterion}</h3>
                    <p className="mt-2">{result.judge.why}</p>
                    <p className="text-foreground/60 mt-1">
                      Votes: {result.votes.map((vote) => `${vote.persona} ${vote.level ?? "—"}`).join(" · ") || "hidden"}
                    </p>
                    <ul className="mt-2 list-disc pl-5">
                      {(result.judge.quotes || []).map((quote) => (
                        <li key={quote}>&ldquo;{quote}&rdquo;</li>
                      ))}
                    </ul>
                    <p className="text-foreground/60 mt-2">{result.calibrator.message}</p>
                    {(result.debate_rounds || []).map((round) => (
                      <p key={round.round} className="mt-1">
                        Debate round {round.round}: {round.votes.map((vote) => `${vote.persona} ${vote.level}`).join(" · ")}
                      </p>
                    ))}
                    <label className="mt-3 block">
                      Your level
                      <select
                        className="border-foreground/15 mt-1 block rounded-md border bg-transparent px-2 py-1"
                        value={levels[result.criterion] || ""}
                        onChange={(event) => setLevels({ ...levels, [result.criterion]: event.target.value })}
                      >
                        <option value="">Keep the council level</option>
                        {LEVELS.map((level) => (
                          <option key={level} value={level}>{level}</option>
                        ))}
                      </select>
                    </label>
                  </article>
                ))}
                <label className="text-sm">
                  Feedback
                  <textarea
                    className="border-foreground/15 mt-1 min-h-32 w-full rounded-lg border bg-transparent p-3"
                    value={feedback}
                    onChange={(event) => setFeedback(event.target.value)}
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  <button
                    className="rounded-lg border px-3 py-2 text-sm"
                    onClick={async () => {
                      const next = await run(
                        () => pa<Draft>(`/drafts/${draft.id}/edit`, { method: "POST", body: JSON.stringify({ overall_feedback: feedback, levels }) }),
                        setError,
                      );
                      if (next) setDraft(next);
                    }}
                  >
                    Save your edit
                  </button>
                  <button
                    className="bg-foreground text-background rounded-lg px-3 py-2 text-sm disabled:opacity-50"
                    disabled={draft.status !== "draft"}
                    onClick={async () => {
                      const next = await run(() => pa<Draft>(`/drafts/${draft.id}/approve`, { method: "POST" }), setError);
                      if (next) {
                        setDraft(next);
                        await loadQueue(course.id);
                      }
                    }}
                  >
                    Approve draft
                  </button>
                  <button
                    className="bg-foreground text-background rounded-lg px-3 py-2 text-sm disabled:opacity-50"
                    disabled={draft.status !== "approved"}
                    onClick={async () => {
                      const next = await run(
                        () => pa<{ draft: Draft }>(`/drafts/${draft.id}/push`, { method: "POST" }),
                        setError,
                      );
                      if (next) {
                        setDraft(next.draft);
                        setError("Recorded locally. Moodle was not contacted.");
                        await loadQueue(course.id);
                      }
                    }}
                  >
                    Push approved grade
                  </button>
                </div>
                <p className="text-foreground/50 text-xs">
                  Status: {draft.status}.{" "}
                  {draft.status === "pushed"
                    ? "Recorded locally. Moodle was not contacted."
                    : draft.status === "approved"
                      ? "Push records this grade. In fake mode Moodle is not contacted."
                      : "Push stays off until you approve."}
                </p>
                {draft.trace_url && (
                  <a className="text-sm underline" href={draft.trace_url} target="_blank" rel="noreferrer">
                    View agent trail
                  </a>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
