"use client";

import { useEffect, useState } from "react";
import {
  Button,
  InlineNotification,
  Select,
  SelectItem,
  Tag,
  TextArea,
  TextInput,
  Tile,
  Toggle,
} from "@carbon/react";
import { pa, run } from "@/components/profassist/bits";

interface Source {
  agent: string;
  source: string;
  version: number | null;
  label: string;
  text: string;
  url: string;
}
interface Provider {
  id: string;
  label: string;
  default_model: string;
  configured: boolean;
  env: string[];
}
interface Secret {
  name: string;
  state: string;
}
interface Connections {
  moodle_mode: string;
  moodle_push_enabled: boolean;
  moodle_base_url: string;
  model_from_env: string;
  base_url: string;
  langfuse_enabled: boolean;
  langfuse_host: string;
  qdrant_host: string;
  qdrant_port: number;
  mcp_installed: boolean;
  mcp_path: string;
  secrets: Secret[];
}
interface PromptVersionRow {
  agent: string;
  version: number;
  body: string;
  active: boolean;
}
interface View {
  chat_enabled: boolean;
  provider: string;
  model: string;
  base_url: string;
  debate_enabled: boolean;
  debate_threshold: number;
  debate_max_rounds: number;
  providers: Provider[];
  agents: string[];
  agent_models: Record<string, { provider: string; model: string }>;
  prompt_sources?: Source[];
  prompts?: PromptVersionRow[];
  moodle_sync_paused: boolean;
  moodle_sync_minutes: number;
  moodle_nightly_enabled: boolean;
  moodle_nightly_hour: number;
  tools: Array<{ agent: string; tool: string; enabled: boolean }>;
  connections?: Connections;
  audit: Array<{ agent: string; version: number; action: string; before: string; after: string }>;
}

const AGENT_LABEL: Record<string, string> = {
  course_designer: "Course drafter",
  rubric_designer: "Rubric drafter",
  persona_evidence: "Evidence grader",
  persona_strict: "Strict grader",
  persona_supportive: "Supportive grader",
  feedback_writer: "Feedback writer",
  integrity: "Integrity checker",
  reflection: "Reflection",
  slide_studio: "Slide studio",
  chat: "Chat",
  grading_council: "Grading council",
};

function agentLabel(agent: string) {
  return AGENT_LABEL[agent] || agent.replaceAll("_", " ");
}

