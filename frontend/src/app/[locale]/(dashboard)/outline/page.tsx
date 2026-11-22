"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AILabel,
  Button,
  Checkbox,
  InlineNotification,
  ProgressIndicator,
  ProgressStep,
  Tag,
  TextArea,
  TextInput,
  Tile,
} from "@carbon/react";
import {
  Calendar,
  Catalog,
  CheckmarkOutline,
  CloudUpload,
  Document,
  Download,
  Education,
  ListChecked,
  MagicWand,
  Policy,
  Task,
  Book,
} from "@carbon/icons-react";
import { pa, run } from "@/components/profassist/bits";
import { CourseFiles, type CourseFile } from "@/components/profassist/course-files";
import { AiSuggestion } from "@/components/profassist/ai-suggestion";
import { CouncilStage } from "@/components/profassist/council-stage";
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Source, Sources, SourcesContent, SourcesTrigger } from "@/components/ai-elements/sources";

const STEPS = [
  { id: "basics", label: "Basics", helper: "Name, code, credit points, session, year, duration, prerequisites, and delivery.", icon: Catalog },
  { id: "attachments", label: "Attachments & Instructions to AI", helper: "Files and instructions for this course. Personal data is removed before the assistant reads them.", icon: CloudUpload },
  { id: "lecture", label: "Lecture and educator", helper: "Who teaches the subject, and when students can reach them.", icon: Education },
  { id: "description", label: "Description", helper: "The subject description that appears on the outline.", icon: Document },
  { id: "outcomes", label: "Outcomes (CLOs)", helper: "Course learning outcomes and how they map to the program.", icon: ListChecked },
  { id: "schedule", label: "Weekly schedule", helper: "Week by week topics for the session.", icon: Calendar },
  { id: "readings", label: "Readings", helper: "Required and recommended readings.", icon: Book },
  { id: "assessments", label: "Assessments", helper: "Tasks, weights, and due dates. Weights should total 100%.", icon: Task },
  { id: "policies", label: "Policies", helper: "Integrity, attendance, lecture capture, and the other faculty policies.", icon: Policy },
  { id: "review", label: "Review & generate", helper: "Check the outline, then generate the PDF and DOCX. Nothing is sent until you approve.", icon: CheckmarkOutline },
];

interface Outline {
  id: string;
  status: string;
  code: string;
  name: string;
  body: Record<string, unknown>;
  pdf_ready: boolean;
  instructions?: string;
  course_id?: string;
}

let freshOutline: Promise<Outline> | null = null;

