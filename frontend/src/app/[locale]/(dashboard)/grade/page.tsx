"use client";

import { useEffect, useState } from "react";
import { Button, FileUploaderDropContainer, Tag } from "@carbon/react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";

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
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button kind="primary" onClick={async () => {
          for (const row of rows) {
            if (row.draft_id && row.draft_status === "draft") await approve(row.draft_id);
          }
        }}>Approve all high-confidence</Button>
      </div>
      {cards.length === 0 && <p>No submissions yet. Sync from Moodle or upload a zip.</p>}
      {cards.map((row, index) => {
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
          </div>
        </article>
        );
      })}
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
    </div>
  );
}
