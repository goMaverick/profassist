"use client";

import { useEffect, useState } from "react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";

interface SubmissionRow {
  id: string;
  group_name: string;
  topic: string;
  draft_id: string | null;
  draft_status: string | null;
  blind: boolean;
  quarantined: boolean;
  trace_url?: string;
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
    calibrator: { status: string; message: string; applied: boolean };
  }>;
}

const LEVELS = ["beginning", "developing", "proficient", "advanced"];

export default function GradePage() {
  const { course, error: loadError, loading } = useWorkspace();
  const [error, setError] = useState("");
  const [rows, setRows] = useState<SubmissionRow[]>([]);
  const [rubricReady, setRubricReady] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [raw, setRaw] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [feedback, setFeedback] = useState("");
  const [levels, setLevels] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function loadQueue(courseId: string) {
    const queue = await pa<{
      assessment: { status: string; criteria: unknown[] } | null;
      submissions: SubmissionRow[];
    }>(`/courses/${courseId}/grade`);
    setRows(queue.submissions);
    setRubricReady(queue.assessment?.status === "approved" && (queue.assessment.criteria?.length ?? 0) > 0);
  }

  useEffect(() => {
    if (course) loadQueue(course.id).catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, [course]);

  async function openRow(row: SubmissionRow) {
    setSelected(row.id);
    const submission = await pa<{ raw_text: string }>(`/submissions/${row.id}`);
    setRaw(submission.raw_text);
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
      {!rubricReady && (
        <Banner>Approve a rubric in Course studio before the council can mark.</Banner>
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
                <span className="text-foreground/50 mt-1 block">{row.draft_status || "not graded"}{row.blind ? " · blind sample" : ""}</span>
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
                    className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50"
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
                <p className="text-foreground/50 text-xs">Status: {draft.status}. Push stays disabled until you approve.</p>
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