export default function OutlineWizardPage() {
  const [outline, setOutline] = useState<Outline | null>(null);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [talking, setTalking] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [instructions, setInstructions] = useState("Focus on healthcare cases. Prefer project work.");
  const [files, setFiles] = useState<CourseFile[]>([]);
  const [instructionsReady, setInstructionsReady] = useState(false);
  const [reviewMode, setReviewMode] = useState("council");
  const [why, setWhy] = useState(false);
  const [toolsNode, setToolsNode] = useState<HTMLElement | null>(null);
  const latest = useRef<Record<string, unknown>>({});
  const saveTimer = useRef<number | null>(null);
  const [review, setReview] = useState<{
    id: string;
    score: number;
    summary: string;
    trace_url?: string;
    unresolved_high: number;
    debate: Array<{ round: number; note: string }>;
    findings: Array<{ id: string; severity: string; section: string; object_id: string; message: string; applied?: boolean }>;
  } | null>(null);

  useEffect(() => {
    const fresh = new URLSearchParams(window.location.search).get("fresh") === "1";
    const open = fresh
      ? (freshOutline ??= pa<Outline>("/outlines", { method: "POST" }))
      : pa<{ items: Outline[] }>("/outlines").then(async (data) =>
          data.items.length ? data.items[0] : pa<Outline>("/outlines?demo=true", { method: "POST" }),
        );
    open
      .then(async (opened) => {
        setOutline(opened);
        if (opened.instructions) setInstructions(opened.instructions);
        const materials = await pa<{ items: CourseFile[] }>(`/outlines/${opened.id}/materials`).catch(() => ({
          items: [],
        }));
        setFiles(materials.items || []);
        setInstructionsReady(true);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not open the outline"));
  }, []);

  useEffect(() => {
    if (!outline || !instructionsReady) return;
    const handle = window.setTimeout(() => {
      void pa(`/outlines/${outline.id}/instructions`, {
        method: "PUT",
        body: JSON.stringify({ instructions }),
      }).catch(() => undefined);
    }, 700);
    return () => window.clearTimeout(handle);
  }, [instructions, outline, instructionsReady]);

  const current = STEPS[step];
  const body = outline?.body || {};

  async function assist() {
    if (!outline) return;
    setDrafting(true);
    const next = await run(
      () =>
        pa<{ outline: Outline; reply: string }>(`/outlines/${outline.id}/assist`, {
          method: "POST",
          body: JSON.stringify({ step: current?.id || "basics", message: instructions || "Suggest this step" }),
        }),
      setError,
    );
    if (next) {
      setOutline(next.outline);
      setNote(next.reply);
    }
    setDrafting(false);
  }

  function queueSave(payload: Record<string, unknown>) {
    latest.current = payload;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      void save(payload);
    }, 800);
  }

  async function save(payload: Record<string, unknown>) {
    if (!outline || current?.id === "attachments" || current?.id === "review") return;
    const next = await run(
      () =>
        pa<Outline>(`/outlines/${outline.id}/step`, {
          method: "PUT",
          body: JSON.stringify({ step: current?.id || "basics", payload }),
        }),
      setError,
    );
    if (next) setOutline(next);
  }

  useEffect(() => {
    setToolsNode(document.getElementById("pa-page-tools"));
  }, []);

  const StepIcon = current?.icon || Document;

  return (
    <div>
      {toolsNode && outline?.pdf_ready && createPortal(
        <>
          <Button kind="ghost" size="md" renderIcon={Download} href={`/api/profassist/outlines/${outline.id}/document?kind=pdf`}>PDF</Button>
          <Button kind="ghost" size="md" renderIcon={Download} href={`/api/profassist/outlines/${outline.id}/document?kind=docx`}>DOCX</Button>
        </>,
        toolsNode,
      )}
      {!outline && !error && <p>Loading the wizard…</p>}
      {error && <InlineNotification kind="error" title="Check this step" subtitle={error} hideCloseButton />}
        <div className="pa-wizard">
        <div>
        <ProgressIndicator vertical currentIndex={step} onChange={(index) => setStep(index)}>
          {STEPS.map((item) => (
            <ProgressStep key={item.id} label={item.label} />
          ))}
        </ProgressIndicator>
        </div>
        <div>
        <Tile>
          <div className="pa-step-head">
            <div>
              <p className="pa-step-kicker">Step {step + 1} of {STEPS.length}</p>
              <Button kind="ghost" size="sm" onClick={() => window.location.assign("/outline?fresh=1")}>Start a new course</Button>
              <h2 style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "1.5rem", fontWeight: 400, margin: 0 }}>
                <StepIcon size={20} />
                {current?.label}
              </h2>
            </div>
          </div>
          <p style={{ color: "#525252" }}>{current?.helper}</p>
          {note && <InlineNotification kind="info" title="Assistant" subtitle={note} hideCloseButton lowContrast />}
        {outline && current?.id === "basics" && <Basics body={body.basics as Record<string, string>} onChange={queueSave} />}
        {outline && current?.id === "attachments" && (
          <CourseFiles
            files={files}
            instructions={instructions}
            onInstructions={setInstructions}
            onUpload={async (file) => {
              const body = new FormData();
              body.append("file", file);
              const saved = await pa<{ materials: CourseFile[] }>(`/outlines/${outline.id}/materials`, {
                method: "POST",
                body,
              });
              setFiles(saved.materials || []);
            }}
            onRemove={async (file) => {
              if (!file.id) return;
              const courseId = outline.course_id || "";
              if (!courseId) return;
              await pa(`/courses/${courseId}/materials/${file.id}`, { method: "DELETE" });
              setFiles((currentFiles) => currentFiles.filter((item) => item.id !== file.id));
            }}
          />
        )}
        {outline && current?.id === "lecture" && <Lecture body={body.lecture as Record<string, string>} onChange={queueSave} />}
        {outline && current?.id === "description" && (
          <Description text={String(body.description || "")} onChange={(description) => queueSave({ description })} />
        )}
        {outline && current?.id === "outcomes" && (
          <Outcomes
            program={String(body.program || "")}
            plos={(body.plos as Array<{ code: string; text: string }>) || []}
            clos={(body.clos as Array<{ code: string; text: string; plos: string[]; bloom?: string }>) || []}
            onChange={queueSave}
          />
        )}
        {outline && current?.id === "schedule" && (
          <Schedule weeks={(body.weeks as Array<Record<string, string>>) || []} onChange={(weeks) => queueSave({ weeks })} />
        )}
        {outline && current?.id === "readings" && (
          <Readings items={(body.readings as string[]) || []} onChange={(readings) => queueSave({ readings })} />
        )}
        {outline && current?.id === "assessments" && (
          <Tasks items={(body.tasks as Array<Record<string, unknown>>) || []} onChange={(tasks) => queueSave({ tasks })} />
        )}
        {outline && current?.id === "policies" && (
          <Policies items={(body.policies as Array<{ key: string; title: string; body: string }>) || []} onChange={(policies) => queueSave({ policies })} />
        )}
        {outline && current?.id === "review" && (
          <div style={{ display: "grid", gap: 16 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Button kind={reviewMode === "council" ? "primary" : "tertiary"} size="sm" onClick={() => setReviewMode("council")}>Full council</Button>
              <Button kind={reviewMode === "single" ? "primary" : "tertiary"} size="sm" onClick={() => setReviewMode("single")}>Curriculum reviewer</Button>
              <Button kind="secondary" size="sm" disabled={!outline} onClick={async () => {
                setTalking(true);
                const result = await run(
                  () => pa<NonNullable<typeof review>>(`/outlines/${outline.id}/review`, { method: "POST", body: JSON.stringify({ mode: reviewMode, reviewer: "curriculum" }) }),
                  setError,
                );
                if (result) setReview(result);
              }}>Send for council review</Button>
            </div>
            <CouncilStage scene="review" onDone={() => setTalking(false)} />
            <article className="pa-preview">
              <h3>{String((body.basics as Record<string, string> | undefined)?.code || outline.code)} {String((body.basics as Record<string, string> | undefined)?.name || outline.name)}</h3>
              <h4>Description</h4>
              <p>{String(body.description || "No description yet.")}</p>
              <h4>Learning outcomes</h4>
              <ul>
                {((body.clos as Array<{ code: string; text: string }>) || []).map((item) => (
                  <li key={item.code}><strong>{item.code}.</strong> {item.text}</li>
                ))}
              </ul>
              <h4>Assessments</h4>
              <ul>
                {((body.tasks as Array<Record<string, unknown>>) || []).map((item) => (
                  <li key={String(item.number)}><strong>{String(item.number)}.</strong> {String(item.name)} · {String(item.weight)}% · due {String(item.due || "later")}</li>
                ))}
              </ul>
            </article>
            {review && <p>Score {review.score}. {review.unresolved_high} high findings still open. {review.summary}</p>}
            {talking && <p>The council is talking through this outline.</p>}
          </div>
        )}
        </Tile>
        <div className="pa-sticky-actions pa-button-set">
          <Button kind="secondary" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>Back</Button>
          <Button kind="tertiary" disabled={!outline} onClick={() => save(latest.current)}>Save draft</Button>
          {step < STEPS.length - 1 ? (
            <Button kind="primary" onClick={() => setStep((value) => value + 1)}>Next</Button>
          ) : (
            <Button kind="primary" onClick={async () => {
              if (!outline) return;
              const next = await run(() => pa<Outline>(`/outlines/${outline.id}/finish`, { method: "POST" }), setError);
              if (next) {
                setOutline(next);
                if (next.course_id) window.sessionStorage.setItem("pa-course", next.course_id);
                setNote("The subject outline is stored, indexed, and ready to download.");
              }
            }}>Generate</Button>
          )}
          {outline && <Tag type={outline.status === "published" ? "green" : "gray"}>{outline.status}</Tag>}
        </div>
        </div>
        <aside className="pa-ai-card">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <AILabel size="mini" aiText="AI" aria-label="AI suggestion" />
            <h2 style={{ margin: 0 }}>Suggestion for {current?.label}</h2>
          </div>
          <Button kind="primary" size="md" renderIcon={MagicWand} onClick={assist} disabled={!outline || drafting}>{drafting ? "Writing…" : "Write a suggestion"}</Button>
          <p style={{ fontSize: "1rem", lineHeight: 1.5 }}>
            {note || "Focus on healthcare cases, and prefer a project a group can finish in four weeks."}
          </p>
          <div className="pa-ai-actions">
            <button type="button" className="pa-why" onClick={() => setWhy((open) => !open)}>{why ? "Hide why" : "Why?"}</button>
            <Button kind="tertiary" size="sm" onClick={() => setNote("Kept. You can edit the fields, then go to the next step.")}>Use this</Button>
          </div>
          {why && <p className="pa-why-body">Based on your files{files.length ? `: ${files.map((file) => file.filename).join(", ")}` : ""} and the note you wrote for this course.</p>}
        </aside>
        </div>
    </div>
  );
}

