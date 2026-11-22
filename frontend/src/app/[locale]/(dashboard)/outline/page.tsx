"use client";

import { useEffect, useState } from "react";
import {
  Button,
  Column,
  Grid,
  InlineNotification,
  ProgressIndicator,
  ProgressStep,
  Tag,
  TextArea,
  TextInput,
} from "@carbon/react";
import { Download, MagicWand, Save } from "@carbon/icons-react";
import { pa, run } from "@/components/profassist/bits";
import { AiSuggestion } from "@/components/profassist/ai-suggestion";
import { CouncilStage } from "@/components/profassist/council-stage";

const STEPS = [
  { id: "basics", label: "Basics" },
  { id: "lecture", label: "Lecture" },
  { id: "description", label: "About" },
  { id: "outcomes", label: "Outcomes" },
  { id: "schedule", label: "Weeks" },
  { id: "readings", label: "Readings" },
  { id: "assessments", label: "Tasks" },
  { id: "policies", label: "Policies" },
];

interface Outline {
  id: string;
  status: string;
  code: string;
  name: string;
  body: Record<string, unknown>;
  pdf_ready: boolean;
}

export default function OutlineWizardPage() {
  const [outline, setOutline] = useState<Outline | null>(null);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [talking, setTalking] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [instructions, setInstructions] = useState("Focus on healthcare cases. Prefer project work.");
  const [files, setFiles] = useState<Array<{ filename: string; status: string }>>([]);
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
        if (data.items.length) setOutline(data.items[0]);
        else setOutline(await pa<Outline>("/outlines?demo=true", { method: "POST" }));
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not open the outline"));
  }, []);

  const current = STEPS[step];
  const body = outline?.body || {};

  async function assist() {
    if (!outline) return;
    setDrafting(true);
    const next = await run(
      () =>
        pa<{ outline: Outline; reply: string }>(`/outlines/${outline.id}/assist`, {
          method: "POST",
          body: JSON.stringify({ step: current.id, message: instructions || "Suggest this step" }),
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
          body: JSON.stringify({ step: current.id, payload }),
        }),
      setError,
    );
    if (next) setOutline(next);
  }

  return (
    <Grid>
      <Column lg={16} md={8} sm={4}>
        <p style={{ color: "#525252", marginTop: 0 }}>
          {outline ? `${outline.code} · ${outline.name} · ${outline.status}` : "Loading the wizard…"}
        </p>
      </Column>
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
        <h2 style={{ fontWeight: 400 }}>Attachments and instructions</h2>
        <p style={{ color: "#525252" }}>
          Files are stored for this professor and course, checked for personal data, and cited when the assistant drafts.
        </p>
        <input
          type="file"
          accept=".pdf,.docx,.pptx,.txt,.md"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file || !outline) return;
            const body = new FormData();
            body.append("file", file);
            const saved = await run(
              () => pa<{ materials: Array<{ filename: string; status: string }> }>(`/outlines/${outline.id}/materials`, { method: "POST", body }),
              setError,
            );
            if (saved) setFiles(saved.materials);
          }}
        />
        <ul>
          {files.map((file) => (
            <li key={file.filename}>{file.filename} · {file.status}</li>
          ))}
        </ul>
        <TextArea
          id="instructions"
          labelText="Instructions to AI"
          value={instructions}
          rows={3}
          onChange={(event) => setInstructions(event.target.value)}
        />
        <Button
          kind="tertiary"
          disabled={!outline}
          onClick={async () => {
            if (!outline) return;
            await run(
              () => pa(`/outlines/${outline.id}/instructions`, { method: "PUT", body: JSON.stringify({ instructions }) }),
              setError,
            );
            setNote("Instructions saved. Suggest this step again to regenerate with them.");
          }}
        >
          Save instructions
        </Button>
      </Column>
      <Column lg={16}>
        <div className="pa-progress">
        <ProgressIndicator currentIndex={step} onChange={(index) => setStep(index)}>
          {STEPS.map((item) => (
            <ProgressStep key={item.id} label={item.label} />
          ))}
        </ProgressIndicator>
        </div>
      </Column>
      <Column lg={12} md={8} sm={4}>
        {outline && current.id === "basics" && <Basics body={body.basics as Record<string, string>} onSave={save} />}
        {outline && current.id === "lecture" && <Lecture body={body.lecture as Record<string, string>} onSave={save} />}
        {outline && current.id === "description" && (
          <Description text={String(body.description || "")} onSave={(description) => save({ description })} />
        )}
        {outline && current.id === "outcomes" && (
          <Outcomes
            program={String(body.program || "")}
            plos={(body.plos as Array<{ code: string; text: string }>) || []}
            clos={(body.clos as Array<{ code: string; text: string; plos: string[] }>) || []}
            onSave={save}
          />
        )}
        {outline && current.id === "schedule" && (
          <Schedule weeks={(body.weeks as Array<Record<string, string>>) || []} onSave={(weeks) => save({ weeks })} />
        )}
        {outline && current.id === "readings" && (
          <Readings items={(body.readings as string[]) || []} onSave={(readings) => save({ readings })} />
        )}
        {outline && current.id === "assessments" && (
          <Tasks items={(body.tasks as Array<Record<string, unknown>>) || []} onSave={(tasks) => save({ tasks })} />
        )}
        {outline && current.id === "policies" && (
          <Policies items={(body.policies as Array<{ key: string; title: string; body: string }>) || []} onSave={(policies) => save({ policies })} />
        )}
        {(note || drafting) && (
          <AiSuggestion
            title={`Suggestion for ${current?.label || "this step"}`}
            description="Generated from the outline, the attachments, and your instructions."
            body={note || "Drafting…"}
            busy={drafting}
            citation={note}
            onAccept={() => setNote("Kept. Edit the fields, then move to the next step.")}
            onRegenerate={assist}
          />
        )}
      </Column>
      <Column lg={16}>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
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
      </Column>
      <Column lg={16}>
        <h2 style={{ fontWeight: 400 }}>Review before approval</h2>
        <div style={{ display: "flex", gap: "0.5rem", margin: "0.5rem 0 1rem" }}>
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
              if (!outline) return;
              setTalking(true);
              const result = await run(
                () =>
                  pa<NonNullable<typeof review>>(`/outlines/${outline.id}/review`, {
                    method: "POST",
                    body: JSON.stringify({
                      mode: reviewMode,
                      reviewer: "curriculum",
                    }),
                  }),
                setError,
              );
              if (result) setReview(result);
            }}
          >
            Run review
          </Button>
        </div>
        {talking && <CouncilStage scene="review" onDone={() => setTalking(false)} />}
        {review && (
          <div style={{ display: "grid", gap: "0.75rem", marginTop: "1rem" }}>
            <p>
              Score {review.score}. {review.unresolved_high} high findings still open. {review.summary}
            </p>
            {review.trace_url && (
              <a href={review.trace_url}>View the Langfuse trace</a>
            )}
            {review.debate.map((item) => (
              <p key={item.round}>Round {item.round}: {item.note}</p>
            ))}
            {review.findings.map((finding) => (
              <div key={finding.id} style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                <Tag type={finding.severity === "high" ? "red" : finding.severity === "medium" ? "magenta" : "gray"}>
                  {finding.severity}
                </Tag>
                <span>
                  {finding.section} · {finding.object_id}: {finding.message}
                </span>
                {!finding.applied && outline && (
                  <Button
                    size="sm"
                    kind="ghost"
                    onClick={async () => {
                      const next = await run(
                        () =>
                          pa<NonNullable<typeof review>>(
                            `/outlines/${outline.id}/reviews/${review.id}/apply?finding_id=${encodeURIComponent(finding.id)}`,
                            { method: "POST" },
                          ),
                        setError,
                      );
                      if (next) setReview(next);
                    }}
                  >
                    Apply fix
                  </Button>
                )}
              </div>
            ))}
            {review.unresolved_high > 0 && (
              <InlineNotification
                kind="warning"
                title="High findings are still open"
                subtitle="You can still approve. Re-run the review after you edit."
                hideCloseButton
              />
            )}
          </div>
        )}
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
      <p style={{ margin: 0, color: "#525252" }}>Who teaches the subject, and when students can reach them.</p>
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
