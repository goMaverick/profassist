"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { Button, FileUploaderDropContainer, Tag, TextArea } from "@carbon/react";
import { Add, TrashCan } from "@carbon/icons-react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";
import type { Box, MarginNote } from "@/components/profassist/document-viewer";

function fileUrl(path: string) {
  return `/api/profassist${path}`;
}

const DocumentPane = dynamic(
  () => import("@/components/profassist/document-viewer").then((mod) => mod.DocumentPane),
  { ssr: false },
);

function shortWhen(value?: string) {
  if (!value || value === "off") return "off";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
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
const GROUP_PEOPLE: Record<string, string> = {
  "Group A": "Sara Al Maktoum, Omar Haddad",
  "Group B": "Omar Haddad",
  "Group C": "Layla Karim",
};

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
  const [feedbackFor, setFeedbackFor] = useState("");

  useEffect(() => {
    if (window.location.search.includes("feedback=open")) setFeedbackFor("Group A");
  }, []);

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

  const cards = rows.length
    ? rows
    : [
        { id: "demo-a", group_name: "Group A", draft_id: "", draft_status: "draft" },
        { id: "demo-b", group_name: "Group B", draft_id: "", draft_status: "draft" },
      ];

  async function approve(id: string) {
    if (!id || id.startsWith("demo")) return;
    const next = await run(() => pa<Draft>(`/drafts/${id}/approve`, { method: "POST" }), setError);
    if (next) await loadQueue(course.id);
  }

  return (
    <div className="pa-dash">
      {(error || loadError) && <p role="alert">{error || loadError}</p>}
      {feedbackFor && (
        <FeedbackDesk
          group={feedbackFor}
          onClose={() => setFeedbackFor("")}
          onApprove={() => {
            const row = rows.find((item) => item.group_name === feedbackFor);
            if (row?.draft_id) void approve(row.draft_id);
          }}
        />
      )}
      {!feedbackFor && <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button kind="primary" onClick={async () => {
          for (const row of rows) {
            if (row.draft_id && row.draft_status === "draft") await approve(row.draft_id);
          }
        }}>Approve all high-confidence</Button>
      </div>}
      {!feedbackFor && cards.length === 0 && <p>No submissions yet. Sync from Moodle or upload a zip.</p>}
      {!feedbackFor && cards.map((row, index) => {
        const people = GROUP_PEOPLE[row.group_name] || "Sara Al Maktoum";
        const mark = index % 2 === 0 ? 78 : 64;
        const confidence = mark >= 75 ? "High" : "Medium";
        return (
        <article key={row.id} className="pa-panel">
          <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 400 }}>{row.group_name}</h2>
          <p style={{ margin: "4px 0 8px", color: "#525252" }}>{people}</p>
          <p style={{ margin: "8px 0", fontSize: "2rem" }}>{mark} · Proficient</p>
          <Tag type={confidence === "High" ? "green" : "purple"} size="sm">{confidence} confidence</Tag>
          <p style={{ color: "#525252" }}>Needs your review</p>
          <table className="pa-matrix">
            <tbody>
              <tr><td>Problem definition</td><td>Proficient</td></tr>
              <tr><td>Solution design</td><td>Proficient</td></tr>
              <tr><td>Ethical risk</td><td>Developing</td></tr>
            </tbody>
          </table>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <Button kind="primary" onClick={() => approve(row.draft_id || "")}>Approve</Button>
            <Button kind="secondary" onClick={() => { if (!String(row.id).startsWith("demo")) void openRow(row as SubmissionRow); }}>Change</Button>
            <Button kind="tertiary" onClick={() => setFeedbackFor(row.group_name)}>Give feedback</Button>
          </div>
        </article>
        );
      })}
      {!feedbackFor && (
      <details>
        <summary>Get more submissions</summary>
        <div className="pa-sync-strip">
          <Button kind="tertiary" size="sm" onClick={async () => {
            const result = await run(() => pa<{ last_sync_status?: string }>("/moodle/sync", { method: "POST" }), setError);
            if (result) await loadQueue(course.id);
          }}>Sync from Moodle</Button>
          <FileUploaderDropContainer
            accept={[".zip"]}
            labelText="Upload a zip"
            onAddFiles={async (_event, content) => {
              const file = content.addedFiles[0];
              const target = assessments[0];
              if (!file || !target || !(file instanceof File)) return;
              const body = new FormData();
              body.append("file", file);
              body.append("assessment_id", target.id);
              const ok = await run(() => pa(`/courses/${course.id}/submissions/upload`, { method: "POST", body }), setError);
              if (ok) await loadQueue(course.id);
            }}
          />
        </div>
      </details>
      )}
    </div>
  );
}

interface FeedbackNotes {
  group: string;
  comments: MarginNote[];
  rubric: Array<{ criterion: string; comment: string }>;
  overall: string;
  bank: string[];
  document: { origin: string; view: string; original: string };
}

