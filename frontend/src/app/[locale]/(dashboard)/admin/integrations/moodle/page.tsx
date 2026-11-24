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
} from "@/components/ui";

interface Capabilities {
  functions?: string[];
  downloadfiles?: boolean;
  uploadfiles?: boolean;
  enablecompletion?: boolean;
}

interface CourseScope {
  mode: "all" | "idnumbers" | "shortnames";
  idnumbers: string[];
  shortnames: string[];
}

interface ConnectionView {
  configured: boolean;
  label: string;
  base_url: string;
  token_state: "saved" | "none";
  token_hint: string;
  status: "unverified" | "ok" | "error" | "disabled";
  last_checked_at: string;
  last_check_error: string;
  site_url: string;
  site_name: string;
  release: string;
  version: string;
  siteid: string;
  capabilities: Capabilities;
  course_scope: CourseScope;
  push_enabled: boolean;
  token_rotated_at: string;
  mode: string;
  activity_logs: { available: boolean; reason: string };
  env_fallback?: { available: boolean; base_url: string; token_configured: boolean };
}

interface ChecklistItem {
  key: string;
  label: string;
  ok: boolean;
}

interface TestResult {
  ok: boolean;
  mode: string;
  error: string;
  site_url: string;
  site_name: string;
  release: string;
  version: string;
  siteid: string;
  capabilities: Capabilities;
  checklist: ChecklistItem[];
  warnings: Array<{ item: string; warningcode: string; message: string }>;
}

interface SyncCounts {
  courses?: number;
  students?: number;
  submissions?: number;
}

interface MoodleStatus {
  mode: string;
  last_status: string;
  last_error: string;
  /** Rows the last run imported or updated. An idempotent re-sync shows zeros. */
  counts: SyncCounts;
  /** Rows stored for this workspace now, whatever the last run did. */
  totals?: SyncCounts;
  last_sync: string;
  connection: {
    configured: boolean;
    status: string;
    push_enabled: boolean;
    last_check_error: string;
  };
}

interface AuditRun {
  id: string;
  trigger: string;
  mode: string;
  status: string;
  counts: Record<string, number>;
  error: string;
  created_at: string;
}

interface AuditPush {
  id: string;
  target_type: string;
  target_id: string;
  accepted: boolean;
  created_at: string;
}

interface Audit {
  runs: AuditRun[];
  pushes: AuditPush[];
}

const STATUS_TONE: Record<string, string> = {
  ok: "border-transparent bg-emerald-100 text-emerald-800 hover:bg-emerald-100",
  error: "border-transparent bg-red-100 text-red-800 hover:bg-red-100",
  unverified: "border-transparent bg-amber-100 text-amber-800 hover:bg-amber-100",
  disabled: "border-transparent bg-slate-100 text-slate-800 hover:bg-slate-100",
};

