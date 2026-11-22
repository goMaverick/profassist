"use client";

import { useEffect, useState } from "react";
import { Banner, pa, run } from "@/components/profassist/bits";

interface Reflection {
  id: string;
  proposal: string;
  status: string;
}
interface Memory {
  id: string;
  kind: string;
  text: string;
  source: string;
}

export default function StylePage() {
  const [soul, setSoul] = useState("");
  const [items, setItems] = useState<Reflection[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  async function load() {
    const [style, reflections, memory] = await Promise.all([
      pa<{ soul_md: string }>("/style"),
      pa<{ items: Reflection[] }>("/reflections"),
      pa<{ items: Memory[] }>("/memories"),
    ]);
    setSoul(style.soul_md);
    setItems(reflections.items);
    setMemories(memory.items);
  }

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <div>
        <p className="text-foreground/50 text-xs tracking-[0.18em] uppercase">soul.md</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">My style</h1>
        <p className="text-foreground/70 mt-2 text-sm">
          Agents read this when they write. It stores how you decide, not facts about students.
          A reflection can propose a change. It is not applied until you approve it.
        </p>
      </div>
      {error && <Banner>{error}</Banner>}
      {saved && <Banner>{saved}</Banner>}
      <textarea
        className="border-foreground/15 min-h-64 w-full rounded-xl border bg-transparent p-4 font-mono text-sm"
        value={soul}
        onChange={(event) => setSoul(event.target.value)}
      />
      <div className="flex gap-2">
        <button
          className="bg-foreground text-background rounded-lg px-3 py-2 text-sm"
          onClick={async () => {
            const ok = await run(() => pa("/style", { method: "PUT", body: JSON.stringify({ soul_md: soul }) }), setError);
            if (ok) setSaved("Saved. The next draft will use this voice.");
          }}
        >
          Save style
        </button>
        <button
          className="rounded-lg border px-3 py-2 text-sm"
          onClick={async () => {
            const created = await run(() => pa<Reflection>("/reflections/run", { method: "POST" }), setError);
            if (created) {
              setSaved("A reflection is waiting. It does not change your style until you approve it.");
              await load();
            }
          }}
        >
          Ask for a reflection
        </button>
      </div>
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">What I remember</h2>
        <p className="text-foreground/60 text-sm">
          Only your memories, in this university. Names are removed before anything is saved. Delete one if it is wrong.
        </p>
        {memories.length === 0 && <p className="text-foreground/60 text-sm">Nothing remembered yet. Saving your style writes the first one.</p>}
        {memories.map((memory) => (
          <div key={memory.id} className="border-foreground/10 flex items-start justify-between gap-3 rounded-lg border p-3 text-sm">
            <p>{memory.text}</p>
            <button
              className="underline"
              onClick={async () => {
                await run(async () => {
                  await pa(`/memories/${memory.id}`, { method: "DELETE" });
                  await load();
                }, setError);
              }}
            >
              Delete
            </button>
          </div>
        ))}
      </section>
      {items.map((item) => (
        <article key={item.id} className="border-foreground/10 rounded-lg border p-3 text-sm">
          <p className="text-foreground/50 text-xs uppercase">{item.status}</p>
          <p className="mt-2">{item.proposal}</p>
          {item.status !== "approved" && (
            <button
              className="mt-2 underline"
              onClick={async () => {
                await run(async () => {
                  await pa(`/reflections/${item.id}/approve`, { method: "POST" });
                  await load();
                }, setError);
              }}
            >
              Add this to my style
            </button>
          )}
        </article>
      ))}
    </div>
  );
}
