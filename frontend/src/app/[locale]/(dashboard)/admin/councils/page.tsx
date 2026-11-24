"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Bot,
  Gavel,
  Plus,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";

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
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import type { Council, CouncilRole, CouncilsView } from "@/lib/profassist";
import { cn } from "@/lib/utils";

const FIRST_COUNCIL = "material";

const ROLE_ICONS: Record<CouncilRole["kind"], typeof Sparkles> = {
  creator: Sparkles,
  deterministic: ShieldCheck,
  llm: Bot,
  chair: Gavel,
};

const ROLE_KIND_LABELS: Record<CouncilRole["kind"], string> = {
  creator: "Creator",
  deterministic: "Deterministic",
  llm: "LLM",
  chair: "Chair",
};

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

/** Node order is speaking order, and the chair always speaks last. */
function orderedRoles(roles: CouncilRole[]): CouncilRole[] {
  const speaking = roles.filter((role) => role.kind !== "chair");
  const chairs = roles.filter((role) => role.kind === "chair");
  return [...speaking, ...chairs].map((role, index) => ({ ...role, position: index }));
}

function Connector() {
  return (
    <span aria-hidden="true" className="text-muted-foreground/60 flex shrink-0 items-center">
      <span className="bg-border h-px w-4" />
      <ArrowRight className="h-3.5 w-3.5" />
    </span>
  );
}

function FlowNode({
  role,
  selected,
  onSelect,
}: {
  role: CouncilRole;
  selected: boolean;
  onSelect: () => void;
}) {
  const Icon = ROLE_ICONS[role.kind] ?? Bot;
  return (
    <button
      type="button"
      aria-label={role.label}
      aria-pressed={selected}
      data-testid={`flow-node-${role.role_key}`}
      data-role-key={role.role_key}
      data-kind={role.kind}
      data-enabled={role.enabled}
      title={`${role.label} · ${ROLE_KIND_LABELS[role.kind] ?? role.kind}${
        role.enabled ? "" : " · disabled"
      }`}
      onClick={onSelect}
      className={cn(
        "flex min-w-[112px] shrink-0 flex-col items-center justify-center gap-1 rounded-xl border px-4 py-3 text-xs font-medium transition-colors",
        role.enabled
          ? "bg-card border-border hover:border-primary shadow-sm"
          : "border-muted-foreground/40 text-muted-foreground border-dashed line-through opacity-60",
        selected && "ring-primary ring-2 ring-offset-2",
      )}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      <span>{role.label}</span>
      <span className="text-[10px] font-normal tracking-wide uppercase opacity-70">
        {ROLE_KIND_LABELS[role.kind] ?? role.kind}
      </span>
    </button>
  );
}

function AddAgentNode({ onAdd }: { onAdd: () => void }) {
  return (
    <button
      type="button"
      aria-label="Add agent"
      onClick={onAdd}
      className="border-muted-foreground/50 text-muted-foreground hover:border-primary hover:text-primary flex min-w-[112px] shrink-0 flex-col items-center justify-center gap-1 rounded-xl border border-dashed px-4 py-3 text-xs font-medium transition-colors"
    >
      <Plus className="h-4 w-4" aria-hidden="true" />
      <span>Add agent</span>
      <span className="text-[10px] font-normal tracking-wide uppercase opacity-70">LLM</span>
    </button>
  );
}

