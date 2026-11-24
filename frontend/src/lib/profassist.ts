export class ProfassistError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function pa<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body && !isForm && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/profassist${path}`, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* empty or binary */
    }
    throw new ProfassistError(detail, response.status);
  }
  const type = response.headers.get("content-type") || "";
  if (!type.includes("json")) {
    return (await response.blob()) as T;
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

export interface Course {
  id: string;
  code: string;
  title: string;
  term: string;
}

export async function firstCourse(): Promise<Course | null> {
  const data = await pa<{ items: Course[] }>("/courses");
  return data.items[0] ?? null;
}

export type BadgeTone = "red" | "green" | "blue" | "amber" | "violet" | "slate";

/** Tailwind classes for the compact status tones shared across course files and memory. */
export const BADGE_TONE: Record<BadgeTone, string> = {
  red: "border-transparent bg-red-100 text-red-800 hover:bg-red-100",
  green: "border-transparent bg-green-100 text-green-800 hover:bg-green-100",
  blue: "border-transparent bg-blue-100 text-blue-800 hover:bg-blue-100",
  amber: "border-transparent bg-amber-100 text-amber-800 hover:bg-amber-100",
  violet: "border-transparent bg-violet-100 text-violet-800 hover:bg-violet-100",
  slate: "border-transparent bg-slate-100 text-slate-800 hover:bg-slate-100",
};

export type InsightStatus = "pending" | "processing" | "ready" | "failed" | "skipped";

/** The per-file comprehension label and tone, or null when the file has no status yet. */
export function insightBadge(status?: string | null): { label: string; tone: BadgeTone } | null {
  if (!status) return null;
  switch (status) {
    case "pending":
      return { label: "Queued", tone: "slate" };
    case "processing":
      return { label: "Reading\u2026", tone: "blue" };
    case "ready":
      return { label: "Read", tone: "green" };
    case "failed":
      return { label: "Could not read", tone: "red" };
    case "skipped":
      return { label: "Not read (privacy)", tone: "amber" };
    default:
      return { label: status.replace(/_/g, " "), tone: "slate" };
  }
}

const KIND_LABELS: Record<string, string> = {
  syllabus: "Syllabus",
  lecture: "Lecture",
  assignment: "Assignment",
  rubric: "Rubric",
  policy: "Policy",
  reading: "Reading",
  other: "Other",
};

export function kindLabel(kind?: string | null): string | null {
  if (!kind) return null;
  return KIND_LABELS[kind] ?? kind.charAt(0).toUpperCase() + kind.slice(1);
}

export function kindTone(kind?: string | null): BadgeTone {
  switch (kind) {
    case "syllabus":
      return "violet";
    case "lecture":
      return "blue";
    case "assignment":
      return "green";
    case "rubric":
      return "amber";
    case "policy":
      return "red";
    default:
      return "slate";
  }
}

export interface DossierTopic {
  name?: string;
  week?: number | null;
}

export interface DossierWeek {
  week?: number;
  topic?: string;
}

export interface DossierOutcome {
  code?: string;
  text?: string;
}

export interface DossierOutcomeMapping {
  clo?: string;
  plos?: string[];
}

export interface DossierOutcomes {
  clos?: DossierOutcome[];
  plos?: DossierOutcome[];
  mappings?: DossierOutcomeMapping[];
}

export interface DossierAssessment {
  name?: string;
  weight?: number | null;
  due?: string;
}

export interface DossierReading {
  citation?: string;
  week?: number | null;
}

export interface DossierKeyTerm {
  term?: string;
  definition?: string;
}

export interface DossierProvenance {
  field?: string;
  value?: string;
  filename?: string;
  chunk_ordinal?: number;
  kind?: string;
}

export interface DossierConflict {
  field?: string;
  winner?: string;
  loser?: string;
  reason?: string;
}

export interface CourseDossier {
  version?: number;
  summary?: string;
  topics?: DossierTopic[];
  weeks?: DossierWeek[];
  outcomes?: DossierOutcomes;
  assessments?: DossierAssessment[];
  readings?: DossierReading[];
  key_terms?: DossierKeyTerm[];
  grading_criteria?: Array<{ name?: string; levels?: unknown }>;
  provenance?: DossierProvenance[];
  conflicts?: DossierConflict[];
}

export interface MemoryMaterial {
  id: string;
  filename: string;
  status?: string;
  size?: number;
  scrubbed?: boolean;
  pii_report?: { quarantined?: boolean; uncertain?: string[] };
  insight_status?: string;
  kind?: string;
  tags?: string[];
  summary?: string;
  trace_url?: string;
}

export type SlideReviewSeverity = "high" | "medium" | "low" | "info";

export interface SlideReviewIssue {
  slide: number | string;
  severity: SlideReviewSeverity;
  issue: string;
  fix: string;
}

export interface SlideReview {
  verdict: "pass" | "revise";
  score: number;
  issues: SlideReviewIssue[];
  strengths: string[];
  checks?: unknown[];
  degraded?: boolean;
  trace_url?: string;
}

/** The council roles that review an assignment artifact, in panel order. */
export type AssignmentReviewRole = "alignment" | "brief" | "rubric" | "chair";

export interface AssignmentReviewIssue {
  reviewer?: string;
  severity?: string;
  /** Where the issue lives: a slide/section number or a free-text section name. */
  section?: string | number;
  slide?: string | number;
  issue: string;
  fix?: string;
}

export interface AssignmentReviewMessage {
  role: AssignmentReviewRole | string;
  text: string;
  severity?: string;
}

/** What GET /assignments/{id}/artifact returns under `review` (older rows: `document.review`). */
export interface AssignmentReview {
  verdict: "pass" | "revise";
  score: number;
  issues: AssignmentReviewIssue[];
  strengths: string[];
  messages: AssignmentReviewMessage[];
  trace_url?: string;
  degraded?: boolean;
}

export interface CourseMemory {
  dossier: CourseDossier | null;
  materials: MemoryMaterial[];
  slide_preferences?: string[];
  artifact_preferences?: string[];
}

export interface MemoryRebuildMaterial {
  material_id?: string;
  filename?: string;
  insight_status?: string;
  trace_url?: string;
}

export interface MemoryRebuildResult {
  status?: string;
  trace_url?: string;
  materials?: MemoryRebuildMaterial[];
}

export interface MaterialExtractResult {
  material?: { material_id?: string; filename?: string; insight_status?: string };
  dossier?: CourseDossier | null;
}

export type CollabRole = "creator" | "curriculum" | "evidence" | "design" | "chair" | "reviewer";

export interface CollabIssue {
  slide?: number | string;
  severity?: string;
  issue?: string;
  fix?: string;
}

/** One turn in the collaboration transcript. `role` is the council seat. */
export interface CollabReviewMessage {
  role: CollabRole | string;
  text: string;
  severity?: string;
  verdict?: string;
  score?: number;
}

export interface CollabReview {
  verdict?: "pass" | "revise" | string;
  score?: number;
  issues?: CollabIssue[];
  strengths?: string[];
  /** Full transcript on the final event, for clients that missed live messages. */
  messages?: CollabReviewMessage[];
  /** Enabled reviewer seats that spoke, in council order, chair last. */
  roles?: (CollabRole | string)[];
  trace_url?: string;
}

export interface CollabDeck {
  id: string;
  title?: string;
  week?: number;
  slides?: unknown[];
  review?: CollabReview | null;
}

/**
 * One Server-Sent Event from the Creator<->Council collaboration stream.
 * `reviewer` is the legacy name for the chair seat.
 * `paused` is a client-only event the studio bubbles up after a pause POST.
 */
export interface CollabEvent {
  type: "start" | "typing" | "message" | "final" | "error" | "paused" | string;
  creator?: string;
  reviewer?: string;
  role?: CollabRole;
  text?: string;
  kind?: string;
  severity?: string;
  verdict?: string;
  score?: number;
  issues?: CollabIssue[];
  deck?: CollabDeck;
  review?: CollabReview;
  paused?: boolean;
  trace_url?: string;
}

export type CouncilRoleKind = "creator" | "deterministic" | "llm" | "chair";

/** One seat in an admin-configured council. Order is the array order in `roles`. */
export interface CouncilRole {
  id?: string;
  role_key: string;
  label: string;
  kind: CouncilRoleKind;
  persona_prompt?: string | null;
  agent_key?: string | null;
  model?: string | null;
  position: number;
  enabled: boolean;
  custom: boolean;
  config?: Record<string, unknown> | null;
}

export interface Council {
  key: string;
  label: string;
  description: string;
  allow_custom: boolean;
  roles: CouncilRole[];
}

/** GET / PUT / reset all return this shape. */
export interface CouncilsView {
  councils: Council[];
  defaults?: Council[] | Record<string, Council> | null;
}
