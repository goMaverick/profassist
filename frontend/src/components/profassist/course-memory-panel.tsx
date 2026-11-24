"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { Banner } from "@/components/profassist/bits";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import {
  BADGE_TONE,
  insightBadge,
  kindLabel,
  kindTone,
  pa,
  ProfassistError,
  type CourseDossier,
  type CourseMemory,
  type DossierConflict,
  type DossierProvenance,
  type MemoryMaterial,
  type MemoryRebuildResult,
} from "@/lib/profassist";

const MAX_SOURCES = 8;

function messageOf(err: unknown) {
  if (err instanceof ProfassistError) {
    return err.status ? `${err.message} (HTTP ${err.status})` : err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

function uniqueSources(provenance: DossierProvenance[]) {
  const seen = new Map<string, string>();
  for (const item of provenance) {
    const filename = (item.filename || "").trim();
    if (!filename) continue;
    const kind = item.kind || "";
    const existing = seen.get(filename);
    if (existing === undefined) {
      if (seen.size >= MAX_SOURCES) break;
      seen.set(filename, kind);
    } else if (!existing && kind) {
      seen.set(filename, kind);
    }
  }
  return Array.from(seen, ([filename, kind]) => ({ filename, kind }));
}

function conflictText(conflict: DossierConflict) {
  const subject = conflict.field || "A field";
  const winner = conflict.winner || "the higher-ranked source";
  const loser = conflict.loser ? ` over ${conflict.loser}` : "";
  const reason = conflict.reason ? ` \u2014 ${conflict.reason}` : "";
  return `${subject}: ${winner}${loser}${reason}`;
}

export function CourseMemoryPanel({ courseId }: { courseId: string }) {
  const [data, setData] = useState<CourseMemory | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [busyFile, setBusyFile] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [traceUrl, setTraceUrl] = useState("");

  const load = useCallback(async () => {
    const response = await pa<CourseMemory>(`/courses/${courseId}/memory`);
    setData(response);
  }, [courseId]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setTraceUrl("");
    setData(null);
    pa<CourseMemory>(`/courses/${courseId}/memory`)
      .then((response) => {
        if (active) setData(response);
      })
      .catch((err: unknown) => {
        if (active) setError(messageOf(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [courseId]);

  const dossier: CourseDossier | null = data?.dossier ?? null;
  const materials = data?.materials ?? [];
  const slidePreferences = data?.slide_preferences ?? [];
  const artifactPreferences = data?.artifact_preferences ?? [];
  const learnedPreferences =
    artifactPreferences.length > 0 ? artifactPreferences : slidePreferences;
  const topics = dossier?.topics?.length ?? 0;
  const assessments = dossier?.assessments?.length ?? 0;
  const conflicts = dossier?.conflicts ?? [];
  const sources = useMemo(() => uniqueSources(dossier?.provenance ?? []), [dossier]);

  async function rebuild() {
    if (rebuilding) return;
    setRebuilding(true);
    setError("");
    try {
      const result = await pa<MemoryRebuildResult>(`/courses/${courseId}/memory/rebuild`, {
        method: "POST",
      });
      setTraceUrl(result.trace_url || "");
      await load();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setRebuilding(false);
    }
  }

  async function readAgain(material: MemoryMaterial) {
    if (busyFile) return;
    setBusyFile(material.id);
    setError("");
    try {
      await pa(`/materials/${material.id}/extract`, { method: "POST" });
      await load();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusyFile(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div className="space-y-1">
          <CardTitle className="text-base">Course memory</CardTitle>
          <CardDescription>
            What the agents have read from this course&apos;s files, with a source for every field.
          </CardDescription>
        </div>
        <Button
          type="button"
          size="sm"
          className="shrink-0"
          disabled={rebuilding || loading}
          onClick={() => void rebuild()}
        >
          <RefreshCw className={rebuilding ? "animate-spin" : undefined} />
          {rebuilding ? "Rebuilding..." : "Rebuild course memory"}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && <Banner>{error}</Banner>}
        {traceUrl && (
          <a
            className="text-xs underline underline-offset-4"
            href={traceUrl}
            target="_blank"
            rel="noreferrer"
          >
            View rebuild trace
          </a>
        )}
        {loading ? (
          <p className="text-muted-foreground text-sm">Loading course memory...</p>
        ) : data ? (
          <>
            {dossier ? (
              <>
                <div className="flex flex-col gap-1">
                  <div className="flex flex-wrap gap-1">
                    <Badge variant="secondary">v{dossier.version ?? 1}</Badge>
                    <Badge variant="secondary">
                      {materials.length} document{materials.length === 1 ? "" : "s"}
                    </Badge>
                    <Badge variant="secondary">
                      {topics} topic{topics === 1 ? "" : "s"}
                    </Badge>
                    <Badge variant="secondary">
                      {assessments} assessment{assessments === 1 ? "" : "s"}
                    </Badge>
                  </div>
                  <p className="text-sm">
                    {dossier.summary || (
                      <span className="text-muted-foreground">No summary yet.</span>
                    )}
                  </p>
                </div>
                {sources.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                      Sources
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {sources.map((source) => {
                        const label = kindLabel(source.kind);
                        return (
                          <Badge
                            key={source.filename}
                            variant="outline"
                            className="max-w-[16rem] truncate"
                          >
                            {label ? `${source.filename} \u00b7 ${label}` : source.filename}
                          </Badge>
                        );
                      })}
                    </div>
                  </div>
                )}
                {conflicts.length > 0 && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                    <p className="flex items-center gap-2 font-medium">
                      <AlertTriangle className="size-4" />
                      Some sources disagreed
                    </p>
                    <ul className="mt-1 list-disc space-y-1 pl-5">
                      {conflicts.slice(0, 6).map((conflict, index) => (
                        <li key={`${conflict.field || "conflict"}-${index}`}>
                          {conflictText(conflict)}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <p className="text-muted-foreground text-sm">
                Course memory is empty. Upload notes and the agents will read them file by file.
              </p>
            )}
            {learnedPreferences.length > 0 && (
              <div className="flex flex-col gap-1">
                <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                  Learned preferences
                </p>
                <div className="flex flex-wrap gap-1">
                  {learnedPreferences.map((preference, index) => (
                    <Badge
                      key={`${preference}-${index}`}
                      variant="outline"
                      className="max-w-full truncate"
                    >
                      {preference}
                    </Badge>
                  ))}
                </div>
                <p className="text-muted-foreground text-xs">
                  Learned from your edits across outlines, assignments, rubrics, decks, and grading.
                  Reflection updates them after 5 new lessons.
                </p>
              </div>
            )}
            <div className="flex flex-col gap-2">
              <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                Files
              </p>
              {materials.length === 0 ? (
                <p className="text-muted-foreground text-sm">No files in this course yet.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {materials.map((material) => (
                    <MaterialRow
                      key={material.id}
                      material={material}
                      busy={busyFile === material.id}
                      disabled={busyFile !== null}
                      onReadAgain={readAgain}
                    />
                  ))}
                </ul>
              )}
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

function MaterialRow({
  material,
  busy,
  disabled,
  onReadAgain,
}: {
  material: MemoryMaterial;
  busy: boolean;
  disabled: boolean;
  onReadAgain: (material: MemoryMaterial) => Promise<void>;
}) {
  const badge = insightBadge(material.insight_status);
  const kind = kindLabel(material.kind);
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-lg border p-2 text-sm">
      <span className="min-w-0 flex-1 truncate">{material.filename}</span>
      {badge && (
        <Badge className={`${BADGE_TONE[badge.tone]} px-1.5 py-0 text-[10px]`}>{badge.label}</Badge>
      )}
      {kind && (
        <Badge className={`${BADGE_TONE[kindTone(material.kind)]} px-1.5 py-0 text-[10px]`}>
          {kind}
        </Badge>
      )}
      {material.tags?.slice(0, 2).map((tag) => (
        <Badge
          key={tag}
          className={`${BADGE_TONE.slate} max-w-[8rem] truncate px-1.5 py-0 text-[10px] font-normal`}
        >
          {tag}
        </Badge>
      ))}
      {material.trace_url && (
        <a
          className="text-xs underline underline-offset-4"
          href={material.trace_url}
          target="_blank"
          rel="noreferrer"
        >
          View trace
        </a>
      )}
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={disabled}
        aria-busy={busy}
        onClick={() => void onReadAgain(material)}
      >
        {busy ? "Reading..." : "Read again"}
      </Button>
    </li>
  );
}
