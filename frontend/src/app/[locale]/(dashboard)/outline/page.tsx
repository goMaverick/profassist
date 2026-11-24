"use client";

import { useEffect, useRef, useState } from "react";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardFooter,
  FormField,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Progress,
  Textarea,
} from "@/components/ui";
import {
  AlertCircle,
  Check,
  Circle,
  FileText,
  Loader2,
  Paperclip,
  Send,
  WandSparkles,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { pa } from "@/components/profassist/bits";
import { setPageContext } from "@/components/profassist/page-context";
import { ProfassistError } from "@/lib/profassist";
import { OutlineDocument, type Outline, type OutlineBody } from "./outline-document";

const STAGES = [
  "Reading notes",
  "Drafting outcomes",
  "Building schedule",
  "Assembling document",
] as const;

const MAX_NOTE_BYTES = 25 * 1024 * 1024;

/** Body keys that a refine can touch, with the words the bubble shows. */
const SECTION_LABELS: ReadonlyArray<readonly [string, string]> = [
  ["basics", "subject details"],
  ["lecture", "lecture information"],
  ["description", "description"],
  ["program", "outcomes"],
  ["plos", "outcomes"],
  ["clos", "outcomes"],
  ["weeks", "schedule"],
  ["readings", "supporting materials"],
  ["outcome_measures", "assessment map"],
  ["assessment_tasks", "assessment tasks"],
  ["genai_intro", "GenAI guidance"],
  ["genai", "GenAI guidance"],
  ["grades", "grades"],
  ["satisfactory", "satisfactory completion"],
  ["satisfactory_note", "satisfactory completion"],
  ["policy_documents", "policies"],
  ["policies", "policies"],
  ["ssp", "SSP"],
  ["academic_integrity", "academic integrity"],
  ["attendance", "attendance"],
  ["supplementary", "supplementary assessment"],
  ["lecture_capture", "lecture capture"],
  ["sustainability", "sustainability"],
  ["late_submission", "late submissions"],
];

interface RefineResponse {
  outline?: Outline;
  reply?: string;
  changed?: unknown;
  changed_sections?: unknown;
}

function field(value: unknown) {
  return value === null || value === undefined ? "" : String(value);
}

function messageOf(err: unknown) {
  if (err instanceof ProfassistError) {
    return err.status ? `${err.message} (HTTP ${err.status})` : err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

function displayCode(value: unknown) {
  const code = field(value);
  return /^NEW-[A-F0-9]{6}$/i.test(code) ? "" : code;
}

function displayName(outline: Outline) {
  const raw = field(outline.body?.basics?.name) || outline.name || "";
  return raw === "New subject" ? "" : raw;
}

/** A generated outline is one we can safely open as a document. */
function hasDocument(outline: Outline) {
  if (outline.pdf_ready || outline.docx_ready || outline.status === "published") return true;
  const body = outline.body ?? {};
  return Boolean((body.clos ?? []).length || (body.weeks ?? []).length);
}

function diffSections(before: OutlineBody | undefined, after: OutlineBody | undefined) {
  const left = before ?? {};
  const right = after ?? {};
  const labels = new Set<string>();
  for (const [key, label] of SECTION_LABELS) {
    if (JSON.stringify(left[key] ?? null) !== JSON.stringify(right[key] ?? null)) {
      labels.add(label);
    }
  }
  return Array.from(labels);
}

function normalizeChanged(value: unknown): string[] {
  if (typeof value === "string") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item.trim();
      if (item && typeof item === "object" && "section" in item) {
        return field((item as { section?: unknown }).section);
      }
      return "";
    })
    .filter(Boolean);
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function GeneratingView({ courseName, stage }: { courseName: string; stage: number }) {
  const progress = Math.min(90, Math.round(((stage + 1) / (STAGES.length + 1)) * 100));
  return (
    <div className="mx-auto w-full max-w-3xl py-10">
      <div className="mb-6 text-center">
        <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
          Subject outline
        </p>
        <h1 className="font-display mt-1 text-2xl font-semibold tracking-tight">
          {courseName || "New outline"}
        </h1>
        <p className="text-muted-foreground mt-2 text-sm">
          Building the full outline from your notes.
        </p>
      </div>
      <Card className="mx-auto max-w-md">
        <CardContent className="space-y-4 pt-6">
          <Progress value={progress} aria-label="Generating the outline" />
          <ol className="space-y-3">
            {STAGES.map((label, index) => {
              const done = index < stage;
              const active = index === stage;
              return (
                <li
                  key={label}
                  className={cn(
                    "flex items-center gap-3 text-sm",
                    !done && !active && "text-muted-foreground",
                  )}
                >
                  {done ? (
                    <Check className="h-4 w-4 text-emerald-600" />
                  ) : active ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Circle className="h-4 w-4" />
                  )}
                  <span>{label}</span>
                </li>
              );
            })}
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}

export default function OutlinePage() {
  const [booting, setBooting] = useState(true);
  const [bootError, setBootError] = useState("");
  const [bootAttempt, setBootAttempt] = useState(0);
  const [outline, setOutline] = useState<Outline | null>(null);
  const [moodleMode, setMoodleMode] = useState("");
  const [screen, setScreen] = useState<"start" | "generating" | "document">("start");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [focus, setFocus] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [attached, setAttached] = useState<string[]>([]);
  const [formError, setFormError] = useState("");
  const [startError, setStartError] = useState("");
  const [stage, setStage] = useState(0);
  const [enhanceOpen, setEnhanceOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [lastSent, setLastSent] = useState("");
  const [enhancing, setEnhancing] = useState(false);
  const [enhanceSent, setEnhanceSent] = useState(false);
  const [enhanceReply, setEnhanceReply] = useState("");
  const [changedSections, setChangedSections] = useState<string[]>([]);
  const [enhanceError, setEnhanceError] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);
  const enhanceRef = useRef<HTMLTextAreaElement | null>(null);
  const generatingRef = useRef(false);
  const enhancingRef = useRef(false);

  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 12000);
    (async () => {
      try {
        const data = await pa<{ items: Outline[] }>("/outlines", {
          signal: controller.signal,
        });
        if (!alive) return;
        const items = data.items ?? [];
        const documented = items.find(hasDocument);
        if (documented) {
          setOutline(documented);
          setName(displayName(documented));
          setCode(displayCode(documented.body?.basics?.code) || displayCode(documented.code));
          setFocus(documented.instructions || "");
          setScreen("document");
          return;
        }
        const draft = items[0];
        if (draft) {
          setOutline(draft);
          setName(displayName(draft));
          setCode(displayCode(draft.body?.basics?.code) || displayCode(draft.code));
          setFocus(draft.instructions || "");
        }
      } catch (err) {
        if (!alive) return;
        const aborted =
          controller.signal.aborted || (err instanceof Error && err.name === "AbortError");
        setBootError(
          aborted ? "The outline service did not respond. Try again." : messageOf(err),
        );
      } finally {
        window.clearTimeout(timer);
        if (alive) setBooting(false);
      }
    })();
    return () => {
      alive = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [bootAttempt]);

  useEffect(() => {
    if (screen !== "document") return;
    let alive = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 8000);
    pa<{ mode?: string }>("/moodle/status", { signal: controller.signal })
      .then((data) => {
        if (alive) setMoodleMode(data.mode || "unknown");
      })
      .catch(() => {
        if (alive) setMoodleMode("unknown");
      })
      .finally(() => window.clearTimeout(timer));
    return () => {
      alive = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [screen, outline?.id]);

  useEffect(() => {
    if (screen !== "generating") return;
    const handle = window.setInterval(() => {
      setStage((value) => Math.min(value + 1, STAGES.length - 1));
    }, 1600);
    return () => window.clearInterval(handle);
  }, [screen]);

  useEffect(() => {
    if (!enhanceOpen) return;
    const handle = window.setTimeout(() => enhanceRef.current?.focus(), 0);
    return () => window.clearTimeout(handle);
  }, [enhanceOpen]);

  useEffect(() => {
    setPageContext({
      page: "/outline",
      title: "Subject outline",
      outline_id: outline?.id,
      course_id: outline?.course_id,
      course_name: name.trim() || outline?.name,
      section:
        screen === "document" ? "Document" : screen === "generating" ? "Generating" : "Start",
    });
    return () => {
      setPageContext({
        outline_id: undefined,
        course_id: undefined,
        course_name: undefined,
        section: undefined,
      });
    };
  }, [outline?.id, outline?.course_id, outline?.name, name, screen]);

  function retryBoot() {
    setBootError("");
    setBooting(true);
    setBootAttempt((value) => value + 1);
  }

  function addFiles(incoming: File[]) {
    if (!incoming.length) return;
    setFormError("");
    const rejected: string[] = [];
    const accepted: File[] = [];
    for (const file of incoming) {
      if (file.size > MAX_NOTE_BYTES) {
        rejected.push(`${file.name} is over 25 MB.`);
        continue;
      }
      if (!/\.(pdf|docx|pptx|txt|md)$/i.test(file.name)) {
        rejected.push(`${file.name} is not a PDF, DOCX, PPTX, TXT or MD file.`);
        continue;
      }
      if (attached.includes(file.name)) continue;
      if (accepted.some((item) => item.name === file.name && item.size === file.size)) continue;
      if (files.some((item) => item.name === file.name && item.size === file.size)) continue;
      accepted.push(file);
    }
    if (accepted.length) setFiles((current) => [...current, ...accepted]);
    if (rejected.length) setFormError(rejected.join(" "));
  }

  function removeFile(file: File) {
    setFiles((current) => current.filter((item) => item !== file));
  }

  async function startGeneration() {
    const courseName = name.trim();
    if (!courseName || generatingRef.current) return;
    generatingRef.current = true;
    setFormError("");
    setStartError("");
    setStage(0);
    setScreen("generating");

    let current = outline && !hasDocument(outline) ? outline : null;
    try {
      if (!current) {
        current = await pa<Outline>("/outlines", { method: "POST" });
        setOutline(current);
      }
      const id = current.id;

      const basics: Record<string, unknown> = { ...(current.body?.basics ?? {}), name: courseName };
      const courseCode = code.trim();
      if (courseCode) basics.code = courseCode;
      let saved = await pa<Outline>(`/outlines/${id}/step`, {
        method: "PUT",
        body: JSON.stringify({ step: "basics", payload: basics }),
      });
      setOutline(saved);

      saved = await pa<Outline>(`/outlines/${id}/instructions`, {
        method: "PUT",
        body: JSON.stringify({ instructions: focus.trim() }),
      });
      setOutline(saved);

      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        try {
          await pa<{ materials: unknown[] }>(`/outlines/${id}/materials`, {
            method: "POST",
            body: form,
          });
        } catch (err) {
          throw new Error(`${file.name}: ${messageOf(err)}`);
        }
        setFiles((currentFiles) => currentFiles.filter((item) => item !== file));
        setAttached((currentFiles) => [...currentFiles, file.name]);
      }

      const payload = await pa<Outline | { outline: Outline }>(`/outlines/${id}/generate`, {
        method: "POST",
        body: JSON.stringify({ message: focus.trim() || courseName }),
      });
      const generated = "outline" in payload ? payload.outline : payload;
      setOutline(generated);
      setName(displayName(generated) || courseName);
      setCode(displayCode(generated.body?.basics?.code) || courseCode);
      setScreen("document");
    } catch (err) {
      setStartError(messageOf(err));
      setScreen("start");
      setStage(0);
    } finally {
      generatingRef.current = false;
    }
  }

  async function sendEnhance(retryText?: string) {
    if (!outline || enhancingRef.current) return;
    const text = (retryText ?? message).trim();
    if (!text) return;
    enhancingRef.current = true;
    setLastSent(text);
    setEnhancing(true);
    setEnhanceSent(false);
    setEnhanceError("");
    setEnhanceReply("");
    setChangedSections([]);
    const before = outline;
    try {
      const result = await pa<RefineResponse>(`/outlines/${outline.id}/refine`, {
        method: "POST",
        body: JSON.stringify({ message: text }),
      });
      const next = result.outline ?? before;
      const explicit = normalizeChanged(result.changed ?? result.changed_sections);
      const detected = diffSections(before.body, next.body);
      const changed = explicit.length ? explicit : detected;
      setOutline(next);
      setChangedSections(changed);
      setEnhanceReply(result.reply?.trim() || "");
      setEnhanceSent(true);
    } catch (err) {
      setEnhanceError(messageOf(err));
    } finally {
      enhancingRef.current = false;
      setEnhancing(false);
    }
  }

  function askAiAboutSelection({ quote, sectionTitle }: { quote: string; sectionTitle: string }) {
    const clipped = quote.length > 120 ? quote.slice(0, 117).trimEnd() + "\u2026" : quote;
    const label = sectionTitle.replace(/^[0-9]+([.][0-9]+)*[.]?\s*/, "").trim();
    const prefix = label ? "Refine " + label + ": " : "Refine this section: ";
    setLastSent("");
    setEnhanceSent(false);
    setEnhanceReply("");
    setChangedSections([]);
    setEnhanceError("");
    setMessage(prefix + "\u201c" + clipped + "\u201d \u2014 ");
    setEnhanceOpen(true);
  }

  if (booting) {
    return (
      <div className="text-muted-foreground flex min-h-[50vh] items-center justify-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        Opening the outline…
      </div>
    );
  }

  if (bootError) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 py-10">
        <Alert variant="destructive" role="alert">
          <AlertCircle className="h-4 w-4" />
          <div>
            <AlertTitle>Could not open the outline</AlertTitle>
            <AlertDescription>{bootError}</AlertDescription>
          </div>
        </Alert>
        <Button type="button" onClick={retryBoot}>
          Try again
        </Button>
      </div>
    );
  }

  if (screen === "generating") {
    return <GeneratingView courseName={name.trim()} stage={stage} />;
  }

  if (screen === "document" && outline) {
    return (
      <div className="w-full pb-20">
        <OutlineDocument
          key={outline.id}
          outline={outline}
          onOutline={setOutline}
          moodleMode={moodleMode}
          onAskAi={askAiAboutSelection}
        />

        <div className="fixed right-6 bottom-6 z-40 print:hidden">
          <Popover open={enhanceOpen} onOpenChange={setEnhanceOpen}>
            <PopoverTrigger asChild>
              <Button type="button" size="lg" className="shadow-lg" aria-haspopup="dialog">
                <WandSparkles className="h-4 w-4" />
                Enhance
              </Button>
            </PopoverTrigger>
            <PopoverContent
              side="top"
              align="end"
              sideOffset={12}
              role="dialog"
              aria-label="Enhance outline"
              aria-busy={enhancing}
              className="pa-enhance-bubble w-80 max-w-[calc(100vw-2rem)] p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold">Enhance outline</p>
                  <p className="text-muted-foreground text-xs">
                    Tell me what to change; I will edit the document.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Close"
                  onClick={() => setEnhanceOpen(false)}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>

              {enhanceError ? (
                <Alert variant="destructive" className="mt-3">
                  <AlertCircle className="h-4 w-4" />
                  <div>
                    <AlertTitle className="text-sm">Could not enhance</AlertTitle>
                    <AlertDescription className="text-xs">{enhanceError}</AlertDescription>
                  </div>
                </Alert>
              ) : null}

              {enhanceSent && !enhancing ? (
                <div className="bg-muted/50 mt-3 rounded-md border p-3 text-sm" aria-live="polite">
                  {enhanceReply ? <p className="whitespace-pre-wrap">{enhanceReply}</p> : null}
                  <p className={cn("text-muted-foreground text-xs", enhanceReply && "mt-1")}>
                    {changedSections.length
                      ? "Updated: " + changedSections.join(", ")
                      : "Nothing changed."}
                  </p>
                </div>
              ) : null}

              {enhancing ? (
                <p
                  className="text-muted-foreground mt-3 flex items-center gap-2 text-sm"
                  aria-live="polite"
                >
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Enhancing…
                </p>
              ) : null}

              <div className="mt-3 space-y-2">
                <Textarea
                  ref={enhanceRef}
                  id="enhance-message"
                  rows={2}
                  maxLength={300}
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder="e.g. Make LO3 more measurable, add a late penalty, change week 7…"
                  disabled={enhancing}
                  aria-label="What should change?"
                  className="resize-none"
                />
                <div className="flex items-center justify-between gap-2">
                  <span className="text-muted-foreground text-[11px]">{message.length}/300</span>
                  <div className="flex items-center gap-2">
                    {enhanceError ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={enhancing}
                        onClick={() => void sendEnhance(lastSent)}
                      >
                        Retry
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      size="sm"
                      disabled={enhancing || !message.trim()}
                      onClick={() => void sendEnhance()}
                    >
                      {enhancing ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Send className="h-3.5 w-3.5" />
                      )}
                      Send
                    </Button>
                  </div>
                </div>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl py-6">
      <div className="mb-6">
        <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
          Subject outline
        </p>
        <h1 className="font-display mt-1 text-3xl font-semibold tracking-tight">
          Course Designer
        </h1>
        <p className="text-muted-foreground mt-2 text-sm">
          Create the course, generate the syllabus, then edit the document.
        </p>
      </div>

      <Card>
        <CardContent className="space-y-5 pt-6">
          {startError ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <div>
                <AlertTitle>Could not generate the outline</AlertTitle>
                <AlertDescription>{startError}</AlertDescription>
              </div>
            </Alert>
          ) : null}

          {formError ? (
            <Alert variant="warning">
              <AlertCircle className="h-4 w-4" />
              <div>
                <AlertTitle>Those notes were not added</AlertTitle>
                <AlertDescription>{formError}</AlertDescription>
              </div>
            </Alert>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-3">
            <FormField
              label="Course name"
              htmlFor="outline-course-name"
              required
              className="sm:col-span-2"
            >
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. AI Solutions"
                autoComplete="off"
              />
            </FormField>
            <FormField label="Course code" htmlFor="outline-course-code">
              <Input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="e.g. MAAI903"
                autoComplete="off"
              />
            </FormField>
          </div>

          <FormField
            label="What should I focus on?"
            htmlFor="outline-focus"
            description="Special instructions, emphases or constraints that should shape the outline."
          >
            <Textarea
              rows={4}
              value={focus}
              onChange={(event) => setFocus(event.target.value)}
              placeholder="e.g. Emphasise applied projects, keep four assessments, add a late penalty."
            />
          </FormField>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="outline" onClick={() => fileRef.current?.click()}>
                <Paperclip className="h-4 w-4" />
                Add notes
              </Button>
              <span className="text-muted-foreground text-xs">
                PDF, DOCX, PPTX, TXT or MD, up to 25 MB each.
              </span>
            </div>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.pptx,.txt,.md"
              multiple
              aria-hidden="true"
              tabIndex={-1}
              onChange={(event) => {
                addFiles(Array.from(event.target.files ?? []));
                event.target.value = "";
              }}
            />
            {files.length > 0 || attached.length > 0 ? (
              <ul className="divide-border divide-y rounded-md border">
                {attached.map((filename, index) => (
                  <li
                    key={`attached-${filename}-${index}`}
                    className="flex items-center gap-2 px-3 py-2 text-sm"
                  >
                    <Check className="h-4 w-4 text-emerald-600" />
                    <span className="truncate">{filename}</span>
                    <Badge variant="secondary" className="ml-auto">
                      Attached
                    </Badge>
                  </li>
                ))}
                {files.map((file) => (
                  <li
                    key={`${file.name}-${file.size}`}
                    className="flex items-center gap-2 px-3 py-2 text-sm"
                  >
                    <FileText className="text-muted-foreground h-4 w-4" />
                    <span className="truncate">{file.name}</span>
                    <span className="text-muted-foreground ml-auto text-xs">
                      {formatSize(file.size)}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remove ${file.name}`}
                      onClick={() => removeFile(file)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground text-xs">No notes added yet.</p>
            )}
          </div>
        </CardContent>

        <CardFooter className="border-t pt-4">
          <div className="flex w-full flex-wrap items-center justify-between gap-3">
            <p className="text-muted-foreground max-w-sm text-xs">
              You can edit the document after it is generated.
            </p>
            <Button
              type="button"
              size="lg"
              disabled={!name.trim()}
              onClick={() => void startGeneration()}
            >
              <WandSparkles className="h-4 w-4" />
              Generate outline
            </Button>
          </div>
        </CardFooter>
      </Card>
    </div>
  );
}
