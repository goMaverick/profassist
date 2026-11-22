"use client";

import { useEffect, useState } from "react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";

interface Clo {
  code: string;
  text: string;
}
interface Week {
  week: number;
  topic: string;
  clos: string[];
  notes: string;
}
interface PlanItem {
  title: string;
  weight: number;
  clos: string[];
  brief: string;
  kind: string;
}
interface Design {
  status: string;
  version: number;
  reply: string;
  weeks: Week[];
  clos: Clo[];
  plan: PlanItem[];
}

export default function DesignPage() {
  const { course, error: loadError, loading } = useWorkspace();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("Draft the weeks, outcomes, and assessment plan from my notes.");
  const [design, setDesign] = useState<Design | null>(null);
  const [busy, setBusy] = useState("");

  async function load(courseId: string) {
    setDesign(await pa<Design>(`/courses/${courseId}/design`));
  }

  useEffect(() => {
    if (course) load(course.id).catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, [course]);

  if (loading) return <p className="text-sm">Loading the design…</p>;
  if (!course) return <Banner>{loadError || "No course in this workspace."}</Banner>;

  function update<K extends keyof Design>(key: K, value: Design[K]) {
    setDesign((current) => (current ? { ...current, [key]: value } : current));
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <p className="text-foreground/50 text-xs tracking-[0.18em] uppercase">{course.code}</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Course design</h1>
        <p className="text-foreground/70 mt-2 text-sm">
          Upload notes in Course studio, then ask for a draft. Edit the weeks, outcomes, and assessment plan. Nothing is used until you approve it.
        </p>
      </div>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      <label className="border-foreground/15 inline-flex w-fit cursor-pointer rounded-lg border px-3 py-2 text-sm">
        Upload a course note
        <input
          className="hidden"
          type="file"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            const body = new FormData();
            body.append("file", file);
            await run(() => pa(`/courses/${course.id}/materials`, { method: "POST", body }), setError);
          }}
        />
      </label>
      <div className="flex flex-col gap-2">
        <textarea
          className="border-foreground/15 min-h-20 w-full rounded-xl border bg-transparent p-3 text-sm"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <button
          className="bg-foreground text-background w-fit rounded-lg px-3 py-2 text-sm disabled:opacity-50"
          disabled={busy !== ""}
          onClick={async () => {
            setBusy("draft");
            const next = await run(
              () => pa<Design>(`/courses/${course.id}/design/draft`, { method: "POST", body: JSON.stringify({ message }) }),
              setError,
            );
            if (next) setDesign(next);
            setBusy("");
          }}
        >
          {busy === "draft" ? "Drafting…" : "Ask for a draft"}
        </button>
        {design?.reply && <p className="text-sm">{design.reply}</p>}
      </div>
      {design && design.clos.length > 0 && (
        <>
          <section className="flex flex-col gap-2">
            <h2 className="text-lg font-medium">Outcomes</h2>
            {design.clos.map((item, index) => (
              <div key={item.code} className="grid grid-cols-[80px_1fr] gap-2">
                <input className="rounded border px-2 py-1 text-sm" value={item.code} onChange={(event) => {
                  const clos = design.clos.slice();
                  clos[index] = { ...item, code: event.target.value };
                  update("clos", clos);
                }} />
                <input className="rounded border px-2 py-1 text-sm" value={item.text} onChange={(event) => {
                  const clos = design.clos.slice();
                  clos[index] = { ...item, text: event.target.value };
                  update("clos", clos);
                }} />
              </div>
            ))}
          </section>
          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-medium">Weeks</h2>
            {design.weeks.map((item, index) => (
              <div key={item.week} className="border-foreground/10 grid gap-2 rounded-lg border p-3">
                <p className="text-xs uppercase">Week {item.week} · {item.clos.join(", ")}</p>
                <input className="rounded border px-2 py-1 text-sm" value={item.topic} onChange={(event) => {
                  const weeks = design.weeks.slice();
                  weeks[index] = { ...item, topic: event.target.value };
                  update("weeks", weeks);
                }} />
                <textarea className="min-h-16 rounded border px-2 py-1 text-sm" value={item.notes} onChange={(event) => {
                  const weeks = design.weeks.slice();
                  weeks[index] = { ...item, notes: event.target.value };
                  update("weeks", weeks);
                }} />
              </div>
            ))}
          </section>
          <section className="flex flex-col gap-3">
            <h2 className="text-lg font-medium">Assessment plan</h2>
            {design.plan.map((item, index) => (
              <div key={`${item.title}-${index}`} className="border-foreground/10 grid gap-2 rounded-lg border p-3 text-sm">
                <input className="rounded border px-2 py-1" value={item.title} onChange={(event) => {
                  const plan = design.plan.slice();
                  plan[index] = { ...item, title: event.target.value };
                  update("plan", plan);
                }} />
                <p className="text-foreground/60">{item.kind} · weight {item.weight} · {item.clos.join(", ")}</p>
                <textarea className="min-h-16 rounded border px-2 py-1" value={item.brief} onChange={(event) => {
                  const plan = design.plan.slice();
                  plan[index] = { ...item, brief: event.target.value };
                  update("plan", plan);
                }} />
              </div>
            ))}
          </section>
          <div className="flex gap-2">
            <button
              className="rounded-lg border px-3 py-2 text-sm"
              onClick={async () => {
                const next = await run(
                  () => pa<Design>(`/courses/${course.id}/design`, { method: "PUT", body: JSON.stringify(design) }),
                  setError,
                );
                if (next) setDesign(next);
              }}
            >
              Save edits
            </button>
            <button
              className="bg-foreground text-background rounded-lg px-3 py-2 text-sm"
              onClick={async () => {
                await run(async () => {
                  await pa(`/courses/${course.id}/design`, { method: "PUT", body: JSON.stringify(design) });
                  const next = await pa<Design>(`/courses/${course.id}/design/approve`, { method: "POST" });
                  setDesign(next);
                }, setError);
              }}
            >
              Approve design
            </button>
            <p className="text-foreground/50 self-center text-xs">{design.status} · version {design.version}</p>
          </div>
        </>
      )}
    </div>
  );
}
