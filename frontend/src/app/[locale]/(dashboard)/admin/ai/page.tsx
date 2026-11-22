"use client";

import { useEffect, useState } from "react";
import { Banner, pa, run } from "@/components/profassist/bits";

interface View {
  chat_enabled: boolean;
  provider: string;
  model: string;
  base_url: string;
  defaults: Record<string, string>;
  prompts: Array<{ agent: string; version: number; body: string; active: boolean }>;
  tools: Array<{ agent: string; tool: string; enabled: boolean }>;
  audit: Array<{ agent: string; version: number; action: string; before: string; after: string }>;
}

export default function AiAdminPage() {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [agent, setAgent] = useState("course_designer");
  const [body, setBody] = useState("");

  async function load() {
    const data = await pa<View>("/admin/ai");
    setView(data);
    const active = data.prompts.find((row) => row.agent === agent && row.active);
    setBody(active?.body || data.defaults[agent] || "");
  }

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
    // The first load fills the editor for the default agent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!view && !error) return <p className="text-sm">Loading AI settings…</p>;

  return (
    <div className="flex max-w-3xl flex-col gap-6 text-sm">
      {error && <Banner>{error}</Banner>}
      {view && (
        <>
          <section className="border-foreground/10 flex flex-col gap-3 rounded-xl border p-4">
            <h2 className="text-lg font-medium">Model and chat</h2>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={view.chat_enabled}
                onChange={(event) => setView({ ...view, chat_enabled: event.target.checked })}
              />
              AI chat enabled
            </label>
            <label>
              Provider
              <input
                className="border-foreground/15 mt-1 block w-full rounded-md border bg-transparent px-2 py-1"
                value={view.provider}
                onChange={(event) => setView({ ...view, provider: event.target.value })}
              />
            </label>
            <label>
              Model
              <input
                className="border-foreground/15 mt-1 block w-full rounded-md border bg-transparent px-2 py-1"
                value={view.model}
                onChange={(event) => setView({ ...view, model: event.target.value })}
              />
            </label>
            <label>
              Base URL (optional OpenAI-compatible endpoint)
              <input
                className="border-foreground/15 mt-1 block w-full rounded-md border bg-transparent px-2 py-1"
                value={view.base_url}
                onChange={(event) => setView({ ...view, base_url: event.target.value })}
              />
            </label>
            <button
              className="bg-foreground text-background w-fit rounded-lg px-3 py-2"
              onClick={async () => {
                const next = await run(
                  () =>
                    pa<View>("/admin/ai", {
                      method: "PUT",
                      body: JSON.stringify({
                        chat_enabled: view.chat_enabled,
                        provider: view.provider,
                        model: view.model,
                        base_url: view.base_url,
                      }),
                    }),
                  setError,
                );
                if (next) setView(next);
              }}
            >
              Save model settings
            </button>
            <p className="text-foreground/60">
              The API key stays in the environment (`LLM_API_KEY` or `OPENAI_API_KEY`). This page does not store secrets.
            </p>
          </section>
          <section className="border-foreground/10 flex flex-col gap-3 rounded-xl border p-4">
            <h2 className="text-lg font-medium">Agent prompt</h2>
            <select
              className="border-foreground/15 rounded-md border bg-transparent px-2 py-1"
              value={agent}
              onChange={(event) => {
                const next = event.target.value;
                setAgent(next);
                const active = view.prompts.find((row) => row.agent === next && row.active);
                setBody(active?.body || view.defaults[next] || "");
              }}
            >
              {Object.keys(view.defaults).map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
            <textarea
              className="border-foreground/15 min-h-32 rounded-lg border bg-transparent p-3"
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
            <button
              className="bg-foreground text-background w-fit rounded-lg px-3 py-2"
              onClick={async () => {
                const next = await run(
                  () =>
                    pa<View>("/admin/ai/prompts", {
                      method: "POST",
                      body: JSON.stringify({ agent, body }),
                    }),
                  setError,
                );
                if (next) setView(next);
              }}
            >
              Publish a new version
            </button>
            <ul className="text-foreground/70">
              {view.prompts
                .filter((row) => row.agent === agent)
                .map((row) => (
                  <li key={`${row.agent}-${row.version}`}>
                    v{row.version} {row.active ? "(active)" : ""}
                  </li>
                ))}
            </ul>
          </section>
          <section className="border-foreground/10 flex flex-col gap-2 rounded-xl border p-4">
            <h2 className="text-lg font-medium">Tools</h2>
            {view.tools.map((tool) => (
              <label key={`${tool.agent}.${tool.tool}`} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={tool.enabled}
                  onChange={async (event) => {
                    const next = await run(
                      () =>
                        pa<View>("/admin/ai/tools", {
                          method: "POST",
                          body: JSON.stringify({
                            agent: tool.agent,
                            tool: tool.tool,
                            enabled: event.target.checked,
                          }),
                        }),
                      setError,
                    );
                    if (next) setView(next);
                  }}
                />
                {tool.agent} / {tool.tool}
              </label>
            ))}
          </section>
          <section className="border-foreground/10 rounded-xl border p-4">
            <h2 className="text-lg font-medium">Audit</h2>
            <ul className="mt-2 flex flex-col gap-2">
              {view.audit.map((row, index) => (
                <li key={index}>
                  {row.action} · {row.agent} · v{row.version}
                </li>
              ))}
              {view.audit.length === 0 && <li className="text-foreground/60">No edits yet.</li>}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
