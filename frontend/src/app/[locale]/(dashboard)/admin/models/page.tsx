"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Banner, pa, run } from "@/components/profassist/bits";
import { Badge, Button, Card } from "@/components/ui";

interface ModelCard {
  name: string;
  kind: string;
  status: string;
  version: string | null;
  source: string;
  license: string;
  data_needed: string;
  synthetic?: boolean;
  threshold?: number;
  bands?: string[];
  threshold_note?: string;
  note: string;
  features?: string[];
}

interface ModelsView {
  models: ModelCard[];
  mlflow: { reachable: boolean; tracking_uri?: string | null };
  settings: {
    worker_url_set: boolean;
    worker_token_set: boolean;
    worker_host?: string | null;
    env_only: boolean;
  };
}

interface ProbeView {
  configured: boolean;
  reachable: boolean | null;
  status: string;
  probe: boolean;
  token_set: boolean;
  worker_url_set: boolean;
  worker_host?: string | null;
  error?: string;
}

interface ContractView {
  schema_version: string;
  endpoint: string;
  timeout_seconds: number;
  request: Record<string, unknown>;
  response: Record<string, unknown>;
  threshold_note: string;
  license: string;
}

const TONE = {
  ready: "border-transparent bg-emerald-100 text-emerald-800 hover:bg-emerald-100",
  warn: "border-transparent bg-amber-100 text-amber-800 hover:bg-amber-100",
  off: "border-transparent bg-slate-100 text-slate-700 hover:bg-slate-100",
  bad: "border-transparent bg-red-100 text-red-800 hover:bg-red-100",
} as const;

function tone(status: string) {
  if (status === "ready" || status === "configured") return TONE.ready;
  if (status === "not_trained" || status === "not_installed") return TONE.warn;
  return TONE.off;
}

function label(status: string) {
  return status.replaceAll("_", " ");
}

function whyNotReady(card: ModelCard) {
  if (card.name === "student-dropout") {
    if (card.status !== "ready") {
      return "No loadable model bundle is present. The adapter reports not_trained and every student stays unscored.";
    }
    return "The bundle is a synthetic demo. ProfAssist does not import day-35 Moodle activity yet, so no real student is scored.";
  }
  if (card.status !== "configured") {
    return "PLAGIARISM_WORKER_URL is not set. The gateway refuses to score and returns a fixed 503.";
  }
  return "The worker URL is set. Run Test worker to confirm the external service answers /health.";
}