export default function CouncilsAdminPage() {
  const [view, setView] = useState<CouncilsView | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Council>>({});
  const [activeKey, setActiveKey] = useState(FIRST_COUNCIL);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    pa<CouncilsView>("/admin/councils")
      .then((data) => {
        setView(data);
        const next: Record<string, Council> = {};
        for (const council of data.councils) next[council.key] = council;
        setDrafts(next);
        if (!data.councils.some((council) => council.key === FIRST_COUNCIL)) {
          const first = data.councils[0];
          if (first) setActiveKey(first.key);
        }
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not load council settings"),
      );
  }, []);

  useEffect(() => {
    if (!selectedKey) return;
    const card = cardRefs.current[selectedKey];
    if (card && typeof card.scrollIntoView === "function") {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [selectedKey]);

  function replaceView(data: CouncilsView) {
    setView(data);
    const next: Record<string, Council> = {};
    for (const council of data.councils) next[council.key] = council;
    setDrafts(next);
  }

  const council = drafts[activeKey];

  function setCouncil(next: Council) {
    setDrafts((current) => ({ ...current, [next.key]: next }));
    setView((current) =>
      current
        ? {
            ...current,
            councils: current.councils.map((item) => (item.key === next.key ? next : item)),
          }
        : current,
    );
  }

  function setRoles(roles: CouncilRole[]) {
    if (!council) return;
    setCouncil({ ...council, roles: orderedRoles(roles) });
  }

  function updateRole(index: number, patch: Partial<CouncilRole>) {
    if (!council) return;
    setRoles(
      council.roles.map((role, current) => (current === index ? { ...role, ...patch } : role)),
    );
  }

  function moveRole(index: number, direction: -1 | 1) {
    if (!council) return;
    const target = index + direction;
    if (target < 0 || target >= council.roles.length) return;
    const roles = [...council.roles];
    const moving = roles[index];
    const displaced = roles[target];
    if (!moving || !displaced) return;
    roles[index] = displaced;
    roles[target] = moving;
    setRoles(roles);
  }

  function selectRole(roleKey: string) {
    // The selection effect scrolls when the selection changes. Clicking the already
    // selected node still brings its editor back into view.
    if (roleKey === selectedKey) {
      const card = cardRefs.current[roleKey];
      if (card && typeof card.scrollIntoView === "function") {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      return;
    }
    setSelectedKey(roleKey);
  }

  function addReviewer() {
    if (!council) return;
    let suffix = 1;
    while (council.roles.some((role) => role.role_key === `reviewer_${suffix}`)) suffix += 1;
    const roleKey = `reviewer_${suffix}`;
    const reviewer: CouncilRole = {
      role_key: roleKey,
      label: `Reviewer ${suffix}`,
      kind: "llm",
      persona_prompt: "",
      agent_key: "reviewer",
      model: "",
      position: council.roles.length,
      enabled: true,
      custom: true,
      config: {},
    };
    const chairIndex = council.roles.findIndex((role) => role.kind === "chair");
    const insertAt = chairIndex === -1 ? council.roles.length : chairIndex;
    setRoles([...council.roles.slice(0, insertAt), reviewer, ...council.roles.slice(insertAt)]);
    setSelectedKey(roleKey);
  }

  function removeRole(index: number) {
    if (!council) return;
    setRoles(council.roles.filter((_, current) => current !== index));
  }

  async function saveCouncil() {
    if (!council) return;
    const missingPrompt = council.roles.find(
      (role) => role.custom && !(role.persona_prompt ?? "").trim(),
    );
    if (missingPrompt) {
      setError(`${missingPrompt.label} needs a persona prompt before you can save.`);
      setNote("");
      return;
    }
    setSaving(true);
    setNote("");
    const next = await run(
      () =>
        pa<CouncilsView>(`/admin/councils/${council.key}`, {
          method: "PUT",
          body: JSON.stringify({ roles: orderedRoles(council.roles) }),
        }),
      setError,
    );
    if (next) {
      replaceView(next);
      setNote(`${council.label} saved.`);
    }
    setSaving(false);
  }

  async function resetCouncil() {
    if (!council) return;
    setResetting(true);
    setNote("");
    const next = await run(
      () => pa<CouncilsView>(`/admin/councils/${council.key}/reset`, { method: "POST" }),
      setError,
    );
    if (next) {
      replaceView(next);
      setSelectedKey(null);
      setNote(`${council.label} restored to defaults.`);
    }
    setResetting(false);
  }

  if (!view && !error) return <p className="text-sm">Loading council settings…</p>;
  if (!view)
    return (
      <Notice variant="destructive" title="Council settings">
        {error}
      </Notice>
    );

  const busy = saving || resetting;
  return (
    <div className="space-y-4">
      {error && (
        <Notice variant="destructive" title="Council settings">
          {error}
        </Notice>
      )}
      {note && (
        <Notice variant="success" title="Saved">
          {note}
        </Notice>
      )}

      <Card className="p-4">
        <h1 className="text-lg font-semibold">Council settings</h1>
        <p className="mt-1 max-w-3xl text-sm font-medium">
          One builder for every AI loop: outline, material, assignment.
        </p>
        <div className="text-muted-foreground mt-2 max-w-3xl space-y-1 text-sm">
          <p>
            Global agent prompts live in Langfuse. Council agent prompts live here, per university.
          </p>
          <p>
            <strong className="text-foreground">Add agent</strong> creates a custom LLM reviewer
            that runs in that loop, just before the chair.
          </p>
        </div>
      </Card>

      <Tabs value={activeKey} onValueChange={setActiveKey}>
        <TabsList className="h-auto flex-wrap justify-start">
          {view.councils.map((item) => (
            <TabsTrigger key={item.key} value={item.key}>
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {view.councils.map((item) => {
          const draft = drafts[item.key] ?? item;
          const chairIndex = draft.roles.findIndex((role) => role.kind === "chair");
          const addIndex = chairIndex === -1 ? draft.roles.length : chairIndex;
          const rail: React.ReactNode[] = [];

          draft.roles.forEach((role, index) => {
            if (draft.allow_custom && index === addIndex) {
              if (rail.length > 0) rail.push(<Connector key={`connector-add-${index}`} />);
              rail.push(<AddAgentNode key="add-agent" onAdd={addReviewer} />);
            }
            if (rail.length > 0) rail.push(<Connector key={`connector-${role.role_key}`} />);
            rail.push(
              <FlowNode
                key={role.role_key}
                role={role}
                selected={selectedKey === role.role_key}
                onSelect={() => selectRole(role.role_key)}
              />,
            );
          });
          if (draft.allow_custom && addIndex === draft.roles.length) {
            if (rail.length > 0) rail.push(<Connector key="connector-add-end" />);
            rail.push(<AddAgentNode key="add-agent" onAdd={addReviewer} />);
          }

          return (
            <TabsContent key={item.key} value={item.key} className="space-y-4">
              <Card className="p-4">
                <p className="text-muted-foreground max-w-3xl text-sm">{draft.description}</p>
                <div className="mt-4 flex flex-wrap items-end justify-between gap-2">
                  <div>
                    <h2 className="text-sm font-semibold">Loop builder</h2>
                    <p className="text-muted-foreground mt-1 max-w-3xl text-xs">
                      Nodes run left to right. Click a node to edit its card. Disabled nodes are
                      dashed and struck through.
                    </p>
                  </div>
                </div>
                {draft.roles.length === 0 && !draft.allow_custom ? (
                  <p className="text-muted-foreground mt-3 text-sm">
                    No roles in this council yet.
                  </p>
                ) : (
                  <div
                    role="group"
                    aria-label={`${draft.label} flow`}
                    className="mt-3 flex items-stretch gap-1 overflow-x-auto pb-2"
                  >
                    {rail}
                  </div>
                )}
                {draft.allow_custom && (
                  <p className="text-muted-foreground mt-2 text-xs">
                    Add agent inserts a custom LLM reviewer before the chair for this university.
                  </p>
                )}
              </Card>

              {draft.roles.length === 0 ? (
                <Card className="p-4">
                  <p className="text-sm">
                    No roles are configured. Add one if this council allows custom roles.
                  </p>
                </Card>
              ) : (
                draft.roles.map((role, index) => {
                  const custom = Boolean(role.custom);
                  const isChair = role.kind === "chair";
                  const showsModel = role.kind !== "deterministic";
                  const showsPrompt = role.kind !== "deterministic";
                  const beforeChair = index === chairIndex - 1;
                  const selected = selectedKey === role.role_key;
                  return (
                    <Card
                      key={role.role_key}
                      ref={(node) => {
                        cardRefs.current[role.role_key] = node;
                      }}
                      data-testid={`role-card-${role.role_key}`}
                      data-selected={selected}
                      className={cn("p-4", selected && "ring-primary ring-2")}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-sm font-semibold">{role.label}</h3>
                            <Badge variant="outline">{role.role_key}</Badge>
                            <Badge variant="outline">{role.kind}</Badge>
                            {custom && <Badge variant="secondary">custom</Badge>}
                          </div>
                          <p className="text-muted-foreground text-xs">
                            {role.enabled
                              ? "Runs in this council."
                              : "Disabled. The graph skips this role."}
                          </p>
                        </div>

                        <div className="flex flex-wrap items-center gap-1">
                          <Button
                            type="button"
                            variant="outline"
                            size="icon-sm"
                            aria-label={`Move ${role.label} up`}
                            disabled={index === 0 || isChair}
                            onClick={() => moveRole(index, -1)}
                          >
                            <ArrowUp />
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="icon-sm"
                            aria-label={`Move ${role.label} down`}
                            disabled={index === draft.roles.length - 1 || isChair || beforeChair}
                            onClick={() => moveRole(index, 1)}
                          >
                            <ArrowDown />
                          </Button>
                          <Switch
                            aria-label={`${role.label} enabled`}
                            checked={role.enabled}
                            onCheckedChange={(enabled) => updateRole(index, { enabled })}
                          />
                          {custom && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              aria-label={`Delete ${role.label}`}
                              onClick={() => removeRole(index)}
                            >
                              <Trash2 />
                            </Button>
                          )}
                        </div>
                      </div>
                      <div className="mt-3 grid gap-3">
                        {showsModel && (
                          <FormField
                            label="Model"
                            htmlFor={`model-${draft.key}-${role.role_key}`}
                            description="For example gemini/gemini-3.5-flash-lite."
                          >
                            <Input
                              aria-label={`Model for ${role.label}`}
                              value={role.model ?? ""}
                              placeholder="gemini/gemini-3.5-flash-lite"
                              onChange={(event) => updateRole(index, { model: event.target.value })}
                            />
                          </FormField>
                        )}
                        {role.kind === "deterministic" ? (
                          <p className="text-muted-foreground rounded-md border border-dashed px-3 py-2 text-xs">
                            Deterministic check - prompt not used.
                          </p>
                        ) : showsPrompt ? (
                          <FormField
                            label="Persona prompt"
                            htmlFor={`persona-${draft.key}-${role.role_key}`}
                            description={
                              custom
                                ? "Required. This reviewer's voice for this university."
                                : "Prompt versions can still override this where configured."
                            }
                            required={custom}
                          >
                            <Textarea
                              rows={4}
                              aria-label={`Persona prompt for ${role.label}`}
                              value={role.persona_prompt ?? ""}
                              onChange={(event) =>
                                updateRole(index, { persona_prompt: event.target.value })
                              }
                            />
                          </FormField>
                        ) : null}
                      </div>
                    </Card>
                  );
                })
              )}

              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" onClick={() => void saveCouncil()} disabled={busy}>
                  {saving ? "Saving…" : "Save council"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void resetCouncil()}
                  disabled={busy}
                >
                  {resetting ? "Resetting…" : "Reset to defaults"}
                </Button>
              </div>
            </TabsContent>
          );
        })}
      </Tabs>
    </div>
  );
}
