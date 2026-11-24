"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  Input,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui";
import {
  ChevronDown,
  Download,
  Highlighter,
  Loader2,
  MessageSquarePlus,
  Pencil,
  Plug,
  Plus,
  Save,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { pa } from "@/components/profassist/bits";

export interface OutlineBasics {
  name?: string;
  code?: string;
  section?: string;
  credit_points?: string | number;
  year?: string | number;
  session?: string;
  duration?: string;
  prerequisites?: string;
  /** Template field. Stored outlines and the PDF/DOCX renderer still read `equivalent`. */
  equivalent_subjects?: string;
  equivalent?: string;
  delivery_mode?: string;
  [key: string]: unknown;
}

export interface OutlineLecture {
  day?: string;
  time?: string;
  location?: string;
  educator_name?: string;
  office?: string;
  email?: string;
  consultation?: string;
  [key: string]: unknown;
}

export interface OutlinePlo {
  code: string;
  text: string;
  [key: string]: unknown;
}

export interface OutlineClo {
  code: string;
  text: string;
  plos?: string[];
  bloom?: string;
  [key: string]: unknown;
}

export interface OutlineWeek {
  week?: string | number;
  topic?: string;
  lo_codes?: string[];
  session_type?: string;
  delivery?: string;
  assessment_note?: string;
  [key: string]: unknown;
}

/** One row of 5.1: a learning outcome and the assessments that measure it. */
export interface OutcomeMeasure {
  lo_code: string;
  measures: string;
  [key: string]: unknown;
}

export interface OutlinePolicy {
  key: string;
  title: string;
  body: string;
  [key: string]: unknown;
}

export interface RubricLevels {
  advanced?: string;
  proficient?: string;
  developing?: string;
  beginning?: string;
  [key: string]: unknown;
}

export interface RubricRow {
  name?: string;
  weight?: string | number;
  levels?: RubricLevels;
  [key: string]: unknown;
}

/** One assessment task as the assignment journey stores it in body.assessment_tasks[]. */
export interface AssessmentTask {
  number?: string;
  title?: string;
  name?: string;
  type?: string;
  group_individual?: string;
  weight?: string | number;
  total_marks?: string | number;
  due?: string;
  lo_codes?: string[];
  overview?: string | string[];
  deliverables?: string[];
  format?: string[];
  format_guidelines?: string[];
  rubric?: RubricRow[];
  assignment_id?: string;
  assessment_id?: string;
  [key: string]: unknown;
}

export interface GradeRow {
  grade: string;
  range: string;
  [key: string]: unknown;
}

export interface TurnitinField {
  label: string;
  value: string;
  [key: string]: unknown;
}

export interface AcademicIntegrity {
  intro?: string;
  turnitin?: string;
  turnitin_fields?: TurnitinField[];
  referencing?: string;
  rules?: string;
  [key: string]: unknown;
}

/** Policy documents and source materials arrive as objects from the backend. */
export interface OutlineDocumentEntry {
  title?: string;
  url?: string;
  text?: string;
  filename?: string;
  [key: string]: unknown;
}

export type OutlineDocumentValue = string | OutlineDocumentEntry;

export interface OutlineBody {
  basics?: OutlineBasics;
  lecture?: OutlineLecture;
  description?: string;
  program?: string;
  plos?: OutlinePlo[];
  clos?: OutlineClo[];
  weeks?: OutlineWeek[];
  readings?: string[];
  outcome_measures?: OutcomeMeasure[];
  /** Assignment-owned. The outline only reads this snapshot. */
  assessment_tasks?: AssessmentTask[];
  genai_intro?: string;
  genai?: string[];
  grades?: GradeRow[];
  satisfactory?: string[];
  satisfactory_note?: string;
  late_submission?: string;
  policy_intro?: string;
  /** Section 6. The backend step is `policies`, which writes body.policies. */
  policy_documents?: OutlineDocumentValue[];
  ssp?: string;
  academic_integrity?: AcademicIntegrity | string;
  attendance?: string;
  supplementary?: string;
  lecture_capture?: string;
  sustainability?: string;
  policies?: Array<OutlinePolicy | string>;
  /** Filenames the backend recorded as the source of this outline. */
  source_materials?: OutlineDocumentValue[];
  [key: string]: unknown;
}

export interface Outline {
  id: string;
  status: string;
  code: string;
  name: string;
  body: OutlineBody;
  pdf_ready: boolean;
  docx_ready?: boolean;
  instructions?: string;
  sources?: OutlineDocumentValue[];
  source_materials?: OutlineDocumentValue[];
  course_id?: string;
}

/** A saved highlight or note anchored to a section of the outline document. */
export interface OutlineAnnotation {
  id: string;
  sectionKey: string;
  sectionTitle: string;
  quote: string;
  note: string;
  color: string;
  createdAt: string;
}

interface SelectionTarget {
  x: number;
  y: number;
  below: boolean;
  quote: string;
  sectionKey: string;
  sectionTitle: string;
}

interface HighlightRegistryLike {
  set: (name: string, value: unknown) => void;
  delete: (name: string) => void;
}

type HighlightConstructor = new (...ranges: Range[]) => unknown;

function cssEscape(value: string) {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") return CSS.escape(value);
  return value.replace(/["\\]/g, "\\$&");
}

function rangeFromOffsets(nodes: Text[], start: number, end: number): Range | null {
  let position = 0;
  let startNode: Text | null = null;
  let startOffset = 0;
  let endNode: Text | null = null;
  let endOffset = 0;
  for (const node of nodes) {
    const length = node.nodeValue?.length ?? 0;
    if (!startNode && start >= position && start < position + length) {
      startNode = node;
      startOffset = start - position;
    }
    if (!endNode && end >= position && end <= position + length) {
      endNode = node;
      endOffset = end - position;
    }
    position += length;
    if (startNode && endNode) break;
  }
  if (!startNode || !endNode) return null;
  const range = document.createRange();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);
  return range;
}

/** Find every occurrence of a stored quote inside a section element. */
function findQuoteRanges(root: HTMLElement, quote: string): Range[] {
  const needle = quote.trim();
  if (!needle) return [];
  const ranges: Range[] = [];

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode() as Text | null;
  while (node) {
    const text = node.nodeValue ?? "";
    const index = text.indexOf(needle);
    if (index !== -1) {
      const range = document.createRange();
      range.setStart(node, index);
      range.setEnd(node, index + needle.length);
      ranges.push(range);
    }
    node = walker.nextNode() as Text | null;
  }
  if (ranges.length) return ranges;

  // Fallback for quotes that span several inline nodes.
  const nodes: Text[] = [];
  const second = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let current = second.nextNode() as Text | null;
  let combined = "";
  while (current) {
    nodes.push(current);
    combined += current.nodeValue ?? "";
    current = second.nextNode() as Text | null;
  }
  let from = combined.indexOf(needle);
  while (from !== -1) {
    const range = rangeFromOffsets(nodes, from, from + needle.length);
    if (range) ranges.push(range);
    from = combined.indexOf(needle, from + needle.length);
  }
  return ranges;
}

const SUBJECT_FIELDS: Array<{ key: keyof OutlineBasics & string; label: string }> = [
  { key: "name", label: "SUBJECT NAME" },
  { key: "code", label: "Course code" },
  { key: "section", label: "Section" },
  { key: "credit_points", label: "Credit Points" },
  { key: "year", label: "Year" },
  { key: "session", label: "Session" },
  { key: "duration", label: "Duration" },
  { key: "prerequisites", label: "Pre-requisite(s)" },
  { key: "equivalent_subjects", label: "Equivalent Subject(s)" },
  { key: "delivery_mode", label: "Mode of Delivery" },
];

const LECTURE_FIELDS: Array<{ key: keyof OutlineLecture & string; label: string }> = [
  { key: "day", label: "Day" },
  { key: "time", label: "Time" },
  { key: "location", label: "Location" },
  { key: "educator_name", label: "Educator's Name" },
  { key: "office", label: "Building & Office No" },
  { key: "email", label: "E-mail Address" },
  { key: "consultation", label: "Consultation" },
];

const SCHEDULE_COLUMNS: Array<{ key: keyof OutlineWeek & string; label: string }> = [
  { key: "week", label: "Week" },
  { key: "topic", label: "Lecture Topic(s)" },
  { key: "lo_codes", label: "Learning Outcomes" },
  { key: "session_type", label: "Session Type" },
  { key: "delivery", label: "Delivery format" },
  { key: "assessment_note", label: "Assessment" },
];

/** The four bands every rubric in the template uses. */
const RUBRIC_BANDS: Array<{
  key: "advanced" | "proficient" | "developing" | "beginning";
  label: string;
}> = [
  { key: "advanced", label: "Excellent (85–100%)" },
  { key: "proficient", label: "Good (70–84%)" },
  { key: "developing", label: "Satisfactory (50–69%)" },
  { key: "beginning", label: "Needs Improvement (<50%)" },
];

/**
 * Sections 6-12 of the faculty template are fixed university text. These constants
 * are the wording of "Subject Outline Template PG"; a matching body field wins.
 */
const OFFICIAL_POLICIES = [
  "Academic Grievance Policy",
  "Academic Integrity Policy",
  "Campus Access and Order Rules",
  "Code of Conduct – Library Users",
  "Code of Practice – Students",
  "Copyright Policy",
  "Intellectual Property Policy",
  "Library Regulations",
  "Minimum Rate of Progress",
  "Music, Video and Software Piracy",
  "Non-Discriminatory Language and Practice & Presentation Policy and Guidelines",
  "Special Consideration Policy & Procedure",
  "Student Attendance Policy",
  "Student Conduct Rules",
  "Rules for use of UOWD ITTS Facilities",
  "Teaching and Assessment: Code of Practice – Teaching",
  "Teaching and Assessment: Assessment and Feedback Policy",
  "Teaching and Assessment: Subject Delivery Policy",
];

const OFFICIAL_GENAI = [
  "Generative AI is not a substitute for decision-making: GenAI should complement, not replace, your critical thinking and decision-making skills.",
  "Output quality depends on prompts: The quality of GenAI outputs is influenced by prompting. Poorly constructed or unclear prompts may generate outputs that are incorrect.",
  "Fact verification is essential: GenAI outputs can be fabricated, presenting inaccurate information or contain harmful bias. Verify all GenAI outputs against reliable sources.",
  "Protect data and copyright: Many GenAI technologies collect information in ways that breach privacy and data protection provisions, particularly where the source material is confidential or subject to copyright. Check the Terms and Conditions of GenAI technologies and if unsure, contact UOW Copyright Guidance.",
  "Transparency in use: Where required, you must acknowledge GenAI use, including providing prompt histories and detailing how GenAI was utilised.",
  "Thoughtful and appropriate application: Be mindful of when and how to use GenAI tools. Assess its appropriateness for each use, and refrain from use when not suitable.",
];

const GENAI_INTRO =
  "GenAI technology (such as ChatGPT or Microsoft Co-pilot) is reshaping the University experience worldwide. UOW is committed to embracing GenAI as a tool to enhance learning experiences and develop vital work-readiness skills. However, misuse or use of GenAI in assessments where prohibited constitutes academic misconduct (as specified by University Policy). Check whether GenAI is permitted for each assessment task and how it is to be used and acknowledged. For example:";

const OFFICIAL_GRADES = [
  { grade: "High Distinction (HD)", range: "85 – 100%" },
  { grade: "Distinction (D)", range: "75 – 84%" },
  { grade: "Credit (C)", range: "65 – 74%" },
  { grade: "Pass (P)", range: "50 – 64%" },
  { grade: "Pass Supplementary (PS)", range: "50%" },
  { grade: "Fail (F)", range: "0 – 49% (and not meeting the attendance requirements)" },
  {
    grade: "Technical Fail (TF)",
    range:
      "Not meeting the final exam passing requirements – see the Assessment Policy PP-REG-DB-2.1",
  },
];

const OFFICIAL_SATISFACTORY = [
  "In order to be considered for a grade of Pass (P) or better in this subject, students must achieve the minimum required mark in the Final Examination (see page 1 for the required score); students who obtain a composite mark greater than or equal to 50% but do not satisfy the Final Examination minimum pass requirements will be awarded a “Technical Fail” grade.",
  "Students must ‘reasonably’ complete all assessment tasks (including the required score for the Final Examination) and submit these as specified in the subject outline. ‘Reasonable’ completion of an assessment task will be determined based on the instructions given to the student including: word length, demonstration of research and analysis where required, adherence to the Plagiarism Policy guidelines, and completion of each section/component of the assessment. Failure to submit all assessment tasks may result in a Fail grade awarded for the subject.",
];

const OFFICIAL_SSP =
  "SSP (Student Support Program) is a program committed to assisting students in developing their academic skills and getting the most out of their studies. As part of their services, SSP provides Peer Tutoring Program and Academic Workshops (https://my.uowdubai.ac.ae/ssd/index.php). Studiosity is an online study tool that students can access 24 hours, 7 days a week. Students can receive feedback on submitted writing in less than 24 hours and receive one-to-one, personal help in real time with a subject specialist. The service can be accessed through the subject Moodle site. For further information please contact: SSP Coordinator, Room 020, Block 5, ssp@uowdubai.ac.ae, Phone Number: +971 4 278 1756.";

const OFFICIAL_ACADEMIC_INTEGRITY =
  "Plagiarism and cheating are serious offences that can lead to expulsion from the university. Students must be familiar with the Academic Integrity policy which outlines the procedure that will be followed in case of academic misconduct including cheating and plagiarism. Please refer to How to Avoid Plagiarism available on the Student Online Resources website (http://my.uowdubai.ac.ae).";

const OFFICIAL_TURNITIN =
  "Students are required to submit all written assignments in soft copy through the TurnItIn system which is available online at www.turnitin.com. Every student must have a TurnItIn account. Failure to submit an assignment through TurnItIn will result in marks for that assignment being withheld. Students do NOT need to hand in a printed copy of the TurnItIn Originality Report. More information about TurnItIn (including how to create an account and add a class) will be provided in the first lecture.";

const OFFICIAL_REFERENCING =
  "For information about referencing and in-text citation please review the Academic Writing Presentation available on the Student Online Resources website (http://my.uowdubai.ac.ae).";

const OFFICIAL_UOWD_RULES =
  "For information about UOWD Rules and Policies, please go to the Student Online Resources website (http://my.uowdubai.ac.ae) and click on the POLICIES link.";

const OFFICIAL_ATTENDANCE =
  "Attendance in this subject is compulsory. Failure to attend all tutorials and computer workshops as per the Student Attendance Policy may result in a FAIL grade. Students are strongly encouraged to become familiar with this policy (which can be found on the Online Resources website at my.uowdubai.ac.ae).";

const OFFICIAL_SUPPLEMENTARY =
  "A supplementary assessment may be offered to students whose performance in this subject is close (45-49 in the final examination and 48-49 in the composite score) to that required to pass the subject, and are otherwise identified as meriting an offer of a supplementary assessment. The precise form of a supplementary assessment will be determined at the time the offer of a supplementary is made.";

const OFFICIAL_LECTURE_CAPTURE =
  "UOWD supports the recording of lectures as a supplemental study tool, to provide students with equity of access, and as a technology-enriched learning strategy to enhance the student experience. To make your own recording of a lecture you must receive the explicit permission of the Educator and those people who are also being recorded. You may only use recorded lectures, whether they are your own or recorded by the university, for your own educational purposes. Recordings cannot be altered, shared or published on another platform, without permission of the University. The UOWD Lecture Capture policy is under development.";

const OFFICIAL_SUSTAINABILITY =
  "UOWD encourages all students to act in a sustainable manner when planning and submitting assessments. If possible, students should not use plastic items, such as folders, covers, and bindings, and other synthetic materials, for presentations, workshops, and other activities. Students are also encouraged to avoid unnecessary printing; and if printing is required, please consider printing double-sided and only printing essential illustrations avoiding blocks of any colour as the use of ink is harmful to the environment. Always behave in a sustainable way.";

const OFFICIAL_LATE_SUBMISSION =
  "Please note that late submissions will incur a penalty of 20% per day, including weekends.";

function percent(value: unknown) {
  const raw = field(value);
  if (!raw) return "";
  return raw.includes("%") ? raw : raw + "%";
}

function groupCode(task: AssessmentTask) {
  if (task.group_individual) return task.group_individual;
  if (/group/i.test(field(task.type))) return "G";
  if (/individual/i.test(field(task.type))) return "I";
  return "";
}

/** Older outlines stored prose policies keyed like the template section. */
function policyBody(body: OutlineBody, key: string) {
  const item = (body.policies ?? []).find(
    (policy) => typeof policy !== "string" && policy.key === key,
  );
  return typeof item === "string" || item === undefined ? "" : field(item.body);
}

function integrityOf(value: AcademicIntegrity | string | undefined): AcademicIntegrity {
  if (typeof value === "string") return { intro: value };
  return value ?? {};
}

function taskTitle(task: AssessmentTask) {
  return field(task.title) || field(task.name);
}

function taskParagraphs(value: unknown) {
  if (Array.isArray(value)) return value.map((item) => field(item)).filter(Boolean);
  const single = field(value);
  return single ? [single] : [];
}

function taskFormat(task: AssessmentTask) {
  return taskParagraphs(task.format ?? task.format_guidelines);
}

/** Policy documents are objects on the wire, so display only their text fields. */
function policyList(value: OutlineBody["policy_documents"]): string[] {
  return (value ?? []).map((item) => field(item)).filter((item) => Boolean(item));
}

/** Section 6 reads policy_documents first, then the step's `policies` list, then the template. */
function policyDocumentsOf(body: OutlineBody): string[] {
  const direct = policyList(body.policy_documents);
  if (direct.length) return direct;
  const fromStep = (body.policies ?? []).filter(
    (policy): policy is string => typeof policy === "string" && Boolean(policy),
  );
  return fromStep.length ? fromStep : OFFICIAL_POLICIES;
}

function genaiIntroOf(body: OutlineBody) {
  return field(body.genai_intro) || GENAI_INTRO;
}

function genaiOf(body: OutlineBody) {
  const points = body.genai ?? [];
  return points.length ? points : OFFICIAL_GENAI;
}

function gradesOf(body: OutlineBody) {
  const grades = body.grades ?? [];
  return grades.length ? grades : OFFICIAL_GRADES;
}

function satisfactoryOf(body: OutlineBody) {
  const items = body.satisfactory ?? [];
  return items.length ? items : OFFICIAL_SATISFACTORY;
}

function satisfactoryNoteOf(body: OutlineBody) {
  return field(body.satisfactory_note);
}

function sspOf(body: OutlineBody) {
  return field(body.ssp) || OFFICIAL_SSP;
}

function attendanceOf(body: OutlineBody) {
  return field(body.attendance) || OFFICIAL_ATTENDANCE;
}

function supplementaryOf(body: OutlineBody) {
  return field(body.supplementary) || OFFICIAL_SUPPLEMENTARY;
}

function lectureCaptureOf(body: OutlineBody) {
  return field(body.lecture_capture) || OFFICIAL_LECTURE_CAPTURE;
}

function sustainabilityOf(body: OutlineBody) {
  return field(body.sustainability) || OFFICIAL_SUSTAINABILITY;
}

function lateSubmissionOf(body: OutlineBody) {
  return field(body.late_submission) || OFFICIAL_LATE_SUBMISSION;
}

/** Seed the edit draft with the wording the reader currently sees. */
function seedDraft(body: OutlineBody): OutlineBody {
  const next = clone(body);
  if (!next.genai_intro) next.genai_intro = GENAI_INTRO;
  if (!next.genai?.length) next.genai = [...OFFICIAL_GENAI];
  if (!next.grades?.length) next.grades = OFFICIAL_GRADES.map((row) => ({ ...row }));
  if (!next.satisfactory?.length) next.satisfactory = [...OFFICIAL_SATISFACTORY];
  next.policy_documents = [...policyDocumentsOf(body)];
  if (!next.ssp) next.ssp = sspOf(body);
  if (!next.attendance) next.attendance = attendanceOf(body);
  if (!next.supplementary) next.supplementary = supplementaryOf(body);
  if (!next.lecture_capture) next.lecture_capture = lectureCaptureOf(body);
  if (!next.sustainability) next.sustainability = sustainabilityOf(body);
  if (!next.late_submission) next.late_submission = lateSubmissionOf(body);
  const current = integrityOf(next.academic_integrity);
  const shown = integrityParts(body);
  next.academic_integrity = {
    intro: field(current.intro) || shown.intro,
    turnitin: field(current.turnitin) || shown.turnitin,
    turnitin_fields: current.turnitin_fields ?? [],
    referencing: field(current.referencing) || shown.referencing,
    rules: field(current.rules) || shown.rules,
  };
  return next;
}

function integrityParts(body: OutlineBody) {
  const integrity = integrityOf(body.academic_integrity);
  return {
    intro:
      field(integrity.intro) ||
      policyBody(body, "academic_integrity") ||
      OFFICIAL_ACADEMIC_INTEGRITY,
    turnitin: field(integrity.turnitin) || OFFICIAL_TURNITIN,
    turnitin_fields: integrity.turnitin_fields ?? [],
    referencing: field(integrity.referencing) || OFFICIAL_REFERENCING,
    rules: field(integrity.rules) || OFFICIAL_UOWD_RULES,
  };
}

function clone(body: OutlineBody | undefined): OutlineBody {
  return JSON.parse(JSON.stringify(body ?? {})) as OutlineBody;
}

function same(a: unknown, b: unknown) {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/** Empty and absent mean the same thing for guidance text. */
function sameText(a: unknown, b: unknown) {
  return same(field(a) || null, field(b) || null);
}

/** Empty and absent mean the same thing for guidance lists and tables. */
function sameRows(a: unknown[] | undefined, b: unknown[] | undefined) {
  return same(a?.length ? a : null, b?.length ? b : null);
}

/** The first displayable string on a backend object. */
function objectText(value: Record<string, unknown>): string {
  for (const key of ["text", "title", "name", "filename"] as const) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) return candidate;
    if (typeof candidate === "number" || typeof candidate === "boolean") return String(candidate);
  }
  return "";
}

/** Display text for any shape the API returns: objects, arrays, scalars or null. */
function field(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) {
    return value
      .map((item) => field(item))
      .filter(Boolean)
      .join(", ");
  }
  if (typeof value === "object") return objectText(value as Record<string, unknown>);
  return String(value);
}

