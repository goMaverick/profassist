"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";
import { setPageContext } from "@/components/profassist/page-context";

interface Criterion {
  id?: string;
  name: string;
  weight: number;
  levels?: Record<string, string>;
}
interface Rubric {
  id: string;
  title: string;
  brief: string;
  status: string;
  kind: string;
  version: number;
  weight: number;
  alignment?: { flags?: string[] };
  criteria?: Criterion[];
}

const LEVELS = ["beginning", "developing", "proficient", "advanced"];
const BLANK_LEVELS: Record<string, string> = {
  beginning: "",
  developing: "",
  proficient: "",
  advanced: "",
};

type Busy = "" | "create" | "suggest" | "save" | "paste" | "file" | "check" | "approve";

function RubricBody() {
  const { course, error: loadError, loading } = useWorkspace();
  const params = useSearchParams();
  const assessmentId = params.get("assessment") || "";
  const [error, setError] = useState("");
  const [items, setItems] = useState<Rubric[]>([]);
  const [current, setCurrent] = useState<Rubric | null>(null);
  const [itemsLoaded, setItemsLoaded] = useState(false);
  const [paste, setPaste] = useState("");
  const [title, setTitle] = useState("New rubric");
  const [busy, setBusy] = useState<Busy>("");
  const busyRef = useRef<Busy>("");

  async function load(courseId: string, keepId?: string) {
    const data = await pa<{ items: Rubric[] }>(`/courses/${courseId}/assessments`);
    setItems(data.items);
    setCurrent((selected) => {
      const wanted = keepId || assessmentId || selected?.id || "";
      return data.items.find((item) => item.id === wanted) || null;
    });
    setItemsLoaded(true);
    return data.items;
  }

  useEffect(() => {
    if (!course || !assessmentId) return;
    load(course.id).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Load failed");
      setItemsLoaded(true);
    });
  }, [course, assessmentId]);

  // Publish the open rubric so chat can answer about it without re-reading the page.
  const courseId = course?.id;
  const courseCode = course?.code;
  const rubricId = current?.id;

  useEffect(() => {
    if (!courseId || !rubricId) return;
    setPageContext({
      page: "/rubric",
      title: "Rubric builder",
      rubric_id: rubricId,
      course_id: courseId,
      course_name: courseCode,
    });
    return () => {
      setPageContext({ rubric_id: undefined, course_id: undefined, course_name: undefined });
    };
  }, [courseId, courseCode, rubricId]);

  if (loading) return <p className="text-sm">Loading rubrics…</p>;
  if (!course) return <Banner>{loadError || "No course in this workspace."}</Banner>;

  if (!assessmentId) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-3">
        <Banner>Rubrics belong to an assignment. Open an assignment and choose Edit rubric.</Banner>
        <Link href="/assignments" className="w-fit text-sm underline">
          Go to assignments
        </Link>
      </div>
    );
  }

  if (!itemsLoaded) return <p className="text-sm">Loading rubrics…</p>;

  if (!current) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-3">
        <Banner>{error || "That rubric is not in this workspace."}</Banner>
        <Link href="/assignments" className="w-fit text-sm underline">
          Back to assignments
        </Link>
      </div>
    );
  }

  // One action at a time, so a slow save cannot race a second click.
  async function act<T>(kind: Busy, action: () => Promise<T>): Promise<T | null> {
    // The ref closes the gap between two clicks in the same frame; the state dims the buttons.
    if (busyRef.current) return null;
    busyRef.current = kind;
    setBusy(kind);
    try {
      return await run(action, setError);
    } finally {
      busyRef.current = "";
      setBusy("");
    }
  }

  function editCriterion(index: number, next: Criterion) {
    if (!current) return;
    const criteria = (current.criteria ?? []).slice();
    criteria[index] = next;
    setCurrent({ ...current, criteria });
  }

  async function refresh(id?: string) {
    if (!course) return;
    await load(course.id, id);
  }

  const criteria = current?.criteria ?? [];
  const weightTotal = criteria.reduce((sum, criterion) => sum + (Number.isFinite(criterion.weight) ? criterion.weight : 0), 0);
  const approved = current?.status === "approved";

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <p className="text-sm text-[#525252]">{course.code}</p>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      <div className="flex flex-wrap items-center gap-2">
        <input className="rounded border px-2 py-1 text-sm" value={title} onChange={(event) => setTitle(event.target.value)} />
        <button
          className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50"
          disabled={busy !== ""}
          onClick={() =>
            act("create", async () => {
              const created = await pa<Rubric>(`/courses/${course.id}/rubrics`, {
                method: "POST",
                body: JSON.stringify({ title }),
              });
              await refresh(created.id);
              return created;
            })
          }
        >
          {busy === "create" ? "Creating…" : "Blank rubric"}
        </button>
        <button
          className="bg-foreground text-background rounded-lg px-3 py-2 text-sm disabled:opacity-50"
          disabled={busy !== "" || approved}
          onClick={() =>
            act("suggest", async () => {
              // Target the selected rubric so a second draft cannot be clobbered by accident.
              const path = current
                ? `/courses/${course.id}/assessment/draft?assessment_id=${encodeURIComponent(current.id)}`
                : `/courses/${course.id}/assessment/draft`;
              const drafted = await pa<Rubric>(path, { method: "POST" });
              await refresh(drafted.id);
              return drafted;
            })
          }
        >
          {busy === "suggest" ? "Suggesting…" : "Suggest from outcomes"}
        </button>
        <select
          className="rounded border px-2 py-1 text-sm"
          value={current?.id || ""}
          onChange={(event) => setCurrent(items.find((item) => item.id === event.target.value) || null)}
        >
          {items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title} · {item.kind} · {item.status} · v{item.version}
            </option>
          ))}
        </select>
      </div>
      {current && (
        <div className="flex flex-col gap-4">
          <p className="text-xs text-[#525252]">
            {current.title} · {current.status} · version {current.version} · {criteria.length} criteria
          </p>
          <textarea
            className="border-foreground/15 min-h-16 rounded-xl border bg-transparent p-3 text-sm disabled:opacity-70"
            value={current.brief}
            disabled={approved}
            onChange={(event) => setCurrent({ ...current, brief: event.target.value })}
          />
          {criteria.length === 0 && (
            <Banner>This rubric has no criteria yet. Add one, suggest from outcomes, or import a rubric.</Banner>
          )}
          {criteria.map((criterion, index) => (
            <article key={criterion.id || `${criterion.name}-${index}`} className="border-foreground/10 flex flex-col gap-2 rounded-lg border p-3">
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded border px-2 py-1 text-sm disabled:opacity-70"
                  placeholder="Criterion name"
                  value={criterion.name}
                  disabled={approved}
                  onChange={(event) => editCriterion(index, { ...criterion, name: event.target.value })}
                />
                <input
                  className="w-20 rounded border px-2 py-1 text-sm disabled:opacity-70"
                  type="number"
                  min={0}
                  value={criterion.weight}
                  disabled={approved}
                  onChange={(event) => editCriterion(index, { ...criterion, weight: Number(event.target.value) })}
                />
              </div>
              {LEVELS.map((level) => (
                <label key={level} className="text-xs">
                  {level}
                  <textarea
                    className="mt-1 min-h-14 w-full rounded border px-2 py-1 text-sm disabled:opacity-70"
                    value={criterion.levels?.[level] ?? ""}
                    disabled={approved}
                    onChange={(event) =>
                      editCriterion(index, {
                        ...criterion,
                        levels: { ...(criterion.levels || {}), [level]: event.target.value },
                      })
                    }
                  />
                </label>
              ))}
            </article>
          ))}
          <p className="text-sm">
            Weight total: {weightTotal}
            {criteria.length > 0 && weightTotal !== 100 ? " (should total 100)" : ""}
          </p>
          {criteria.length > 0 && weightTotal !== 100 && (
            <Banner>Weights add up to {weightTotal}, not 100. Adjust the weights before you approve.</Banner>
          )}
          {!approved && (
            <button
              className="w-fit text-sm underline disabled:opacity-50"
              disabled={busy !== ""}
              onClick={() =>
                setCurrent({
                  ...current,
                  criteria: [...criteria, { name: "", weight: 1, levels: { ...BLANK_LEVELS } }],
                })
              }
            >
              Add a criterion
            </button>
          )}
          {!approved && (
            <textarea
              className="border-foreground/15 min-h-24 rounded-xl border bg-transparent p-3 text-sm"
              placeholder={"Paste a rubric. Example:\nCriterion: Evidence\nWeight: 2\nBeginning: Names the task\nDeveloping: Partly shows it\nProficient: Quotes an example\nAdvanced: States a limitation"}
              value={paste}
              onChange={(event) => setPaste(event.target.value)}
            />
          )}
          {!approved && (
            <label className="text-sm">
              Import docx, pdf, or xlsx
              <input
                className="mt-1 block"
                type="file"
                accept=".docx,.pdf,.xlsx,.txt"
                disabled={busy !== ""}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  void act("file", async () => {
                    try {
                      const body = new FormData();
                      body.append("file", file);
                      const next = await pa<Rubric>(`/assessments/${current.id}/import`, { method: "POST", body });
                      await refresh(next.id);
                      return next;
                    } finally {
                      event.target.value = "";
                    }
                  });
                }}
              />
            </label>
          )}
          {(current.alignment?.flags || []).map((flag, index) => (
            <Banner key={`${index}-${flag}`}>{flag}</Banner>
          ))}
          <div className="flex flex-wrap gap-2">
            <button
              className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50"
              disabled={busy !== "" || approved}
              onClick={() =>
                act("save", async () => {
                  const next = await pa<Rubric>(`/assessments/${current.id}/rubric`, {
                    method: "PUT",
                    body: JSON.stringify({ brief: current.brief, criteria }),
                  });
                  await refresh(next.id);
                  return next;
                })
              }
            >
              {busy === "save" ? "Saving…" : "Save version"}
            </button>
            <button
              className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50"
              disabled={busy !== "" || approved}
              onClick={() => {
                const text = paste.trim();
                if (!text) {
                  setError("Paste a rubric first. Nothing was sent.");
                  return;
                }
                void act("paste", async () => {
                  const body = new FormData();
                  body.append("pasted", text);
                  const next = await pa<Rubric>(`/assessments/${current.id}/import`, { method: "POST", body });
                  await refresh(next.id);
                  return next;
                });
              }}
            >
              {busy === "paste" ? "Importing…" : "Import pasted text"}
            </button>
            <button
              className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50"
              disabled={busy !== ""}
              onClick={() =>
                act("check", async () => {
                  const next = await pa<Rubric>(`/assessments/${current.id}/check`, { method: "POST" });
                  await refresh(next.id);
                  return next;
                })
              }
            >
              {busy === "check" ? "Checking…" : "Check alignment"}
            </button>
            <button
              className="bg-foreground text-background rounded-lg px-3 py-2 text-sm disabled:opacity-50"
              disabled={busy !== "" || approved}
              onClick={() =>
                act("approve", async () => {
                  const saved = await pa<Rubric>(`/assessments/${current.id}/rubric`, {
                    method: "PUT",
                    body: JSON.stringify({ brief: current.brief, criteria }),
                  });
                  const approvedRow = await pa<Rubric>(`/assessments/${saved.id}/approve`, { method: "POST" });
                  await refresh(approvedRow.id);
                  return approvedRow;
                })
              }
            >
              {busy === "approve" ? "Approving…" : approved ? "Approved" : "Approve rubric"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function RubricPage() {
  return (
    <Suspense fallback={<p className="text-sm">Loading rubrics…</p>}>
      <RubricBody />
    </Suspense>
  );
}
