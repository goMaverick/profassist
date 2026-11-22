"use client";

import { useEffect, useState } from "react";
import { Banner, pa, run, useWorkspace } from "@/components/profassist/bits";

interface Flag {
  id: string;
  section: string;
  passage_a: string;
  passage_b: string;
  score: number;
  kind: string;
  viva: string[];
  rare_details: string[];
  status: string;
  note: string;
}

export default function IntegrityPage() {
  const { course, error: loadError, loading } = useWorkspace();
  const [error, setError] = useState("");
  const [flags, setFlags] = useState<Flag[]>([]);
  const [busy, setBusy] = useState(false);

  async function load(courseId: string) {
    const data = await pa<{ items: Flag[] }>(`/courses/${courseId}/integrity`);
    setFlags(data.items);
  }

  useEffect(() => {
    if (course) load(course.id).catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, [course]);

  if (loading) return <p className="text-sm">Loading flags…</p>;
  if (!course) return <Banner>{loadError || "No course in this workspace."}</Banner>;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <p className="text-sm text-[#525252]">{course.code}. A flag is evidence for a conversation. AI-text detection is not used.</p>
      {(error || loadError) && <Banner>{error || loadError}</Banner>}
      <button
        className="bg-foreground text-background w-fit rounded-lg px-3 py-2 text-sm disabled:opacity-50"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          const data = await run(() => pa<{ items: Flag[] }>(`/courses/${course.id}/integrity/scan`, { method: "POST" }), setError);
          if (data) setFlags(data.items);
          setBusy(false);
        }}
      >
        {busy ? "Comparing…" : "Scan submissions"}
      </button>
      {flags.length === 0 && <p className="text-foreground/60 text-sm">No flags yet.</p>}
      {flags.map((flag) => (
        <article key={flag.id} className="border-foreground/10 rounded-xl border p-4 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium capitalize">{flag.section} · {flag.kind.replace("_", " ")}</p>
            <span className="text-foreground/50">{flag.status} · overlap {flag.score}</span>
          </div>
          <p className="text-foreground/60 mt-1">{flag.note}</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <pre className="bg-foreground/[0.03] rounded-lg p-3 whitespace-pre-wrap">{flag.passage_a}</pre>
            <pre className="bg-foreground/[0.03] rounded-lg p-3 whitespace-pre-wrap">{flag.passage_b}</pre>
          </div>
          {flag.rare_details.length > 0 && (
            <p className="mt-2">Shared details: {flag.rare_details.join(", ")}</p>
          )}
          <ol className="mt-3 list-decimal pl-5">
            {flag.viva.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ol>
          <div className="mt-3 flex gap-3">
            <button className="underline" onClick={async () => {
              await run(async () => {
                await pa(`/integrity/${flag.id}`, { method: "POST", body: JSON.stringify({ status: "confirmed" }) });
                await load(course.id);
              }, setError);
            }}>Confirm as worth a viva</button>
            <button className="underline" onClick={async () => {
              await run(async () => {
                await pa(`/integrity/${flag.id}`, { method: "POST", body: JSON.stringify({ status: "dismissed" }) });
                await load(course.id);
              }, setError);
            }}>Dismiss</button>
          </div>
        </article>
      ))}
    </div>
  );
}