export default function ModelsPage() {
  const [view, setView] = useState<ModelsView | null>(null);
  const [contract, setContract] = useState<ContractView | null>(null);
  const [probe, setProbe] = useState<ProbeView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      pa<ModelsView>("/admin/ml/models"),
      pa<ContractView>("/admin/ml/plagiarism/contract").catch(() => null),
    ])
      .then(([data, details]) => {
        setView(data);
        setContract(details);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not load the ML control room"),
      );
  }, []);

  async function testWorker() {
    setBusy(true);
    setProbe(null);
    const result = await run(
      () => pa<ProbeView>("/admin/ml/plagiarism/probe", { method: "POST" }),
      setError,
    );
    if (result) setProbe(result);
    setBusy(false);
  }

  if (!view && !error) return <p className="text-sm">Loading ML control room...</p>;
  if (!view) return <Banner>{error}</Banner>;

  const dropout = view.models.find((card) => card.name === "student-dropout");
  const reuse = view.models.find((card) => card.name === "passage-reuse");
  const features = dropout?.features ?? [];
  const workerHost = view.settings.worker_host;

  return (
    <div className="flex max-w-5xl flex-col gap-3 text-sm">
      {error && <Banner>{error}</Banner>}

      <div className="grid gap-3 md:grid-cols-2">
        <Card className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-medium">Student dropout</h2>
              <p className="text-foreground/60 text-xs">
                Course-withdrawal early warning. Advisory only: it never enrols, messages, or grades
                a student.
              </p>
            </div>
            <Badge variant="outline" className={tone(dropout?.status ?? "not_trained")}>
              {label(dropout?.status ?? "not_trained")}
            </Badge>
          </div>

          <dl className="mt-3 grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-foreground/60">Synthetic</dt>
            <dd>
              {dropout?.synthetic
                ? "Yes - demo artifact, not real student data"
                : "No synthetic flag reported"}
            </dd>
            <dt className="text-foreground/60">Threshold</dt>
            <dd>
              {dropout?.threshold !== undefined ? dropout.threshold : "not set"}
              <span className="text-foreground/50"> (the bundle owns this value)</span>
            </dd>
            <dt className="text-foreground/60">Features</dt>
            <dd>
              {features.length || 14} required
              <details className="mt-1">
                <summary className="text-foreground/60 cursor-pointer">Show feature names</summary>
                <ul className="mt-1 grid gap-0.5 pl-4">
                  {features.map((feature) => (
                    <li key={feature}>
                      <code className="text-[11px]">{feature}</code>
                    </li>
                  ))}
                </ul>
              </details>
            </dd>

            <dt className="text-foreground/60">Data needed</dt>
            <dd>{dropout?.data_needed}</dd>
            <dt className="text-foreground/60">License</dt>
            <dd>{dropout?.license}</dd>
            <dt className="text-foreground/60">Version</dt>
            <dd>{dropout?.version ?? "not reported"}</dd>
          </dl>

          <p className="text-foreground/60 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs">
            <strong className="text-foreground">Why not production-ready:</strong>{" "}
            {dropout ? whyNotReady(dropout) : "The gateway did not return a dropout card."}
          </p>

          <div className="mt-3 flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/students">At-risk students</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/integrations/moodle">Moodle import</Link>
            </Button>
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-medium">Passage reuse / plagiarism</h2>
              <p className="text-foreground/60 text-xs">
                Integrity signal from an external worker. The worker owns the model, threshold, and
                matching.
              </p>
            </div>
            <Badge variant="outline" className={tone(reuse?.status ?? "not_installed")}>
              {label(reuse?.status ?? "not_installed")}
            </Badge>
          </div>

          <dl className="mt-3 grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-foreground/60">Worker URL</dt>
            <dd>
              {view.settings.worker_url_set ? (
                <>
                  set
                  {workerHost ? (
                    <>
                      {" | "}
                      <code className="text-[11px]">{workerHost}</code>
                    </>
                  ) : (
                    <span className="text-foreground/50"> | host hidden</span>
                  )}
                </>
              ) : (
                "not set"
              )}
            </dd>
            <dt className="text-foreground/60">Token</dt>
            <dd>{view.settings.worker_token_set ? "set, hidden" : "not set"}</dd>
            <dt className="text-foreground/60">Threshold</dt>
            <dd>{reuse?.threshold_note ?? "not reported"}</dd>

            <dt className="text-foreground/60">Data needed</dt>
            <dd>{reuse?.data_needed}</dd>
            <dt className="text-foreground/60">License</dt>
            <dd>{reuse?.license}</dd>
            <dt className="text-foreground/60">Version</dt>
            <dd>{reuse?.version ?? "not reported"}</dd>
          </dl>

          <p className="text-foreground/60 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs">
            <strong className="text-foreground">Why not production-ready:</strong>{" "}
            {reuse ? whyNotReady(reuse) : "The gateway did not return a passage-reuse card."}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void testWorker()}>
              {busy ? "Testing..." : "Test worker"}
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/integrity">Open integrity</Link>
            </Button>
            <span className="text-foreground/50 text-xs">3-second /health timeout</span>
          </div>

          {probe && (
            <div
              className={`mt-3 rounded-lg border px-2.5 py-2 text-xs ${
                probe.reachable ? TONE.ready : TONE.bad
              }`}
            >
              <strong>{probe.reachable ? "Worker reachable" : "Worker not reachable"}</strong>
              <span className="ml-2">
                configured {String(probe.configured)} | reachable {String(probe.reachable)}
                {probe.worker_host ? ` | host ${probe.worker_host}` : ""}
              </span>
              <p className="mt-1">{probe.error ?? `Status: ${label(probe.status)}.`}</p>
            </div>
          )}
        </Card>
      </div>

      <Card className="p-3">
        <p className="text-foreground/70 text-xs">
          <strong className="text-foreground">
            No pass/fail model exists in the upstream repo.
          </strong>{" "}
          Dropout predicts withdrawal; plagiarism predicts text reuse.
        </p>
      </Card>

      <Card className="p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-medium">MLflow registry</h2>
            <Badge variant="outline" className={view.mlflow.reachable ? TONE.ready : TONE.warn}>
              {view.mlflow.reachable ? "reachable" : "unreachable"}
            </Badge>
            <code className="text-foreground/60 text-xs">
              {view.mlflow.tracking_uri || "tracking URI not set"}
            </code>
          </div>
          <Link className="text-xs underline" href="/admin/ai">
            AI settings
          </Link>
        </div>
        {!view.mlflow.reachable && (
          <p className="text-foreground/60 mt-2 text-xs">
            Restart hint: start it with <code>docker compose up -d mlflow</code>, or set{" "}
            <code>MLFLOW_TRACKING_URI</code> and restart the API.
          </p>
        )}
      </Card>

      {contract && (
        <Card className="p-3">
          <details>
            <summary className="cursor-pointer text-sm font-medium">
              Worker JSON contract (v{contract.schema_version})
            </summary>
            <p className="text-foreground/60 mt-2 text-xs">
              Static from docs/ml.md. It contains no secrets and no worker URL.
            </p>
            <pre className="bg-foreground/[0.03] mt-2 overflow-x-auto rounded-lg p-3 text-xs">
              {JSON.stringify(contract, null, 2)}
            </pre>
          </details>
        </Card>
      )}
    </div>
  );
}