export default function AiAdminPage() {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [testNote, setTestNote] = useState("");
  const [promptKey, setPromptKey] = useState("course_designer");
  const [draft, setDraft] = useState("");
  const [savingPrompt, setSavingPrompt] = useState(false);

  async function load() {
    const data = await pa<View>("/admin/ai");
    setView(data);
    const first = data.prompt_sources?.[0];
    if (first) {
      setPromptKey(first.agent);
      setDraft(first.text);
    }
  }

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, []);

  if (!view && !error) return <p>Loading AI settings…</p>;
  if (!view) return <InlineNotification kind="error" title="AI settings" subtitle={error} hideCloseButton />;

  const connections = view.connections;
  const chosen = (view.prompt_sources || []).find((item) => item.agent === promptKey);
  const versions = (view.prompts || []).filter((item) => item.agent === promptKey);

  async function saveSettings() {
    const next = await run(
      () =>
        pa<View>("/admin/ai", {
          method: "PUT",
          body: JSON.stringify({
            chat_enabled: view.chat_enabled,
            provider: view.provider,
            model: view.model,
            base_url: view.base_url,
            debate_enabled: view.debate_enabled,
            debate_threshold: view.debate_threshold,
            debate_max_rounds: view.debate_max_rounds,
            agent_models: view.agent_models,
            moodle_sync_paused: view.moodle_sync_paused,
            moodle_sync_minutes: view.moodle_sync_minutes,
            moodle_nightly_enabled: view.moodle_nightly_enabled,
            moodle_nightly_hour: view.moodle_nightly_hour,
          }),
        }),
      setError,
    );
    if (next) {
      setView(next);
      setNote("Saved. Keys were not changed.");
    }
  }

  return (
    <div className="pa-dash" style={{ display: "grid", gap: 16 }}>
      {error && <InlineNotification kind="error" title="Check this" subtitle={error} hideCloseButton />}
      {note && <InlineNotification kind="success" title="Saved" subtitle={note} hideCloseButton lowContrast />}
      <Tile id="ai-council">
        <p className="pa-step-kicker">Admin</p>
        <h1 style={{ fontWeight: 400, margin: "4px 0 8px" }}>AI settings</h1>
        <p style={{ maxWidth: 720 }}>
          This is where an admin turns the assistant on, picks a model for each agent, and sees which servers are connected.
          Secret keys stay in the server environment. This page never shows a key.
        </p>
        <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
          <Toggle
            id="chat-enabled"
            labelText="Chat"
            labelA="Chat is off"
            labelB="Chat is on"
            toggled={view.chat_enabled}
            onToggle={(checked) => setView({ ...view, chat_enabled: checked })}
          />
          <p>When chat is off, the professor can still use the pages. The chat bar will not call a model.</p>
          <Toggle
            id="debate-enabled"
            labelText="Council debate"
            labelA="Graders do not debate"
            labelB="Graders debate when they disagree"
            toggled={view.debate_enabled}
            onToggle={(checked) => setView({ ...view, debate_enabled: checked })}
          />
          <TextInput
            id="debate-threshold"
            labelText="How far apart the graders must be before they debate"
            helperText="0 means any disagreement. 3 means they debate only when the bands are far apart."
            type="number"
            min={0}
            max={3}
            value={String(view.debate_threshold)}
            onChange={(event) => setView({ ...view, debate_threshold: Number(event.target.value) })}
          />
          <TextInput
            id="debate-rounds"
            labelText="How many debate rounds"
            helperText="The chair stops after this many rounds, from 0 to 3."
            type="number"
            min={0}
            max={3}
            value={String(view.debate_max_rounds)}
            onChange={(event) => setView({ ...view, debate_max_rounds: Number(event.target.value) })}
          />
          <TextInput
            id="default-model"
            labelText="Default model"
            helperText="Used when an agent below does not name its own model. The environment can also set LLM_MODEL."
            value={view.model}
            onChange={(event) => setView({ ...view, model: event.target.value })}
          />
          <Button kind="primary" onClick={() => void saveSettings()}>Save these choices</Button>
        </div>
      </Tile>

      <Tile id="ai-agents">
        <h2 style={{ fontWeight: 400, marginTop: 0 }}>Model for each agent</h2>
        <p>
          The three council graders can each use a different provider. The chair does not have its own row.
          The chair uses the default model above.
        </p>
        <div style={{ display: "grid", gap: 16 }}>
          {view.agents.map((agent) => {
            const choice = view.agent_models[agent] || { provider: view.provider, model: view.model };
            return (
              <div key={agent} style={{ display: "grid", gap: 8, borderTop: "1px solid #e0e0e0", paddingTop: 12 }}>
                <strong>{agentLabel(agent)}</strong>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <Select
                  id={`provider-${agent}`}
                  labelText="Provider"
                  value={choice.provider}
                  onChange={(event) =>
                    setView({
                      ...view,
                      agent_models: {
                        ...view.agent_models,
                        [agent]: { ...choice, provider: event.target.value },
                      },
                    })
                  }
                >
                  {view.providers.map((provider) => (
                    <SelectItem key={provider.id} value={provider.id} text={provider.label} />
                  ))}
                </Select>
                <TextInput
                  id={`model-${agent}`}
                  labelText="Model"
                  value={choice.model}
                  onChange={(event) =>
                    setView({
                      ...view,
                      agent_models: {
                        ...view.agent_models,
                        [agent]: { ...choice, model: event.target.value },
                      },
                    })
                  }
                />
                </div>
              </div>
            );
          })}
        </div>
        <div style={{ marginTop: 12 }}>
          <Button kind="secondary" onClick={() => void saveSettings()}>Save agent models</Button>
        </div>
      </Tile>

      <Tile id="ai-providers">
        <h2 style={{ fontWeight: 400, marginTop: 0 }}>Provider connections</h2>
        <p>
          A key is either “not set” or “set, hidden”. Add a missing key as an environment variable and restart the server.
          This page cannot type a key in.
        </p>
        {testNote && <InlineNotification kind="info" title="Connection test" subtitle={testNote} hideCloseButton lowContrast />}
        {view.providers.map((provider) => (
          <div key={provider.id} style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", padding: "8px 0", borderTop: "1px solid #e0e0e0" }}>
            <div>
              <strong>{provider.label}</strong>
              <p style={{ margin: "4px 0" }}>
                <Tag type={provider.configured ? "green" : "gray"} size="sm">
                  {provider.configured ? "key set, hidden" : "no key"}
                </Tag>
              </p>
              <p style={{ margin: 0, color: "#525252" }}>Looks for {provider.env.join(" or ")}. Default model {provider.default_model}.</p>
            </div>
            <Button
              kind="tertiary"
              size="sm"
              onClick={async () => {
                const result = await run(
                  () =>
                    pa<{ ok: boolean; detail: string }>("/admin/ai/test", {
                      method: "POST",
                      body: JSON.stringify({ provider: provider.id, model: provider.default_model }),
                    }),
                  setError,
                );
                if (result) setTestNote(`${provider.label}: ${result.detail}`);
              }}
            >
              Test {provider.label}
            </Button>
          </div>
        ))}
      </Tile>

      <Tile id="ai-prompts">
        <h2 style={{ fontWeight: 400, marginTop: 0 }}>Prompts</h2>
        <p>
          Each agent has one instruction. If Langfuse is connected, the production label there wins.
          If Langfuse is off, a version you save here is used for this university. Older versions stay in the list.
        </p>
        <Select
          id="prompt-agent"
          labelText="Which prompt"
          value={promptKey}
          onChange={(event) => {
            const key = event.target.value;
            const source = (view.prompt_sources || []).find((item) => item.agent === key);
            setPromptKey(key);
            setDraft(source?.text || "");
          }}
        >
          {(view.prompt_sources || []).map((source) => (
            <SelectItem key={source.agent} value={source.agent} text={agentLabel(source.agent)} />
          ))}
        </Select>
        {chosen && (
          <p>
            Using the {chosen.source} copy{chosen.version ? `, version ${chosen.version}` : ""} ({chosen.label}).
            {chosen.url && (
              <>
                {" "}
                <a href={chosen.url}>Open this prompt in Langfuse</a>
              </>
            )}
          </p>
        )}
        <TextArea
          id="prompt-body"
          labelText="Prompt text"
          helperText="Saving makes a new version. It does not delete the previous one."
          rows={6}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          kind="primary"
          disabled={savingPrompt || !draft.trim()}
          onClick={async () => {
            setSavingPrompt(true);
            const next = await run(
              () =>
                pa<View>("/admin/ai/prompts", {
                  method: "POST",
                  body: JSON.stringify({ agent: promptKey, body: draft }),
                }),
              setError,
            );
            if (next) {
              setView(next);
              setNote(`Saved a new version of ${agentLabel(promptKey)}.`);
            }
            setSavingPrompt(false);
          }}
        >
          Save a new version
        </Button>
        <h3 style={{ fontWeight: 600 }}>Versions saved here</h3>
        {versions.length === 0 && <p>No saved versions yet. The text above is the built-in default.</p>}
        <ul style={{ paddingLeft: 18 }}>
          {versions.map((row) => (
            <li key={`${row.agent}-${row.version}`}>
              Version {row.version} {row.active ? "· in use" : "· kept"}
            </li>
          ))}
        </ul>
      </Tile>

      <Tile id="ai-tools">
        <h2 style={{ fontWeight: 400, marginTop: 0 }}>Tools and the MCP server</h2>
        <p>
          FastMCP serves the same tools the chat can call, at {connections?.mcp_path || "/mcp"}.
          {connections?.mcp_installed
            ? " The FastMCP package is installed, so that address is mounted."
            : " The FastMCP package is not installed, so that address is not mounted."}
          {" "}Turning a tool off here stops the chat from calling it. It does not delete the tool.
        </p>
        {view.tools.map((tool) => (
          <div key={`${tool.agent}.${tool.tool}`} style={{ borderTop: "1px solid #e0e0e0", padding: "4px 0" }}>
          <Toggle
            id={`tool-${tool.agent}-${tool.tool}`}
            labelText={`${agentLabel(tool.agent)} · ${tool.tool.replaceAll("_", " ")}`}
            labelA="Off"
            labelB="On"
            toggled={tool.enabled}
            onToggle={async (checked) => {
              const next = await run(
                () =>
                  pa<View>("/admin/ai/tools", {
                    method: "POST",
                    body: JSON.stringify({ agent: tool.agent, tool: tool.tool, enabled: checked }),
                  }),
                setError,
              );
              if (next) setView(next);
            }}
          />
          </div>
        ))}
      </Tile>

      <Tile id="ai-moodle">
        <h2 style={{ fontWeight: 400, marginTop: 0 }}>Moodle connection</h2>
        <p>These values come from the server environment. Change them there and restart. This page cannot edit them.</p>
        <p><strong>Mode.</strong> {connections?.moodle_mode === "fake" ? "Fake. Moodle is not contacted. Sync and push are recorded on this computer." : "Real. The server will call the university Moodle."}</p>
        <p><strong>Grade push (MOODLE_PUSH_ENABLED).</strong> {connections?.moodle_push_enabled ? "On. An approved grade can be written to Moodle." : "Off. Approving a grade does not write it to Moodle."}</p>
        <p><strong>Moodle address (MOODLE_BASE_URL).</strong> {connections?.moodle_base_url}</p>
        <p><strong>Moodle token (MOODLE_WS_TOKEN).</strong> {connections?.secrets.find((item) => item.name === "MOODLE_WS_TOKEN")?.state}</p>
        <h3 style={{ fontWeight: 600 }}>Sync schedule</h3>
        <p>The regular pull is the main path. “Sync now” on the grading page is only a backup.</p>
        <Toggle
          id="sync-paused"
          labelText="Regular sync"
          labelA="Running"
          labelB="Paused"
          toggled={view.moodle_sync_paused}
          onToggle={(checked) => setView({ ...view, moodle_sync_paused: checked })}
        />
        <Select
          id="sync-minutes"
          labelText="How often to pull"
          value={String(view.moodle_sync_minutes)}
          onChange={(event) => setView({ ...view, moodle_sync_minutes: Number(event.target.value) })}
        >
          {[15, 30, 60, 120].map((minutes) => (
            <SelectItem key={minutes} value={String(minutes)} text={`Every ${minutes} minutes`} />
          ))}
        </Select>
        <Toggle
          id="nightly"
          labelText="Nightly full sync"
          labelA="Off"
          labelB="On"
          toggled={view.moodle_nightly_enabled}
          onToggle={(checked) => setView({ ...view, moodle_nightly_enabled: checked })}
        />
        <TextInput
          id="nightly-hour"
          labelText="Nightly hour, UTC"
          type="number"
          min={0}
          max={23}
          value={String(view.moodle_nightly_hour)}
          onChange={(event) => setView({ ...view, moodle_nightly_hour: Number(event.target.value) })}
        />
        <Button kind="secondary" onClick={() => void saveSettings()}>Save the sync schedule</Button>
      </Tile>

      <Tile id="ai-tracing">
        <h2 style={{ fontWeight: 400, marginTop: 0 }}>Tracing, search, and keys</h2>
        <p>
          Langfuse records each agent step after personal data has been removed. Qdrant stores the search index for notes and memory.
          Both are read from the environment.
        </p>
        <p><strong>Langfuse.</strong> {connections?.langfuse_enabled ? "On." : "Off. Traces stay in the server log only."} Host {connections?.langfuse_host}.</p>
        <p><strong>Langfuse public key.</strong> {connections?.secrets.find((item) => item.name === "LANGFUSE_PUBLIC_KEY")?.state}</p>
        <p><strong>Langfuse secret key.</strong> {connections?.secrets.find((item) => item.name === "LANGFUSE_SECRET_KEY")?.state}</p>
        <p><strong>Qdrant.</strong> {connections?.qdrant_host}:{connections?.qdrant_port}. API key {connections?.secrets.find((item) => item.name === "QDRANT_API_KEY")?.state}.</p>
        <p><strong>Model from the environment (LLM_MODEL).</strong> {connections?.model_from_env}</p>
        <p><strong>Model server URL (LLM_BASE_URL).</strong> {connections?.base_url}</p>
        <h3 style={{ fontWeight: 600 }}>Every secret this server looks for</h3>
        <ul style={{ paddingLeft: 18 }}>
          {(connections?.secrets || []).map((item) => (
            <li key={item.name}><strong>{item.name}.</strong> {item.state}</li>
          ))}
        </ul>
        <h3 style={{ fontWeight: 600 }}>Recent prompt and setting changes</h3>
        {view.audit.length === 0 && <p>No edits yet.</p>}
        <ul style={{ paddingLeft: 18 }}>
          {view.audit.map((row, index) => (
            <li key={`${row.agent}-${row.version}-${index}`}>{row.action} · {agentLabel(row.agent)} · version {row.version}</li>
          ))}
        </ul>
      </Tile>
    </div>
  );
}
