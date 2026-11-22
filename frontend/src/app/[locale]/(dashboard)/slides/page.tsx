"use client";

import { useEffect, useState } from "react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";

interface Bullet {
  text?: string;
  citation?: { filename?: string; section?: string; quote?: string };
}
interface Slide {
  title: string;
  objective?: string;
  bullets: Array<string | Bullet>;
  notes?: string;
  gap?: boolean;
}
interface Deck {
  id: string;
  title: string;
  status: string;
  slides: Slide[];
  gaps?: string[];
  previews?: string[];
}

export default function SlideReviewPage() {
  const { course, error: loadError, loading } = useWorkspace();
  const [error, setError] = useState("");
  const [decks, setDecks] = useState<Deck[]>([]);
  const [busy, setBusy] = useState(false);
  const [master, setMaster] = useState("");
  const [week, setWeek] = useState(1);

  async function load(courseId: string) {
    const data = await pa<{ items: Deck[] }>(`/courses/${courseId}/slides`);
    setDecks(data.items);
  }

  useEffect(() => {
    if (course) load(course.id).catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, [course]);

  if (loading) return <p className="text-sm">Loading decks…</p>;
  if (!course) return <Banner>{loadError || "No course in this workspace."}</Banner>;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <p className="text-foreground/50 text-xs tracking-[0.18em] uppercase">Slide studio</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Review slides and sources</h1>
        <p className="text-foreground/70 mt-2 text-sm">
          Each bullet stays next to the note it came from. A gap means the upload does not cover that objective.
        </p>
      </div>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm">
          Week
          <input
            className="ml-2 w-16 rounded border px-2 py-1"
            type="number"
            min={1}
            value={week}
            onChange={(event) => setWeek(Number(event.target.value) || 1)}
          />
        </label>
        <button
          className="bg-foreground text-background w-fit rounded-lg px-3 py-2 text-sm disabled:opacity-50"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            const deck = await run(
              () => pa<Deck>(`/courses/${course.id}/slides/studio?week=${week}`, { method: "POST" }),
              setError,
            );
            if (deck) await load(course.id);
            setBusy(false);
          }}
        >
          {busy ? "Planning the deck…" : "Build this week's deck"}
        </button>
      </div>
      <label className="text-sm">
        Deck master (.pptx or .potx)
        <input
          className="mt-1 block text-sm"
          type="file"
          accept=".pptx,.potx"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            const body = new FormData();
            body.append("file", file);
            const ok = await run(() => pa("/style/template", { method: "POST", body }), setError);
            if (ok) setMaster(`${file.name} will be used the next time you build a deck.`);
          }}
        />
        {master && <span className="text-foreground/60 mt-1 block">{master}</span>}
      </label>
      {decks.map((deck) => (
        <article key={deck.id} className="flex flex-col gap-3">
          <h2 className="font-medium">
            {deck.title} <span className="text-foreground/50 text-sm">{deck.status}</span>
          </h2>
          {deck.previews && deck.previews.length > 0 && (
            <div className="flex gap-2 overflow-x-auto">
              {deck.previews.map((src, previewIndex) => (
                // Data-URL thumbnails. next/image does not accept them.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={`${deck.id}-preview-${previewIndex}`}
                  src={src}
                  alt=""
                  className="h-28 rounded border"
                />
              ))}
            </div>
          )}
          {deck.slides.map((slide, index) => (
            <div key={`${deck.id}-${index}`} className="border-foreground/10 grid gap-3 rounded-xl border p-4 md:grid-cols-2">
              <div>
                <p className="font-medium">{slide.title}</p>
                {slide.gap && <p className="mt-2 text-sm">Gap: the notes do not cover this objective.</p>}
                <ul className="mt-2 list-disc pl-5 text-sm">
                  {(slide.bullets || []).map((bullet, bulletIndex) => {
                    const text = typeof bullet === "string" ? bullet : bullet.text;
                    return <li key={bulletIndex}>{text}</li>;
                  })}
                </ul>
                {slide.notes && <p className="text-foreground/60 mt-3 text-xs">Notes: {slide.notes}</p>}
              </div>
              <div className="bg-foreground/[0.03] rounded-lg p-3 text-sm">
                <p className="text-foreground/50 text-xs tracking-wide uppercase">Sources</p>
                {(slide.bullets || []).map((bullet, bulletIndex) => {
                  if (typeof bullet === "string") return <p key={bulletIndex}>{bullet}</p>;
                  const cite = bullet.citation || {};
                  return (
                    <p key={bulletIndex} className="mt-2">
                      <span className="font-medium">{cite.filename || "note"}</span>
                      {cite.section ? ` · ${cite.section}` : ""}
                      <span className="mt-1 block">{cite.quote || bullet.text}</span>
                    </p>
                  );
                })}
              </div>
            </div>
          ))}
        </article>
      ))}
    </div>
  );
}
