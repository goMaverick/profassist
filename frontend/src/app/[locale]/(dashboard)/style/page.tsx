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
  owner_name?: string;
  created_at?: string;
}
interface StylePayload {
  soul_md: string;
  about_md: string;
  about_history: Array<{ version: number; text: string; source: string }>;
  owner_name: string;
  owner_role?: string;
  courses?: string[];
}

export default function StylePage() {
  const [soul, setSoul] = useState("");
  const [about, setAbout] = useState("");
  const [history, setHistory] = useState<StylePayload["about_history"]>([]);
  const [owner, setOwner] = useState("");
  const [role, setRole] = useState("");
  const [courses, setCourses] = useState<string[]>([]);
  const [items, setItems] = useState<Reflection[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  async function load() {
    const [style, reflections, memory] = await Promise.all([
      pa<StylePayload>("/style"),
      pa<{ items: Reflection[] }>("/reflections"),
      pa<{ items: Memory[] }>("/memories"),
    ]);
    setSoul(style.soul_md);
    setAbout(style.about_md || "");
    setHistory(style.about_history || []);
    setOwner(style.owner_name || "");
    setRole(style.owner_role || "");
    setCourses(style.courses || []);
    setItems(reflections.items);
    setMemories(memory.items);
  }

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <p className="text-sm text-[#525252]">This stores how you decide, not facts about students.</p>
      {error && <Banner>{error}</Banner>}
      {saved && <Banner>{saved}</Banner>}
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">About me</h2>
        <p className="text-foreground/60 text-sm">
          {owner ? `${owner}${role ? ` · ${role}` : ""}${courses.length ? ` · ${courses.join(", ")}` : ""}. ` : ""}
          Every agent reads this portrait for you, in this university only. It is built from your signed-in profile and the edits you make, then rewritten from your memories. It does not change the shared prompts.
        </p>
        <textarea
          className="border-foreground/15 min-h-40 w-full rounded-xl border bg-transparent p-4 text-sm"
          value={about}
          onChange={(event) => setAbout(event.target.value)}
        />
        <div className="flex gap-2">
          <button
            className="bg-foreground text-background rounded-lg px-3 py-2 text-sm"
            onClick={async () => {
              const next = await run(
                () => pa<StylePayload>("/style/about", { method: "PUT", body: JSON.stringify({ about_md: about }) }),
                setError,
              );
              if (next) {
                setAbout(next.about_md || "");
                setHistory(next.about_history || []);
                setSaved("About me saved. The next draft will include it.");
              }
            }}
          >
            Save about me
          </button>
          <button
            className="rounded-lg border px-3 py-2 text-sm"
            onClick={async () => {
              const next = await run(() => pa<StylePayload>("/style/about/reset", { method: "POST" }), setError);
              if (next) {
                setAbout(next.about_md || "");
                setHistory(next.about_history || []);
                setSaved("About me was rebuilt from your style and memories.");
              }
            }}
          >
            Reset
          </button>
        </div>
        {history.length > 0 && (
          <div className="text-foreground/60 text-xs">
            Earlier versions: {history.slice(-5).map((item) => `v${item.version} (${item.source})`).join(", ")}
          </div>
        )}
      </section>
      <textarea
        className="border-foreground/15 min-h-64 w-full rounded-xl border bg-transparent p-4 font-mono text-sm"
        value={soul}
        onChange={(event) => setSoul(event.target.value)}
      />
      <p className="text-foreground/60 text-sm">
        This voice and the About me portrait are both injected into every agent prompt. Changes are remembered per professor.
      </p>
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
              setSaved("A reflection was added to About me. Edit the portrait above to change it.");
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
            <div>
              <p>{memory.text}</p>
              <p className="text-foreground/50 mt-1 text-xs">
                {[memory.owner_name, memory.kind, memory.source, memory.created_at].filter(Boolean).join(" · ")}
              </p>
            </div>
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
          <p className="text-foreground/50 text-xs uppercase">In your portrait</p>
          <p className="mt-2">{item.proposal}</p>
          <p className="text-foreground/60 mt-2 text-xs">
            This is already in About me. Edit the portrait above to change it.
          </p>
        </article>
      ))}
    </div>
  );
}
