"use client";

import { useEffect, useState, type ReactNode } from "react";
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

const ROLE_KIND_LABELS: Record<CouncilRole["kind"], string> = {
  creator: "Creator",
  deterministic: "Legacy code check",
  llm: "LLM",
  chair: "Chair",
};

/** The seeded creator can arrive as kind "llm" but it is still the creator seat. */
function kindLabel(role: CouncilRole): string {
  if (role.kind === "llm" && role.role_key === "creator") return "Creator";
  return ROLE_KIND_LABELS[role.kind] ?? role.kind;
}

function roleIcon(role: CouncilRole) {
  if (role.kind === "creator" || role.role_key === "creator") return Sparkles;
  if (role.kind === "deterministic") return ShieldCheck;
  if (role.kind === "chair") return Gavel;
  return Bot;
}

function shortModel(role: CouncilRole): string {
  if (role.kind === "deterministic") return "No model call";
  const model = (role.model ?? "").trim();
  if (!model) return "No model set";
  return model.split("/").pop() || model;
}

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
  const Icon = roleIcon(role);
  return (
    <button
      type="button"
      aria-label={role.label}
      aria-pressed={selected}
      data-testid={`flow-node-${role.role_key}`}
      data-role-key={role.role_key}
      data-kind={role.kind}
      data-enabled={role.enabled}
      title={`${role.label} · ${kindLabel(role)}${role.enabled ? "" : " · disabled"}`}
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
        {kindLabel(role)}
      </span>
    </button>
  );
}