const FIELD_LABELS: Record<string, string> = {
  name: "Subject name",
  code: "Subject code",
  credit_points: "Credit points",
  session: "Session",
  year: "Year",
  duration: "Duration",
  prerequisites: "Prerequisites",
  delivery_mode: "Delivery mode",
  day: "Lecture day",
  time: "Lecture time",
  location: "Location",
  educator_name: "Educator",
  office: "Office",
  email: "Contact email",
  consultation: "Consultation hours",
};

function Basics({ body, onChange }: { body: Record<string, string>; onChange: (payload: Record<string, unknown>) => void }) {
  const [form, setForm] = useState(body || {});
  const wide = new Set(["name", "prerequisites"]);
  return (
    <div className="pa-fields">
      {["name", "code", "credit_points", "session", "year", "duration", "prerequisites", "delivery_mode"].map((key) => (
        <div key={key} className={wide.has(key) ? "pa-wide" : undefined}>
          <TextInput
            id={key}
            labelText={FIELD_LABELS[key] || key}
            value={String(form[key] ?? "")}
            onChange={(event) => {
              const next = { ...form, [key]: event.target.value };
              setForm(next);
              onChange(next);
            }}
          />
        </div>
      ))}
    </div>
  );
}

function Lecture({ body, onChange }: { body: Record<string, string>; onChange: (payload: Record<string, unknown>) => void }) {
  const [form, setForm] = useState(body || {});
  return (
    <div className="pa-fields">
      {["day", "time", "location", "educator_name", "office", "email", "consultation"].map((key) => (
        <div key={key} className={key === "consultation" || key === "email" ? "pa-wide" : undefined}>
          <TextInput
            id={key}
            labelText={FIELD_LABELS[key] || key}
            value={String(form[key] ?? "")}
            onChange={(event) => {
              const next = { ...form, [key]: event.target.value };
              setForm(next);
              onChange(next);
            }}
          />
        </div>
      ))}
    </div>
  );
}

