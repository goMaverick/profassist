"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Check,
  Download,
  FileText,
  Gavel,
  ListChecks,
  Loader2,
  Pencil,
  Plus,
  Save,
  Send,
  ShieldCheck,
  Sparkles,
  Target,
  Upload,
  Users,
  X,
} from "lucide-react";

import { pa } from "@/components/profassist/bits";
import {
  ProfassistError,
  type AssignmentReview,
  type AssignmentReviewIssue,
  type AssignmentReviewMessage,
} from "@/lib/profassist";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Input,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui";

const LEVELS = ["advanced", "proficient", "developing", "beginning"] as const;
type LevelKey = (typeof LEVELS)[number];

/** The four bands the assessment template uses, in the same order as the outline rubric. */
const LEVEL_LABELS: Record<LevelKey, string> = {
  advanced: "Excellent",
  proficient: "Good",
  developing: "Satisfactory",
  beginning: "Needs improvement",
};

/** Same label and key order as the DOCX/PDF renderer in app/profassist/assignment_doc.py. */
const CLASS_FIELDS: Array<{ label: string; key: string }> = [
  { label: "Institution", key: "institution" },
  { label: "Course", key: "course" },
  { label: "Lecturer", key: "lecturer" },
  { label: "Assessment", key: "assessment" },
  { label: "Weight", key: "weight" },
  { label: "Report length", key: "report_length" },
  { label: "Report due", key: "report_due" },
  { label: "Presentation", key: "presentation" },
  { label: "Submission", key: "submission" },
];

/** Section keys the refine response uses, mapped to what a reader calls them. */
const SECTION_LABELS: Record<string, string> = {
  class_details: "Class details",
  overview: "Overview",
  problem_choices: "Problem choices",
  deliverables: "Deliverables",
  report_sections: "Report sections",
  rubric: "Rubric",
  title: "Title",
  brief: "Brief",
};

interface Criterion {
  id?: string;
  name: string;
  weight: number;
  levels: Record<LevelKey, string>;
}

interface RubricState {
  id: string;
  brief: string;
  status: string;
  criteria: Criterion[];
}

interface ProblemChoice {
  problem: string;
  description: string;
}

interface DeliverableRow {
  title: string;
  description: string;
}

interface ReportSection {
  number: string;
  section: string;
  guidelines: string;
}

interface DocumentBody {
  class_details?: Record<string, unknown>;
  overview?: unknown[];
  problem_choices?: unknown[];
  deliverables?: unknown[];
  report_sections?: unknown[];
  /** Older artifacts store the council review inside the document. */
  review?: unknown;
}

interface AssignmentSummary {
  id: string;
  number?: unknown;
  title?: unknown;
  status?: unknown;
  course?: unknown;
  course_code?: unknown;
  course_title?: unknown;
  assessment_id?: unknown;
  assessmentId?: unknown;
  [key: string]: unknown;
}

interface Artifact {
  assignment: AssignmentSummary;
  document: DocumentBody;
  rubric: RubricState;
  review?: AssignmentReview;
}

interface RefineResponse {
  reply?: string;
  changed?: boolean;
  changed_sections?: unknown;
  assignment?: unknown;
  document?: unknown;
  rubric?: unknown;
}

