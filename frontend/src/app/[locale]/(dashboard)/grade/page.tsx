"use client";

import { Fragment, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { Button, FileUploaderDropContainer, Modal, Tag, TextArea } from "@carbon/react";
import { Add, Catalog, Checkmark, DocumentView, Edit, TrashCan, Watson } from "@carbon/icons-react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";
import type { Box, Hit, MarginNote } from "@/components/profassist/document-viewer";

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
  const [feedbackFor, setFeedbackFor] = useState("Group A");
  const [sent, setSent] = useState("");

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
          courseCode={course.code}
          sent={sent}
          onClose={() => setFeedbackFor("")}
          onApprove={() => {
            const row = rows.find((item) => item.group_name === feedbackFor);
            if (row?.draft_id) void approve(row.draft_id);
          }}
          onSend={() => {
            void run(
              () =>
                pa<{ message: string }>("/grade/send", {
                  method: "POST",
                  body: JSON.stringify({ group: feedbackFor, course: course.code }),
                }),
              setError,
            ).then((result) => {
              if (result) setSent(result.message);
            });
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
  onClose,
  onApprove,
  onSend,
}: {
  group: string;
  courseCode: string;
  sent: string;
  onClose: () => void;
  onApprove: () => void;
  onSend: () => void;
}) {
  const [notes, setNotes] = useState<FeedbackNotes | null>(null);
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
    pa<FeedbackNotes>(`/grade/feedback?group=${encodeURIComponent(group)}&course=${encodeURIComponent(courseCode)}`)
      .then((data) => {
        setNotes(data);
        setOverrides(data.overrides || {});
      })
      .catch(() => setNotes(null));
  }, [group, courseCode]);

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

  if (!notes) return null;
  const grade = notes.ai_grade;
  const criteria = grade?.criteria || [];

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
    const next = { ...overrides, [row.id]: band };
    setOverrides(next);
    setStep(1);
    void persist({ ...notes, overrides: next });
  }

  return (
    <section className="pa-feedback" aria-label="Feedback">
      <div className={docOpen ? "pa-doc-wrap is-open" : "pa-doc-wrap"}>
        <Button className="pa-doc-close" kind="ghost" onClick={() => setDocOpen(false)}>Close submission</Button>
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
          const next = { ...notes, comments: notes.comments.map((item) => (item.id === id ? { ...item, text } : item)) };
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
        <Button className="pa-view-sub" kind="tertiary" onClick={() => setDocOpen(true)}>View submission</Button>
        <p className="pa-grade-banner">The AI suggested a grade using your rubric. Check it and approve.</p>
        <p className="pa-grade-total">{total} / {grade?.out_of || 100} ({letter})</p>
        {checks > 0 && <span className="pa-check-tag">Check {checks} row{checks === 1 ? "" : "s"}</span>}
        <button type="button" className="pa-why" onClick={() => setHowOpen(true)}>How was this made?</button>
        <table className="pa-rubric">
          <thead>
            <tr>
              <th>Criterion</th>
              <th>AI score</th>
              <th>Reason</th>
              <th><span className="pa-sr">Actions</span></th>
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
                    <td>{needs && <i className="pa-dot" aria-hidden="true" />}{row.name}</td>
                    <td>{chosenScore(row)}/{row.weight} {band}</td>
                    <td>{row.short || row.reason}</td>
                    <td className="pa-row-actions">
                      <Button kind="ghost" size="sm" hasIconOnly renderIcon={Checkmark} iconDescription="This row is fine" onClick={() => { setAccepted((current) => ({ ...current, [row.id]: true })); setOpenRow(""); }} />
                      <Button kind="ghost" size="sm" hasIconOnly renderIcon={Edit} iconDescription={open ? "Close this row" : "Change this row"} onClick={() => setOpenRow(open ? "" : row.id)} />
                    </td>
                  </tr>
                  {open && (
                    <tr className="pa-rubric-edit">
                      <td colSpan={4}>
                        <div className="pa-bands" role="group" aria-label={row.name}>
                          {row.bands.map((item) => (
                            <button key={item.name} type="button" className={band === item.name ? "is-on" : ""} aria-pressed={band === item.name} onClick={() => choose(row, item.name)}>
                              <strong>{item.name}</strong>
                              <span>{item.low}-{item.high}</span>
                              {band === item.name && <em>{changed ? "Changed by you" : "AI picked"}</em>}
                            </button>
                          ))}
                        </div>
                        <div className="pa-row-links">
                          <button type="button" className="pa-why" onClick={() => setActiveHit(row.id)}>Evidence {evidenceNumber.get(row.id)}</button>
                          <button type="button" className="pa-why" onClick={() => setWhy((current) => current === row.id ? "" : row.id)}>{why === row.id ? "Hide why" : "Why?"}</button>
                        </div>
                        {why === row.id && (
                          <div className="pa-why-body">
                            {row.graders.map((person) => (
                              <p key={person.name}><strong>{person.name}</strong> chose {person.band}. {person.reason}</p>
                            ))}
                            <p>{row.agreed ? "The three graders agreed." : "The three graders did not agree. Please check this row."}</p>
                          </div>
                        )}
                        <TextArea
                          id={`rubric-${index}`}
                          labelText="Your comment"
                          value={notes.rubric[index]?.comment || ""}
                          onFocus={() => setFocus(index)}
                          onBlur={() => void persist(notes)}
                          onChange={(event) => {
                            const rubric = notes.rubric.map((item, itemIndex) => itemIndex === index ? { ...item, comment: event.target.value } : item);
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
        <TextArea
          id="overall-feedback"
          labelText="Feedback to students"
          value={notes.overall}
          onFocus={() => setFocus("overall")}
          onBlur={() => void persist(notes)}
          onChange={(event) => setNotes({ ...notes, overall: event.target.value })}
        />
        <button type="button" className="pa-why" onClick={() => setBankOpen((open) => !open)}>{bankOpen ? "Hide comment bank" : "Comment bank"}</button>
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
        {bankOpen && (
          <>
            <TextArea id="bank-new" labelText="Add a reusable comment" value={fresh} onChange={(event) => setFresh(event.target.value)} />
            <Button kind="tertiary" size="sm" onClick={() => {
              if (!fresh.trim()) return;
              const next = { ...notes, bank: [...notes.bank, fresh.trim()] };
              setFresh("");
              void persist(next);
            }}>Save to bank</Button>
          </>
        )}
        <TextArea id="margin-comment" labelText="Margin comment" value={comment} onChange={(event) => setComment(event.target.value)} />
        <Button
          kind="tertiary"
          onClick={() => {
            const row = criteria[0];
            if (!row || !comment.trim()) return;
            const next = {
              ...notes,
              comments: [
                ...notes.comments,
                { id: `you-${Date.now()}`, page: row.page, box: row.box, quote: row.evidence, text: comment.trim() },
              ],
            };
            setComment("");
            setNotes(next);
            setDocOpen(true);
            void persist(next);
          }}
        >
          Add margin comment
        </Button>
        <div className="pa-grade-bar">
          <Button kind="secondary" onClick={() => void persist(notes)}>Save draft</Button>
          <Button kind="primary" onClick={() => { setStep(2); onApprove(); }}>Approve grade</Button>
          <Button kind="primary" onClick={() => { setStep(3); onSend(); }}>Send to Moodle</Button>
        </div>
        {sent && (
          <>
            <p className="pa-grade-banner">{sent}</p>
            <p>This assignment is complete. Recorded here. Moodle was not contacted.</p>
          </>
        )}
        {howOpen && (
          <div className="pa-drawer" role="dialog" aria-label="How was this made?">
            <div className="pa-drawer-card">
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <h2 className="pa-section">How was this made?</h2>
                <Button kind="ghost" size="sm" onClick={() => setHowOpen(false)}>Close</Button>
              </div>
              <ol className="pa-made">
                {[
                  { icon: Catalog, label: "You set the rubric", link: true },
                  { icon: DocumentView, label: "AI read the submission" },
                  { icon: Watson, label: "AI filled each rubric row with a band, score, reason and evidence" },
                  { icon: Checkmark, label: "You check, change and approve" },
                ].map((item, index) => {
                  const Icon = item.icon;
                  const current = step < 2 ? index === 3 : false;
                  return (
                    <li key={item.label} className={current ? "is-now" : "is-done"}>
                      <span className="pa-made-num">{index + 1}</span>
                      <span>
                        <Icon size={16} />
                        {item.link ? (
                          <button type="button" className="pa-why" onClick={() => setRubricOpen(true)}>{item.label}</button>
                        ) : item.label}
                      </span>
                    </li>
                  );
                })}
              </ol>
              {grade && (
                <>
                  <Tag type="blue" size="sm">{grade.confidence} confidence</Tag>
                  <p>Drafted by AI council: 3 graders + chair, using the {grade.rubric}.</p>
                  <div className="pa-council">
                    {grade.council.map((person) => (
                      <span key={person.name} title={person.name} style={{ background: person.color }}>{person.initials}</span>
                    ))}
                  </div>
                  <ol className="pa-steps">
                    {["AI drafted", "You reviewed", "Approved", "Sent to Moodle"].map((label, index) => (
                      <li key={label} className={index === step ? "is-now" : index < step ? "is-done" : ""}>{label}</li>
                    ))}
                  </ol>
                </>
              )}
            </div>
          </div>
        )}
        <Modal open={rubricOpen} passiveModal modalHeading={grade?.rubric || "Rubric"} onRequestClose={() => setRubricOpen(false)}>
          <p>This rubric comes from {grade?.source}. Each row is worth the points shown.</p>
          {criteria.map((row) => (
            <p key={row.id}><strong>{row.name}</strong> ({row.weight} points): {row.bands.map((band) => `${band.name} ${band.low}-${band.high}`).join(", ")}.</p>
          ))}
        </Modal>
      </aside>
    </section>
  );
}