function outlineStatus(outline: Outline) {
  return outline.status === "published" || outline.pdf_ready ? "Published" : "Draft";
}

function listField(value: unknown) {
  return Array.isArray(value)
    ? value
        .map((item) => field(item))
        .filter(Boolean)
        .join(", ")
    : field(value);
}

function splitList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

/** The seeded outlines and the PDF/DOCX renderer still key this field `equivalent`. */
function equivalentOf(basics: OutlineBasics) {
  return field(basics.equivalent_subjects ?? basics.equivalent);
}

function basicsPayload(basics: OutlineBasics): Record<string, unknown> {
  const equivalent = equivalentOf(basics);
  return { ...basics, equivalent_subjects: equivalent, equivalent };
}

type DocumentSectionKey =
  | "subject-details"
  | "lecture"
  | "description"
  | "outcomes"
  | "schedule"
  | "readings"
  | "assessment"
  | "assessment-tasks"
  | "genai"
  | "grades"
  | "satisfactory"
  | "late-submission"
  | "policies"
  | "ssp"
  | "academic-integrity"
  | "attendance"
  | "supplementary"
  | "lecture-capture"
  | "sustainability";

/** A pencil that appears when the reader hovers or focuses the section. */
function SectionEditButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      className="shrink-0 opacity-100 transition-opacity focus-visible:opacity-100 sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100"
      aria-label={"Edit " + label}
      title={"Edit " + label}
      onClick={onClick}
    >
      <Pencil className="h-3.5 w-3.5" />
    </Button>
  );
}

