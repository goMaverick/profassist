"use client";

import { useEffect, useState } from "react";
import {
  AILabel,
  Button,
  Column,
  Grid,
  InlineNotification,
  ProgressIndicator,
  ProgressStep,
  Tag,
  TextArea,
  TextInput,
  Tile,
} from "@carbon/react";
import { Download, MagicWand, Save } from "@carbon/icons-react";
import { pa, run } from "@/components/profassist/bits";
import { CourseFiles, type CourseFile } from "@/components/profassist/course-files";
import { AiSuggestion } from "@/components/profassist/ai-suggestion";
import { CouncilStage } from "@/components/profassist/council-stage";

const STEPS = [
  { id: "basics", label: "Basics", helper: "Name, code, credit points, session, year, duration, prerequisites, and delivery." },
  { id: "attachments", label: "Attachments & Instructions to AI", helper: "Files and instructions for this course. Personal data is removed before the assistant reads them." },
  { id: "lecture", label: "Lecture and educator", helper: "Who teaches the subject, and when students can reach them." },
  { id: "description", label: "Description", helper: "The subject description that appears on the outline." },
  { id: "outcomes", label: "Outcomes (CLOs)", helper: "Course learning outcomes and how they map to the program." },
  { id: "schedule", label: "Weekly schedule", helper: "Week by week topics for the session." },
  { id: "readings", label: "Readings", helper: "Required and recommended readings." },
  { id: "assessments", label: "Assessments", helper: "Tasks, weights, and due dates. Weights should total 100%." },
  { id: "policies", label: "Policies", helper: "Integrity, attendance, lecture capture, and the other faculty policies." },
  { id: "review", label: "Review & generate", helper: "Check the outline, then generate the PDF and DOCX. Nothing is sent until you approve." },
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
    pa<{ items: Outline[] }>("/outlines")
      .then(async (data) => {
        const opened = data.items.length
          ? data.items[0]
          : await pa<Outline>("/outlines?demo=true", { method: "POST" });
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

  async function save(payload: Record<string, unknown>) {
    if (!outline) return;
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

  return (
    <Grid>
      {!outline && !error && (
        <Column lg={16}>
          <p>Loading the wizard…</p>
        </Column>
      )}
      {error && (
        <Column lg={16}>
          <InlineNotification kind="error" title="Check this step" subtitle={error} hideCloseButton />
        </Column>
      )}
      {note && (
        <Column lg={16}>
          <InlineNotification kind="success" title="Assistant" subtitle={note} hideCloseButton lowContrast />
        </Column>
      )}
      <Column lg={16}>
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
          <h2 style={{ fontSize: "1.25rem", fontWeight: 400, marginTop: 0 }}>{current?.label}</h2>
          <p style={{ color: "#525252", marginTop: 0 }}>{current?.helper}</p>
        {outline && current?.id === "basics" && <Basics body={body.basics as Record<string, string>} onSave={save} />}
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
        {outline && current?.id === "lecture" && <Lecture body={body.lecture as Record<string, string>} onSave={save} />}
        {outline && current?.id === "description" && (
          <Description text={String(body.description || "")} onSave={(description) => save({ description })} />
        )}
        {outline && current?.id === "outcomes" && (
          <Outcomes
            program={String(body.program || "")}
            plos={(body.plos as Array<{ code: string; text: string }>) || []}
            clos={(body.clos as Array<{ code: string; text: string; plos: string[] }>) || []}
            onSave={save}
          />
        )}
        {outline && current?.id === "schedule" && (
          <Schedule weeks={(body.weeks as Array<Record<string, string>>) || []} onSave={(weeks) => save({ weeks })} />
        )}
        {outline && current?.id === "readings" && (
          <Readings items={(body.readings as string[]) || []} onSave={(readings) => save({ readings })} />
        )}
        {outline && current?.id === "assessments" && (
          <Tasks items={(body.tasks as Array<Record<string, unknown>>) || []} onSave={(tasks) => save({ tasks })} />
        )}
        {outline && current?.id === "policies" && (
          <Policies items={(body.policies as Array<{ key: string; title: string; body: string }>) || []} onSave={(policies) => save({ policies })} />
        )}
        {outline && current?.id === "review" && (
          <div style={{ display: "grid", gap: 12 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Button kind={reviewMode === "council" ? "primary" : "tertiary"} onClick={() => setReviewMode("council")}>
                Full council
              </Button>
              <Button kind={reviewMode === "single" ? "primary" : "tertiary"} onClick={() => setReviewMode("single")}>
                Curriculum reviewer
              </Button>
              <Button
                kind="secondary"
                disabled={!outline}
                onClick={async () => {
                  setTalking(true);
                  const result = await run(
                    () =>
                      pa<NonNullable<typeof review>>(`/outlines/${outline.id}/review`, {
                        method: "POST",
                        body: JSON.stringify({ mode: reviewMode, reviewer: "curriculum" }),
                      }),
                    setError,
                  );
                  if (result) setReview(result);
                }}
              >
                Send for council review
              </Button>
            </div>
            {talking && <CouncilStage scene="review" onDone={() => setTalking(false)} />}
            <p style={{ margin: 0 }}>
              {String((body.basics as Record<string, string> | undefined)?.code || outline.code)}{" "}
              {String((body.basics as Record<string, string> | undefined)?.name || outline.name)}
            </p>
            <p style={{ margin: 0 }}>{String(body.description || "No description yet.")}</p>
            {review && (
              <p style={{ margin: 0 }}>
                Score {review.score}. {review.unresolved_high} high findings still open. {review.summary}
              </p>
            )}
          </div>
        )}
        </Tile>
        <div className="pa-sticky-actions">
          <Button kind="tertiary" renderIcon={MagicWand} onClick={assist} disabled={!outline || drafting}>
            Suggest this step
          </Button>
          <Button kind="secondary" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>
            Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button kind="primary" onClick={() => setStep((value) => value + 1)}>
              Next
            </Button>
          ) : (
            <Button
              kind="primary"
              renderIcon={Save}
              onClick={async () => {
                if (!outline) return;
                const next = await run(() => pa<Outline>(`/outlines/${outline.id}/finish`, { method: "POST" }), setError);
                if (next) {
                  setOutline(next);
                  setNote("The subject outline is stored, indexed, and ready to download.");
                }
              }}
            >
              Finish and generate
            </Button>
          )}
          {outline?.pdf_ready && (
            <>
              <Button kind="ghost" renderIcon={Download} href={`/api/profassist/outlines/${outline.id}/document?kind=pdf`}>
                PDF
              </Button>
              <Button kind="ghost" renderIcon={Download} href={`/api/profassist/outlines/${outline.id}/document?kind=docx`}>
                DOCX
              </Button>
            </>
          )}
          {outline && <Tag type={outline.status === "published" ? "green" : "gray"}>{outline.status}</Tag>}
        </div>
        </div>
        <aside className="pa-ai-card">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <AILabel size="mini" aiText="AI" aria-label="AI suggestion" />
            <h2 style={{ margin: 0 }}>Suggestion</h2>
          </div>
          <p style={{ marginTop: 0, color: "#525252", fontSize: "0.875rem" }}>
            Example: focus on healthcare cases, and prefer a project a group can build in four weeks.
          </p>
          {(note || drafting) ? (
            <AiSuggestion
              title={`Suggestion for ${current?.label || "this step"}`}
              description="Generated from the outline, the attachments, and your instructions."
              body={note || "Drafting…"}
              busy={drafting}
              citation={note}
              onAccept={() => setNote("Kept. Edit the fields, then move to the next step.")}
              onRegenerate={assist}
            />
          ) : (
            <div className="pa-empty">
              <MagicWand size={20} />
              <span>Ask for a suggestion. It stays in this panel until you keep or regenerate it.</span>
            </div>
          )}
        </aside>
        </div>
      </Column>
    </Grid>
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

function Basics({ body, onSave }: { body: Record<string, string>; onSave: (payload: Record<string, unknown>) => void }) {
  const [form, setForm] = useState(body || {});
  return (
    <div className="pa-fields">
      <p style={{ margin: 0, color: "#525252" }}>These fields match the faculty subject outline.</p>
      {["name", "code", "credit_points", "session", "year", "duration", "prerequisites", "delivery_mode"].map((key) => (
        <TextInput
          key={key}
          id={key}
          labelText={FIELD_LABELS[key] || key}
          value={String(form[key] ?? "")}
          onChange={(event) => setForm({ ...form, [key]: event.target.value })}
        />
      ))}
      <Button kind="secondary" onClick={() => onSave(form)}>
        Save basics
      </Button>
    </div>
  );
}

function Lecture({ body, onSave }: { body: Record<string, string>; onSave: (payload: Record<string, unknown>) => void }) {
  const [form, setForm] = useState(body || {});
  return (
    <div className="pa-fields">
      {["day", "time", "location", "educator_name", "office", "email", "consultation"].map((key) => (
        <TextInput
          key={key}
          id={key}
          labelText={FIELD_LABELS[key] || key}
          value={String(form[key] ?? "")}
          onChange={(event) => setForm({ ...form, [key]: event.target.value })}
        />
      ))}
      <Button kind="secondary" onClick={() => onSave(form)}>
        Save lecture
      </Button>
    </div>
  );
}

function Description({ text, onSave }: { text: string; onSave: (text: string) => void }) {
  const [value, setValue] = useState(text);
  return (
    <div>
      <TextArea id="description" labelText="Subject description" value={value} rows={8} onChange={(event) => setValue(event.target.value)} />
      <Button kind="secondary" onClick={() => onSave(value)}>
        Save description
      </Button>
    </div>
  );
}

function Outcomes({
  program,
  plos,
  clos,
  onSave,
}: {
  program: string;
  plos: Array<{ code: string; text: string }>;
  clos: Array<{ code: string; text: string; plos: string[] }>;
  onSave: (payload: Record<string, unknown>) => void;
}) {
  return (
    <div style={{ display: "grid", gap: "0.75rem" }}>
      <p>{program || "No program yet. Ask for a suggestion."}</p>
      {plos.map((item) => (
        <Tag key={item.code} type="blue">
          {item.code}: {item.text}
        </Tag>
      ))}
      {clos.map((item) => (
        <Tag key={item.code} type="teal">
          {item.code} maps to {(item.plos || []).join(", ")}
        </Tag>
      ))}
      <Button kind="secondary" onClick={() => onSave({ program, plos, clos })}>
        Keep these outcomes
      </Button>
    </div>
  );
}

function Schedule({ weeks, onSave }: { weeks: Array<Record<string, string>>; onSave: (weeks: Array<Record<string, string>>) => void }) {
  return (
    <div style={{ display: "grid", gap: "0.5rem" }}>
      {weeks.map((week) => (
        <div key={String(week.week)} style={{ display: "grid", gridTemplateColumns: "4rem 1fr 8rem", gap: "0.5rem" }}>
          <strong>W{week.week}</strong>
          <span>{week.topic}</span>
          <span>{week.assessment_note}</span>
        </div>
      ))}
      <Button kind="secondary" onClick={() => onSave(weeks)}>
        Keep this schedule
      </Button>
    </div>
  );
}

function Readings({ items, onSave }: { items: string[]; onSave: (items: string[]) => void }) {
  return (
    <div>
      <ol>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ol>
      <Button kind="secondary" onClick={() => onSave(items)}>
        Keep readings
      </Button>
    </div>
  );
}

function Tasks({ items, onSave }: { items: Array<Record<string, unknown>>; onSave: (items: Array<Record<string, unknown>>) => void }) {
  return (
    <div style={{ display: "grid", gap: "0.75rem" }}>
      {items.map((item) => (
        <div key={String(item.number)}>
          <strong>
            {String(item.number)} {String(item.name)}
          </strong>
          <span> · {String(item.weight)}% · {String(item.due)}</span>
          <p style={{ margin: "0.25rem 0" }}>{String(item.brief || "")}</p>
        </div>
      ))}
      <Button kind="secondary" onClick={() => onSave(items)}>
        Keep assessments
      </Button>
    </div>
  );
}

function Policies({
  items,
  onSave,
}: {
  items: Array<{ key: string; title: string; body: string }>;
  onSave: (items: Array<{ key: string; title: string; body: string }>) => void;
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
          }}
        />
      ))}
      <Button kind="secondary" onClick={() => onSave(rows)}>
        Save policies
      </Button>
    </div>
  );
}
