"use client";

import { useEffect, useState } from "react";

import { pa, run } from "@/components/profassist/bits";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  FormField,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";

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
  published_to_langfuse?: boolean;
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

function toolName(tool: string) {
  return tool.replaceAll("_", " ");
}

const BADGE_TONE = {
  green: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700",
  blue: "border-blue-500/40 bg-blue-500/10 text-blue-700",
  gray: "border-border bg-muted text-muted-foreground",
} as const;

function Notice({
  variant = "default",
  title,
  children,
}: {
  variant?: "default" | "destructive" | "success";
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Alert variant={variant}>
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  );
}

function ToggleRow({
  id,
  label,
  labelA,
  labelB,
  checked,
  onCheckedChange,
}: {
  id: string;
  label: string;
  labelA: string;
  labelB: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="space-y-0.5">
        <Label htmlFor={id}>{label}</Label>
        <p className="text-muted-foreground text-xs">{checked ? labelB : labelA}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}

const TOOL_HELP: Record<string, string> = {
  retrieve_notes: "Reads the files uploaded for this course.",
  draft: "Writes a draft the professor can edit.",
  quote_check: "Checks that a quote appears in the submission.",
  judge: "Picks one rubric band from the graders.",
  feedback: "Writes the comment the student will see.",
  fingerprint: "Compares submissions for shared wording.",
  viva: "Suggests questions for a conversation about the work.",
  compare_edits: "Notices how the professor changed a draft.",
  plan: "Outlines the slides before they are written.",
  retrieve: "Finds the note a slide should cite.",
  cite: "Attaches a source to each slide.",
  critique: "Flags a slide that is not supported by the notes.",
  pptx: "Builds the PowerPoint file.",
  rag_search: "Searches the course notes from the chat.",
  propose: "Suggests a few project ideas.",
  write: "Writes a strong, average, and weak example.",
  curriculum: "Checks the weekly topics against the outcomes.",
  alignment: "Checks that course outcomes map to the program.",
  balance: "Checks that assessment weights add up.",
  student: "Reads the outline the way a student would.",
  debate: "Lets the reviewers answer one another.",
  list_courses: "Lists the courses in this workspace.",
  get_course: "Opens one course.",
  list_outlines: "Lists subject outlines.",
  start_outline: "Starts a blank outline.",
  assist_outline: "Drafts one step of an outline.",
  create_assignment: "Creates an assignment from the outline.",
  dropout_risk: "Shows who may need a check-in.",
  integrity_concerns: "Opens work that may be too similar.",
  suggest_assessments: "Suggests assessment tasks.",
  accept_assessments: "Saves the tasks the professor accepts.",
  generate_slides: "Makes slides from the notes.",
  moodle_sync: "Pulls courses and submissions.",
  moodle_push: "Sends an approved grade.",
  start_grade: "Starts a grade draft.",
  list_memories: "Lists what the assistant remembers.",
  delete_memory: "Forgets one saved note.",
  admin_ai_settings: "Reads these settings.",
};

function toolHelp(agent: string, tool: string) {
  if (agent === "outline_review" && tool === "judge") {
    return "Keeps a finding only when the reviewers agree it is a real gap.";
  }
  return TOOL_HELP[tool] || "The assistant can call this when the switch is on.";
}

function promptStatus(source: Source, saved: PromptVersionRow | undefined) {
  if (source.source === "langfuse") {
    return source.version ? `From Langfuse, version ${source.version}` : "From Langfuse";
  }
  if (saved) return `Saved version ${saved.version}`;
  if (source.source === "database" && source.version) return `Saved version ${source.version}`;
  return "Built-in";
}

function dubaiLine(utcHour: number) {
  const utc = ((Number(utcHour) % 24) + 24) % 24;
  const dubai = (utc + 4) % 24;
  const clock = (hour: number) => `${String(hour).padStart(2, "0")}:00`;
  return `${clock(utc)} UTC is ${clock(dubai)} in Dubai.`;
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
  if (!view)
    return (
      <Notice variant="destructive" title="AI settings">
        {error}
      </Notice>
    );

  const current = view;
  const connections = view.connections;
  const chosen = (view.prompt_sources || []).find((item) => item.agent === promptKey);
  const versions = (view.prompts || []).filter((item) => item.agent === promptKey);

  async function saveSettings() {
    const next = await run(
      () =>
        pa<View>("/admin/ai", {
          method: "PUT",
          body: JSON.stringify({
            chat_enabled: current.chat_enabled,
            provider: current.provider,
            model: current.model,
            base_url: current.base_url,
            debate_enabled: current.debate_enabled,
            debate_threshold: current.debate_threshold,
            debate_max_rounds: current.debate_max_rounds,
            agent_models: current.agent_models,
            moodle_sync_paused: current.moodle_sync_paused,
            moodle_sync_minutes: current.moodle_sync_minutes,
            moodle_nightly_enabled: current.moodle_nightly_enabled,
            moodle_nightly_hour: current.moodle_nightly_hour,
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
    <div className="pa-dash grid gap-4">
      {error && (
        <Notice variant="destructive" title="Check this">
          {error}
        </Notice>
      )}
      {note && (
        <Notice variant="success" title="Saved">
          {note}
        </Notice>
      )}
      <Card id="ai-council" className="p-4">
        <p className="mt-0 max-w-3xl">
          Turn the assistant on, pick a model for each agent, and see which servers are connected.
          Secret keys stay in the server environment. This page never shows a key.
        </p>
        <div className="mt-4 grid gap-3">
          <ToggleRow
            id="chat-enabled"
            label="Chat"
            labelA="Chat is off"
            labelB="Chat is on"
            checked={view.chat_enabled}
            onCheckedChange={(checked) => setView({ ...view, chat_enabled: checked })}
          />
          <p>
            When chat is off, the professor can still use the pages. The chat bar will not call a
            model.
          </p>
          <ToggleRow
            id="debate-enabled"
            label="Council debate"
            labelA="Graders do not debate"
            labelB="Graders debate when they disagree"
            checked={view.debate_enabled}
            onCheckedChange={(checked) => setView({ ...view, debate_enabled: checked })}
          />
          <FormField
            label="How far apart the graders must be before they debate"
            htmlFor="debate-threshold"
            description="0 means any disagreement. 3 means they debate only when the bands are far apart."
          >
            <Input
              id="debate-threshold"
              type="number"
              min={0}
              max={3}
              value={String(view.debate_threshold)}
              onChange={(event) =>
                setView({ ...view, debate_threshold: Number(event.target.value) })
              }
            />
          </FormField>
          <FormField
            label="How many debate rounds"
            htmlFor="debate-rounds"
            description="The chair stops after this many rounds, from 0 to 3."
          >
            <Input
              id="debate-rounds"
              type="number"
              min={0}
              max={3}
              value={String(view.debate_max_rounds)}
              onChange={(event) =>
                setView({ ...view, debate_max_rounds: Number(event.target.value) })
              }
            />
          </FormField>
          <FormField
            label="Default model"
            htmlFor="default-model"
            description="Used when an agent below does not name its own model. The environment can also set LLM_MODEL."
          >
            <Input
              id="default-model"
              value={view.model}
              onChange={(event) => setView({ ...view, model: event.target.value })}
            />
          </FormField>
          <div>
            <Button onClick={() => void saveSettings()}>Save these choices</Button>
          </div>
        </div>
      </Card>

      <Card id="ai-agents" className="p-4">
        <h2 className="pa-card-title">Model for each agent</h2>
        <p>
          The three council graders can each use a different provider. The chair does not have its
          own row. The chair uses the default model above.
        </p>
        <div className="grid gap-4">
          {view.agents.map((agent) => {
            const choice = view.agent_models[agent] || {
              provider: view.provider,
              model: view.model,
            };
            return (
              <div key={agent} className="border-border grid gap-2 border-t pt-3">
                <strong>{agentLabel(agent)}</strong>
                <div className="grid gap-3 sm:grid-cols-2">
                  <FormField label="Provider" htmlFor={`provider-${agent}`}>
                    <Select
                      value={choice.provider}
                      onValueChange={(provider) =>
                        setView({
                          ...view,
                          agent_models: {
                            ...view.agent_models,
                            [agent]: { ...choice, provider },
                          },
                        })
                      }
                    >
                      <SelectTrigger id={`provider-${agent}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {view.providers.map((provider) => (
                          <SelectItem key={provider.id} value={provider.id}>
                            {provider.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </FormField>
                  <FormField label="Model" htmlFor={`model-${agent}`}>
                    <Input
                      id={`model-${agent}`}
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
                  </FormField>
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-3">
          <Button variant="secondary" onClick={() => void saveSettings()}>
            Save agent models
          </Button>
        </div>
      </Card>

      <Card id="ai-providers" className="p-4">
        <h2 className="pa-card-title">Provider connections</h2>
        <p>
          A key is either “not set” or “set, hidden”. Add a missing key as an environment variable
          and restart the server. This page cannot type a key in.
        </p>
        {testNote && <Notice title="Connection test">{testNote}</Notice>}
        {view.providers.map((provider) => (
          <div
            key={provider.id}
            className="border-border flex items-center justify-between gap-3 border-t py-2"
          >
            <div>
              <strong>{provider.label}</strong>
              <div className="my-1">
                <Badge
                  variant="outline"
                  className={provider.configured ? BADGE_TONE.green : BADGE_TONE.gray}
                >
                  {provider.configured ? "key set, hidden" : "no key"}
                </Badge>
              </div>
              <p className="text-muted-foreground m-0">
                Looks for {provider.env.join(" or ")}. Default model {provider.default_model}.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                const result = await run(
                  () =>
                    pa<{ ok: boolean; detail: string }>("/admin/ai/test", {
                      method: "POST",
                      body: JSON.stringify({
                        provider: provider.id,
                        model: provider.default_model,
                      }),
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
      </Card>

      <Card id="ai-prompts" className="p-4">
        <h2 className="pa-card-title">Prompts</h2>
        <p>
          Global agent prompts are versioned in Langfuse when enabled. The local copy is the
          fallback. Saving makes a new version; older versions stay in the list.
        </p>
        <h3 className="pa-card-sub">Every prompt</h3>
        <ul className="pa-prompt-list" aria-label="Prompt status">
          {(view.prompt_sources || []).map((source) => {
            const saved = (view.prompts || []).find(
              (item) => item.agent === source.agent && item.active,
            );
            return (
              <li key={source.agent}>
                <button
                  type="button"
                  onClick={() => {
                    setPromptKey(source.agent);
                    setDraft(source.text);
                  }}
                >
                  {agentLabel(source.agent)}
                </button>
                <Badge
                  variant="outline"
                  className={
                    source.source === "langfuse"
                      ? BADGE_TONE.blue
                      : saved
                        ? BADGE_TONE.green
                        : BADGE_TONE.gray
                  }
                >
                  {promptStatus(source, saved)}
                </Badge>
              </li>
            );
          })}
        </ul>
        <div className="space-y-1.5">
          <Label htmlFor="prompt-agent">Which prompt</Label>
          <Select
            value={promptKey}
            onValueChange={(key) => {
              const source = (view.prompt_sources || []).find((item) => item.agent === key);
              setPromptKey(key);
              setDraft(source?.text || "");
            }}
          >
            <SelectTrigger id="prompt-agent">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(view.prompt_sources || []).map((source) => (
                <SelectItem key={source.agent} value={source.agent}>
                  {agentLabel(source.agent)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {chosen && (
          <p>
            Using the {chosen.source} copy{chosen.version ? `, version ${chosen.version}` : ""} (
            {chosen.label}).
            {chosen.url && (
              <>
                {" "}
                <a href={chosen.url}>Open this prompt in Langfuse</a>
              </>
            )}
          </p>
        )}
        <FormField
          label="Prompt text"
          htmlFor="prompt-body"
          description="Saving makes a new version. It does not delete the previous one."
        >
          <Textarea
            id="prompt-body"
            rows={6}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        </FormField>
        <div className="mt-3">
          <Button
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
                setNote(
                  next.published_to_langfuse
                    ? `Published ${agentLabel(promptKey)} to Langfuse and saved the local fallback.`
                    : `Saved ${agentLabel(promptKey)} locally. It is the fallback when Langfuse is off.`,
                );
              }
              setSavingPrompt(false);
            }}
          >
            Save a new version
          </Button>
        </div>
        <h3 className="pa-card-sub">Versions saved here</h3>
        {versions.length === 0 && (
          <p>No saved versions yet. The text above is the built-in default.</p>
        )}
        <ul className="pl-5">
          {versions.map((row) => (
            <li key={`${row.agent}-${row.version}`}>
              Version {row.version} {row.active ? "· in use" : "· kept"}
            </li>
          ))}
        </ul>
      </Card>

      <Card id="ai-tools" className="p-4">
        <h2 className="pa-card-title">Tools and the MCP server</h2>
        <p>
          FastMCP serves the same tools the chat can call, at {connections?.mcp_path || "/mcp"}.
          {connections?.mcp_installed
            ? " The FastMCP package is installed, so that address is mounted."
            : " The FastMCP package is not installed, so that address is not mounted."}{" "}
          Turning a tool off here stops the chat from calling it. It does not delete the tool.
        </p>
        {Array.from(new Set(view.tools.map((tool) => tool.agent))).map((agent) => (
          <section key={agent} className="pa-tool-group">
            <h3 className="pa-card-sub">{agentLabel(agent)}</h3>
            {view.tools
              .filter((tool) => tool.agent === agent)
              .map((tool) => (
                <div key={`${tool.agent}.${tool.tool}`} className="pa-tool-row">
                  <div>
                    <strong>{toolName(tool.tool)}</strong>
                    <p>{toolHelp(tool.agent, tool.tool)}</p>
                  </div>
                  <Switch
                    id={`tool-${tool.agent}-${tool.tool}`}
                    aria-label={toolName(tool.tool)}
                    checked={tool.enabled}
                    onCheckedChange={async (checked) => {
                      const next = await run(
                        () =>
                          pa<View>("/admin/ai/tools", {
                            method: "POST",
                            body: JSON.stringify({
                              agent: tool.agent,
                              tool: tool.tool,
                              enabled: checked,
                            }),
                          }),
                        setError,
                      );
                      if (next) setView(next);
                    }}
                  />
                </div>
              ))}
          </section>
        ))}
      </Card>

      <Card id="ai-moodle" className="p-4">
        <h2 className="pa-card-title">Moodle connection</h2>
        <p>
          These values come from the server environment. Change them there and restart. This page
          cannot edit them.
        </p>
        <p>
          <strong>Mode.</strong>{" "}
          {connections?.moodle_mode === "fake"
            ? "Fake. Moodle is not contacted. Sync and push are recorded on this computer."
            : "Real. The server will call the university Moodle."}
        </p>
        <p>
          <strong>Grade push (MOODLE_PUSH_ENABLED).</strong>{" "}
          {connections?.moodle_push_enabled
            ? "On. An approved grade can be written to Moodle."
            : "Off. Approving a grade does not write it to Moodle."}
        </p>
        <p>
          <strong>Moodle address (MOODLE_BASE_URL).</strong> {connections?.moodle_base_url}
        </p>
        <p>
          <strong>Moodle token (MOODLE_WS_TOKEN).</strong>{" "}
          {connections?.secrets.find((item) => item.name === "MOODLE_WS_TOKEN")?.state}
        </p>
        <h3 className="pa-card-sub">Sync schedule</h3>
        <p>The regular pull is the main path. “Sync now” on the grading page is only a backup.</p>
        <ToggleRow
          id="sync-running"
          label="Regular sync"
          labelA="Paused"
          labelB="Running"
          checked={!view.moodle_sync_paused}
          onCheckedChange={(checked) => setView({ ...view, moodle_sync_paused: !checked })}
        />
        <div className="mt-3 space-y-1.5">
          <Label htmlFor="sync-minutes">How often to pull</Label>
          <Select
            value={String(view.moodle_sync_minutes)}
            onValueChange={(value) => setView({ ...view, moodle_sync_minutes: Number(value) })}
          >
            <SelectTrigger id="sync-minutes">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[15, 30, 60, 120].map((minutes) => (
                <SelectItem key={minutes} value={String(minutes)}>
                  Every {minutes} minutes
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="mt-3">
          <ToggleRow
            id="nightly"
            label="Nightly full sync"
            labelA="Off"
            labelB="On"
            checked={view.moodle_nightly_enabled}
            onCheckedChange={(checked) => setView({ ...view, moodle_nightly_enabled: checked })}
          />
        </div>
        <FormField
          label="Nightly hour"
          htmlFor="nightly-hour"
          description={dubaiLine(view.moodle_nightly_hour)}
        >
          <Input
            id="nightly-hour"
            type="number"
            min={0}
            max={23}
            value={String(view.moodle_nightly_hour)}
            onChange={(event) =>
              setView({ ...view, moodle_nightly_hour: Number(event.target.value) })
            }
          />
        </FormField>
        <div className="mt-3">
          <Button variant="secondary" onClick={() => void saveSettings()}>
            Save the sync schedule
          </Button>
        </div>
      </Card>

      <Card id="ai-tracing" className="p-4">
        <h2 className="pa-card-title">Tracing, search, and keys</h2>
        <p>
          Langfuse records each agent step after personal data has been removed. Qdrant stores the
          search index for notes and memory. Both are read from the environment.
        </p>
        <p>
          <strong>Langfuse.</strong>{" "}
          {connections?.langfuse_enabled ? "On." : "Off. Traces stay in the server log only."} Host{" "}
          {connections?.langfuse_host}.
        </p>
        <p>
          <strong>Langfuse public key.</strong>{" "}
          {connections?.secrets.find((item) => item.name === "LANGFUSE_PUBLIC_KEY")?.state}
        </p>
        <p>
          <strong>Langfuse secret key.</strong>{" "}
          {connections?.secrets.find((item) => item.name === "LANGFUSE_SECRET_KEY")?.state}
        </p>
        <p>
          <strong>Qdrant.</strong> {connections?.qdrant_host}:{connections?.qdrant_port}. API key{" "}
          {connections?.secrets.find((item) => item.name === "QDRANT_API_KEY")?.state}.
        </p>
        <p>
          <strong>Model from the environment (LLM_MODEL).</strong> {connections?.model_from_env}
        </p>
        <p>
          <strong>Model server URL (LLM_BASE_URL).</strong> {connections?.base_url}
        </p>
        <h3 className="pa-card-sub">Every secret this server looks for</h3>
        <ul className="pl-5">
          {(connections?.secrets || []).map((item) => (
            <li key={item.name}>
              <strong>{item.name}.</strong> {item.state}
            </li>
          ))}
        </ul>
        <h3 className="pa-card-sub">Recent prompt and setting changes</h3>
        {view.audit.length === 0 && <p>No edits yet.</p>}
        <ul className="pl-5">
          {view.audit.map((row, index) => (
            <li key={`${row.agent}-${row.version}-${index}`}>
              {row.action} · {agentLabel(row.agent)} · version {row.version}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
