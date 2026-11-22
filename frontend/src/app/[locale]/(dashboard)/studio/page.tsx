"use client";

import { useEffect, useState } from "react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";

interface Material {
  id: string;
  filename: string;
  status: string;
  pii_report: { quarantined?: boolean; uncertain?: string[] };
}
interface Objective {
  id: string;
  text: string;
  status: string;
}
interface Deck {
  id: string;
  title: string;
  status: string;
  slides: Array<{ title: string; bullets: string[] }>;
}
interface Assessment {
  id: string;
  title: string;
  brief: string;
  status: string;
  criteria: Array<{ name: string; levels: Record<string, string> }>;
}

export default function StudioPage() {
  const { course, error: loadError, loading } = useWorkspace();
  const [error, setError] = useState("");
  const [materials, setMaterials] = useState<Material[]>([]);
  const [objectives, setObjectives] = useState<Objective[]>([]);
  const [decks, setDecks] = useState<Deck[]>([]);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [busy, setBusy] = useState("");

  async function refresh(courseId: string) {
    const [mats, objs, slides, rubric] = await Promise.all([
      pa<{ items: Material[] }>(`/courses/${courseId}/materials`),
      pa<{ items: Objective[] }>(`/courses/${courseId}/objectives`),
      pa<{ items: Deck[] }>(`/courses/${courseId}/slides`),
      pa<{ assessment: Assessment | null }>(`/courses/${courseId}/assessment`),
    ]);
    setMaterials(mats.items);
    setObjectives(objs.items);
    setDecks(slides.items);
    setAssessment(rubric.assessment);
  }

  useEffect(() => {
    if (course) refresh(course.id).catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, [course]);

  if (loading) return <p className="text-sm">Loading the studio…</p>;
  if (!course) return <Banner>{loadError || "No demo course yet. Is the database seeded?"}</Banner>;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
      <p className="text-sm text-[#525252]">{course.code}</p>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-medium">Course notes</h2>
        <label className="border-foreground/15 hover:bg-foreground/[0.03] inline-flex w-fit cursor-pointer rounded-lg border px-3 py-2 text-sm">
          Upload a note (txt, md, pdf, docx)
          <input
            className="hidden"
            type="file"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              setBusy("upload");
              const body = new FormData();
              body.append("file", file);
              await run(async () => {
                await pa(`/courses/${course.id}/materials`, { method: "POST", body });
                await refresh(course.id);
              }, setError);
              setBusy("");
            }}
          />
        </label>
        <ul className="flex flex-col gap-2">
          {materials.map((item) => (
            <li key={item.id} className="border-foreground/10 flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
              <span>{item.filename}</span>
              <span className="text-foreground/60">
                {item.status === "quarantined" ? "Quarantined — personal data was not fully removed" : "Indexed"}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-medium">Objectives</h2>
          <button
            className="bg-foreground text-background rounded-lg px-3 py-2 text-sm disabled:opacity-50"
            disabled={busy !== ""}
            onClick={async () => {
              setBusy("objectives");
              await run(async () => {
                await pa(`/courses/${course.id}/objectives/draft`, { method: "POST" });
                await refresh(course.id);
              }, setError);
              setBusy("");
            }}
          >
            {busy === "objectives" ? "Drafting…" : "Draft from notes"}
          </button>
        </div>
        {objectives.map((item) => (
          <div key={item.id} className="border-foreground/10 rounded-lg border p-3 text-sm">
            <p>{item.text}</p>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-foreground/50">{item.status}</span>
              {item.status !== "approved" && (
                <button
                  className="underline"
                  onClick={async () => {
                    await run(async () => {
                      await pa(`/objectives/${item.id}/approve`, { method: "POST" });
                      await refresh(course.id);
                    }, setError);
                  }}
                >
                  Approve
                </button>
              )}
            </div>
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-medium">Slides</h2>
          <button
            className="bg-foreground text-background rounded-lg px-3 py-2 text-sm disabled:opacity-50"
            disabled={busy !== ""}
            onClick={async () => {
              setBusy("slides");
              await run(async () => {
                await pa(`/courses/${course.id}/slides/draft`, { method: "POST" });
                await refresh(course.id);
              }, setError);
              setBusy("");
            }}
          >
            {busy === "slides" ? "Drafting…" : "Draft slides"}
          </button>
        </div>
        {decks.map((deck) => (
          <div key={deck.id} className="border-foreground/10 rounded-lg border p-3 text-sm">
            <div className="flex items-center justify-between">
              <p className="font-medium">{deck.title}</p>
              <span className="text-foreground/50">{deck.status}</span>
            </div>
            <ul className="mt-2 list-disc pl-5">
              {deck.slides.flatMap((slide) => slide.bullets).slice(0, 4).map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
            <div className="mt-3 flex gap-3">
              <button
                className="underline"
                onClick={async () => {
                  const blob = await pa<Blob>(`/slides/${deck.id}/pptx`);
                  const url = URL.createObjectURL(blob);
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = `${deck.title}.pptx`;
                  link.click();
                  URL.revokeObjectURL(url);
                }}
              >
                Download pptx
              </button>
              {deck.status !== "approved" && (
                <button
                  className="underline"
                  onClick={async () => {
                    await run(async () => {
                      await pa(`/slides/${deck.id}/approve`, { method: "POST" });
                      await refresh(course.id);
                    }, setError);
                  }}
                >
                  Approve slides
                </button>
              )}
            </div>
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-medium">Assessment and rubric</h2>
          <button
            className="bg-foreground text-background rounded-lg px-3 py-2 text-sm disabled:opacity-50"
            disabled={busy !== ""}
            onClick={async () => {
              setBusy("rubric");
              await run(async () => {
                await pa(`/courses/${course.id}/assessment/draft`, { method: "POST" });
                await refresh(course.id);
              }, setError);
              setBusy("");
            }}
          >
            {busy === "rubric" ? "Designing…" : "Design rubric"}
          </button>
        </div>
        {assessment && (
          <div className="border-foreground/10 rounded-lg border p-3 text-sm">
            <div className="flex items-center justify-between">
              <p className="font-medium">{assessment.title}</p>
              <span className="text-foreground/50">{assessment.status}</span>
            </div>
            <p className="text-foreground/70 mt-2">{assessment.brief}</p>
            <ul className="mt-3 flex flex-col gap-2">
              {assessment.criteria.map((criterion) => (
                <li key={criterion.name}>
                  <p className="font-medium">{criterion.name}</p>
                  <p className="text-foreground/60">Proficient: {criterion.levels.proficient}</p>
                </li>
              ))}
            </ul>
            {assessment.status !== "approved" && assessment.criteria.length > 0 && (
              <button
                className="mt-3 underline"
                onClick={async () => {
                  await run(async () => {
                    await pa(`/assessments/${assessment.id}/approve`, { method: "POST" });
                    await refresh(course.id);
                  }, setError);
                }}
              >
                Approve rubric
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