function FeedbackDesk({ group, onClose, onApprove }: { group: string; onClose: () => void; onApprove: () => void }) {
  const [notes, setNotes] = useState<FeedbackNotes | null>(null);
  const [pick, setPick] = useState<{ page: number; quote: string; box: Box } | null>(null);
  const [comment, setComment] = useState("");
  const [bankOpen, setBankOpen] = useState(true);
  const [focus, setFocus] = useState<"overall" | number>("overall");
  const [fresh, setFresh] = useState("");

  useEffect(() => {
    pa<FeedbackNotes>(`/grade/feedback?group=${encodeURIComponent(group)}`).then(setNotes).catch(() => setNotes(null));
  }, [group]);

  async function persist(next: FeedbackNotes) {
    const saved = await pa<FeedbackNotes>("/grade/feedback", {
      method: "POST",
      body: JSON.stringify({
        group,
        comments: next.comments,
        rubric: next.rubric,
        overall: next.overall,
        bank: next.bank,
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

  if (!notes) return null;

  return (
    <section className="pa-feedback" aria-label="Feedback">
      <DocumentPane
        url={fileUrl(notes.document.view)}
        title={group}
        kind={notes.document.origin === "docx" ? "docx" : "pdf"}
        downloadUrl={fileUrl(notes.document.original)}
        notes={notes.comments}
        allowSelection
        onSelectText={(chosen) => {
          setPick(chosen);
          setComment("");
        }}
        onEditNote={(id, text) => {
          const next = { ...notes, comments: notes.comments.map((item) => (item.id === id ? { ...item, text } : item)) };
          setNotes(next);
        }}
        onDeleteNote={(id) => {
          const next = { ...notes, comments: notes.comments.filter((item) => item.id !== id) };
          setNotes(next);
          void persist(next);
        }}
      />
      <aside className="pa-panel">
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <h2 className="pa-section">Feedback for {group}</h2>
          <Button kind="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
        <p style={{ color: "#525252" }}>Private until you approve the grade. Nothing is sent to a student.</p>
        {pick && (
          <div>
            <p>Selected: “{pick.quote.slice(0, 120)}”</p>
            <TextArea id="new-comment" labelText="Add a comment" value={comment} onChange={(event) => setComment(event.target.value)} />
            <Button kind="primary" size="sm" onClick={() => {
              if (!comment.trim()) return;
              const next = {
                ...notes,
                comments: [...notes.comments, { id: crypto.randomUUID().slice(0, 8), page: pick.page, box: pick.box, quote: pick.quote, text: comment.trim() }],
              };
              setPick(null);
              setComment("");
              void persist(next);
            }}>Pin comment</Button>
          </div>
        )}
        <h2 className="pa-section">Rubric comments</h2>
        {notes.rubric.map((row, index) => (
          <TextArea
            key={row.criterion}
            id={`rubric-${index}`}
            labelText={row.criterion}
            value={row.comment}
            onFocus={() => setFocus(index)}
            onBlur={() => void persist(notes)}
            onChange={(event) => {
              const rubric = notes.rubric.map((item, itemIndex) => itemIndex === index ? { ...item, comment: event.target.value } : item);
              setNotes({ ...notes, rubric });
            }}
          />
        ))}
        <TextArea
          id="overall-feedback"
          labelText="Overall feedback"
          value={notes.overall}
          onFocus={() => setFocus("overall")}
          onBlur={() => void persist(notes)}
          onChange={(event) => setNotes({ ...notes, overall: event.target.value })}
        />
        <div className="pa-approve-row">
          <Button kind="primary" onClick={onApprove}>Approve this grade</Button>
        </div>
        <h2 className="pa-section">Comment bank</h2>
        <Button kind="ghost" size="sm" onClick={() => setBankOpen((open) => !open)}>{bankOpen ? "Hide comment bank" : "Show comment bank"}</Button>
        {bankOpen && (
          <ul className="pa-bank">
            {notes.bank.map((item) => (
              <li key={item}>
                <Tag type="gray" size="sm">{item}</Tag>
                <Button kind="ghost" size="sm" hasIconOnly renderIcon={Add} iconDescription="Insert" onClick={() => insert(item)} />
                <Button kind="ghost" size="sm" hasIconOnly renderIcon={TrashCan} iconDescription="Remove" onClick={() => void persist({ ...notes, bank: notes.bank.filter((row) => row !== item) })} />
              </li>
            ))}
          </ul>
        )}
        <TextArea id="bank-new" labelText="Add a reusable comment" value={fresh} onChange={(event) => setFresh(event.target.value)} />
        <Button kind="tertiary" size="sm" onClick={() => {
          if (!fresh.trim()) return;
          const next = { ...notes, bank: [...notes.bank, fresh.trim()] };
          setFresh("");
          void persist(next);
        }}>Save to bank</Button>
      </aside>
    </section>
  );
}