function Section({
  id,
  title,
  children,
  onEdit,
}: {
  id?: DocumentSectionKey;
  title: string;
  children: ReactNode;
  onEdit?: () => void;
}) {
  return (
    <section
      id={id ? "doc-section-" + id : undefined}
      data-doc-section={id || undefined}
      data-doc-title={title}
      className="pa-doc-section group scroll-mt-36"
    >
      <div className="flex items-start justify-between gap-2">
        <h2>{title}</h2>
        {onEdit ? <SectionEditButton label={title} onClick={onEdit} /> : null}
      </div>
      {children}
    </section>
  );
}

function DocSubsection({
  id,
  title,
  children,
  onEdit,
  headingClassName = "pa-doc-subhead",
}: {
  id: DocumentSectionKey;
  title: string;
  children: ReactNode;
  onEdit?: () => void;
  headingClassName?: string;
}) {
  return (
    <section
      id={"doc-section-" + id}
      data-doc-section={id}
      data-doc-title={title}
      className="group scroll-mt-36"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className={headingClassName}>{title}</h3>
        {onEdit ? <SectionEditButton label={title} onClick={onEdit} /> : null}
      </div>
      {children}
    </section>
  );
}

function PaperPage({
  index,
  total,
  courseName,
  children,
}: {
  index: number;
  total: number;
  courseName: string;
  children: ReactNode;
}) {
  return (
    <section className="pa-doc-page pa-paper-page">
      <div className="pa-paper-meta">
        <span className="pa-paper-course">{courseName || "Untitled subject"}</span>
        <span className="pa-paper-folio">{"Page " + index + " of " + total}</span>
      </div>
      {children}
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{value || <span className="pa-doc-empty">—</span>}</td>
    </tr>
  );
}