function textOf(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

/** True for a raw identifier the API sometimes stores where a human title belongs. */
function uuidLike(value: string): boolean {
  const text = value.trim().toLowerCase();
  if (!text) return false;
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(text)) {
    return true;
  }
  if (/^[0-9a-f]{32}$/.test(text)) return true;
  // A truncated id keeps the hyphenated prefix, e.g. "3f2a1b4c-9d8e-4f".
  return /^[0-9a-f]{8}(-[0-9a-f]{1,4}){0,4}$/.test(text);
}

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function listOf(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function weightOf(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const match = /\d+(?:\.\d+)?/.exec(textOf(value));
  return match ? Number(match[0]) : 0;
}

function sectionLabel(key: string): string {
  return SECTION_LABELS[key] ?? key.replaceAll("_", " ");
}

function describeError(error: unknown, fallback: string): string {
  if (error instanceof ProfassistError) {
    if (error.status === 503) {
      return error.message + " (503: the AI provider is unavailable, so nothing changed.)";
    }
    return error.message || fallback;
  }
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}

/** The artifact wraps the document as `document`; older rows nest the body one level deeper. */
function asDocument(raw: unknown): DocumentBody {
  const docKeys = [
    "class_details",
    "overview",
    "problem_choices",
    "deliverables",
    "report_sections",
  ];
  const outer = recordOf(raw);
  if (docKeys.some((key) => key in outer)) return outer as DocumentBody;
  const inner = recordOf(outer.document ?? outer.body);
  if (docKeys.some((key) => key in inner)) return inner as DocumentBody;
  return outer as DocumentBody;
}

function asCriterion(raw: unknown): Criterion {
  const row = recordOf(raw);
  const levels = recordOf(row.levels);
  return {
    id: textOf(row.id) || undefined,
    name: textOf(row.name),
    weight: weightOf(row.weight),
    levels: {
      advanced: textOf(levels.advanced ?? levels.excellent),
      proficient: textOf(levels.proficient ?? levels.good),
      developing: textOf(levels.developing ?? levels.satisfactory),
      beginning: textOf(levels.beginning ?? levels.needs_improvement),
    },
  };
}

function asRubric(raw: unknown, assignment: AssignmentSummary): RubricState {
  const row = recordOf(raw);
  const items = Array.isArray(raw) ? raw : listOf(row.criteria);
  return {
    id:
      textOf(row.id) ||
      textOf(row.assessment_id) ||
      textOf(assignment.assessment_id) ||
      textOf(assignment.assessmentId),
    brief: textOf(row.brief),
    status: textOf(row.status),
    criteria: items.map(asCriterion),
  };
}

const REVIEW_VERDICTS = new Set(["pass", "revise"]);

function normalizeReviewIssue(raw: unknown): AssignmentReviewIssue | null {
  const row = recordOf(raw);
  const issue = textOf(row.issue).trim();
  if (!issue) return null;
  const section = row.section ?? row.slide;
  return {
    reviewer: textOf(row.reviewer).trim() || undefined,
    severity: textOf(row.severity).trim().toLowerCase() || "medium",
    section: typeof section === "number" ? section : textOf(section).trim() || undefined,
    issue,
    fix: textOf(row.fix).trim() || undefined,
  };
}

function normalizeReviewMessage(raw: unknown): AssignmentReviewMessage | null {
  const row = recordOf(raw);
  const text = textOf(row.text).trim();
  if (!text) return null;
  return {
    role: textOf(row.role).trim().toLowerCase() || "chair",
    text,
    severity: textOf(row.severity).trim().toLowerCase() || undefined,
  };
}

/** An absent or empty review means the artifact has not been to the council yet. */
function asReview(raw: unknown): AssignmentReview | undefined {
  const row = recordOf(raw);
  const verdict = textOf(row.verdict).trim().toLowerCase();
  if (!REVIEW_VERDICTS.has(verdict)) return undefined;
  const score = row.score;
  const review: AssignmentReview = {
    verdict: verdict as AssignmentReview["verdict"],
    score: typeof score === "number" && Number.isFinite(score) ? score : 0,
    issues: listOf(row.issues)
      .map(normalizeReviewIssue)
      .filter((item): item is AssignmentReviewIssue => item !== null),
    strengths: listOf(row.strengths)
      .map((item) => textOf(item).trim())
      .filter((item) => item.length > 0),
    messages: listOf(row.messages)
      .map(normalizeReviewMessage)
      .filter((item): item is AssignmentReviewMessage => item !== null),
  };
  if (typeof row.trace_url === "string" && row.trace_url) review.trace_url = row.trace_url;
  if (row.degraded === true) review.degraded = true;
  return review;
}

function asArtifact(raw: unknown): Artifact {
  const row = recordOf(raw);
  const assignment = recordOf(row.assignment) as unknown as AssignmentSummary;
  const document = asDocument(row.document);
  return {
    assignment: { ...assignment, id: textOf(assignment.id) },
    document,
    rubric: asRubric(row.rubric, assignment),
    // The review moved out of the document, but older rows still nest it there.
    review: asReview(row.review ?? recordOf(row.document).review ?? document.review),
  };
}

/** Apply a refine/finish payload onto the artifact that is already open. */
function mergeArtifact(current: Artifact, raw: unknown): Artifact {
  const row = recordOf(raw);
  const assignmentRow = recordOf(row.assignment);
  const assignment = (
    Object.keys(assignmentRow).length
      ? { ...current.assignment, ...assignmentRow }
      : current.assignment
  ) as AssignmentSummary;
  const merged: AssignmentSummary = { ...assignment, id: textOf(assignment.id) };
  return {
    assignment: merged,
    document: row.document ? asDocument(row.document) : current.document,
    rubric: row.rubric ? asRubric(row.rubric, merged) : current.rubric,
  };
}

function changedNames(raw: unknown): string[] {
  return listOf(raw)
    .map((item) => {
      if (typeof item === "string") return sectionLabel(item);
      const row = recordOf(item);
      const key =
        textOf(row.section) || textOf(row.key) || textOf(row.name) || textOf(row.label) || "";
      return key ? sectionLabel(key) : "";
    })
    .filter(Boolean);
}

function cloneCriterion(row: Criterion): Criterion {
  return { ...row, levels: { ...row.levels } };
}

function payloadCriterion(row: Criterion) {
  return {
    name: row.name.trim(),
    weight: Number.isFinite(row.weight) ? Math.max(0, Math.round(row.weight)) : 0,
    levels: {
      advanced: row.levels.advanced,
      proficient: row.levels.proficient,
      developing: row.levels.developing,
      beginning: row.levels.beginning,
    },
  };
}

/** The editable shape of `document`. Keys match what the renderer and the API read. */
interface DocumentDraft {
  class_details: Record<string, string>;
  overview: string[];
  problem_choices: ProblemChoice[];
  deliverables: DeliverableRow[];
  report_sections: ReportSection[];
}

const EMPTY_DOCUMENT: DocumentDraft = {
  class_details: {},
  overview: [],
  problem_choices: [],
  deliverables: [],
  report_sections: [],
};

function normalizeDocument(doc: DocumentBody): DocumentDraft {
  const details: Record<string, string> = {};
  for (const [key, value] of Object.entries(recordOf(doc.class_details))) {
    details[key] = textOf(value);
  }
  return {
    class_details: details,
    overview: listOf(doc.overview)
      .map(textOf)
      .filter((line) => line.length > 0),
    problem_choices: listOf(doc.problem_choices).map((item) => {
      const row = recordOf(item);
      return { problem: textOf(row.problem), description: textOf(row.description) };
    }),
    deliverables: listOf(doc.deliverables).map((item) => {
      if (typeof item === "string") return { title: "", description: item };
      const row = recordOf(item);
      return { title: textOf(row.title), description: textOf(row.description) };
    }),
    report_sections: listOf(doc.report_sections).map((item) => {
      const row = recordOf(item);
      return {
        number: textOf(row.number),
        section: textOf(row.section),
        guidelines: textOf(row.guidelines),
      };
    }),
  };
}

/** The PUT payload: the same keys the DOCX/PDF renderer reads, in template order. */
function serializeDocument(draft: DocumentDraft): DocumentBody {
  return {
    class_details: { ...draft.class_details },
    overview: draft.overview.filter((line) => line.trim().length > 0),
    problem_choices: draft.problem_choices.map((row) => ({
      problem: row.problem,
      description: row.description,
    })),
    deliverables: draft.deliverables.map((row) => ({
      title: row.title,
      description: row.description,
    })),
    report_sections: draft.report_sections.map((row) => ({
      number: row.number,
      section: row.section,
      guidelines: row.guidelines,
    })),
  };
}
function SectionShell({
  sectionKey,
  title,
  onEdit,
  enhance,
  children,
}: {
  sectionKey: string;
  title: string;
  onEdit: () => void;
  enhance: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      id={"doc-section-" + sectionKey}
      className="group scroll-mt-36 border-t border-neutral-200 pt-5 first:border-0 first:pt-0"
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <h2 className="text-base font-semibold text-neutral-900">{title}</h2>
        <div className="flex shrink-0 items-center gap-1 opacity-100 transition-opacity focus-within:opacity-100 sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100 print:hidden">
          {enhance}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={"Edit " + title}
                className="text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900"
                onClick={onEdit}
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Edit {title}</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {children}
    </section>
  );
}

/** One A4 portrait sheet in the paginated artifact. Only page 1 carries the h1. */
function PaperPage({
  index,
  total,
  course,
  title,
  meta = [],
  titleField,
  children,
}: {
  index: number;
  total: number;
  course: string;
  title: string;
  meta?: string[];
  titleField?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="pa-doc-page pa-paper-page">
      <div className="pa-paper-meta">
        <span className="pa-paper-course">{course || "Untitled assignment"}</span>
        <span className="pa-paper-folio">{"Page " + index + " of " + total}</span>
      </div>
      <header className="mb-6 border-b border-neutral-200 pb-5">
        <p className="pa-doc-kicker">{course || "Assignment"}</p>
        {index === 1 ? (
          <h1 className="text-2xl leading-tight font-semibold text-neutral-900">{title}</h1>
        ) : (
          <p className="text-lg leading-tight font-semibold text-neutral-900">{title}</p>
        )}
        {meta.length ? <p className="mt-1 text-sm text-neutral-500">{meta.join(" - ")}</p> : null}
        {titleField}
      </header>
      <div className="space-y-6">{children}</div>
    </section>
  );
}

function EnhanceBubble({
  assignmentId,
  section,
  label,
  onApplied,
}: {
  assignmentId: string;
  section: string;
  label: string;
  onApplied: (result: RefineResponse) => void;
}) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState("");
  const [error, setError] = useState("");

  async function send() {
    const instruction = message.trim();
    if (!instruction) {
      setError("Describe the change you want first.");
      return;
    }
    setBusy(true);
    setError("");
    setReply("");
    try {
      const data = await pa<RefineResponse>("/assignments/" + assignmentId + "/assist", {
        method: "POST",
        body: JSON.stringify({
          message: "In the " + label + " section: " + instruction,
          mode: "refine",
        }),
      });
      const changed = changedNames(data?.changed_sections);
      const said =
        textOf(data?.reply) ||
        (data?.changed === false ? "No change was needed." : "The artifact was updated.");
      setReply(changed.length ? said + " Changed: " + changed.join(", ") + "." : said);
      setMessage("");
      onApplied(data ?? {});
    } catch (err) {
      setReply("");
      setError(describeError(err, "That change could not be made."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next && !busy) setError("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          data-enhance-trigger="true"
          aria-label={"Enhance " + label}
          className="text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900"
        >
          <Sparkles className="h-3.5 w-3.5" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium">Enhance: {label}</p>
            <p className="text-muted-foreground text-xs">
              The AI edits this artifact. Nothing is published.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={"enhance-" + section} className="sr-only">
              Change for {label}
            </Label>
            <Textarea
              id={"enhance-" + section}
              rows={3}
              value={message}
              disabled={busy}
              placeholder="e.g. tighten this to two paragraphs"
              onChange={(event) => setMessage(event.target.value)}
            />
          </div>
          {error ? (
            <p role="alert" className="text-destructive text-xs">
              {error}
            </p>
          ) : null}
          {reply ? (
            <p role="status" className="bg-muted/60 rounded-md p-2 text-xs">
              {reply}
            </p>
          ) : null}
          <div className="flex items-center justify-end gap-2">
            <Button type="button" size="sm" onClick={() => void send()} disabled={busy}>
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              {busy ? "Enhancing..." : "Enhance"}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
const REVIEW_ROLE_LABELS: Record<string, string> = {
  alignment: "Alignment",
  brief: "Brief",
  rubric: "Rubric",
  chair: "Chair",
};

function reviewRoleLabel(role: string): string {
  const known = REVIEW_ROLE_LABELS[role];
  if (known) return known;
  const fallback = role.replaceAll("_", " ").trim();
  return fallback ? fallback.charAt(0).toUpperCase() + fallback.slice(1) : "Council";
}

/** The four council roles each get a distinct avatar so a reader can scan the panel. */
function ReviewerAvatar({ role }: { role: string }) {
  const Icon =
    role === "alignment"
      ? Target
      : role === "brief"
        ? FileText
        : role === "rubric"
          ? ListChecks
          : Gavel;
  const tone =
    role === "alignment"
      ? "border-blue-200 bg-blue-100 text-blue-700"
      : role === "brief"
        ? "border-violet-200 bg-violet-100 text-violet-700"
        : role === "rubric"
          ? "border-emerald-200 bg-emerald-100 text-emerald-700"
          : "border-amber-200 bg-amber-100 text-amber-700";
  return (
    <span
      aria-hidden="true"
      className={"mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border " + tone}
    >
      <Icon className="h-3.5 w-3.5" />
    </span>
  );
}

const REVIEW_SEVERITY_TONE: Record<string, string> = {
  high: "border-transparent bg-red-100 text-red-800",
  medium: "border-transparent bg-amber-100 text-amber-800",
  low: "border-transparent bg-blue-100 text-blue-800",
  info: "border-transparent bg-slate-100 text-slate-700",
};

function reviewSeverityTone(severity?: string): string {
  return REVIEW_SEVERITY_TONE[(severity ?? "").toLowerCase()] ?? REVIEW_SEVERITY_TONE.info ?? "";
}

/** Issues carry a slide or a section: a number becomes "Section n", a name is shown as-is. */
function reviewLocation(issue: AssignmentReviewIssue): string {
  const value = issue.section ?? issue.slide;
  if (typeof value === "number") return "Section " + value;
  return (value ?? "").trim();
}

function groupReviewMessages(messages: AssignmentReviewMessage[]) {
  const groups: Array<{ role: string; messages: AssignmentReviewMessage[] }> = [];
  const byRole = new Map<string, { role: string; messages: AssignmentReviewMessage[] }>();
  for (const message of messages) {
    const role = message.role.trim().toLowerCase() || "chair";
    const group = byRole.get(role);
    if (group) {
      group.messages.push(message);
    } else {
      const created = { role, messages: [message] };
      byRole.set(role, created);
      groups.push(created);
    }
  }
  return groups;
}

/**
 * Read-only council verdict. It sits above the A4 pages and never publishes, approves,
 * or rewrites anything: the only action is asking the council to review again.
 */
function CouncilReviewPanel({
  review,
  busy,
  disabled,
  onReview,
}: {
  review?: AssignmentReview;
  busy: boolean;
  disabled: boolean;
  onReview: () => void;
}) {
  const issues = review?.issues ?? [];
  const strengths = review?.strengths ?? [];
  const groups = groupReviewMessages(review?.messages ?? []);
  const passed = review?.verdict === "pass";

  return (
    <section
      aria-label="Council review"
      className="bg-card mb-4 rounded-lg border p-4 print:hidden"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 className="text-sm font-semibold">Council review</h2>
          {review ? (
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                className={
                  passed
                    ? "border-transparent bg-green-100 text-green-800"
                    : "border-transparent bg-amber-100 text-amber-800"
                }
              >
                {passed ? "Passed" : "Needs revision"}
              </Badge>
              <span className="text-muted-foreground text-sm">{review.score}/100</span>
              <span className="text-muted-foreground text-sm">
                {issues.length} issue{issues.length === 1 ? "" : "s"}
              </span>
              {review.trace_url ? (
                <a
                  className="text-xs underline underline-offset-4"
                  href={review.trace_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Trace
                </a>
              ) : null}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">
              No council review yet. Review alignment, brief, and rubric before publishing.
            </p>
          )}
        </div>
        <Button type="button" size="sm" variant="outline" onClick={onReview} disabled={disabled}>
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <ShieldCheck className="h-3.5 w-3.5" />
          )}
          {busy ? "Reviewing..." : "Review with council"}
        </Button>
      </div>

      {review ? (
        <>
          {review.degraded ? (
            <p className="mt-3 text-xs text-amber-700">
              Degraded review: the council model was unavailable, so only deterministic checks ran.
            </p>
          ) : null}

          {groups.length ? (
            <div className="mt-3 space-y-3">
              {groups.map((group) => (
                <div key={group.role} className="flex items-start gap-2">
                  <ReviewerAvatar role={group.role} />
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-muted-foreground text-[11px] font-semibold tracking-wide uppercase">
                      {reviewRoleLabel(group.role)}
                    </p>
                    {group.messages.map((message, index) => (
                      <p
                        key={group.role + "-" + index}
                        className="bg-background/60 rounded-md border px-2 py-1.5 text-sm leading-relaxed"
                      >
                        {message.text}
                      </p>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="mt-3 space-y-2">
            <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              Issues
            </p>
            {issues.length === 0 ? (
              <p className="text-muted-foreground text-sm">No issues found.</p>
            ) : (
              <ul className="space-y-2">
                {issues.map((issue, index) => {
                  const location = reviewLocation(issue);
                  return (
                    <li key={"issue-" + index} className="bg-background/60 rounded-md border p-2">
                      <div className="flex flex-wrap items-start gap-2">
                        <Badge className={reviewSeverityTone(issue.severity)}>
                          {issue.severity || "info"}
                        </Badge>
                        {location ? (
                          <span className="text-muted-foreground text-xs font-medium">
                            {location}
                          </span>
                        ) : null}
                        {issue.reviewer ? (
                          <span className="text-muted-foreground text-xs">
                            {reviewRoleLabel(issue.reviewer)}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-sm">{issue.issue}</p>
                      {issue.fix ? (
                        <p className="text-muted-foreground mt-1 text-xs">Fix: {issue.fix}</p>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {strengths.length ? (
            <div className="mt-3">
              <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                Strengths
              </p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-neutral-700">
                {strengths.map((strength, index) => (
                  <li key={"strength-" + index}>{strength}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <p className="text-muted-foreground mt-3 text-xs">
            Advisory only: the council never publishes or rewrites the assignment.
          </p>
        </>
      ) : null}
    </section>
  );
}
type Busy = "" | "save" | "approve" | "publish" | "review";

export default function AssignmentArtifactPage() {
  const params = useParams();
  const rawId = params?.id;
  const assignmentId = Array.isArray(rawId) ? (rawId[0] ?? "") : (rawId ?? "");

  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<Busy>("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Criterion[]>([]);
  const [draftDoc, setDraftDoc] = useState<DocumentDraft>(EMPTY_DOCUMENT);
  const [draftTitle, setDraftTitle] = useState("");
  const [pendingSection, setPendingSection] = useState<string | null>(null);

  const load = useCallback(
    async (showLoading = true) => {
      if (!assignmentId) {
        setLoading(false);
        setLoadError("This page needs an assignment id.");
        return;
      }
      if (showLoading) setLoading(true);
      try {
        const data = await pa<unknown>("/assignments/" + assignmentId + "/artifact");
        setArtifact(asArtifact(data));
        setLoadError("");
      } catch (err) {
        setArtifact(null);
        setLoadError(describeError(err, "Could not open this assignment."));
      } finally {
        setLoading(false);
      }
    },
    [assignmentId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // A section pencil opens edit mode and puts the cursor on that section's first control.
  useEffect(() => {
    if (!editing || !pendingSection) return;
    const container = document.getElementById("doc-section-" + pendingSection);
    if (!container) {
      setPendingSection(null);
      return;
    }
    const handle = window.setTimeout(() => {
      container.scrollIntoView({ behavior: "smooth", block: "start" });
      const first = container.querySelector<HTMLElement>(
        "input:not([type='hidden']), textarea, select, [data-enhance-trigger]",
      );
      first?.focus({ preventScroll: true });
      setPendingSection(null);
    }, 0);
    return () => window.clearTimeout(handle);
  }, [editing, pendingSection]);

  const assignment = artifact?.assignment;
  const doc = artifact?.document ?? {};
  const rubric = artifact?.rubric;
  const details = recordOf(doc.class_details);
  const liveCriteria = rubric?.criteria ?? [];
  const criteria = editing ? draft : liveCriteria;
  const total = criteria.reduce(
    (sum, row) => sum + (Number.isFinite(row.weight) ? row.weight : 0),
    0,
  );
  const assessmentId = rubric?.id ?? "";
  const approved = rubric?.status === "approved";
  const status = textOf(assignment?.status) || "draft";
  const published = status.toLowerCase() === "published";
  const number = textOf(assignment?.number);
  const storedAssessment = textOf(details.assessment);
  const storedTitle = textOf(assignment?.title);
  const safeTitle = uuidLike(storedTitle) ? "" : storedTitle;
  const title = storedAssessment || safeTitle || (number ? "Assignment " + number : "Assignment");
  const course =
    textOf(assignment?.course_code) ||
    textOf(assignment?.course_title) ||
    textOf(assignment?.course) ||
    textOf(details.course);

  // Edit mode reads the draft, so a keystroke never mutates the artifact the server sent.
  const liveDocument = normalizeDocument(doc);
  const view = editing ? draftDoc : liveDocument;
  // The heading prefers the live assessment name, but never a raw id.
  const liveAssessment = textOf(view.class_details.assessment);
  const displayTitle = liveAssessment && !uuidLike(liveAssessment) ? liveAssessment : title;

  const classRows = CLASS_FIELDS.map((field) => ({
    key: field.key,
    label: field.label,
    value: view.class_details[field.key] ?? "",
  }));
  const extraRows = Object.keys(view.class_details)
    .filter(
      (key) =>
        !CLASS_FIELDS.some((field) => field.key === key) &&
        (editing || Boolean(view.class_details[key])),
    )
    .map((key) => ({
      key,
      label: key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()),
      value: view.class_details[key] ?? "",
    }));
  const rows = [...classRows, ...extraRows];
  const overview = view.overview;
  const problemChoices = view.problem_choices;
  const deliverables = view.deliverables;
  const reportSections = view.report_sections;
  const reportPageOne = reportSections.slice(0, 6);
  const reportPageTwo = reportSections.slice(6);

  function startEdit(section?: string) {
    setActionError("");
    setNotice("");
    setDraftDoc(normalizeDocument(doc));
    setDraftTitle(safeTitle);
    setDraft(liveCriteria.map(cloneCriterion));
    setEditing(true);
    setPendingSection(section ?? null);
  }

  function cancelEdit() {
    setDraft([]);
    setDraftDoc(EMPTY_DOCUMENT);
    setDraftTitle("");
    setEditing(false);
    setPendingSection(null);
    setActionError("");
  }

  function setDetail(key: string, value: string) {
    setDraftDoc((current) => ({
      ...current,
      class_details: { ...current.class_details, [key]: value },
    }));
  }

  function setOverview(index: number, value: string) {
    setDraftDoc((current) => ({
      ...current,
      overview: current.overview.map((row, position) => (position === index ? value : row)),
    }));
  }

  function addOverview() {
    setDraftDoc((current) => ({ ...current, overview: [...current.overview, ""] }));
  }

  function removeOverview(index: number) {
    setDraftDoc((current) => ({
      ...current,
      overview: current.overview.filter((_, position) => position !== index),
    }));
  }

  function setProblem(index: number, patch: Partial<ProblemChoice>) {
    setDraftDoc((current) => ({
      ...current,
      problem_choices: current.problem_choices.map((row, position) =>
        position === index ? { ...row, ...patch } : row,
      ),
    }));
  }

  function addProblem() {
    setDraftDoc((current) => ({
      ...current,
      problem_choices: [...current.problem_choices, { problem: "", description: "" }],
    }));
  }

  function removeProblem(index: number) {
    setDraftDoc((current) => ({
      ...current,
      problem_choices: current.problem_choices.filter((_, position) => position !== index),
    }));
  }

  function setDeliverable(index: number, patch: Partial<DeliverableRow>) {
    setDraftDoc((current) => ({
      ...current,
      deliverables: current.deliverables.map((row, position) =>
        position === index ? { ...row, ...patch } : row,
      ),
    }));
  }

  function addDeliverable() {
    setDraftDoc((current) => ({
      ...current,
      deliverables: [...current.deliverables, { title: "", description: "" }],
    }));
  }

  function removeDeliverable(index: number) {
    setDraftDoc((current) => ({
      ...current,
      deliverables: current.deliverables.filter((_, position) => position !== index),
    }));
  }

  /** Report sections keep their number: the template is fixed at eleven rows. */
  function setReportSection(
    index: number,
    patch: Partial<Pick<ReportSection, "section" | "guidelines">>,
  ) {
    setDraftDoc((current) => ({
      ...current,
      report_sections: current.report_sections.map((row, position) =>
        position === index ? { ...row, ...patch } : row,
      ),
    }));
  }

  function updateCriterion(index: number, patch: Partial<Criterion>) {
    setDraft((current) =>
      current.map((row, position) => (position === index ? { ...row, ...patch } : row)),
    );
  }

  function updateLevel(index: number, level: LevelKey, value: string) {
    setDraft((current) =>
      current.map((row, position) =>
        position === index ? { ...row, levels: { ...row.levels, [level]: value } } : row,
      ),
    );
  }

  function addCriterion() {
    setDraft((current) => [
      ...current,
      {
        name: "",
        weight: 0,
        levels: { advanced: "", proficient: "", developing: "", beginning: "" },
      },
    ]);
  }

  function removeCriterion(index: number) {
    setDraft((current) => current.filter((_, position) => position !== index));
  }

  async function putRubric(): Promise<unknown> {
    // Outside edit mode there is no draft, so save the rubric that is on screen.
    const payload = (editing ? draft : liveCriteria).map(payloadCriterion);
    return pa<unknown>("/assessments/" + assessmentId + "/rubric", {
      method: "PUT",
      body: JSON.stringify({ brief: rubric?.brief ?? "", criteria: payload }),
    });
  }

  /**
   * Toolbar Save. The document and the rubric live behind two endpoints, so both are
   * flushed. A refused document keeps the draft and edit mode, so nothing is lost.
   */
  async function saveAll(quiet = false): Promise<boolean> {
    if (!assignmentId) return false;
    setBusy("save");
    setActionError("");
    setNotice("");

    const nextDocument = serializeDocument(draftDoc);
    const body: Record<string, unknown> = { document: nextDocument };
    const nextTitle = draftTitle.trim();
    if (nextTitle && nextTitle !== safeTitle) body.title = nextTitle;

    try {
      const result = await pa<unknown>("/assignments/" + assignmentId, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      const returnedDocument = recordOf(result).document;
      setArtifact((current) => {
        if (!current) return current;
        const merged = mergeArtifact(current, result);
        return returnedDocument ? merged : { ...merged, document: nextDocument };
      });
    } catch (err) {
      setActionError(describeError(err, "The assignment could not be saved."));
      setBusy("");
      return false;
    }

    // Only write the rubric when its cells changed, so a document save does not churn
    // the rubric version or its history.
    const rubricChanged =
      JSON.stringify(draft.map(payloadCriterion)) !==
      JSON.stringify(liveCriteria.map(payloadCriterion));
    if (assessmentId && rubricChanged) {
      try {
        const saved = await putRubric();
        setArtifact((current) =>
          current ? { ...current, rubric: asRubric(saved, current.assignment) } : current,
        );
      } catch (err) {
        setActionError(
          "The document was saved, but the rubric was not: " +
            describeError(err, "the rubric endpoint refused it."),
        );
        setBusy("");
        return false;
      }
    }

    setDraft([]);
    setDraftDoc(EMPTY_DOCUMENT);
    setDraftTitle("");
    setEditing(false);
    setBusy("");
    if (!quiet) setNotice("Assignment saved.");
    return true;
  }

  async function saveRubric(quiet = false): Promise<boolean> {
    if (!assessmentId) {
      setActionError(
        "The artifact did not include an assessment id, so the rubric cannot be saved.",
      );
      return false;
    }
    setBusy("save");
    setActionError("");
    setNotice("");
    try {
      const saved = await putRubric();
      setArtifact((current) =>
        current ? { ...current, rubric: asRubric(saved, current.assignment) } : current,
      );
      setDraft([]);
      setDraftDoc(EMPTY_DOCUMENT);
      setEditing(false);
      if (!quiet) setNotice("Rubric saved.");
      return true;
    } catch (err) {
      setActionError(describeError(err, "The rubric could not be saved."));
      return false;
    } finally {
      setBusy("");
    }
  }

  async function approveRubric() {
    if (!assessmentId) {
      setActionError(
        "The artifact did not include an assessment id, so the rubric cannot be approved.",
      );
      return;
    }
    setActionError("");
    setNotice("");
    // Approval reads the stored rubric, so unsaved document and rubric cells are flushed first.
    if (editing) {
      const saved = await saveAll(true);
      if (!saved) return;
    }
    setBusy("approve");
    try {
      const approvedRow = await pa<unknown>("/assessments/" + assessmentId + "/approve", {
        method: "POST",
      });
      setArtifact((current) =>
        current ? { ...current, rubric: asRubric(approvedRow, current.assignment) } : current,
      );
      setNotice("Rubric " + (textOf(recordOf(approvedRow).status) || "approved") + ".");
    } catch (err) {
      setActionError(describeError(err, "The rubric could not be approved."));
    } finally {
      setBusy("");
    }
  }

  async function publish() {
    setBusy("publish");
    setActionError("");
    setNotice("");
    try {
      const result = recordOf(
        await pa<unknown>("/assignments/" + assignmentId + "/finish", { method: "POST" }),
      );
      if (Object.keys(recordOf(result.assignment)).length) {
        setArtifact((current) => (current ? mergeArtifact(current, result) : current));
      } else {
        await load();
      }
      const finished = textOf(recordOf(result.assignment).status) || textOf(result.status);
      setNotice("Published." + (finished ? " Status: " + finished + "." : ""));
    } catch (err) {
      setActionError(describeError(err, "The assignment could not be published."));
    } finally {
      setBusy("");
    }
  }

  /** Advisory only: it stores the council verdict but never publishes or rewrites. */
  async function runCouncilReview() {
    if (!assignmentId) return;
    setBusy("review");
    setActionError("");
    setNotice("");
    try {
      const result = recordOf(
        await pa<unknown>("/assignments/" + assignmentId + "/review", { method: "POST" }),
      );
      const nextReview = asReview(result.review);
      if (nextReview) {
        if (!nextReview.trace_url && typeof result.trace_url === "string") {
          nextReview.trace_url = result.trace_url;
        }
        setArtifact((current) => (current ? { ...current, review: nextReview } : current));
      }
      // The review is persisted server-side, so read the artifact back for the full row.
      await load(false);
      setNotice("Council review updated.");
    } catch (err) {
      setActionError(describeError(err, "The council could not review this assignment."));
    } finally {
      setBusy("");
    }
  }

  function applyRefine(data: RefineResponse) {
    setArtifact((current) => (current ? mergeArtifact(current, data) : current));
  }

  /** Renders one half of the eleven report rows; offset keeps edit indexes global. */
  function renderReportTable(rows: ReportSection[], offset: number) {
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">#</TableHead>
            <TableHead className="w-56">Section</TableHead>
            <TableHead>Guidelines</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, position) => {
            const index = offset + position;
            return (
              <TableRow key={index}>
                <TableCell className="align-top text-neutral-500">
                  {row.number || index + 1}
                </TableCell>
                <TableCell className="align-top font-medium text-neutral-900">
                  {editing ? (
                    <Input
                      aria-label={"Report section " + (index + 1) + " name"}
                      value={row.section}
                      onChange={(event) => setReportSection(index, { section: event.target.value })}
                    />
                  ) : (
                    row.section || "-"
                  )}
                </TableCell>
                <TableCell className="align-top text-sm leading-6 text-neutral-700">
                  {editing ? (
                    <Textarea
                      rows={2}
                      aria-label={"Report section " + (index + 1) + " guidelines"}
                      value={row.guidelines}
                      onChange={(event) =>
                        setReportSection(index, { guidelines: event.target.value })
                      }
                    />
                  ) : (
                    row.guidelines || "-"
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    );
  }
  const due = textOf(assignment?.due) || textOf(details.report_due);
  const weightText = textOf(assignment?.weight) || textOf(details.weight);
  const weightLabel = weightText ? (weightText.includes("%") ? weightText : weightText + "%") : "";
  const meta = [number ? "Assignment " + number : "", weightLabel, due ? "Due " + due : ""].filter(
    Boolean,
  );

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-[820px] space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-[560px] w-full" />
      </div>
    );
  }

  if (!artifact) {
    return (
      <div className="mx-auto w-full max-w-[820px] space-y-3">
        <Button asChild variant="ghost" size="sm">
          <Link href="/assignments">
            <ArrowLeft className="h-4 w-4" />
            All assignments
          </Link>
        </Button>
        <Alert variant="destructive">
          <AlertTitle>Could not open this assignment</AlertTitle>
          <AlertDescription>{loadError || "The artifact was empty."}</AlertDescription>
        </Alert>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[820px]">
      <div className="mb-2">
        <Button asChild variant="ghost" size="sm">
          <Link href="/assignments">
            <ArrowLeft className="h-4 w-4" />
            All assignments
          </Link>
        </Button>
      </div>

      <div className="bg-background/95 supports-[backdrop-filter]:bg-background/80 sticky top-14 z-30 -mx-1 mb-4 border-b px-1 py-2 backdrop-blur print:hidden">
        <div className="flex flex-wrap items-center gap-2">
          <div className="mr-auto min-w-0">
            <p className="text-muted-foreground truncate text-[11px] font-medium tracking-wide uppercase">
              {course || (number ? "Assignment " + number : "Assignment")}
            </p>
            <p className="truncate text-sm font-semibold">{title}</p>
          </div>
          <Badge variant={published ? "default" : "secondary"}>{status}</Badge>
          <div className="flex flex-wrap items-center gap-1.5">
            {editing ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={cancelEdit}
                  disabled={busy !== ""}
                >
                  <X className="h-3.5 w-3.5" />
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void saveAll()}
                  disabled={busy !== ""}
                >
                  {busy === "save" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  {busy === "save" ? "Saving..." : "Save"}
                </Button>
              </>
            ) : (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => startEdit()}
                  disabled={busy !== ""}
                >
                  <Pencil className="h-3.5 w-3.5" />
                  Edit
                </Button>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="inline-flex">
                      <Button type="button" variant="outline" size="sm" disabled>
                        <Save className="h-3.5 w-3.5" />
                        Save
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>Enter edit mode to make changes</TooltipContent>
                </Tooltip>
              </>
            )}
            <Button asChild variant="outline" size="sm">
              <a href={"/api/profassist/assignments/" + assignmentId + "/document?kind=pdf"}>
                <Download className="h-3.5 w-3.5" />
                Download PDF
              </a>
            </Button>
            <Button asChild variant="outline" size="sm">
              <a href={"/api/profassist/assignments/" + assignmentId + "/document?kind=docx"}>
                <Download className="h-3.5 w-3.5" />
                Download DOCX
              </a>
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void publish()}
              disabled={editing || busy !== "" || published}
              title={
                editing
                  ? "Save or cancel your edits first"
                  : published
                    ? "This assignment is already published"
                    : "Publish this assignment"
              }
            >
              {busy === "publish" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="h-3.5 w-3.5" />
              )}
              {busy === "publish" ? "Publishing..." : "Publish"}
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href={"/assignments?id=" + assignmentId + "&tab=groups"}>
                <Users className="h-3.5 w-3.5" />
                Set up groups
              </Link>
            </Button>
          </div>
        </div>
        {actionError ? (
          <p role="alert" className="text-destructive mt-2 text-xs">
            {actionError}
          </p>
        ) : null}
        {notice ? (
          <p role="status" className="mt-2 text-xs text-emerald-700">
            {notice}
          </p>
        ) : null}
      </div>

      <CouncilReviewPanel
        review={artifact.review}
        busy={busy === "review"}
        disabled={busy !== ""}
        onReview={() => void runCouncilReview()}
      />

      <div className="pa-artifact-scroll">
        <PaperPage
          index={1}
          total={5}
          course={course}
          title={displayTitle}
          meta={meta}
          titleField={
            editing ? (
              <div className="mt-3 max-w-md space-y-1.5 print:hidden">
                <Label htmlFor="assignment-title">Assignment title</Label>
                <Input
                  id="assignment-title"
                  value={draftTitle}
                  onChange={(event) => setDraftTitle(event.target.value)}
                />
              </div>
            ) : null
          }
        >
          <SectionShell
            sectionKey="class_details"
            title="Class details"
            onEdit={() => startEdit("class_details")}
            enhance={
              <EnhanceBubble
                assignmentId={assignmentId}
                section="class_details"
                label="Class details"
                onApplied={applyRefine}
              />
            }
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-48">Field</TableHead>
                  <TableHead>Value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.key}>
                    <TableHead scope="row" className="font-medium text-neutral-600">
                      {row.label}
                    </TableHead>
                    <TableCell className="align-top text-neutral-900">
                      {editing ? (
                        <Input
                          aria-label={row.label}
                          value={row.value}
                          onChange={(event) => setDetail(row.key, event.target.value)}
                        />
                      ) : (
                        row.value || "-"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SectionShell>

          <SectionShell
            sectionKey="overview"
            title="Overview"
            onEdit={() => startEdit("overview")}
            enhance={
              <EnhanceBubble
                assignmentId={assignmentId}
                section="overview"
                label="Overview"
                onApplied={applyRefine}
              />
            }
          >
            {editing ? (
              <div className="space-y-3">
                {overview.map((paragraph, index) => (
                  <div key={index} className="flex items-start gap-2">
                    <Textarea
                      rows={3}
                      aria-label={"Overview paragraph " + (index + 1)}
                      value={paragraph}
                      onChange={(event) => setOverview(index, event.target.value)}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label={"Remove overview paragraph " + (index + 1)}
                      onClick={() => removeOverview(index)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
                {overview.length === 0 ? (
                  <p className="text-sm text-neutral-500">No overview yet.</p>
                ) : null}
                <Button type="button" variant="outline" size="sm" onClick={addOverview}>
                  <Plus className="h-3.5 w-3.5" />
                  Add paragraph
                </Button>
              </div>
            ) : overview.length ? (
              <div className="space-y-2">
                {overview.map((paragraph, index) => (
                  <p key={index} className="text-sm leading-6 text-neutral-800">
                    {paragraph}
                  </p>
                ))}
              </div>
            ) : (
              <p className="text-sm text-neutral-500">No overview yet.</p>
            )}
          </SectionShell>
        </PaperPage>

        <PaperPage index={2} total={5} course={course} title={displayTitle}>
          <SectionShell
            sectionKey="problem_choices"
            title="Choosing your problem"
            onEdit={() => startEdit("problem_choices")}
            enhance={
              <EnhanceBubble
                assignmentId={assignmentId}
                section="problem_choices"
                label="Problem choices"
                onApplied={applyRefine}
              />
            }
          >
            <div className="space-y-2">
              {problemChoices.length ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-56">Problem</TableHead>
                      <TableHead>Description</TableHead>
                      {editing ? (
                        <TableHead className="w-10">
                          <span className="sr-only">Remove</span>
                        </TableHead>
                      ) : null}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {problemChoices.map((row, index) => (
                      <TableRow key={index}>
                        <TableCell className="align-top font-medium text-neutral-900">
                          {editing ? (
                            <Input
                              aria-label={"Problem " + (index + 1)}
                              value={row.problem}
                              onChange={(event) =>
                                setProblem(index, { problem: event.target.value })
                              }
                            />
                          ) : (
                            row.problem || "-"
                          )}
                        </TableCell>
                        <TableCell className="align-top text-neutral-700">
                          {editing ? (
                            <Textarea
                              rows={2}
                              aria-label={"Problem " + (index + 1) + " description"}
                              value={row.description}
                              onChange={(event) =>
                                setProblem(index, { description: event.target.value })
                              }
                            />
                          ) : (
                            row.description || "-"
                          )}
                        </TableCell>
                        {editing ? (
                          <TableCell className="align-top">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              aria-label={"Remove problem " + (index + 1)}
                              onClick={() => removeProblem(index)}
                            >
                              <X className="h-3.5 w-3.5" />
                            </Button>
                          </TableCell>
                        ) : null}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-sm text-neutral-500">No problem choices yet.</p>
              )}
              {editing ? (
                <Button type="button" variant="outline" size="sm" onClick={addProblem}>
                  <Plus className="h-3.5 w-3.5" />
                  Add problem
                </Button>
              ) : null}
            </div>
          </SectionShell>

          <SectionShell
            sectionKey="deliverables"
            title="Deliverables"
            onEdit={() => startEdit("deliverables")}
            enhance={
              <EnhanceBubble
                assignmentId={assignmentId}
                section="deliverables"
                label="Deliverables"
                onApplied={applyRefine}
              />
            }
          >
            <div className="space-y-2">
              {deliverables.length ? (
                editing ? (
                  <div className="space-y-3">
                    {deliverables.map((item, index) => (
                      <div
                        key={index}
                        className="space-y-1.5 rounded-lg border border-neutral-200 p-3"
                      >
                        <div className="flex items-start gap-2">
                          <Input
                            aria-label={"Deliverable " + (index + 1) + " title"}
                            value={item.title}
                            onChange={(event) =>
                              setDeliverable(index, { title: event.target.value })
                            }
                          />
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label={"Remove deliverable " + (index + 1)}
                            onClick={() => removeDeliverable(index)}
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                        <Textarea
                          rows={2}
                          aria-label={"Deliverable " + (index + 1) + " description"}
                          value={item.description}
                          onChange={(event) =>
                            setDeliverable(index, { description: event.target.value })
                          }
                        />
                      </div>
                    ))}
                  </div>
                ) : (
                  <ol className="list-decimal space-y-2 pl-5 text-sm leading-6 text-neutral-800">
                    {deliverables.map((item, index) => (
                      <li key={index}>
                        {item.title ? (
                          <strong className="font-semibold text-neutral-900">{item.title}: </strong>
                        ) : null}
                        {item.description || "-"}
                      </li>
                    ))}
                  </ol>
                )
              ) : (
                <p className="text-sm text-neutral-500">No deliverables yet.</p>
              )}
              {editing ? (
                <Button type="button" variant="outline" size="sm" onClick={addDeliverable}>
                  <Plus className="h-3.5 w-3.5" />
                  Add deliverable
                </Button>
              ) : null}
            </div>
          </SectionShell>
        </PaperPage>

        <PaperPage index={3} total={5} course={course} title={displayTitle}>
          <SectionShell
            sectionKey="report_sections"
            title="Technical report sections"
            onEdit={() => startEdit("report_sections")}
            enhance={
              <EnhanceBubble
                assignmentId={assignmentId}
                section="report_sections"
                label="Report sections"
                onApplied={applyRefine}
              />
            }
          >
            {reportPageOne.length ? (
              <>
                {renderReportTable(reportPageOne, 0)}
                <p className="mt-2 text-xs text-neutral-500">
                  {reportSections.length} report{" "}
                  {reportSections.length === 1 ? "section" : "sections"}
                </p>
              </>
            ) : (
              <p className="text-sm text-neutral-500">No report sections yet.</p>
            )}
          </SectionShell>
        </PaperPage>

        <PaperPage index={4} total={5} course={course} title={displayTitle}>
          <SectionShell
            sectionKey="report_sections_more"
            title="Technical report sections (continued)"
            onEdit={() => startEdit("report_sections_more")}
            enhance={
              <EnhanceBubble
                assignmentId={assignmentId}
                section="report_sections"
                label="Report sections"
                onApplied={applyRefine}
              />
            }
          >
            {reportPageTwo.length ? (
              renderReportTable(reportPageTwo, 6)
            ) : (
              <p className="text-sm text-neutral-500">No more report sections.</p>
            )}
          </SectionShell>
        </PaperPage>

        <PaperPage index={5} total={5} course={course} title={displayTitle}>
          <SectionShell
            sectionKey="rubric"
            title="Rubric"
            onEdit={() => startEdit("rubric")}
            enhance={
              <EnhanceBubble
                assignmentId={assignmentId}
                section="rubric"
                label="Rubric"
                onApplied={applyRefine}
              />
            }
          >
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={criteria.length > 0 && total !== 100 ? "destructive" : "secondary"}>
                  Total {total}%
                </Badge>
                {approved ? <Badge variant="default">Approved</Badge> : null}
                {editing ? (
                  <span className="text-xs text-neutral-500">
                    Edit the cells, then Save. Weights are percentages of 100.
                  </span>
                ) : null}
              </div>
              {criteria.length > 0 && total !== 100 ? (
                <p role="alert" className="text-xs font-medium text-red-700">
                  Weights total {total}%, not 100%. Adjust the weights before you approve.
                </p>
              ) : null}
              {criteria.length ? (
                <div className="space-y-3">
                  {criteria.map((row, index) => (
                    <article
                      key={row.id || index}
                      className="min-w-0 space-y-2 rounded-lg border border-neutral-200 p-3 print:break-inside-avoid"
                    >
                      <header className="flex flex-wrap items-start justify-between gap-2">
                        {editing ? (
                          <div className="min-w-0 flex-1">
                            <Input
                              aria-label={"Criterion " + (index + 1) + " name"}
                              placeholder="Criterion name"
                              value={row.name}
                              onChange={(event) =>
                                updateCriterion(index, { name: event.target.value })
                              }
                            />
                          </div>
                        ) : (
                          <h3 className="min-w-0 flex-1 text-sm font-semibold break-words text-neutral-900">
                            {row.name || "Untitled criterion"}
                          </h3>
                        )}
                        <div className="flex shrink-0 items-center gap-1.5">
                          {editing ? (
                            <>
                              <Input
                                type="number"
                                min={0}
                                aria-label={"Weight for criterion " + (index + 1)}
                                className="w-20"
                                value={String(row.weight)}
                                onChange={(event) =>
                                  updateCriterion(index, { weight: weightOf(event.target.value) })
                                }
                              />
                              <span className="text-xs text-neutral-500">%</span>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                aria-label={"Remove criterion " + (index + 1)}
                                onClick={() => removeCriterion(index)}
                              >
                                <X className="h-3.5 w-3.5" />
                              </Button>
                            </>
                          ) : (
                            <Badge variant="secondary">{row.weight}%</Badge>
                          )}
                        </div>
                      </header>
                      <div className="grid min-w-0 gap-2 sm:grid-cols-2 print:grid-cols-2">
                        {LEVELS.map((level) => (
                          <div key={level} className="min-w-0 rounded-md bg-neutral-50 p-2">
                            <p className="mb-1 text-[11px] font-semibold tracking-wide text-neutral-500 uppercase">
                              {LEVEL_LABELS[level]}
                            </p>
                            {editing ? (
                              <Textarea
                                rows={2}
                                aria-label={LEVEL_LABELS[level] + " for criterion " + (index + 1)}
                                className="min-h-14 text-xs"
                                value={row.levels[level]}
                                onChange={(event) => updateLevel(index, level, event.target.value)}
                              />
                            ) : (
                              <p className="text-xs leading-5 break-words text-neutral-700">
                                {row.levels[level] || "-"}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-neutral-500">
                  No rubric criteria yet. Enter edit mode to add the first criterion.
                </p>
              )}
              <div className="flex flex-wrap items-center gap-2 print:hidden">
                {editing ? (
                  <Button type="button" variant="outline" size="sm" onClick={addCriterion}>
                    <Plus className="h-3.5 w-3.5" />
                    Add criterion
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void (editing ? saveAll() : saveRubric())}
                  disabled={busy !== "" || approved}
                  title={
                    approved
                      ? "Approved rubrics stay as you approved them"
                      : editing
                        ? "Save the document and the rubric"
                        : "Save the rubric"
                  }
                >
                  {busy === "save" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  {busy === "save" ? "Saving..." : editing ? "Save all" : "Save rubric"}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void approveRubric()}
                  disabled={busy !== "" || approved}
                  title={approved ? "This rubric is approved" : "Approve the rubric for grading"}
                >
                  {busy === "approve" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Check className="h-3.5 w-3.5" />
                  )}
                  {busy === "approve" ? "Approving..." : approved ? "Approved" : "Approve rubric"}
                </Button>
              </div>
            </div>
          </SectionShell>
        </PaperPage>
      </div>
    </div>
  );
}
