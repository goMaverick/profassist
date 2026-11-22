"use client";

import { useEffect, useState } from "react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";

interface Criterion {
  id?: string;
  name: string;
  weight: number;
  levels: Record<string, string>;
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
  criteria: Criterion[];
}

const LEVELS = ["beginning", "developing", "proficient", "advanced"];

export default function RubricPage() {
  const { course, error: loadError, loading } = useWorkspace();
  const [error, setError] = useState("");
  const [items, setItems] = useState<Rubric[]>([]);
  const [current, setCurrent] = useState<Rubric | null>(null);
  const [paste, setPaste] = useState("");
  const [title, setTitle] = useState("New rubric");

  async function load(courseId: string) {
    const data = await pa<{ items: Rubric[] }>(`/courses/${courseId}/assessments`);
    setItems(data.items);
    setCurrent((selected) => data.items.find((item) => item.id === selected?.id) || data.items[0] || null);
  }

  useEffect(() => {
    if (course) load(course.id).catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, [course]);

  if (loading) return <p className="text-sm">Loading rubrics…</p>;
  if (!course) return <Banner>{loadError || "No course in this workspace."}</Banner>;

  function editCriterion(index: number, next: Criterion) {
    if (!current) return;
    const criteria = current.criteria.slice();
    criteria[index] = next;
    setCurrent({ ...current, criteria });
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <p className="text-foreground/50 text-xs tracking-[0.18em] uppercase">{course.code}</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Rubric builder</h1>
        <p className="text-foreground/70 mt-2 text-sm">
          Start from a blank rubric, ask the model, or import one. Check the wording, then approve it onto the assignment.
        </p>
      </div>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      <div className="flex flex-wrap items-center gap-2">
        <input className="rounded border px-2 py-1 text-sm" value={title} onChange={(event) => setTitle(event.target.value)} />
        <button
          className="rounded-lg border px-3 py-2 text-sm"
          onClick={async () => {
            const created = await run(
              () => pa<Rubric>(`/courses/${course.id}/rubrics`, { method: "POST", body: JSON.stringify({ title }) }),
              setError,
            );
            if (created) {
              await load(course.id);
              setCurrent(created);
            }
          }}
        >
          Blank rubric
        </button>
        <button
          className="bg-foreground text-background rounded-lg px-3 py-2 text-sm"
          onClick={async () => {
            const drafted = await run(() => pa<Rubric>(`/courses/${course.id}/assessment/draft`, { method: "POST" }), setError);
            if (drafted) {
              await load(course.id);
              setCurrent(drafted);
            }
          }}
        >
          Suggest from outcomes
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
          <textarea
            className="border-foreground/15 min-h-16 rounded-xl border bg-transparent p-3 text-sm"
            value={current.brief}
            onChange={(event) => setCurrent({ ...current, brief: event.target.value })}
          />
          {current.criteria.map((criterion, index) => (
            <article key={`${criterion.name}-${index}`} className="border-foreground/10 flex flex-col gap-2 rounded-lg border p-3">
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded border px-2 py-1 text-sm"
                  value={criterion.name}
                  onChange={(event) => editCriterion(index, { ...criterion, name: event.target.value })}
                />
                <input
                  className="w-20 rounded border px-2 py-1 text-sm"
                  type="number"
                  value={criterion.weight}
                  onChange={(event) => editCriterion(index, { ...criterion, weight: Number(event.target.value) })}
                />
              </div>
              {LEVELS.map((level) => (
                <label key={level} className="text-xs">
                  {level}
                  <textarea
                    className="mt-1 min-h-14 w-full rounded border px-2 py-1 text-sm"
                    value={criterion.levels[level] || ""}
                    onChange={(event) =>
                      editCriterion(index, {
                        ...criterion,
                        levels: { ...criterion.levels, [level]: event.target.value },
                      })
                    }
                  />
                </label>
              ))}
            </article>
          ))}
          <button
            className="w-fit text-sm underline"
            onClick={() =>
              setCurrent({
                ...current,
                criteria: [
                  ...current.criteria,
                  { name: "New criterion", weight: 1, levels: { beginning: "", developing: "", proficient: "", advanced: "" } },
                ],
              })
            }
          >
            Add a criterion
          </button>
          <textarea
            className="border-foreground/15 min-h-24 rounded-xl border bg-transparent p-3 text-sm"
            placeholder={"Paste a rubric. Example:\nCriterion: Evidence\nWeight: 2\nBeginning: Names the task\nDeveloping: Partly shows it\nProficient: Quotes an example\nAdvanced: States a limitation"}
            value={paste}
            onChange={(event) => setPaste(event.target.value)}
          />
          <label className="text-sm">
            Import docx, pdf, or xlsx
            <input
              className="mt-1 block"
              type="file"
              accept=".docx,.pdf,.xlsx,.txt"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (!file || !current) return;
                const body = new FormData();
                body.append("file", file);
                const next = await run(
                  () => pa<Rubric>(`/assessments/${current.id}/import`, { method: "POST", body }),
                  setError,
                );
                if (next) setCurrent(next);
              }}
            />
          </label>
          {(current.alignment?.flags || []).map((flag) => (
            <Banner key={flag}>{flag}</Banner>
          ))}
          <div className="flex flex-wrap gap-2">
            <button
              className="rounded-lg border px-3 py-2 text-sm"
              onClick={async () => {
                const next = await run(
                  () =>
                    pa<Rubric>(`/assessments/${current.id}/rubric`, {
                      method: "PUT",
                      body: JSON.stringify({ brief: current.brief, criteria: current.criteria }),
                    }),
                  setError,
                );
                if (next) setCurrent(next);
              }}
            >
              Save version
            </button>
            <button
              className="rounded-lg border px-3 py-2 text-sm"
              onClick={async () => {
                if (paste.trim()) {
                  const body = new FormData();
                  body.append("pasted", paste);
                  const next = await run(
                    () => pa<Rubric>(`/assessments/${current.id}/import`, { method: "POST", body }),
                    setError,
                  );
                  if (next) setCurrent(next);
                }
              }}
            >
              Import pasted text
            </button>
            <button
              className="rounded-lg border px-3 py-2 text-sm"
              onClick={async () => {
                const next = await run(() => pa<Rubric>(`/assessments/${current.id}/check`, { method: "POST" }), setError);
                if (next) setCurrent(next);
              }}
            >
              Check alignment
            </button>
            <button
              className="bg-foreground text-background rounded-lg px-3 py-2 text-sm"
              onClick={async () => {
                await run(async () => {
                  await pa(`/assessments/${current.id}/rubric`, {
                    method: "PUT",
                    body: JSON.stringify({ brief: current.brief, criteria: current.criteria }),
                  });
                  await pa(`/assessments/${current.id}/approve`, { method: "POST" });
                  await load(course.id);
                }, setError);
              }}
            >
              Approve rubric
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
