"use client";

import { Fragment, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

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

function orderedRoles(roles: CouncilRole[]): CouncilRole[] {
  return roles.map((role, index) => ({ ...role, position: index }));
}
export default function CouncilsAdminPage() {
  const [view, setView] = useState<CouncilsView | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Council>>({});
  const [activeKey, setActiveKey] = useState(FIRST_COUNCIL);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

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

  function addReviewer() {
    if (!council) return;
    let suffix = 1;
    while (council.roles.some((role) => role.role_key === `reviewer_${suffix}`)) suffix += 1;
    setRoles([
      ...council.roles,
      {
        role_key: `reviewer_${suffix}`,
        label: `Reviewer ${suffix}`,
        kind: "llm",
        persona_prompt: "",
        agent_key: "reviewer",
        model: "",
        position: council.roles.length,
        enabled: true,
        custom: true,
        config: {},
      },
    ]);
  }

  function removeRole(index: number) {
    if (!council) return;
    setRoles(council.roles.filter((_, current) => current !== index));
  }

  async function saveCouncil() {
    if (!council) return;
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
        <p className="text-muted-foreground mt-1 max-w-3xl text-sm">
          Choose which roles run, in what order, and which model and persona each role uses.
        </p>
        <p className="mt-2 max-w-3xl text-sm">
          This changes the actual graph. Langfuse still traces; prompt versions can still override
          where configured.
        </p>
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
          return (
            <TabsContent key={item.key} value={item.key} className="space-y-4">
              <Card className="p-4">
                <p className="text-muted-foreground max-w-3xl text-sm">{draft.description}</p>
                <h2 className="mt-4 text-sm font-semibold">Flow preview</h2>
                {draft.roles.length === 0 ? (
                  <p className="text-muted-foreground mt-2 text-sm">
                    No roles in this council yet.
                  </p>
                ) : (
                  <div
                    className="mt-2 flex flex-wrap items-center gap-1.5"
                    aria-label={`${draft.label} flow preview`}
                  >
                    {draft.roles.map((role, index) => (
                      <Fragment key={`${role.role_key}-${index}`}>
                        {index > 0 && (
                          <span aria-hidden="true" className="text-muted-foreground">
                            →
                          </span>
                        )}
                        <Badge
                          variant="outline"
                          className={cn(
                            role.enabled ? "" : "text-muted-foreground line-through opacity-60",
                          )}
                        >
                          {role.label}
                        </Badge>
                      </Fragment>
                    ))}
                  </div>
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
                  const usesModel = role.kind === "llm" || role.kind === "chair";
                  const usesPrompt = usesModel || custom;
                  return (
                    <Card key={`${role.role_key}-${index}`} className="p-4">
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
                            disabled={index === 0}
                            onClick={() => moveRole(index, -1)}
                          >
                            <ArrowUp />
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="icon-sm"
                            aria-label={`Move ${role.label} down`}
                            disabled={index === draft.roles.length - 1}
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
                        {usesModel && (
                          <FormField
                            label="Model"
                            htmlFor={`model-${draft.key}-${index}`}
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
                            Deterministic check {"\u2014"} prompt not used
                          </p>
                        ) : usesPrompt ? (
                          <FormField
                            label="Persona prompt"
                            htmlFor={`persona-${draft.key}-${index}`}
                            description="Prompt versions can still override this where configured."
                          >
                            <Textarea
                              rows={4}
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
                {draft.allow_custom && (draft.key === "material" || draft.key === "assignment") && (
                  <Button type="button" variant="outline" onClick={addReviewer} disabled={busy}>
                    <Plus />
                    Add reviewer
                  </Button>
                )}
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