function LoPloMatrix({ clos, plos }: { clos: OutlineClo[]; plos: OutlinePlo[] }) {
  if (!clos.length) {
    return <p className="pa-doc-empty">No learning outcomes yet.</p>;
  }
  return (
    <div className="pa-doc-table-scroll">
      <table className="pa-doc-table is-matrix">
        <thead>
          <tr>
            <th scope="col">LO</th>
            <th scope="col">Learning outcome</th>
            {plos.map((plo, index) => (
              <th key={plo.code || index} scope="col">
                {plo.code || "PLO " + (index + 1)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {clos.map((clo, index) => (
            <tr key={clo.code || index}>
              <th scope="row">{clo.code || "LO" + (index + 1)}</th>
              <td>{clo.text}</td>
              {plos.map((plo, ploIndex) => (
                <td key={plo.code || ploIndex}>
                  {(clo.plos ?? []).includes(plo.code) ? (
                    <span className="pa-doc-mark">X</span>
                  ) : (
                    ""
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type BodyPatch = (key: string, value: unknown) => void;

function TaskDetail({ task, index }: { task: AssessmentTask; index: number }) {
  const rubric = task.rubric ?? [];
  const overview = taskParagraphs(task.overview);
  const deliverables = taskParagraphs(task.deliverables);
  const format = taskFormat(task);
  return (
    <div className="pa-doc-task">
      <h4 className="pa-doc-task-title">
        {"Assessment task: " + (taskTitle(task) || "Assessment " + (index + 1))}
      </h4>

      <table className="pa-doc-table is-keyval">
        <tbody>
          <tr>
            <th scope="row">Type</th>
            <td>{field(task.type)}</td>
          </tr>
          <tr>
            <th scope="row">Learning outcome measured</th>
            <td>{listField(task.lo_codes)}</td>
          </tr>
          <tr>
            <th scope="row">Total marks</th>
            <td>{field(task.total_marks)}</td>
          </tr>
          <tr>
            <th scope="row">Weighting</th>
            <td>{percent(task.weight)}</td>
          </tr>
          <tr>
            <th scope="row">Date, time and location</th>
            <td>{field(task.due)}</td>
          </tr>
        </tbody>
      </table>

      {overview.length > 0 ? (
        <>
          <h5 className="pa-doc-task-head">Overview</h5>
          {overview.map((item, position) => (
            <p key={position} className="pa-doc-body-text">
              {item}
            </p>
          ))}
        </>
      ) : null}

      {deliverables.length > 0 ? (
        <>
          <h5 className="pa-doc-task-head">Deliverables</h5>
          <ol className="pa-doc-readings">
            {deliverables.map((item, position) => (
              <li key={position}>{item}</li>
            ))}
          </ol>
        </>
      ) : null}

      {format.length > 0 ? (
        <>
          <h5 className="pa-doc-task-head">Format and guidelines</h5>
          <ol className="pa-doc-readings">
            {format.map((item, position) => (
              <li key={position}>{item}</li>
            ))}
          </ol>
        </>
      ) : null}

      {rubric.length > 0 ? (
        <>
          <h5 className="pa-doc-task-head">Marking rubric</h5>
          <div className="pa-doc-table-scroll">
            <table className="pa-doc-table is-rubric">
              <thead>
                <tr>
                  <th scope="col">Criteria</th>
                  {RUBRIC_BANDS.map((band) => (
                    <th key={band.key} scope="col">
                      {band.label}
                    </th>
                  ))}
                  <th scope="col">Weight</th>
                </tr>
              </thead>
              <tbody>
                {rubric.map((row, position) => (
                  <tr key={position}>
                    <th scope="row">{field(row.name)}</th>
                    {RUBRIC_BANDS.map((band) => (
                      <td key={band.key}>{field((row.levels ?? {})[band.key])}</td>
                    ))}
                    <td>{percent(row.weight)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}

/** 5.2 is owned by the assignment journey, so it stays read-only here. */
function AssessmentTasks({ tasks }: { tasks: AssessmentTask[] }) {
  const assignmentId =
    tasks.map((task) => field(task.assignment_id) || field(task.assessment_id)).find(Boolean) ?? "";
  return (
    <>
      {tasks.length ? (
        <>
          <div className="pa-doc-table-scroll">
            <table className="pa-doc-table">
              <thead>
                <tr>
                  <th scope="col">Assessment</th>
                  <th scope="col">Weight</th>
                  <th scope="col">Learning outcome</th>
                  <th scope="col">Group (G) / Individual (I)</th>
                  <th scope="col">Total marks</th>
                  <th scope="col">Due date</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task, index) => (
                  <tr key={(field(task.number) || String(index)) + index}>
                    <th scope="row">
                      {[field(task.number), taskTitle(task)].filter(Boolean).join(" ") ||
                        "Assessment " + (index + 1)}
                    </th>
                    <td>{percent(task.weight)}</td>
                    <td>{listField(task.lo_codes)}</td>
                    <td>{groupCode(task)}</td>
                    <td>{field(task.total_marks)}</td>
                    <td>{field(task.due)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {tasks.map((task, index) => (
            <TaskDetail key={"detail-" + index} task={task} index={index} />
          ))}
        </>
      ) : (
        <p className="pa-doc-empty">No assessment tasks yet.</p>
      )}

      <p className="pa-doc-note">
        Assessment tasks and rubrics are designed in Assignments, so they are read-only here.{" "}
        {assignmentId ? (
          <a
            className="pa-doc-link"
            href={"/assignments?assessment=" + encodeURIComponent(assignmentId)}
          >
            Edit in Assignments
          </a>
        ) : null}
      </p>
    </>
  );
}

function EditableText({
  id,
  label,
  value,
  editing,
  rows = 4,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  editing: boolean;
  rows?: number;
  onChange: (next: string) => void;
}) {
  if (!editing) {
    return <p className="pa-doc-body-text">{value}</p>;
  }
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Textarea
        id={id}
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function EditableList({
  label,
  items,
  editing,
  onChange,
}: {
  label: string;
  items: OutlineDocumentValue[];
  editing: boolean;
  onChange: (next: string[]) => void;
}) {
  const rows = items.map((item) => field(item));
  if (!editing) {
    if (!rows.length) return <p className="pa-doc-empty">No {label.toLowerCase()}s yet.</p>;
    return (
      <ol className="pa-doc-readings">
        {rows.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ol>
    );
  }
  return (
    <>
      <ol className="pa-doc-readings">
        {rows.map((item, index) => (
          <li key={index}>
            <textarea
              className="pa-doc-input"
              rows={2}
              aria-label={label + " " + (index + 1)}
              value={item}
              onChange={(event) => {
                const next = rows.slice();
                next[index] = event.target.value;
                onChange(next);
              }}
            />
          </li>
        ))}
      </ol>
      <div className="pa-doc-row-tools">
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange([...rows, ""])}>
          <Plus className="h-4 w-4" />
          {"Add " + label.toLowerCase()}
        </Button>
        {rows.length > 0 ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onChange(rows.slice(0, -1))}
          >
            <X className="h-4 w-4" />
            {"Remove last " + label.toLowerCase()}
          </Button>
        ) : null}
      </div>
    </>
  );
}

function EditableGrades({
  grades,
  editing,
  onChange,
}: {
  grades: GradeRow[];
  editing: boolean;
  onChange: (next: GradeRow[]) => void;
}) {
  if (!editing) {
    return (
      <table className="pa-doc-table is-keyval">
        <tbody>
          {grades.map((row, index) => (
            <tr key={index}>
              <th scope="row">{row.grade}</th>
              <td>{row.range}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return (
    <>
      <div className="pa-doc-table-scroll">
        <table className="pa-doc-table">
          <thead>
            <tr>
              <th scope="col">Grade</th>
              <th scope="col">Range of marks</th>
              <th scope="col">
                <span className="pa-doc-sr-only">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {grades.map((row, index) => (
              <tr key={index}>
                <td>
                  <input
                    className="pa-doc-input"
                    aria-label={"Grade " + (index + 1)}
                    value={row.grade}
                    onChange={(event) => {
                      const next = grades.slice();
                      next[index] = { ...row, grade: event.target.value };
                      onChange(next);
                    }}
                  />
                </td>
                <td>
                  <input
                    className="pa-doc-input"
                    aria-label={"Range for grade " + (index + 1)}
                    value={row.range}
                    onChange={(event) => {
                      const next = grades.slice();
                      next[index] = { ...row, range: event.target.value };
                      onChange(next);
                    }}
                  />
                </td>
                <td className="pa-doc-cell-tool">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Remove this grade"
                    onClick={() => onChange(grades.filter((_, position) => position !== index))}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pa-doc-row-tools">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onChange([...grades, { grade: "", range: "" }])}
        >
          <Plus className="h-4 w-4" />
          Add grade
        </Button>
      </div>
    </>
  );
}

/** 5.2 to 5.5 and the late-submission rule. part splits the read view across pages. */
function AssessmentDetail({
  editing,
  body,
  onChange,
  onEdit,
  part,
}: {
  editing: boolean;
  body: OutlineBody;
  onChange: BodyPatch;
  onEdit?: (section: DocumentSectionKey) => void;
  part?: "tasks" | "guides";
}) {
  const tasks = body.assessment_tasks ?? [];
  const genai = editing ? (body.genai ?? []) : genaiOf(body);
  const grades = editing ? (body.grades ?? []) : gradesOf(body);
  const satisfactory = editing ? (body.satisfactory ?? []) : satisfactoryOf(body);
  const note = satisfactoryNoteOf(body);
  const edit = (section: DocumentSectionKey) => (onEdit ? () => onEdit(section) : undefined);
  const showTasks = !part || part === "tasks";
  const showGuides = !part || part === "guides";

  return (
    <>
      {showTasks ? (
        <DocSubsection id="assessment-tasks" title="5.2 Assessment tasks">
          <AssessmentTasks tasks={tasks} />
        </DocSubsection>
      ) : null}

      {showGuides ? (
        <>
          <DocSubsection id="genai" title="5.3 Using Generative AI (GenAI)" onEdit={edit("genai")}>
            <EditableText
              id="doc-genai-intro"
              label="GenAI introduction"
              value={editing ? field(body.genai_intro) : genaiIntroOf(body)}
              editing={editing}
              rows={6}
              onChange={(value) => onChange("genai_intro", value)}
            />
            <EditableList
              label="GenAI point"
              items={genai}
              editing={editing}
              onChange={(next) => onChange("genai", next)}
            />
          </DocSubsection>

          <DocSubsection id="grades" title="5.4 Grades awarded" onEdit={edit("grades")}>
            <p className="pa-doc-note">
              The approved grades of performance and associated ranges of marks are:
            </p>
            <EditableGrades
              grades={grades}
              editing={editing}
              onChange={(next) => onChange("grades", next)}
            />
          </DocSubsection>

          <DocSubsection
            id="satisfactory"
            title="5.5 Satisfactory completion requirements"
            onEdit={edit("satisfactory")}
          >
            <EditableList
              label="Completion requirement"
              items={satisfactory}
              editing={editing}
              onChange={(next) => onChange("satisfactory", next)}
            />
            {editing || note ? (
              <EditableText
                id="doc-satisfactory-note"
                label="Note for the faculty"
                value={note}
                editing={editing}
                rows={3}
                onChange={(value) => onChange("satisfactory_note", value)}
              />
            ) : null}
          </DocSubsection>

          <DocSubsection
            id="late-submission"
            title="Late submissions"
            headingClassName="pa-doc-task-head"
            onEdit={edit("late-submission")}
          >
            <EditableText
              id="doc-late-submission"
              label="Late submission rule"
              value={editing ? field(body.late_submission) : lateSubmissionOf(body)}
              editing={editing}
              rows={2}
              onChange={(value) => onChange("late_submission", value)}
            />
          </DocSubsection>
        </>
      ) : null}
    </>
  );
}

/** Sections 6 to 12. Empty fields fall back to the faculty template wording. */
function GuidanceSections({
  editing,
  body,
  onChange,
  onEdit,
}: {
  editing: boolean;
  body: OutlineBody;
  onChange: BodyPatch;
  onEdit?: (section: DocumentSectionKey) => void;
}) {
  const integrity = integrityParts(body);
  const policies = editing
    ? body.policy_documents
      ? policyList(body.policy_documents)
      : policyDocumentsOf(body)
    : policyDocumentsOf(body);
  const ssp = editing ? field(body.ssp) : sspOf(body);
  const attendance = editing ? field(body.attendance) : attendanceOf(body);
  const supplementary = editing ? field(body.supplementary) : supplementaryOf(body);
  const capture = editing ? field(body.lecture_capture) : lectureCaptureOf(body);
  const sustainability = editing ? field(body.sustainability) : sustainabilityOf(body);

  return (
    <>
      <Section
        id="policies"
        title="6. Relevant policies and documents"
        onEdit={onEdit ? () => onEdit("policies") : undefined}
      >
        <p className="pa-doc-note">
          All students must read and be familiar with the following UOWD policies and documents,
          which are available on the Student Online Resources (my.uowdubai.ac.ae) website by
          following the Policies link:
        </p>
        <EditableList
          label="Policy document"
          items={policies}
          editing={editing}
          onChange={(next) => onChange("policy_documents", next)}
        />
      </Section>

      <Section
        id="ssp"
        title="7. SSP and Studiosity"
        onEdit={onEdit ? () => onEdit("ssp") : undefined}
      >
        <EditableText
          id="doc-ssp"
          label="SSP and Studiosity"
          value={ssp}
          editing={editing}
          rows={6}
          onChange={(value) => onChange("ssp", value)}
        />
      </Section>

      <Section
        id="academic-integrity"
        title="8. Academic integrity"
        onEdit={onEdit ? () => onEdit("academic-integrity") : undefined}
      >
        <EditableText
          id="doc-integrity-intro"
          label="Academic integrity"
          value={editing ? field(integrityOf(body.academic_integrity).intro) : integrity.intro}
          editing={editing}
          rows={4}
          onChange={(value) =>
            onChange("academic_integrity", {
              ...integrityOf(body.academic_integrity),
              intro: value,
            })
          }
        />

        <h3 className="pa-doc-subhead">8.1 TurnItIn</h3>
        <EditableText
          id="doc-integrity-turnitin"
          label="TurnItIn"
          value={
            editing ? field(integrityOf(body.academic_integrity).turnitin) : integrity.turnitin
          }
          editing={editing}
          rows={5}
          onChange={(value) =>
            onChange("academic_integrity", {
              ...integrityOf(body.academic_integrity),
              turnitin: value,
            })
          }
        />
        {(editing
          ? (integrityOf(body.academic_integrity).turnitin_fields ?? [])
          : integrity.turnitin_fields
        ).length > 0 && (
          <table className="pa-doc-table is-keyval">
            <tbody>
              {(editing
                ? (integrityOf(body.academic_integrity).turnitin_fields ?? [])
                : integrity.turnitin_fields
              ).map((row, index) => (
                <tr key={index}>
                  <th scope="row">
                    {editing ? (
                      <input
                        className="pa-doc-input"
                        aria-label={"TurnItIn field " + (index + 1) + " label"}
                        value={row.label}
                        onChange={(event) => {
                          const fields = (
                            integrityOf(body.academic_integrity).turnitin_fields ?? []
                          ).slice();
                          fields[index] = { ...row, label: event.target.value };
                          onChange("academic_integrity", {
                            ...integrityOf(body.academic_integrity),
                            turnitin_fields: fields,
                          });
                        }}
                      />
                    ) : (
                      row.label
                    )}
                  </th>
                  <td>
                    {editing ? (
                      <input
                        className="pa-doc-input"
                        aria-label={"TurnItIn field " + (index + 1) + " value"}
                        value={row.value}
                        onChange={(event) => {
                          const fields = (
                            integrityOf(body.academic_integrity).turnitin_fields ?? []
                          ).slice();
                          fields[index] = { ...row, value: event.target.value };
                          onChange("academic_integrity", {
                            ...integrityOf(body.academic_integrity),
                            turnitin_fields: fields,
                          });
                        }}
                      />
                    ) : (
                      row.value
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {editing && (
          <div className="pa-doc-row-tools">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() =>
                onChange("academic_integrity", {
                  ...integrityOf(body.academic_integrity),
                  turnitin_fields: [
                    ...(integrityOf(body.academic_integrity).turnitin_fields ?? []),
                    { label: "", value: "" },
                  ],
                })
              }
            >
              <Plus className="h-4 w-4" />
              Add TurnItIn field
            </Button>
          </div>
        )}

        <h3 className="pa-doc-subhead">8.2 Reference and in-text citation</h3>
        <EditableText
          id="doc-integrity-referencing"
          label="Referencing"
          value={
            editing
              ? field(integrityOf(body.academic_integrity).referencing)
              : integrity.referencing
          }
          editing={editing}
          rows={3}
          onChange={(value) =>
            onChange("academic_integrity", {
              ...integrityOf(body.academic_integrity),
              referencing: value,
            })
          }
        />

        <h3 className="pa-doc-subhead">8.3 UOWD rules and policies</h3>
        <EditableText
          id="doc-integrity-rules"
          label="Rules and policies"
          value={editing ? field(integrityOf(body.academic_integrity).rules) : integrity.rules}
          editing={editing}
          rows={3}
          onChange={(value) =>
            onChange("academic_integrity", {
              ...integrityOf(body.academic_integrity),
              rules: value,
            })
          }
        />
      </Section>

      <Section
        id="attendance"
        title="9. Attendance requirements"
        onEdit={onEdit ? () => onEdit("attendance") : undefined}
      >
        <EditableText
          id="doc-attendance"
          label="Attendance"
          value={attendance}
          editing={editing}
          rows={4}
          onChange={(value) => onChange("attendance", value)}
        />
      </Section>

      <Section
        id="supplementary"
        title="10. Supplementary assessments"
        onEdit={onEdit ? () => onEdit("supplementary") : undefined}
      >
        <EditableText
          id="doc-supplementary"
          label="Supplementary assessments"
          value={supplementary}
          editing={editing}
          rows={4}
          onChange={(value) => onChange("supplementary", value)}
        />
      </Section>

      <Section
        id="lecture-capture"
        title="11. Lecture capture"
        onEdit={onEdit ? () => onEdit("lecture-capture") : undefined}
      >
        <EditableText
          id="doc-lecture-capture"
          label="Lecture capture"
          value={capture}
          editing={editing}
          rows={4}
          onChange={(value) => onChange("lecture_capture", value)}
        />
      </Section>

      <Section
        id="sustainability"
        title="12. Sustainability"
        onEdit={onEdit ? () => onEdit("sustainability") : undefined}
      >
        <EditableText
          id="doc-sustainability"
          label="Sustainability"
          value={sustainability}
          editing={editing}
          rows={4}
          onChange={(value) => onChange("sustainability", value)}
        />
      </Section>
    </>
  );
}

export function OutlineDocument({
  outline,
  onOutline,
  moodleMode = "",
  onAskAi,
}: {
  outline: Outline;
  onOutline: (outline: Outline) => void;
  moodleMode?: string;
  onAskAi?: (target: { quote: string; sectionTitle: string }) => void;
}) {
  const body = outline.body ?? {};
  const basics = body.basics ?? {};
  const lecture = body.lecture ?? {};
  const plos = body.plos ?? [];
  const clos = body.clos ?? [];
  const weeks = body.weeks ?? [];
  const readings = body.readings ?? [];
  const outcomeMeasures = body.outcome_measures ?? [];

  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<OutlineBody>(() => clone(outline.body));
  const [publishing, setPublishing] = useState(false);
  const [publishNotice, setPublishNotice] = useState("");
  const [publishError, setPublishError] = useState("");
  const [pendingSection, setPendingSection] = useState<DocumentSectionKey | null>(null);

  const storageKey = "profassist:outline-annotations:" + outline.id;
  const paperRef = useRef<HTMLDivElement | null>(null);
  const [annotations, setAnnotations] = useState<OutlineAnnotation[]>([]);
  const [annotationsReady, setAnnotationsReady] = useState(false);
  const [annotationsOpen, setAnnotationsOpen] = useState(true);
  const [selectionTarget, setSelectionTarget] = useState<SelectionTarget | null>(null);
  const [annotateOpen, setAnnotateOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");

  // Entering edit from a section pencil: scroll it into view and focus its first field.
  useEffect(() => {
    if (!editing || !pendingSection) return;
    const container = window.document.getElementById("doc-section-" + pendingSection);
    if (!container) {
      setPendingSection(null);
      return;
    }
    const handle = window.setTimeout(() => {
      container.scrollIntoView({ behavior: "smooth", block: "start" });
      const first = container.querySelector<HTMLElement>(
        "input:not([type='hidden']), textarea, select",
      );
      first?.focus({ preventScroll: true });
      setPendingSection(null);
    }, 0);
    return () => window.clearTimeout(handle);
  }, [editing, pendingSection]);

  // Selecting text in the paper reveals the highlight/annotate/Ask AI toolbar.
  useEffect(() => {
    if (editing) return;
    const container = paperRef.current;
    if (!container) return;
    const handleMouseUp = () => {
      window.setTimeout(() => {
        const selection = window.getSelection();
        const quote = selection?.toString().trim() ?? "";
        if (!selection || !quote || selection.rangeCount === 0) {
          setSelectionTarget(null);
          return;
        }
        const range = selection.getRangeAt(0);
        if (!container.contains(range.commonAncestorContainer)) {
          setSelectionTarget(null);
          return;
        }
        const start =
          range.startContainer.nodeType === Node.ELEMENT_NODE
            ? (range.startContainer as Element)
            : range.startContainer.parentElement;
        const section = start?.closest<HTMLElement>("[data-doc-section]");
        const rect = range.getBoundingClientRect();
        if (!rect || (rect.width === 0 && rect.height === 0)) {
          setSelectionTarget(null);
          return;
        }
        const below = rect.top < 96;
        const x = Math.min(Math.max(rect.left + rect.width / 2, 132), window.innerWidth - 132);
        setSelectionTarget({
          x,
          y: below ? rect.bottom : rect.top,
          below,
          quote,
          sectionKey: section?.getAttribute("data-doc-section") ?? "",
          sectionTitle: section?.getAttribute("data-doc-title") ?? "",
        });
      }, 0);
    };
    container.addEventListener("mouseup", handleMouseUp);
    return () => container.removeEventListener("mouseup", handleMouseUp);
  }, [editing]);

  // Dismiss the toolbar on an outside click or while the paper scrolls.
  useEffect(() => {
    if (!selectionTarget) return;
    const handleDown = (event: MouseEvent) => {
      const element = event.target as HTMLElement | null;
      if (element?.closest("[data-pa-selection-toolbar]")) return;
      if (element?.closest(".pa-artifact-scroll")) return;
      setSelectionTarget(null);
      setAnnotateOpen(false);
    };
    const handleScroll = () => {
      setSelectionTarget(null);
      setAnnotateOpen(false);
    };
    document.addEventListener("mousedown", handleDown);
    window.addEventListener("scroll", handleScroll, true);
    return () => {
      document.removeEventListener("mousedown", handleDown);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [selectionTarget]);

  // Load stored annotations once per outline, then persist every later change.
  useEffect(() => {
    let parsed: OutlineAnnotation[] = [];
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw) {
        const value: unknown = JSON.parse(raw);
        if (Array.isArray(value)) parsed = value as OutlineAnnotation[];
      }
    } catch {
      parsed = [];
    }
    setAnnotations(parsed);
    setAnnotationsReady(true);
  }, [storageKey]);

  useEffect(() => {
    if (!annotationsReady) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(annotations));
    } catch {
      // Persisting annotations is best-effort.
    }
  }, [annotations, annotationsReady, storageKey]);

  // Paint saved annotations with the CSS Custom Highlight API when available.
  useEffect(() => {
    const registry = (globalThis as unknown as { CSS?: { highlights?: HighlightRegistryLike } }).CSS
      ?.highlights;
    const HighlightCtor = (globalThis as unknown as { Highlight?: HighlightConstructor }).Highlight;
    if (!registry || !HighlightCtor) return;
    const container = paperRef.current;
    if (!container) return;
    const ranges: Range[] = [];
    for (const annotation of annotations) {
      if (!annotation.quote) continue;
      const scope = annotation.sectionKey
        ? (container.querySelector<HTMLElement>(
            '[data-doc-section="' + cssEscape(annotation.sectionKey) + '"]',
          ) ?? container)
        : container;
      ranges.push(...findQuoteRanges(scope, annotation.quote));
    }
    if (ranges.length) {
      registry.set("pa-annotations", new HighlightCtor(...ranges));
    } else {
      registry.delete("pa-annotations");
    }
    return () => {
      registry.delete("pa-annotations");
    };
  }, [annotations, editing]);

  const rawCode = field(basics.code) || outline.code;
  const code = /^NEW-[A-F0-9]{6}$/i.test(rawCode) ? "" : rawCode;
  const name = field(basics.name) || outline.name;
  const sources = Array.from(
    new Set(
      [
        ...(body.source_materials ?? []),
        ...(outline.source_materials ?? []),
        ...(outline.sources ?? []),
      ]
        .map(field)
        .filter(Boolean),
    ),
  );

  const patch: BodyPatch = (key, value) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  function startEdit(section?: DocumentSectionKey) {
    setError("");
    setPublishNotice("");
    setPublishError("");
    setDraft(seedDraft(outline.body));
    setSelectionTarget(null);
    setAnnotateOpen(false);
    setEditing(true);
    setPendingSection(section ?? null);
  }

  function cancelEdit() {
    setDraft(clone(outline.body));
    setError("");
    setEditing(false);
    setPendingSection(null);
  }

  function setBasic(key: keyof OutlineBasics & string, value: string) {
    setDraft((current) => ({
      ...current,
      basics: { ...(current.basics ?? {}), [key]: value },
    }));
  }

  function setLecture(key: keyof OutlineLecture & string, value: string) {
    setDraft((current) => ({
      ...current,
      lecture: { ...(current.lecture ?? {}), [key]: value },
    }));
  }

  function setPlo(index: number, key: "code" | "text", value: string) {
    setDraft((current) => {
      const rows = (current.plos ?? []).slice();
      rows[index] = { ...(rows[index] ?? { code: "", text: "" }), [key]: value };
      return { ...current, plos: rows };
    });
  }

  function setClo(index: number, key: "code" | "text" | "plos", value: string) {
    setDraft((current) => {
      const rows = (current.clos ?? []).slice();
      const row = { ...(rows[index] ?? { code: "", text: "" }) };
      if (key === "plos") row.plos = splitList(value);
      else row[key] = value;
      rows[index] = row;
      return { ...current, clos: rows };
    });
  }

  function setWeek(index: number, key: keyof OutlineWeek & string, value: string) {
    setDraft((current) => {
      const rows = (current.weeks ?? []).slice();
      const row = { ...(rows[index] ?? {}) };
      if (key === "lo_codes") row.lo_codes = splitList(value);
      else row[key] = value;
      rows[index] = row;
      return { ...current, weeks: rows };
    });
  }

  function setReading(index: number, value: string) {
    setDraft((current) => {
      const rows = (current.readings ?? []).slice();
      rows[index] = value;
      return { ...current, readings: rows };
    });
  }

  function setMeasure(index: number, key: "lo_code" | "measures", value: string) {
    setDraft((current) => {
      const rows = (current.outcome_measures ?? []).slice();
      rows[index] = { ...(rows[index] ?? { lo_code: "", measures: "" }), [key]: value };
      return { ...current, outcome_measures: rows };
    });
  }

  function addPlo() {
    setDraft((current) => ({
      ...current,
      plos: [
        ...(current.plos ?? []),
        { code: "PLO" + ((current.plos ?? []).length + 1), text: "" },
      ],
    }));
  }

  function addClo() {
    setDraft((current) => ({
      ...current,
      clos: [
        ...(current.clos ?? []),
        { code: "LO" + ((current.clos ?? []).length + 1), text: "", plos: [] },
      ],
    }));
  }

  function addWeek() {
    setDraft((current) => ({
      ...current,
      weeks: [
        ...(current.weeks ?? []),
        {
          week: (current.weeks ?? []).length + 1,
          topic: "",
          lo_codes: [],
          session_type: "",
          delivery: "",
          assessment_note: "",
        },
      ],
    }));
  }

  function addReading() {
    setDraft((current) => ({ ...current, readings: [...(current.readings ?? []), ""] }));
  }

  function addMeasure() {
    setDraft((current) => ({
      ...current,
      outcome_measures: [
        ...(current.outcome_measures ?? []),
        { lo_code: (current.clos ?? [])[0]?.code ?? "", measures: "" },
      ],
    }));
  }

  function dropRow(
    key: "plos" | "clos" | "weeks" | "readings" | "outcome_measures",
    index: number,
  ) {
    setDraft((current) => {
      const rows = (current[key] ?? []) as unknown[];
      return { ...current, [key]: rows.filter((_, position) => position !== index) };
    });
  }

  async function save() {
    setError("");
    const live = outline.body ?? {};
    const todo: Array<{ step: string; label: string; payload: Record<string, unknown> }> = [];

    if (!same(draft.basics, live.basics)) {
      todo.push({
        step: "basics",
        label: "Subject details",
        payload: basicsPayload(draft.basics ?? {}),
      });
    }
    if (!same(draft.lecture, live.lecture)) {
      todo.push({ step: "lecture", label: "Lecture information", payload: draft.lecture ?? {} });
    }
    if ((draft.description ?? "") !== (live.description ?? "")) {
      todo.push({
        step: "description",
        label: "Subject description",
        payload: { description: draft.description ?? "" },
      });
    }
    if (
      !same(
        { program: draft.program, plos: draft.plos, clos: draft.clos },
        { program: live.program, plos: live.plos, clos: live.clos },
      )
    ) {
      todo.push({
        step: "outcomes",
        label: "Learning outcomes",
        payload: {
          program: draft.program ?? "",
          plos: draft.plos ?? [],
          clos: draft.clos ?? [],
        },
      });
    }
    if (!same(draft.weeks, live.weeks)) {
      todo.push({
        step: "schedule",
        label: "Subject schedule",
        payload: { weeks: draft.weeks ?? [] },
      });
    }
    if (!same(draft.readings, live.readings)) {
      todo.push({
        step: "readings",
        label: "Supporting materials",
        payload: { readings: draft.readings ?? [] },
      });
    }
    if (!same(draft.outcome_measures, live.outcome_measures)) {
      todo.push({
        step: "assessment_map",
        label: "5.1 Assessment of learning outcomes",
        payload: { outcome_measures: draft.outcome_measures ?? [] },
      });
    }
    if (!sameText(draft.genai_intro, genaiIntroOf(live)) || !sameRows(draft.genai, genaiOf(live))) {
      todo.push({
        step: "genai",
        label: "5.3 Using Generative AI",
        payload: { genai_intro: draft.genai_intro ?? "", genai: draft.genai ?? [] },
      });
    }
    if (!sameRows(draft.grades, gradesOf(live))) {
      todo.push({
        step: "grades",
        label: "5.4 Grades awarded",
        payload: { grades: draft.grades ?? [] },
      });
    }
    if (
      !sameRows(draft.satisfactory, satisfactoryOf(live)) ||
      !sameText(draft.satisfactory_note, satisfactoryNoteOf(live))
    ) {
      todo.push({
        step: "satisfactory",
        label: "5.5 Satisfactory completion",
        payload: {
          satisfactory: draft.satisfactory ?? [],
          satisfactory_note: draft.satisfactory_note ?? "",
        },
      });
    }
    const documents = policyList(draft.policy_documents);
    if (!sameRows(documents, policyDocumentsOf(live))) {
      todo.push({
        step: "policy_documents",
        label: "6 Relevant policies and documents",
        payload: { policy_documents: documents },
      });
    }
    if (!sameText(draft.ssp, sspOf(live))) {
      todo.push({ step: "ssp", label: "7 SSP and Studiosity", payload: { ssp: draft.ssp ?? "" } });
    }
    if (!same(integrityOf(draft.academic_integrity), integrityParts(live))) {
      todo.push({
        step: "academic_integrity",
        label: "8 Academic integrity",
        payload: { academic_integrity: integrityOf(draft.academic_integrity) },
      });
    }
    if (!sameText(draft.attendance, attendanceOf(live))) {
      todo.push({
        step: "attendance",
        label: "9 Attendance requirements",
        payload: { attendance: draft.attendance ?? "" },
      });
    }
    if (!sameText(draft.supplementary, supplementaryOf(live))) {
      todo.push({
        step: "supplementary",
        label: "10 Supplementary assessments",
        payload: { supplementary: draft.supplementary ?? "" },
      });
    }
    if (!sameText(draft.lecture_capture, lectureCaptureOf(live))) {
      todo.push({
        step: "lecture_capture",
        label: "11 Lecture capture",
        payload: { lecture_capture: draft.lecture_capture ?? "" },
      });
    }
    if (!sameText(draft.sustainability, sustainabilityOf(live))) {
      todo.push({
        step: "sustainability",
        label: "12 Sustainability",
        payload: { sustainability: draft.sustainability ?? "" },
      });
    }
    if (!sameText(draft.late_submission, lateSubmissionOf(live))) {
      todo.push({
        step: "late_submission",
        label: "Late submissions",
        payload: { late_submission: draft.late_submission ?? "" },
      });
    }

    if (!todo.length) {
      setEditing(false);
      return;
    }

    setSaving(true);
    let latest = outline;
    try {
      for (const item of todo) {
        try {
          latest = await pa<Outline>("/outlines/" + outline.id + "/step", {
            method: "PUT",
            body: JSON.stringify({ step: item.step, payload: item.payload }),
          });
        } catch (err) {
          const detail = err instanceof Error ? err.message : "the server refused it";
          throw new Error(item.label + " could not be saved: " + detail);
        }
      }
      onOutline(latest);
      setEditing(false);
    } catch (err) {
      if (latest !== outline) onOutline(latest);
      setError(err instanceof Error ? err.message : "Could not save the outline.");
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    if (editing || saving || publishing) return;
    setPublishError("");
    setPublishNotice("");
    setPublishing(true);
    try {
      const published = await pa<Outline>("/outlines/" + outline.id + "/finish", {
        method: "POST",
      });
      onOutline(published);
      const generated: string[] = [];
      if (published.pdf_ready) generated.push("PDF");
      if (published.docx_ready) generated.push("DOCX");
      setPublishNotice(
        "Published. Status: " +
          (published.status || "unknown") +
          (generated.length ? ". Generated " + generated.join(" and ") + "." : "."),
      );
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : "The outline could not be published.");
    } finally {
      setPublishing(false);
    }
  }

  function saveAnnotation(note: string) {
    if (!selectionTarget) return;
    const annotation: OutlineAnnotation = {
      id: Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8),
      sectionKey: selectionTarget.sectionKey,
      sectionTitle: selectionTarget.sectionTitle,
      quote: selectionTarget.quote,
      note: note.trim(),
      color: "yellow",
      createdAt: new Date().toISOString(),
    };
    setAnnotations((current) => [...current, annotation]);
    window.getSelection()?.removeAllRanges();
    setSelectionTarget(null);
    setAnnotateOpen(false);
    setNoteDraft("");
  }

  function removeAnnotation(id: string) {
    setAnnotations((current) => current.filter((annotation) => annotation.id !== id));
  }

  function askAi(target: { quote: string; sectionTitle: string }) {
    onAskAi?.(target);
    setSelectionTarget(null);
    setAnnotateOpen(false);
  }

  return (
    <div className="pa-outline-doc">
      <div className="bg-background/95 supports-[backdrop-filter]:bg-background/80 sticky top-14 z-30 mb-5 border-b py-2 backdrop-blur print:hidden">
        <div className="mx-auto flex max-w-[820px] flex-wrap items-center gap-2 px-0.5">
          <div className="mr-auto min-w-0">
            <p className="text-muted-foreground truncate text-[11px] font-medium tracking-wide uppercase">
              {code || "Subject outline"}
            </p>
            <p className="truncate text-sm font-semibold">{name || "Untitled subject"}</p>
          </div>
          <Badge
            variant={outline.status === "published" || outline.pdf_ready ? "default" : "secondary"}
          >
            {outlineStatus(outline)}
          </Badge>
          <div className="flex flex-wrap items-center gap-1.5">
            {editing ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={cancelEdit}
                  disabled={saving}
                >
                  <X className="h-3.5 w-3.5" />
                  Cancel
                </Button>
                <Button type="button" size="sm" onClick={() => void save()} disabled={saving}>
                  <Save className="h-3.5 w-3.5" />
                  {saving ? "Saving..." : "Save changes"}
                </Button>
              </>
            ) : (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => startEdit()}
                  disabled={publishing}
                >
                  <Pencil className="h-3.5 w-3.5" />
                  Edit document
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled
                  title="Enter edit mode to make changes"
                >
                  <Save className="h-3.5 w-3.5" />
                  Save
                </Button>
              </>
            )}
            {outline.pdf_ready ? (
              <Button asChild variant="outline" size="sm">
                <a href={"/api/profassist/outlines/" + outline.id + "/document?kind=pdf"}>
                  <Download className="h-3.5 w-3.5" />
                  Download PDF
                </a>
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled
                title="Publish first to generate the PDF"
              >
                <Download className="h-3.5 w-3.5" />
                Download PDF
              </Button>
            )}
            {outline.docx_ready ? (
              <Button asChild variant="outline" size="sm">
                <a href={"/api/profassist/outlines/" + outline.id + "/document?kind=docx"}>
                  <Download className="h-3.5 w-3.5" />
                  Download DOCX
                </a>
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled
                title="Publish first to generate the DOCX"
              >
                <Download className="h-3.5 w-3.5" />
                Download DOCX
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              onClick={() => void publish()}
              disabled={editing || saving || publishing}
              title={
                editing
                  ? "Save or cancel your edits first"
                  : "Publish and generate the PDF and DOCX"
              }
            >
              {publishing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="h-3.5 w-3.5" />
              )}
              {publishing ? "Publishing..." : "Publish"}
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex">
                  <Button type="button" variant="outline" size="sm" disabled>
                    <Plug className="h-3.5 w-3.5" />
                    Moodle
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                {moodleMode === "real"
                  ? "Publishing an outline to Moodle is not available yet."
                  : "Connect Moodle first"}
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
        {publishNotice ? (
          <p role="status" className="mx-auto mt-2 max-w-[820px] text-xs text-emerald-700">
            {publishNotice}
          </p>
        ) : null}
        {publishError ? (
          <p role="alert" className="text-destructive mx-auto mt-2 max-w-[820px] text-xs">
            {publishError}
          </p>
        ) : null}
      </div>

      <Card className="mx-auto w-full max-w-[820px] overflow-hidden shadow-sm print:border-0 print:shadow-none">
        <CardContent className="p-0">
          {error && (
            <p className="pa-outline-error m-0 border-b" role="alert">
              {error}
            </p>
          )}

          {editing ? (
            <div className="pa-doc-page pa-doc-artifact pa-doc-edit">
              <header className="pa-doc-head">
                {code && <p className="pa-doc-kicker">{code}</p>}
                <h1>{name || "Untitled subject"}</h1>
                {sources.length > 0 && (
                  <p className="pa-doc-sources">{"Prepared from: " + sources.join(", ")}</p>
                )}
              </header>

              <Section id="subject-details" title="Subject details">
                <table className="pa-doc-table is-keyval">
                  <tbody>
                    {SUBJECT_FIELDS.map((item) => (
                      <tr key={item.key}>
                        <th scope="row">{item.label}</th>
                        <td>
                          <input
                            className="pa-doc-input"
                            aria-label={item.label}
                            value={
                              item.key === "equivalent_subjects"
                                ? equivalentOf(draft.basics ?? {})
                                : field(draft.basics?.[item.key])
                            }
                            onChange={(event) => setBasic(item.key, event.target.value)}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>

              <Section id="lecture" title="Lecture information">
                <table className="pa-doc-table is-keyval">
                  <tbody>
                    {LECTURE_FIELDS.map((item) => (
                      <tr key={item.key}>
                        <th scope="row">{item.label}</th>
                        <td>
                          <input
                            className="pa-doc-input"
                            aria-label={item.label}
                            value={field(draft.lecture?.[item.key])}
                            onChange={(event) => setLecture(item.key, event.target.value)}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>

              <Section id="description" title="1. Subject description">
                <div className="space-y-2">
                  <Label htmlFor="doc-description">Subject description</Label>
                  <Textarea
                    id="doc-description"
                    rows={8}
                    value={draft.description ?? ""}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, description: event.target.value }))
                    }
                  />
                </div>
              </Section>

              <Section id="outcomes" title="2. Learning Outcome and contribution to PLO">
                <div className="space-y-2">
                  <Label htmlFor="doc-program">Program</Label>
                  <Input
                    id="doc-program"
                    value={draft.program ?? ""}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, program: event.target.value }))
                    }
                  />
                </div>
                <h3 className="pa-doc-subhead">Program learning outcomes</h3>
                <table className="pa-doc-table">
                  <thead>
                    <tr>
                      <th scope="col">PLO</th>
                      <th scope="col">Description</th>
                      <th scope="col">
                        <span className="pa-doc-sr-only">Remove</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(draft.plos ?? []).map((plo, index) => (
                      <tr key={plo.code || index}>
                        <td>
                          <input
                            className="pa-doc-input"
                            aria-label={"PLO " + (index + 1) + " code"}
                            value={field(plo.code)}
                            onChange={(event) => setPlo(index, "code", event.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            className="pa-doc-input"
                            aria-label={"PLO " + (index + 1) + " description"}
                            value={field(plo.text)}
                            onChange={(event) => setPlo(index, "text", event.target.value)}
                          />
                        </td>
                        <td className="pa-doc-cell-tool">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label="Remove this PLO"
                            onClick={() => dropRow("plos", index)}
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="pa-doc-row-tools">
                  <Button type="button" variant="ghost" size="sm" onClick={addPlo}>
                    <Plus className="h-4 w-4" />
                    Add PLO
                  </Button>
                </div>

                <h3 className="pa-doc-subhead">Learning outcomes</h3>
                <table className="pa-doc-table">
                  <thead>
                    <tr>
                      <th scope="col">LO</th>
                      <th scope="col">Outcome</th>
                      <th scope="col">PLOs</th>
                      <th scope="col">
                        <span className="pa-doc-sr-only">Remove</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(draft.clos ?? []).map((clo, index) => (
                      <tr key={clo.code || index}>
                        <td>
                          <input
                            className="pa-doc-input"
                            aria-label={"Outcome " + (index + 1) + " code"}
                            value={field(clo.code)}
                            onChange={(event) => setClo(index, "code", event.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            className="pa-doc-input"
                            aria-label={"Outcome " + (index + 1) + " text"}
                            value={field(clo.text)}
                            onChange={(event) => setClo(index, "text", event.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            className="pa-doc-input"
                            aria-label={
                              "Outcome " + (index + 1) + " mapped PLO codes, comma separated"
                            }
                            value={listField(clo.plos)}
                            onChange={(event) => setClo(index, "plos", event.target.value)}
                          />
                        </td>
                        <td className="pa-doc-cell-tool">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label="Remove this learning outcome"
                            onClick={() => dropRow("clos", index)}
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="pa-doc-row-tools">
                  <Button type="button" variant="ghost" size="sm" onClick={addClo}>
                    <Plus className="h-4 w-4" />
                    Add learning outcome
                  </Button>
                </div>

                <h3 className="pa-doc-subhead">
                  Map of learning outcomes to program learning outcomes
                </h3>
                <LoPloMatrix clos={draft.clos ?? []} plos={draft.plos ?? []} />
              </Section>

              <Section id="schedule" title="3. Subject schedule">
                <div className="pa-doc-table-scroll">
                  <table className="pa-doc-table">
                    <thead>
                      <tr>
                        {SCHEDULE_COLUMNS.map((column) => (
                          <th key={column.key} scope="col">
                            {column.label}
                          </th>
                        ))}
                        <th scope="col">
                          <span className="pa-doc-sr-only">Remove</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {(draft.weeks ?? []).map((week, index) => (
                        <tr key={String(week.week ?? index)}>
                          {SCHEDULE_COLUMNS.map((column) => (
                            <td key={column.key}>
                              <input
                                className="pa-doc-input"
                                aria-label={
                                  column.label + " for week " + (field(week.week) || index + 1)
                                }
                                value={
                                  column.key === "lo_codes"
                                    ? listField(week.lo_codes)
                                    : field(week[column.key])
                                }
                                onChange={(event) => setWeek(index, column.key, event.target.value)}
                              />
                            </td>
                          ))}
                          <td className="pa-doc-cell-tool">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              aria-label={"Remove week " + (field(week.week) || index + 1)}
                              onClick={() => dropRow("weeks", index)}
                            >
                              <X className="h-3.5 w-3.5" />
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="pa-doc-row-tools">
                  <Button type="button" variant="ghost" size="sm" onClick={addWeek}>
                    <Plus className="h-4 w-4" />
                    Add week
                  </Button>
                </div>
              </Section>

              <Section id="readings" title="4. Supporting materials">
                <p className="pa-doc-note">
                  Read the following materials before each session; they support the lecture and the
                  workshop.
                </p>
                <ol className="pa-doc-readings">
                  {(draft.readings ?? []).map((reading, index) => (
                    <li key={index}>
                      <textarea
                        className="pa-doc-input"
                        rows={2}
                        aria-label={"Reading " + (index + 1)}
                        value={reading}
                        onChange={(event) => setReading(index, event.target.value)}
                      />
                    </li>
                  ))}
                </ol>
                <div className="pa-doc-row-tools">
                  <Button type="button" variant="ghost" size="sm" onClick={addReading}>
                    <Plus className="h-4 w-4" />
                    Add reading
                  </Button>
                  {(draft.readings ?? []).length > 0 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => dropRow("readings", (draft.readings ?? []).length - 1)}
                    >
                      <X className="h-4 w-4" />
                      Remove last reading
                    </Button>
                  )}
                </div>
              </Section>

              <Section title="5. Assessment">
                <DocSubsection id="assessment" title="5.1 Assessment of learning outcomes">
                  <div className="pa-doc-table-scroll">
                    <table className="pa-doc-table">
                      <thead>
                        <tr>
                          <th scope="col">Learning outcome</th>
                          <th scope="col">Measures</th>
                          <th scope="col">
                            <span className="pa-doc-sr-only">Remove</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {(draft.outcome_measures ?? []).map((row, index) => (
                          <tr key={row.lo_code + "-" + index}>
                            <td>
                              <input
                                className="pa-doc-input"
                                aria-label={"Learning outcome code for measure row " + (index + 1)}
                                value={row.lo_code}
                                onChange={(event) =>
                                  setMeasure(index, "lo_code", event.target.value)
                                }
                              />
                            </td>
                            <td>
                              <input
                                className="pa-doc-input"
                                aria-label={"Measures for measure row " + (index + 1)}
                                value={row.measures}
                                onChange={(event) =>
                                  setMeasure(index, "measures", event.target.value)
                                }
                              />
                            </td>
                            <td className="pa-doc-cell-tool">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                aria-label="Remove this measure row"
                                onClick={() => dropRow("outcome_measures", index)}
                              >
                                <X className="h-3.5 w-3.5" />
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="pa-doc-row-tools">
                    <Button type="button" variant="ghost" size="sm" onClick={addMeasure}>
                      <Plus className="h-4 w-4" />
                      Add measure
                    </Button>
                  </div>
                </DocSubsection>
              </Section>

              <AssessmentDetail editing body={draft} onChange={patch} />
              <GuidanceSections editing body={draft} onChange={patch} />
            </div>
          ) : (
            <div className="pa-artifact-scroll" ref={paperRef}>
              <PaperPage index={1} total={7} courseName={name || "Untitled subject"}>
                <header className="pa-doc-head">
                  {code && <p className="pa-doc-kicker">{code}</p>}
                  <h1>{name || "Untitled subject"}</h1>
                  {sources.length > 0 && (
                    <p className="pa-doc-sources">{"Prepared from: " + sources.join(", ")}</p>
                  )}
                </header>

                <Section
                  id="subject-details"
                  title="Subject details"
                  onEdit={() => startEdit("subject-details")}
                >
                  <table className="pa-doc-table is-keyval">
                    <tbody>
                      {SUBJECT_FIELDS.map((item) => (
                        <KeyValue
                          key={item.key}
                          label={item.label}
                          value={
                            item.key === "equivalent_subjects"
                              ? equivalentOf(basics)
                              : field(basics[item.key])
                          }
                        />
                      ))}
                    </tbody>
                  </table>
                </Section>

                <Section
                  id="lecture"
                  title="Lecture information"
                  onEdit={() => startEdit("lecture")}
                >
                  <table className="pa-doc-table is-keyval">
                    <tbody>
                      {LECTURE_FIELDS.map((item) => (
                        <KeyValue
                          key={item.key}
                          label={item.label}
                          value={field(lecture[item.key])}
                        />
                      ))}
                    </tbody>
                  </table>
                </Section>
              </PaperPage>

              <PaperPage index={2} total={7} courseName={name || "Untitled subject"}>
                <Section
                  id="description"
                  title="1. Subject description"
                  onEdit={() => startEdit("description")}
                >
                  <p className="pa-doc-body-text">{body.description || "No description yet."}</p>
                </Section>

                <Section
                  id="outcomes"
                  title="2. Learning Outcome and contribution to PLO"
                  onEdit={() => startEdit("outcomes")}
                >
                  {body.program && <p className="pa-doc-note">Program: {body.program}</p>}
                  <h3 className="pa-doc-subhead">Program learning outcomes</h3>
                  {plos.length ? (
                    <table className="pa-doc-table">
                      <thead>
                        <tr>
                          <th scope="col">PLO</th>
                          <th scope="col">Description</th>
                        </tr>
                      </thead>
                      <tbody>
                        {plos.map((plo, index) => (
                          <tr key={plo.code || index}>
                            <th scope="row">{plo.code || "PLO " + (index + 1)}</th>
                            <td>{plo.text}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="pa-doc-empty">No program learning outcomes yet.</p>
                  )}

                  <h3 className="pa-doc-subhead">
                    Map of learning outcomes to program learning outcomes
                  </h3>
                  <LoPloMatrix clos={clos} plos={plos} />
                </Section>
              </PaperPage>

              <PaperPage index={3} total={7} courseName={name || "Untitled subject"}>
                <Section
                  id="schedule"
                  title="3. Subject schedule"
                  onEdit={() => startEdit("schedule")}
                >
                  {weeks.length ? (
                    <div className="pa-doc-table-scroll">
                      <table className="pa-doc-table">
                        <thead>
                          <tr>
                            {SCHEDULE_COLUMNS.map((column) => (
                              <th key={column.key} scope="col">
                                {column.label}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {weeks.map((week, index) => (
                            <tr key={String(week.week ?? index)}>
                              {SCHEDULE_COLUMNS.map((column) => (
                                <td key={column.key}>
                                  {column.key === "lo_codes"
                                    ? listField(week.lo_codes)
                                    : field(week[column.key])}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="pa-doc-empty">No subject schedule yet.</p>
                  )}
                </Section>
              </PaperPage>

              <PaperPage index={4} total={7} courseName={name || "Untitled subject"}>
                <Section
                  id="readings"
                  title="4. Supporting materials"
                  onEdit={() => startEdit("readings")}
                >
                  <p className="pa-doc-note">
                    Read the following materials before each session; they support the lecture and
                    the workshop.
                  </p>
                  {readings.length ? (
                    <ol className="pa-doc-readings">
                      {readings.map((reading, index) => (
                        <li key={index}>{reading}</li>
                      ))}
                    </ol>
                  ) : (
                    <p className="pa-doc-empty">No readings yet.</p>
                  )}
                </Section>

                <Section title="5. Assessment">
                  <DocSubsection
                    id="assessment"
                    title="5.1 Assessment of learning outcomes"
                    onEdit={() => startEdit("assessment")}
                  >
                    {outcomeMeasures.length ? (
                      <div className="pa-doc-table-scroll">
                        <table className="pa-doc-table">
                          <thead>
                            <tr>
                              <th scope="col">Learning outcome</th>
                              <th scope="col">Measures</th>
                            </tr>
                          </thead>
                          <tbody>
                            {outcomeMeasures.map((row, index) => (
                              <tr key={row.lo_code + "-" + index}>
                                <th scope="row">{row.lo_code || "LO" + (index + 1)}</th>
                                <td>{row.measures}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="pa-doc-empty">No assessment map yet.</p>
                    )}
                  </DocSubsection>
                </Section>
              </PaperPage>

              <PaperPage index={5} total={7} courseName={name || "Untitled subject"}>
                <AssessmentDetail
                  editing={false}
                  body={body}
                  onChange={patch}
                  onEdit={startEdit}
                  part="tasks"
                />
              </PaperPage>

              <PaperPage index={6} total={7} courseName={name || "Untitled subject"}>
                <AssessmentDetail
                  editing={false}
                  body={body}
                  onChange={patch}
                  onEdit={startEdit}
                  part="guides"
                />
              </PaperPage>

              <PaperPage index={7} total={7} courseName={name || "Untitled subject"}>
                <GuidanceSections editing={false} body={body} onChange={patch} onEdit={startEdit} />
              </PaperPage>
            </div>
          )}
        </CardContent>
      </Card>

      {!editing ? (
        <Card className="mx-auto mt-4 w-full max-w-[820px] print:hidden">
          <CardContent className="p-0">
            <Button
              type="button"
              variant="ghost"
              className="flex w-full items-center justify-between gap-2 rounded-none px-4 py-3"
              aria-expanded={annotationsOpen}
              onClick={() => setAnnotationsOpen((value) => !value)}
            >
              <span className="flex items-center gap-2 text-sm font-semibold">
                <Highlighter className="h-4 w-4" />
                Annotations
              </span>
              <span className="flex items-center gap-2">
                <Badge variant="secondary">{annotations.length}</Badge>
                <ChevronDown
                  className={
                    "h-4 w-4 transition-transform " + (annotationsOpen ? "rotate-180" : "")
                  }
                />
              </span>
            </Button>
            {annotationsOpen ? (
              <div className="border-t px-4 py-3">
                {annotations.length ? (
                  <ul className="space-y-3">
                    {annotations.map((annotation) => (
                      <li key={annotation.id} className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline">
                            {annotation.sectionTitle || annotation.sectionKey || "Document"}
                          </Badge>
                          <span className="text-muted-foreground text-xs">
                            {new Date(annotation.createdAt).toLocaleDateString()}
                          </span>
                        </div>
                        <blockquote className="border-l-2 pl-3 text-sm italic">
                          {annotation.quote}
                        </blockquote>
                        {annotation.note ? <p className="text-sm">{annotation.note}</p> : null}
                        <div className="flex items-center gap-1">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              askAi({
                                quote: annotation.quote,
                                sectionTitle: annotation.sectionTitle,
                              })
                            }
                          >
                            <Sparkles className="h-3.5 w-3.5" />
                            Ask AI
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => removeAnnotation(annotation.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Remove
                          </Button>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-muted-foreground text-sm">
                    Select text in the outline to highlight it or add a note.
                  </p>
                )}
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {!editing && selectionTarget ? (
        <div
          className="pa-selection-toolbar"
          data-pa-selection-toolbar=""
          role="toolbar"
          aria-label="Selected text actions"
          style={{
            left: selectionTarget.x,
            top: selectionTarget.y,
            transform: selectionTarget.below
              ? "translate(-50%, 12px)"
              : "translate(-50%, calc(-100% - 12px))",
          }}
        >
          <Button type="button" variant="ghost" size="sm" onClick={() => saveAnnotation("")}>
            <Highlighter className="h-3.5 w-3.5" />
            Highlight
          </Button>
          <Popover open={annotateOpen} onOpenChange={setAnnotateOpen}>
            <PopoverTrigger asChild>
              <Button type="button" variant="ghost" size="sm">
                <MessageSquarePlus className="h-3.5 w-3.5" />
                Annotate
              </Button>
            </PopoverTrigger>
            <PopoverContent
              data-pa-selection-toolbar=""
              side="top"
              align="center"
              className="w-72 space-y-2"
              role="dialog"
              aria-label="Add annotation note"
            >
              <p className="text-sm font-semibold">Add a note</p>
              <blockquote className="text-muted-foreground border-l-2 pl-2 text-xs italic">
                {selectionTarget.quote}
              </blockquote>
              <Textarea
                rows={3}
                value={noteDraft}
                onChange={(event) => setNoteDraft(event.target.value)}
                placeholder="What do you want to remember or change?"
                aria-label="Annotation note"
              />
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setAnnotateOpen(false);
                    setNoteDraft("");
                  }}
                >
                  Cancel
                </Button>
                <Button type="button" size="sm" onClick={() => saveAnnotation(noteDraft)}>
                  Save note
                </Button>
              </div>
            </PopoverContent>
          </Popover>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() =>
              askAi({
                quote: selectionTarget.quote,
                sectionTitle: selectionTarget.sectionTitle,
              })
            }
          >
            <Sparkles className="h-3.5 w-3.5" />
            Ask AI
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Dismiss"
            onClick={() => {
              setSelectionTarget(null);
              setAnnotateOpen(false);
            }}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