function statusLabel(status: string) {
  if (status === "ok") return "Verified";
  if (status === "error") return "Check failed";
  if (status === "disabled") return "Disabled";
  return "Not checked yet";
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

function when(value: string) {
  if (!value) return "never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function countLabel(value: number | undefined, noun: string) {
  const count = value ?? 0;
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export default function MoodleIntegrationPage() {
  const [view, setView] = useState<ConnectionView | null>(null);
  const [status, setStatus] = useState<MoodleStatus | null>(null);
  const [audit, setAudit] = useState<Audit>({ runs: [], pushes: [] });
  const [test, setTest] = useState<TestResult | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const [label, setLabel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [token, setToken] = useState("");
  const [scopeMode, setScopeMode] = useState<CourseScope["mode"]>("all");
  const [idnumbers, setIdnumbers] = useState("");
  const [pushEnabled, setPushEnabled] = useState(false);

  async function load() {
    const [connection, current, log] = await Promise.all([
      pa<ConnectionView>("/moodle/connection"),
      pa<MoodleStatus>("/moodle/status").catch(() => null),
      pa<Audit>("/moodle/audit").catch(() => ({ runs: [], pushes: [] })),
    ]);
    setView(connection);
    setStatus(current);
    setAudit(log);
    setLabel(connection.label);
    setBaseUrl(connection.base_url);
    setToken("");
    setScopeMode(connection.course_scope.mode || "all");
    setIdnumbers((connection.course_scope.idnumbers || []).join(", "));
    setPushEnabled(connection.push_enabled);
  }

  useEffect(() => {
    load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, []);

  if (!view && !error) return <p>Loading Moodle connection?</p>;
  if (!view)
    return (
      <Notice variant="destructive" title="Moodle connection">
        {error}
      </Notice>
    );

  async function save() {
    setSaving(true);
    setNote("");
    const saved = await run(
      () =>
        pa<ConnectionView>("/moodle/connection", {
          method: "PUT",
          body: JSON.stringify({
            label,
            base_url: baseUrl,
            ws_token: token,
            course_scope: {
              mode: scopeMode,
              idnumbers: idnumbers
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
              shortnames: [],
            },
            push_enabled: pushEnabled,
          }),
        }),
      setError,
    );
    if (saved) {
      setView(saved);
      setToken("");
      setNote("Saved. The token is stored encrypted and is never shown again.");
      await load().catch(() => undefined);
    }
    setSaving(false);
  }

  async function runTest() {
    setTest(null);
    setNote("");
    const result = await run(
      () => pa<TestResult>("/moodle/connection/test", { method: "POST" }),
      setError,
    );
    if (result) {
      setTest(result);
      await load().catch(() => undefined);
    }
  }

  async function syncNow() {
    setSyncing(true);
    setNote("");
    const result = await run(() => pa<MoodleStatus>("/moodle/sync", { method: "POST" }), setError);
    if (result) {
      setStatus(result);
      setNote("Sync finished. Counts are in the run history below.");
      await load().catch(() => undefined);
    }
    setSyncing(false);
  }

  async function disable() {
    const result = await run(
      () => pa<ConnectionView>("/moodle/connection", { method: "DELETE" }),
      setError,
    );
    if (result) {
      setView(result);
      setToken("");
      setNote("Connection disabled and the stored token was erased.");
      await load().catch(() => undefined);
    }
  }

  const capabilities = view.capabilities || {};
  const checklist: ChecklistItem[] = [
    { key: "connection", label: "Moodle answers", ok: view.status === "ok" },
    {
      key: "functions",
      label: "Web-service functions advertised",
      ok: Boolean(capabilities.functions?.length),
    },
    {
      key: "downloadfiles",
      label: "Can download submission files",
      ok: Boolean(capabilities.downloadfiles),
    },
    { key: "uploadfiles", label: "Can upload files", ok: Boolean(capabilities.uploadfiles) },
    {
      key: "enablecompletion",
      label: "Completion tracking is on",
      ok: Boolean(capabilities.enablecompletion),
    },
  ];

  return (
    <div className="grid max-w-5xl gap-4">
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
      {view.mode === "fake" && (
        <Notice title="Fake Moodle is active">
          MOODLE_MODE=fake. Sync and push are recorded locally and no university is contacted. Turn
          fake mode off before a real test.
        </Notice>
      )}
      {!view.configured && (
        <Notice title="No connection yet">
          This workspace has no Moodle connection. Add the site address and a web-service token
          below, then test it. Until then scheduled sync is skipped.
        </Notice>
      )}
      {!view.configured && view.env_fallback?.available && (
        <Notice title="Environment demo connection">
          {`MOODLE_BASE_URL and MOODLE_WS_TOKEN are set for this process (${view.env_fallback.base_url}). Scheduled sync uses them until a saved connection replaces them. The token is never shown here.`}
        </Notice>
      )}

      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="pa-card-title">Moodle connection</h2>
            <p className="text-muted-foreground m-0">
              One Moodle site per university. The token is encrypted with the server key and never
              returned by this page.
            </p>
          </div>
          <Badge variant="outline" className={STATUS_TONE[view.status] || STATUS_TONE.unverified}>
            {statusLabel(view.status)}
          </Badge>
        </div>

        <div className="mt-4 grid gap-3">
          <FormField label="Label" htmlFor="moodle-label" description="Shown on this page only.">
            <Input
              id="moodle-label"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </FormField>
          <FormField
            label="Moodle base URL"
            htmlFor="moodle-base-url"
            description="https:// only. Localhost needs MOODLE_ALLOW_PRIVATE=true in development."
          >
            <Input
              id="moodle-base-url"
              placeholder="https://moodle.university.edu"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
            />
          </FormField>
          <FormField
            label="Web-service token"
            htmlFor="moodle-token"
            description={
              view.token_state === "saved"
                ? `A token is saved (${view.token_hint}). Leave this empty to keep it; type a new one to replace it.`
                : "Paste the token from Moodle. It is stored encrypted."
            }
          >
            <Input
              id="moodle-token"
              type="password"
              autoComplete="new-password"
              placeholder={view.token_state === "saved" ? "Saved - leave blank to keep" : "wstoken"}
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
          </FormField>
          <FormField
            label="Course scope"
            htmlFor="moodle-scope"
            description="All visible courses, or only the idnumbers you list."
          >
            <Select
              value={scopeMode}
              onValueChange={(value) => setScopeMode(value as CourseScope["mode"])}
            >
              <SelectTrigger id="moodle-scope">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All visible courses</SelectItem>
                <SelectItem value="idnumbers">Only these course idnumbers</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          {scopeMode === "idnumbers" && (
            <FormField
              label="Course idnumbers"
              htmlFor="moodle-idnumbers"
              description="Comma separated."
            >
              <Input
                id="moodle-idnumbers"
                placeholder="MAAI903, MAAI904"
                value={idnumbers}
                onChange={(event) => setIdnumbers(event.target.value)}
              />
            </FormField>
          )}
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-0.5">
              <Label htmlFor="moodle-push">Push approved grades</Label>
              <p className="text-muted-foreground text-xs">
                {pushEnabled
                  ? "An approved grade may be written to Moodle."
                  : "Approving a grade never writes to Moodle."}
              </p>
            </div>
            <Switch id="moodle-push" checked={pushEnabled} onCheckedChange={setPushEnabled} />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button disabled={saving} onClick={() => void save()}>
              {saving ? "Saving..." : "Save connection"}
            </Button>
            <Button variant="outline" disabled={!view.configured} onClick={() => void runTest()}>
              Test connection
            </Button>
            <Button
              variant="outline"
              disabled={!view.configured || syncing}
              onClick={() => void syncNow()}
            >
              {syncing ? "Syncing..." : "Sync now"}
            </Button>
            <Button variant="ghost" disabled={!view.configured} onClick={() => void disable()}>
              Disable and erase token
            </Button>
          </div>
          {view.last_checked_at && (
            <p className="text-muted-foreground m-0 text-xs">
              Last checked {when(view.last_checked_at)} - release {view.release || "unknown"} -
              siteid {view.siteid || "unknown"}
            </p>
          )}
          {view.last_check_error && (
            <Notice variant="destructive" title="Last check failed">
              {view.last_check_error}
            </Notice>
          )}
        </div>
      </Card>

      {(test || view.configured) && (
        <Card className="p-4">
          <h2 className="pa-card-title">Capability checklist</h2>
          <p className="text-muted-foreground">
            {test
              ? test.ok
                ? `Moodle answered: ${test.site_name || test.site_url}`
                : test.error
              : view.configured
                ? "Run Test connection to refresh these values from the site."
                : "No connection to check yet."}
          </p>
          <ul className="mt-3 grid gap-2">
            {(test?.checklist || checklist).map((item) => (
              <li key={item.key} className="flex items-center justify-between gap-3 text-sm">
                <span>{item.label}</span>
                <Badge
                  variant="outline"
                  className={item.ok ? STATUS_TONE.ok : STATUS_TONE.disabled}
                >
                  {item.ok ? "ok" : "not available"}
                </Badge>
              </li>
            ))}
          </ul>
          {test && test.warnings.length > 0 && (
            <Notice title="Moodle returned warnings">
              <ul className="m-0 pl-5">
                {test.warnings.map((warning, index) => (
                  <li key={`${warning.warningcode}-${index}`}>
                    {warning.item || "Moodle"}: {warning.message}
                  </li>
                ))}
              </ul>
            </Notice>
          )}
          {test?.capabilities.functions?.length ? (
            <details className="mt-3 text-sm">
              <summary>
                {test.capabilities.functions.length} web-service functions available
              </summary>
              <ul className="mt-2 grid gap-1 pl-5">
                {test.capabilities.functions.map((name) => (
                  <li key={name}>
                    <code>{name}</code>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </Card>
      )}

      <Card className="p-4">
        <h2 className="pa-card-title">Schedule and last run</h2>
        <p className="text-muted-foreground">
          The background pull is the main path. Sync now is a manual backup.
        </p>
        {status && (
          <ul className="m-0 grid gap-1 pl-5 text-sm">
            <li>Mode: {status.mode}</li>
            <li>
              Last run: {when(status.last_sync)} - {countLabel(status.counts.courses, "course")} -{" "}
              {countLabel(status.counts.students, "student")} -{" "}
              {countLabel(status.counts.submissions, "submission")}
            </li>
            <li>Last status: {status.last_status || "none yet"}</li>
            <li>
              Currently synced: {countLabel(status.totals?.courses, "course")} -{" "}
              {countLabel(status.totals?.students, "student")} -{" "}
              {countLabel(status.totals?.submissions, "submission")}
            </li>
          </ul>
        )}
        {status?.last_error && (
          <Notice variant="destructive" title="Last sync error">
            {status.last_error}
          </Notice>
        )}
      </Card>

      <Card className="p-4">
        <h2 className="pa-card-title">Last 10 syncs and pushes</h2>
        {audit.runs.length === 0 && audit.pushes.length === 0 && (
          <p className="text-muted-foreground">No runs recorded yet.</p>
        )}
        {audit.runs.length > 0 && (
          <>
            <h3 className="pa-card-sub">Sync runs</h3>
            <ul className="m-0 grid gap-2 pl-0">
              {audit.runs.map((row) => (
                <li
                  key={row.id}
                  className="flex flex-wrap items-center justify-between gap-2 text-sm"
                >
                  <span>
                    {when(row.created_at)} - {row.trigger} - {row.mode}
                  </span>
                  <span className="flex items-center gap-2">
                    {row.error && <span className="text-muted-foreground">{row.error}</span>}
                    <Badge
                      variant="outline"
                      className={row.status === "ok" ? STATUS_TONE.ok : STATUS_TONE.error}
                    >
                      {row.status}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
        {audit.pushes.length > 0 && (
          <>
            <h3 className="pa-card-sub">Pushes</h3>
            <ul className="m-0 grid gap-2 pl-0">
              {audit.pushes.map((row) => (
                <li
                  key={row.id}
                  className="flex flex-wrap items-center justify-between gap-2 text-sm"
                >
                  <span>
                    {when(row.created_at)} - {row.target_type} {row.target_id}
                  </span>
                  <Badge
                    variant="outline"
                    className={row.accepted ? STATUS_TONE.ok : STATUS_TONE.error}
                  >
                    {row.accepted ? "accepted" : "refused"}
                  </Badge>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>

      <Notice
        title={
          view.activity_logs.available
            ? "Activity logs are available"
            : "Activity logs are not available"
        }
      >
        {view.activity_logs.reason}
        {view.activity_logs.available
          ? " Dropout risk stays advisory; nothing changes a student's enrolment or marks."
          : " The activity table stays empty and dropout risk remains unscored until activity rows exist."}
      </Notice>
    </div>
  );
}