function AddAgentNode({ onAdd }: { onAdd: () => void }) {
  return (
    <button
      type="button"
      aria-label="Add agent"
      data-testid="rail-add-agent"
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
  const [baseline, setBaseline] = useState<Record<string, Council>>({});
  const [activeKey, setActiveKey] = useState(FIRST_COUNCIL);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  function applyView(data: CouncilsView) {
    const next: Record<string, Council> = {};
    for (const council of data.councils) next[council.key] = council;
    setView(data);
    setDrafts(next);
    setBaseline(next);
  }

  useEffect(() => {
    pa<CouncilsView>("/admin/councils")
      .then((data) => {
        applyView(data);
        if (!data.councils.some((council) => council.key === FIRST_COUNCIL)) {
          const first = data.councils[0];
          if (first) setActiveKey(first.key);
        }
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not load council settings"),
      );
  }, []);

  const council = drafts[activeKey];

  // Keep the inspector pointed at a role that still exists in the active council.
  useEffect(() => {
    if (!council) {
      setSelectedKey(null);
      return;
    }
    setSelectedKey((current) =>
      current && council.roles.some((role) => role.role_key === current)
        ? current
        : (council.roles[0]?.role_key ?? null),
    );
  }, [council]);

  function setCouncil(next: Council) {
    setDrafts((current) => ({ ...current, [next.key]: next }));
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
      applyView(next);
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
      applyView(next);
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
  const original = baseline[activeKey];
  const dirty = Boolean(
    council && original && JSON.stringify(council.roles) !== JSON.stringify(original.roles),
  );
  const selectedIndex =
    council && selectedKey ? council.roles.findIndex((role) => role.role_key === selectedKey) : -1;
  const selectedRole =
    selectedIndex >= 0 && council ? (council.roles[selectedIndex] ?? null) : null;

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

      <Tabs value={activeKey} onValueChange={setActiveKey}>
        <Card className="space-y-3 p-4">
          <div className="space-y-1">
            <h1 className="text-lg font-semibold">Council settings</h1>
            <p className="text-sm font-medium">
              One builder for every AI loop: outline, material, assignment.
            </p>
            <p className="text-muted-foreground max-w-3xl text-sm">
              Every reviewer is an LLM agent with its own prompt and model. The Chair reconciles.
              Global prompts live in Langfuse; council prompts live here, per university.
            </p>
          </div>
          <TabsList className="h-auto flex-wrap justify-start">
            {view.councils.map((item) => (
              <TabsTrigger key={item.key} value={item.key}>
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Card>

        {view.councils.map((item) => {
          const draft = drafts[item.key] ?? item;
          const chairIndex = draft.roles.findIndex((role) => role.kind === "chair");
          const addIndex = chairIndex === -1 ? draft.roles.length : chairIndex;
          const rail: ReactNode[] = [];

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
                onSelect={() => setSelectedKey(role.role_key)}
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
                <div className="mt-3">
                  <h2 className="text-sm font-semibold">Loop builder</h2>
                  <p className="text-muted-foreground mt-1 max-w-3xl text-xs">
                    Nodes run left to right. Click a node or a row to edit it. Disabled nodes are
                    dashed and struck through.
                  </p>
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

              <div className="grid min-w-0 gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
                <Card className="flex min-w-0 flex-col p-0">
                  <div className="flex items-start justify-between gap-2 border-b px-3 py-2">
                    <div>
                      <h2 className="text-sm font-semibold">Agents</h2>
                      <p className="text-muted-foreground text-xs">
                        {draft.roles.length} in this loop · chair last
                      </p>
                    </div>
                    {dirty && (
                      <Badge variant="secondary" data-testid="unsaved-badge">
                        Unsaved
                      </Badge>
                    )}
                  </div>

                  <div
                    role="list"
                    aria-label={`${draft.label} agents`}
                    data-testid="agent-list"
                    className="flex-1 space-y-1 p-2"
                  >
                    {draft.roles.length === 0 ? (
                      <p className="text-muted-foreground px-2 py-3 text-sm">
                        No roles are configured. Add one if this council allows custom roles.
                      </p>
                    ) : (
                      draft.roles.map((role, index) => {
                        const selected = selectedKey === role.role_key;
                        const custom = Boolean(role.custom);
                        const Icon = roleIcon(role);
                        return (
                          <div
                            key={role.role_key}
                            role="listitem"
                            data-testid={`agent-row-${role.role_key}`}
                            className={cn(
                              "flex items-stretch gap-1 rounded-lg border transition-colors",
                              selected
                                ? "border-primary bg-primary/5"
                                : "border-border/70 hover:border-border",
                            )}
                          >
                            <button
                              type="button"
                              aria-label={`Select ${role.label}`}
                              aria-pressed={selected}
                              onClick={() => setSelectedKey(role.role_key)}
                              className="flex min-w-0 flex-1 flex-col gap-1 p-2 text-left"
                            >
                              <span className="flex min-w-0 items-center gap-1.5">
                                <Icon
                                  className="text-muted-foreground h-3.5 w-3.5 shrink-0"
                                  aria-hidden="true"
                                />
                                <span
                                  className={cn(
                                    "min-w-0 truncate text-sm font-medium",
                                    !role.enabled && "text-muted-foreground line-through",
                                  )}
                                >
                                  {role.label}
                                </span>
                                {custom && (
                                  <span className="bg-secondary text-secondary-foreground shrink-0 rounded px-1 text-[10px] font-semibold tracking-wide uppercase">
                                    custom
                                  </span>
                                )}
                                <span
                                  aria-hidden="true"
                                  className={cn(
                                    "ml-auto h-2 w-2 shrink-0 rounded-full",
                                    role.enabled ? "bg-emerald-500" : "bg-muted-foreground/40",
                                  )}
                                />
                              </span>
                              <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 pl-5 text-[11px]">
                                <span className="border-border shrink-0 rounded border px-1 py-px text-[10px] font-semibold">
                                  {kindLabel(role)}
                                </span>
                                <span className="min-w-0 truncate font-mono">{role.role_key}</span>
                                <span className="min-w-0 truncate" title={role.model ?? undefined}>
                                  {shortModel(role)}
                                </span>
                              </span>
                            </button>
                            {selected && (
                              <div className="flex shrink-0 flex-col justify-center gap-0.5 pr-1">
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label={`Move ${role.label} up`}
                                  disabled={index === 0 || role.kind === "chair"}
                                  onClick={() => moveRole(index, -1)}
                                >
                                  <ArrowUp />
                                </Button>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label={`Move ${role.label} down`}
                                  disabled={
                                    index === draft.roles.length - 1 ||
                                    role.kind === "chair" ||
                                    index === chairIndex - 1
                                  }
                                  onClick={() => moveRole(index, 1)}
                                >
                                  <ArrowDown />
                                </Button>
                              </div>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>

                  <div className="space-y-2 border-t p-2">
                    {draft.allow_custom && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="w-full border-dashed"
                        data-testid="list-add-agent"
                        onClick={addReviewer}
                      >
                        <Plus />
                        Add agent
                      </Button>
                    )}
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        className="flex-1"
                        onClick={() => void saveCouncil()}
                        disabled={busy}
                      >
                        {saving ? "Saving…" : "Save council"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void resetCouncil()}
                        disabled={busy}
                      >
                        {resetting ? "Resetting…" : "Reset to defaults"}
                      </Button>
                    </div>
                    <p
                      data-testid="save-state"
                      className={cn(
                        "text-[11px]",
                        dirty ? "text-foreground font-medium" : "text-muted-foreground",
                      )}
                    >
                      {dirty ? "Unsaved changes." : "All changes saved."}
                    </p>
                  </div>
                </Card>

                <Card data-testid="role-inspector" className="min-w-0 p-4">
                  {selectedRole ? (
                    (() => {
                      const custom = Boolean(selectedRole.custom);
                      const deterministic = selectedRole.kind === "deterministic";
                      const Icon = roleIcon(selectedRole);
                      return (
                        <div
                          data-testid={`role-card-${selectedRole.role_key}`}
                          data-selected="true"
                          className="space-y-4"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <Icon
                                  className="text-muted-foreground h-4 w-4"
                                  aria-hidden="true"
                                />
                                <h2 className="text-base font-semibold">{selectedRole.label}</h2>
                                <Badge variant="outline">{selectedRole.role_key}</Badge>
                                <Badge variant="outline">{kindLabel(selectedRole)}</Badge>
                                {custom && <Badge variant="secondary">custom</Badge>}
                              </div>
                              <p className="text-muted-foreground text-xs">
                                {selectedRole.enabled
                                  ? "Runs in this council."
                                  : "Disabled. The graph skips this role."}
                              </p>
                            </div>

                            <div className="flex flex-wrap items-center gap-1">
                              <Switch
                                aria-label={`${selectedRole.label} enabled`}
                                checked={selectedRole.enabled}
                                onCheckedChange={(enabled) =>
                                  updateRole(selectedIndex, { enabled })
                                }
                              />
                              <Button
                                type="button"
                                variant="outline"
                                size="icon-sm"
                                aria-label={`Move ${selectedRole.label} up`}
                                disabled={selectedIndex === 0 || selectedRole.kind === "chair"}
                                onClick={() => moveRole(selectedIndex, -1)}
                              >
                                <ArrowUp />
                              </Button>
                              <Button
                                type="button"
                                variant="outline"
                                size="icon-sm"
                                aria-label={`Move ${selectedRole.label} down`}
                                disabled={
                                  selectedIndex === draft.roles.length - 1 ||
                                  selectedRole.kind === "chair" ||
                                  selectedIndex === chairIndex - 1
                                }
                                onClick={() => moveRole(selectedIndex, 1)}
                              >
                                <ArrowDown />
                              </Button>
                              {custom && (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label={`Delete ${selectedRole.label}`}
                                  onClick={() => removeRole(selectedIndex)}
                                >
                                  <Trash2 />
                                </Button>
                              )}
                            </div>
                          </div>

                          {deterministic ? (
                            <div
                              data-testid="legacy-code-check"
                              className="bg-muted/40 rounded-md border border-dashed p-3"
                            >
                              <p className="flex items-center gap-1.5 text-sm font-medium">
                                <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                                Legacy code check
                              </p>
                              <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
                                This saved role predates LLM-only councils; reset to defaults to
                                replace it.
                              </p>
                            </div>
                          ) : (
                            <div className="grid gap-3">
                              <FormField
                                label="Model"
                                htmlFor={`model-${draft.key}-${selectedRole.role_key}`}
                                description="For example gemini/gemini-3.5-flash-lite."
                              >
                                <Input
                                  aria-label={`Model for ${selectedRole.label}`}
                                  value={selectedRole.model ?? ""}
                                  placeholder="gemini/gemini-3.5-flash-lite"
                                  onChange={(event) =>
                                    updateRole(selectedIndex, { model: event.target.value })
                                  }
                                />
                              </FormField>
                              <FormField
                                label="Persona prompt"
                                htmlFor={`persona-${draft.key}-${selectedRole.role_key}`}
                                description={
                                  custom
                                    ? "Required. This reviewer's voice for this university."
                                    : "Prompt versions can still override this where configured."
                                }
                                required={custom}
                              >
                                <Textarea
                                  rows={6}
                                  aria-label={`Persona prompt for ${selectedRole.label}`}
                                  value={selectedRole.persona_prompt ?? ""}
                                  onChange={(event) =>
                                    updateRole(selectedIndex, {
                                      persona_prompt: event.target.value,
                                    })
                                  }
                                />
                              </FormField>
                            </div>
                          )}
                        </div>
                      );
                    })()
                  ) : (
                    <p className="text-muted-foreground text-sm">
                      Select an agent to edit its model and prompt.
                    </p>
                  )}
                </Card>
              </div>
            </TabsContent>
          );
        })}
      </Tabs>
    </div>
  );
}