function Description({ text, onChange }: { text: string; onChange: (text: string) => void }) {
  const [value, setValue] = useState(text);
  return (
    <TextArea id="description" labelText="Subject description" value={value} rows={8} onChange={(event) => { setValue(event.target.value); onChange(event.target.value); }} />
  );
}

const BLOOM: Record<string, string> = {
  design: "Create",
  implement: "Apply",
  evaluate: "Evaluate",
  apply: "Apply",
  assess: "Evaluate",
  explain: "Understand",
};

function bloomOf(text: string, given?: string) {
  if (given) return given;
  const verb = text.trim().split(/\s+/)[0]?.toLowerCase() || "";
  return BLOOM[verb] || "Apply";
}

function Outcomes({
  program,
  plos,
  clos,
  onChange,
}: {
  program: string;
  plos: Array<{ code: string; text: string }>;
  clos: Array<{ code: string; text: string; plos: string[]; bloom?: string }>;
  onChange: (payload: Record<string, unknown>) => void;
}) {
  const [rows, setRows] = useState(clos.map((item) => ({ ...item, bloom: bloomOf(item.text, item.bloom) })));
  function commit(next: typeof rows) {
    setRows(next);
    onChange({ program, plos, clos: next });
  }
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <p style={{ margin: 0 }}>{program || "No program yet."}</p>
      <div style={{ display: "grid", gap: 8 }}>
        {plos.map((item) => (
          <p key={item.code} style={{ margin: 0 }}>
            <strong>{item.code}</strong> {item.text}
          </p>
        ))}
      </div>
      {rows.map((item, index) => (
        <article key={item.code} className="pa-clo">
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <strong>{item.code}</strong>
            <Tag type="purple">{item.bloom}</Tag>
          </div>
          <TextInput
            id={item.code}
            labelText="Outcome"
            value={item.text}
            onChange={(event) => {
              const next = rows.slice();
              next[index] = { ...item, text: event.target.value, bloom: bloomOf(event.target.value) };
              commit(next);
            }}
          />
        </article>
      ))}
      <table className="pa-matrix">
        <thead>
          <tr>
            <th>Outcome</th>
            {plos.map((plo) => <th key={plo.code}>{plo.code}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((item, index) => (
            <tr key={item.code}>
              <td>{item.code}</td>
              {plos.map((plo) => (
                <td key={plo.code}>
                  <Checkbox
                    id={`${item.code}-${plo.code}`}
                    labelText={`${item.code} maps to ${plo.code}`}
                    hideLabel
                    checked={(item.plos || []).includes(plo.code)}
                    onChange={(_, data) => {
                      const mapped = new Set(item.plos || []);
                      if (data.checked) mapped.add(plo.code);
                      else mapped.delete(plo.code);
                      const next = rows.slice();
                      next[index] = { ...item, plos: [...mapped] };
                      commit(next);
                    }}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Schedule({ weeks, onChange }: { weeks: Array<Record<string, string>>; onChange: (weeks: Array<Record<string, string>>) => void }) {
  const [rows, setRows] = useState(weeks);
  return (
    <table className="pa-matrix pa-schedule">
      <thead>
        <tr>
          <th>Week</th>
          <th>Topic</th>
          <th>Session</th>
          <th>Note</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((week, index) => (
          <tr key={String(week.week)}>
            <td>{week.week}</td>
            {(["topic", "session_type", "assessment_note"] as const).map((key) => (
              <td key={key}>
                <input
                  aria-label={`${key} week ${week.week}`}
                  value={String(week[key] || "")}
                  onChange={(event) => {
                    const next = rows.slice();
                    next[index] = { ...week, [key]: event.target.value };
                    setRows(next);
                    onChange(next);
                  }}
                />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Readings({ items, onChange }: { items: string[]; onChange: (items: string[]) => void }) {
  const [rows, setRows] = useState(items);
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {rows.map((item, index) => (
        <TextArea
          key={index}
          id={`reading-${index}`}
          labelText={`Reading ${index + 1}`}
          value={item}
          rows={2}
          onChange={(event) => {
            const next = rows.slice();
            next[index] = event.target.value;
            setRows(next);
            onChange(next);
          }}
        />
      ))}
    </div>
  );
}

const METER = ["#0f62fe", "#0043ce", "#6929c4", "#005d5d", "#198038"];

function Tasks({ items, onChange }: { items: Array<Record<string, unknown>>; onChange: (items: Array<Record<string, unknown>>) => void }) {
  const [rows, setRows] = useState(items);
  const total = rows.reduce((sum, item) => sum + Number(item.weight || 0), 0);
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="pa-meter" aria-label={`Assessment weights total ${total} percent`}>
        {rows.map((item, index) => (
          <span key={String(item.number)} style={{ width: `${Math.max(0, Number(item.weight || 0))}%`, background: METER[index % METER.length] }} />
        ))}
      </div>
      <p style={{ margin: 0, color: total === 100 ? "#198038" : "#da1e28" }}>
        {total === 100 ? "Weights total 100%." : `Weights total ${total}%. They need to total 100%.`}
      </p>
      {rows.map((item, index) => (
        <div key={String(item.number)} className="pa-fields">
          <TextInput id={`task-${item.number}`} labelText={String(item.number)} value={String(item.name || "")} onChange={(event) => {
            const next = rows.slice();
            next[index] = { ...item, name: event.target.value };
            setRows(next);
            onChange(next);
          }} />
          <TextInput id={`due-${item.number}`} labelText="Due" value={String(item.due || "")} onChange={(event) => {
            const next = rows.slice();
            next[index] = { ...item, due: event.target.value };
            setRows(next);
            onChange(next);
          }} />
          <TextInput id={`weight-${item.number}`} labelText="Weight %" value={String(item.weight ?? "")} onChange={(event) => {
            const next = rows.slice();
            next[index] = { ...item, weight: Number(event.target.value || 0) };
            setRows(next);
            onChange(next);
          }} />
        </div>
      ))}
    </div>
  );
}

function Policies({
  items,
  onChange,
}: {
  items: Array<{ key: string; title: string; body: string }>;
  onChange: (items: Array<{ key: string; title: string; body: string }>) => void;
}) {
  const [rows, setRows] = useState(items);
  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      {rows.map((item, index) => (
        <TextArea
          key={item.key}
          id={item.key}
          labelText={item.title}
          value={item.body}
          rows={4}
          onChange={(event) => {
            const next = rows.slice();
            next[index] = { ...item, body: event.target.value };
            setRows(next);
            onChange(next);
          }}
        />
      ))}
    </div>
  );
}
