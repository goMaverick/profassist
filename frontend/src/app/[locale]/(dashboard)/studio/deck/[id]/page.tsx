"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Check,
  Download,
  Loader2,
  Pencil,
  Plus,
  Save,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import { pa } from "@/components/profassist/bits";
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
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui";
import { ProfassistError, type SlideReview, type SlideReviewIssue } from "@/lib/profassist";

interface Citation {
  filename: string;
  quote?: string;
  section?: string;
  chunk_id?: string;
}

interface Bullet {
  text: string;
  citation?: Citation;
}

interface Slide {
  title: string;
  bullets: Bullet[];
  speaker_notes?: string;
}

/** Cited bullets go back as objects; everything else stays a plain string. */
interface BulletPayload {
  text: string;
  citation: Citation;
}

interface SlidePayload {
  title: string;
  bullets: Array<string | BulletPayload>;
  speaker_notes?: string;
}

interface Deck {
  id: string;
  course_id?: string;
  title: string;
  status: string;
  week?: number;
  slides: Slide[];
  instructions?: string;
  review?: SlideReview;
  review_trace_url?: string;
}

interface AssistResponse {
  reply?: string;
  deck?: Deck;
  changed_slides?: unknown;
}

interface ReviewResponse {
  review?: SlideReview | null;
  trace_url?: string;
}

type Busy = "" | "save" | "approve" | "download" | "review";

function describeError(err: unknown, fallback: string) {
  if (err instanceof ProfassistError) {
    return err.status ? `${err.message} (HTTP ${err.status})` : err.message;
  }
  return err instanceof Error && err.message ? err.message : fallback;
}

/** Only a citation that names a source file is worth showing. */
function citationFrom(raw: unknown): Citation | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const row = raw as Record<string, unknown>;
  const filename = typeof row.filename === "string" ? row.filename.trim() : "";
  if (!filename) return undefined;
  const citation: Citation = { filename };
  if (typeof row.quote === "string" && row.quote) citation.quote = row.quote;
  if (typeof row.section === "string" && row.section) citation.section = row.section;
  if (typeof row.chunk_id === "string" && row.chunk_id) citation.chunk_id = row.chunk_id;
  return citation;
}

/** A bullet is a plain string on older decks and {text, citation} on cited ones. */
function normalizeBullet(raw: unknown): Bullet | null {
  if (typeof raw === "string") return raw.trim() ? { text: raw } : null;
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const text =
    typeof row.text === "string" ? row.text : typeof row.bullet === "string" ? row.bullet : "";
  if (!text.trim()) return null;
  const citation = citationFrom(row.citation);
  return citation ? { text, citation } : { text };
}

function normalizeSlide(raw: unknown): Slide {
  if (!raw || typeof raw !== "object") return { title: "", bullets: [] };
  const row = raw as Record<string, unknown>;
  const slide: Slide = {
    title: typeof row.title === "string" ? row.title : "",
    bullets: Array.isArray(row.bullets)
      ? row.bullets.map(normalizeBullet).filter((bullet): bullet is Bullet => bullet !== null)
      : [],
  };
  const notes =
    typeof row.speaker_notes === "string" && row.speaker_notes
      ? row.speaker_notes
      : typeof row.notes === "string" && row.notes
        ? row.notes
        : "";
  if (notes) slide.speaker_notes = notes;
  return slide;
}

const REVIEW_SEVERITIES = new Set(["high", "medium", "low", "info"]);

function normalizeIssue(raw: unknown): SlideReviewIssue | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const issue = typeof row.issue === "string" ? row.issue.trim() : "";
  if (!issue) return null;
  const severity =
    typeof row.severity === "string" && REVIEW_SEVERITIES.has(row.severity)
      ? (row.severity as SlideReviewIssue["severity"])
      : "medium";
  const slide =
    typeof row.slide === "number" ? row.slide : typeof row.slide === "string" ? row.slide : "Deck";
  return {
    slide,
    severity,
    issue,
    fix: typeof row.fix === "string" ? row.fix.trim() : "",
  };
}

/** An empty object from the API means the deck has not been reviewed yet. */
function normalizeReview(raw: unknown): SlideReview | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const row = raw as Record<string, unknown>;
  const verdict = row.verdict === "pass" || row.verdict === "revise" ? row.verdict : undefined;
  if (!verdict) return undefined;
  const review: SlideReview = {
    verdict,
    score: typeof row.score === "number" && Number.isFinite(row.score) ? row.score : 0,
    issues: Array.isArray(row.issues)
      ? row.issues.map(normalizeIssue).filter((item): item is SlideReviewIssue => item !== null)
      : [],
    strengths: Array.isArray(row.strengths)
      ? row.strengths.filter(
          (item): item is string => typeof item === "string" && item.trim() !== "",
        )
      : [],
    checks: Array.isArray(row.checks) ? row.checks : [],
  };
  if (row.degraded === true) review.degraded = true;
  if (typeof row.trace_url === "string" && row.trace_url) review.trace_url = row.trace_url;
  return review;
}

/** The contract sends a whole deck back; still tolerate a partial payload. */
function normalizeDeck(raw: Deck | null | undefined, fallbackId: string): Deck {
  const deck: Deck = {
    id: raw && typeof raw.id === "string" && raw.id ? raw.id : fallbackId,
    title: raw && typeof raw.title === "string" && raw.title ? raw.title : "Untitled deck",
    status: raw && typeof raw.status === "string" && raw.status ? raw.status : "draft",
    slides: raw && Array.isArray(raw.slides) ? raw.slides.map(normalizeSlide) : [],
  };
  if (raw && typeof raw.course_id === "string" && raw.course_id) deck.course_id = raw.course_id;
  if (raw && typeof raw.week === "number") deck.week = raw.week;
  if (raw && typeof raw.instructions === "string" && raw.instructions) {
    deck.instructions = raw.instructions;
  }
  const review = normalizeReview(raw?.review);
  if (review) deck.review = review;
  if (raw && typeof raw.review_trace_url === "string" && raw.review_trace_url) {
    deck.review_trace_url = raw.review_trace_url;
  }
  return deck;
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

/** A human heading for a deck whose stored title may be an id or a placeholder. */
function deckHeading(deck: Deck): string {
  const stored = deck.title.trim();
  if (stored && stored !== "Untitled deck" && !uuidLike(stored)) return stored;
  const week = deck.week ? `Week ${deck.week}` : "";
  const slide = deck.slides[0]?.title?.trim() ?? "";
  if (week && slide) return `${week} \u2014 ${slide}`;
  if (week) return week;
  return "Deck";
}

function copyBullet(bullet: Bullet): Bullet {
  const copy: Bullet = { text: bullet.text };
  if (bullet.citation) copy.citation = { ...bullet.citation };
  return copy;
}

function copySlide(slide: Slide): Slide {
  const copy: Slide = { title: slide.title, bullets: slide.bullets.map(copyBullet) };
  if (slide.speaker_notes) copy.speaker_notes = slide.speaker_notes;
  return copy;
}

/** The PUT payload: trim what the professor typed, drop empty rows, keep citations. */
function cleanSlide(slide: Slide): SlidePayload {
  const bullets: Array<string | BulletPayload> = [];
  for (const bullet of slide.bullets) {
    const text = bullet.text.trim();
    if (!text) continue;
    if (bullet.citation) {
      bullets.push({ text, citation: { ...bullet.citation } });
    } else {
      bullets.push(text);
    }
  }
  const clean: SlidePayload = { title: slide.title.trim(), bullets };
  const notes = slide.speaker_notes?.trim();
  if (notes) clean.speaker_notes = notes;
  return clean;
}

function bulletFromPayload(raw: string | BulletPayload): Bullet {
  if (typeof raw === "string") return { text: raw };
  return raw.citation
    ? { text: raw.text, citation: { ...raw.citation } }
    : { text: raw.text };
}

function slideFromPayload(payload: SlidePayload): Slide {
  const slide: Slide = {
    title: payload.title,
    bullets: payload.bullets.map(bulletFromPayload),
  };
  if (payload.speaker_notes) slide.speaker_notes = payload.speaker_notes;
  return slide;
}

/** Hover text for a source chip: the section and the quoted line when present. */
function citationHint(citation: Citation): string {
  const parts = [citation.section, citation.quote].filter(
    (part): part is string => typeof part === "string" && part.trim() !== "",
  );
  return parts.length > 0 ? parts.join(" — ") : citation.filename;
}

function safeFileName(title: string) {
  return title.replace(/[\\/:*?"<>|]/g, "-").trim() || "deck";
}

function changedSlideLabels(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => {
      if (typeof item === "number") return `slide ${item + 1}`;
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const row = item as { index?: unknown; title?: unknown };
        if (typeof row.index === "number") return `slide ${row.index + 1}`;
        if (typeof row.title === "string") return row.title;
      }
      return "";
    })
    .filter(Boolean);
}

function EnhanceBubble({
  deckId,
  slideIndex,
  label,
  onApplied,
}: {
  deckId: string;
  slideIndex: number;
  label: string;
  onApplied: (deck: Deck) => void;
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
      const data = await pa<AssistResponse>(`/slides/${deckId}/assist`, {
        method: "POST",
        body: JSON.stringify({ message: instruction, slide_index: slideIndex }),
      });
      const changed = changedSlideLabels(data?.changed_slides);
      const said = data?.reply?.trim() || "The deck was updated.";
      setReply(changed.length ? `${said} Changed: ${changed.join(", ")}.` : said);
      setMessage("");
      if (data?.deck) onApplied(data.deck);
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
          aria-label={`Enhance ${label}`}
          className="text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900"
        >
          <Sparkles />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <div className="space-y-3">
          <div>
            <p className="text-sm font-medium">Enhance: {label}</p>
            <p className="text-muted-foreground text-xs">
              The AI edits this deck draft. Nothing is published.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`enhance-slide-${slideIndex}`} className="sr-only">
              Change for {label}
            </Label>
            <Textarea
              id={`enhance-slide-${slideIndex}`}
              rows={3}
              value={message}
              disabled={busy}
              placeholder="e.g. rewrite slide 3 with an example"
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
          <div className="flex items-center justify-end">
            <Button type="button" size="sm" onClick={() => void send()} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" /> : <Send />}
              {busy ? "Enhancing..." : "Enhance"}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

const SEVERITY_TONE: Record<SlideReviewIssue["severity"], string> = {
  high: "border-transparent bg-red-100 text-red-800",
  medium: "border-transparent bg-amber-100 text-amber-800",
  low: "border-transparent bg-blue-100 text-blue-800",
  info: "border-transparent bg-slate-100 text-slate-700",
};

function slideLabel(slide: SlideReviewIssue["slide"]): string {
  if (typeof slide === "number") return `Slide ${slide}`;
  return slide.trim() || "Deck";
}

function groupIssues(issues: SlideReviewIssue[]) {
  const groups: Array<{ label: string; issues: SlideReviewIssue[] }> = [];
  const byLabel = new Map<string, { label: string; issues: SlideReviewIssue[] }>();
  for (const issue of issues) {
    const label = slideLabel(issue.slide);
    const group = byLabel.get(label);
    if (group) {
      group.issues.push(issue);
    } else {
      const created = { label, issues: [issue] };
      byLabel.set(label, created);
      groups.push(created);
    }
  }
  return groups;
}

function ReviewPanel({
  review,
  traceUrl,
  busy,
  onReview,
}: {
  review?: SlideReview;
  traceUrl: string;
  busy: boolean;
  onReview: () => void;
}) {
  const issues = review?.issues ?? [];
  const strengths = review?.strengths ?? [];
  const groups = groupIssues(issues);
  const passed = review?.verdict === "pass";
  return (
    <section aria-label="Deck review" className="bg-card mb-4 rounded-lg border p-4 print:hidden">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 className="text-sm font-semibold">Deck review</h2>
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
              {traceUrl ? (
                <a
                  className="text-xs underline underline-offset-4"
                  href={traceUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Traced
                </a>
              ) : null}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">
              No review yet. Review checks citations, coverage, and slide quality.
            </p>
          )}
        </div>
        <Button type="button" size="sm" variant="outline" onClick={onReview} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
          {review ? "Review again" : "Review"}
        </Button>
      </div>
      {review ? (
        <>
          {review.degraded ? (
            <p className="mt-3 text-xs text-amber-700">
              Deterministic checks only; the model review was unavailable.
            </p>
          ) : null}
          {strengths.length > 0 ? (
            <div className="mt-3">
              <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                Strengths
              </p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-neutral-700">
                {strengths.map((strength, index) => (
                  <li key={`${strength}-${index}`}>{strength}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="mt-3 space-y-3">
            {groups.length === 0 ? (
              <p className="text-muted-foreground text-sm">No issues found.</p>
            ) : (
              groups.map((group) => (
                <div key={group.label}>
                  <p className="text-sm font-medium">{group.label}</p>
                  <ul className="mt-1 space-y-2">
                    {group.issues.map((issue, index) => (
                      <li
                        key={`${group.label}-${index}`}
                        className="bg-background/60 rounded-md border p-2"
                      >
                        <div className="flex flex-wrap items-start gap-2">
                          <Badge className={SEVERITY_TONE[issue.severity]}>{issue.severity}</Badge>
                          <p className="min-w-0 flex-1 text-sm">{issue.issue}</p>
                        </div>
                        {issue.fix ? (
                          <p className="text-muted-foreground mt-1 text-xs">Fix: {issue.fix}</p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}

export default function DeckArtifactPage() {
  const params = useParams();
  const rawId = params?.id;
  const deckId = Array.isArray(rawId) ? (rawId[0] ?? "") : (rawId ?? "");

  const [deck, setDeck] = useState<Deck | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<Busy>("");
  const [editingTitle, setEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [editingSlide, setEditingSlide] = useState<number | null>(null);
  const [slideDraft, setSlideDraft] = useState<Slide | null>(null);

  const load = useCallback(
    async (showLoading = true) => {
      if (!deckId) {
        setLoading(false);
        setLoadError("This page needs a deck id.");
        return;
      }
      if (showLoading) setLoading(true);
      try {
        const data = await pa<Deck>(`/slides/${deckId}`);
        setDeck(normalizeDeck(data, deckId));
        setLoadError("");
      } catch (err) {
        setDeck(null);
        setLoadError(describeError(err, "Could not open this deck."));
      } finally {
        setLoading(false);
      }
    },
    [deckId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const approved = (deck?.status ?? "").toLowerCase() === "approved";
  const dirty = editingTitle || editingSlide !== null;
  const status = deck?.status || "draft";
  const heading = deck ? deckHeading(deck) : "Deck";

  function stopEditing() {
    setEditingTitle(false);
    setDraftTitle("");
    setEditingSlide(null);
    setSlideDraft(null);
  }

  /** The toolbar Cancel only closes the title field; a slide draft stays open. */
  function cancelTitleEdit() {
    setEditingTitle(false);
    setDraftTitle("");
  }

  function startTitleEdit() {
    if (!deck || approved) return;
    setActionError("");
    setNotice("");
    setEditingTitle(true);
    setDraftTitle(uuidLike(deck.title) ? "" : deck.title);
  }

  function startSlideEdit(index: number) {
    if (!deck || approved) return;
    const slide = deck.slides[index];
    if (!slide) return;
    setActionError("");
    setNotice("");
    setEditingSlide(index);
    setSlideDraft(copySlide(slide));
  }

  function cancelSlideEdit() {
    setEditingSlide(null);
    setSlideDraft(null);
  }

  function patchSlideDraft(patch: Partial<Slide>) {
    setSlideDraft((current) => (current ? { ...current, ...patch } : current));
  }

  function setBullet(index: number, value: string) {
    setSlideDraft((current) =>
      current
        ? {
            ...current,
            bullets: current.bullets.map((bullet, position) =>
              // Editing the text means it no longer matches the quoted source.
              position === index ? { text: value } : bullet,
            ),
          }
        : current,
    );
  }

  function addBullet() {
    setSlideDraft((current) =>
      current ? { ...current, bullets: [...current.bullets, { text: "" }] } : current,
    );
  }

  function removeBullet(index: number) {
    setSlideDraft((current) =>
      current
        ? { ...current, bullets: current.bullets.filter((_, position) => position !== index) }
        : current,
    );
  }

  function applyDeck(raw: Deck) {
    setDeck((current) => {
      const merged = normalizeDeck(raw, current?.id ?? deckId);
      if (!current) return merged;
      return {
        ...current,
        ...merged,
        course_id: merged.course_id ?? current.course_id,
        week: merged.week ?? current.week,
        instructions: merged.instructions ?? current.instructions,
      };
    });
  }

  async function save(quiet = false): Promise<boolean> {
    if (!deck) return false;
    setBusy("save");
    setActionError("");
    if (!quiet) setNotice("");

    const slides = deck.slides.map((slide, index) =>
      cleanSlide(index === editingSlide && slideDraft ? slideDraft : slide),
    );
    const body: { title?: string; slides: SlidePayload[] } = { slides };
    const nextTitle = draftTitle.trim();
    if (editingTitle && nextTitle && nextTitle !== deck.title) body.title = nextTitle;

    try {
      const saved = await pa<Deck | null>(`/slides/${deck.id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      if (saved && Array.isArray(saved.slides)) {
        applyDeck(saved);
      } else {
        setDeck((current) =>
          current
            ? {
                ...current,
                title: body.title ?? current.title,
                slides: slides.map(slideFromPayload),
              }
            : current,
        );
      }
      stopEditing();
      if (!quiet) setNotice("Deck saved.");
      return true;
    } catch (err) {
      setActionError(describeError(err, "The deck could not be saved."));
      return false;
    } finally {
      setBusy("");
    }
  }

  async function approve() {
    if (!deck || approved) return;
    // Approval reads the stored deck, so unsaved edits are flushed first.
    if (dirty) {
      const saved = await save(true);
      if (!saved) return;
    }
    setBusy("approve");
    setActionError("");
    setNotice("");
    try {
      const result = await pa<Deck | null>(`/slides/${deck.id}/approve`, { method: "POST" });
      const nextStatus =
        result && typeof result.status === "string" && result.status ? result.status : "approved";
      if (result && Array.isArray(result.slides)) {
        applyDeck(result);
      } else {
        setDeck((current) => (current ? { ...current, status: nextStatus } : current));
      }
      setNotice(`Deck ${nextStatus}.`);
    } catch (err) {
      setActionError(describeError(err, "The deck could not be approved."));
    } finally {
      setBusy("");
    }
  }

  async function downloadPptx() {
    if (!deck) return;
    setBusy("download");
    setActionError("");
    setNotice("");
    try {
      const blob = await pa<Blob>(`/slides/${deck.id}/pptx`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${safeFileName(deck.title)}.pptx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setActionError(describeError(err, "The PPTX could not be downloaded."));
    } finally {
      setBusy("");
    }
  }

  /** Advisory only: it persists the review but never edits or approves the deck. */
  async function runReview() {
    if (!deck) return;
    setBusy("review");
    setActionError("");
    setNotice("");
    try {
      const result = await pa<ReviewResponse>(`/slides/${deck.id}/review`, { method: "POST" });
      const nextReview = normalizeReview(result?.review);
      if (nextReview) {
        setDeck((current) =>
          current
            ? {
                ...current,
                review: nextReview,
                review_trace_url:
                  result?.trace_url || nextReview.trace_url || current.review_trace_url,
              }
            : current,
        );
      }
      await load(false);
      setNotice("Review updated.");
    } catch (err) {
      setActionError(describeError(err, "The deck could not be reviewed."));
    } finally {
      setBusy("");
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-[900px] space-y-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-[560px] w-full" />
      </div>
    );
  }

  if (!deck) {
    return (
      <div className="mx-auto w-full max-w-[900px] space-y-3">
        <Button asChild variant="ghost" size="sm">
          <Link href="/studio">
            <ArrowLeft />
            Studio
          </Link>
        </Button>
        <Alert variant="destructive">
          <AlertTitle>Could not open this deck</AlertTitle>
          <AlertDescription>{loadError || "The deck was empty."}</AlertDescription>
        </Alert>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1200px]">
      <div className="bg-background/95 supports-[backdrop-filter]:bg-background/80 sticky top-14 z-30 -mx-1 mb-4 border-b px-1 py-2 backdrop-blur print:hidden">
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="ghost" size="sm" className="-ml-2 shrink-0">
            <Link href="/studio">
              <ArrowLeft />
              Studio
            </Link>
          </Button>
          <div className="mr-auto min-w-0">
            <p className="text-muted-foreground truncate text-[11px] font-medium tracking-wide uppercase">
              {deck.week ? `Week ${deck.week}` : "Lecture deck"}
            </p>
            <p className="truncate text-sm font-semibold">{heading}</p>
          </div>
          <Badge variant={approved ? "default" : "secondary"}>{status}</Badge>
          <div className="flex flex-wrap items-center gap-1.5">
            {editingTitle ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={cancelTitleEdit}
                disabled={busy !== ""}
              >
                <X />
                Cancel
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={startTitleEdit}
                disabled={approved || busy !== ""}
                title={approved ? "This deck is approved and read-only" : "Edit the deck title"}
              >
                <Pencil />
                Edit
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              onClick={() => void save()}
              disabled={!dirty || busy !== "" || approved}
            >
              {busy === "save" ? <Loader2 className="animate-spin" /> : <Save />}
              {busy === "save" ? "Saving..." : "Save"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void downloadPptx()}
              disabled={busy === "download"}
            >
              {busy === "download" ? <Loader2 className="animate-spin" /> : <Download />}
              Download PPTX
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void runReview()}
              disabled={busy !== ""}
              aria-label="Review deck"
              title="Review this deck (advisory only)"
            >
              {busy === "review" ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
              Review
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void approve()}
              disabled={approved || busy !== ""}
              title={approved ? "This deck is already approved" : "Approve this deck"}
            >
              {busy === "approve" ? <Loader2 className="animate-spin" /> : <Check />}
              {approved ? "Approved" : busy === "approve" ? "Approving..." : "Approve"}
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

      <ReviewPanel
        review={deck.review}
        traceUrl={deck.review_trace_url || deck.review?.trace_url || ""}
        busy={busy === "review"}
        onReview={() => void runReview()}
      />

      <div className="pa-artifact-scroll">
        <h1 className="sr-only">{heading}</h1>
        <div className="mx-auto mb-4 max-w-[1120px] space-y-2">
          <p className="text-sm text-neutral-600">
            {deck.slides.length} slide{deck.slides.length === 1 ? "" : "s"}
            {approved ? " \u00b7 approved and read-only" : ""}
          </p>
          {deck.instructions ? (
            <p className="text-sm text-neutral-600">
              <span className="font-medium">Instructions:</span> {deck.instructions}
            </p>
          ) : null}
          {editingTitle ? (
            <div className="max-w-md space-y-1.5 print:hidden">
              <Label htmlFor="deck-title">Deck title</Label>
              <Input
                id="deck-title"
                value={draftTitle}
                disabled={busy !== ""}
                onChange={(event) => setDraftTitle(event.target.value)}
              />
            </div>
          ) : null}
        </div>

        {deck.slides.length === 0 ? (
          <section className="pa-doc-page pa-paper-page is-landscape">
            <div className="pa-paper-meta">
              <span className="pa-paper-course">{heading}</span>
              <span className="pa-paper-folio">Slide 0 of 0</span>
            </div>
            <p className="text-sm text-neutral-500">
              This deck has no slides yet. Ask the studio to draft it from your course notes.
            </p>
          </section>
        ) : (
          deck.slides.map((slide, index) => {
            const label = `slide ${index + 1}`;
            const isEditing = editingSlide === index && slideDraft !== null;
            return (
              <section key={index} className="pa-doc-page pa-paper-page is-landscape">
                <div className="pa-paper-meta">
                  <span className="pa-paper-course">
                    {deck.week ? `Week ${deck.week}` : heading}
                  </span>
                  <span className="pa-paper-folio">
                    {"Slide " + (index + 1) + " of " + deck.slides.length}
                  </span>
                </div>
                <div id={`slide-${index}`} className="group">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="text-[11px] font-medium tracking-wide text-neutral-500 uppercase">
                        Slide {index + 1}
                      </p>
                      {isEditing ? (
                        <div className="mt-2 space-y-3">
                          <div className="space-y-1.5">
                            <Label htmlFor={`slide-title-${index}`}>Slide title</Label>
                            <Input
                              id={`slide-title-${index}`}
                              value={slideDraft.title}
                              disabled={busy !== ""}
                              onChange={(event) => patchSlideDraft({ title: event.target.value })}
                            />
                          </div>
                          <div className="space-y-1.5">
                            <p className="text-sm font-medium">Bullets</p>
                            {slideDraft.bullets.length === 0 ? (
                              <p className="text-muted-foreground text-xs">
                                No bullets on this slide yet.
                              </p>
                            ) : null}
                            {slideDraft.bullets.map((bullet, bulletIndex) => (
                              <div key={bulletIndex} className="flex items-start gap-1.5">
                                <Textarea
                                  aria-label={`Slide ${index + 1} bullet ${bulletIndex + 1}`}
                                  rows={2}
                                  value={bullet.text}
                                  disabled={busy !== ""}
                                  onChange={(event) => setBullet(bulletIndex, event.target.value)}
                                />
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label={`Remove slide ${index + 1} bullet ${bulletIndex + 1}`}
                                  onClick={() => removeBullet(bulletIndex)}
                                  disabled={busy !== ""}
                                >
                                  <Trash2 />
                                </Button>
                              </div>
                            ))}
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={addBullet}
                              disabled={busy !== ""}
                            >
                              <Plus />
                              Add bullet
                            </Button>
                          </div>
                          <div className="space-y-1.5">
                            <Label htmlFor={`slide-notes-${index}`}>Speaker notes</Label>
                            <Textarea
                              id={`slide-notes-${index}`}
                              rows={3}
                              value={slideDraft.speaker_notes ?? ""}
                              disabled={busy !== ""}
                              placeholder="Optional notes for the presenter"
                              onChange={(event) =>
                                patchSlideDraft({ speaker_notes: event.target.value })
                              }
                            />
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={cancelSlideEdit}
                              disabled={busy !== ""}
                            >
                              <X />
                              Cancel
                            </Button>
                            <span className="text-muted-foreground text-xs">
                              Save in the toolbar to keep this slide.
                            </span>
                          </div>
                        </div>
                      ) : (
                        <>
                          <h2 className="mt-1 text-base font-semibold text-neutral-900">
                            {slide.title || "Untitled slide"}
                          </h2>
                          {slide.bullets.length > 0 ? (
                            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-neutral-700">
                              {slide.bullets.map((bullet, bulletIndex) => (
                                <li key={bulletIndex}>
                                  {bullet.text}
                                  {bullet.citation ? (
                                    <>
                                      {" "}
                                      <span
                                        className="text-muted-foreground text-xs"
                                        title={citationHint(bullet.citation)}
                                      >
                                        source: {bullet.citation.filename}
                                      </span>
                                    </>
                                  ) : null}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="mt-2 text-sm text-neutral-500">No bullets.</p>
                          )}
                          {slide.speaker_notes ? (
                            <p className="mt-3 border-l-2 border-neutral-200 pl-3 text-xs text-neutral-500">
                              <span className="font-medium text-neutral-600">Speaker notes:</span>{" "}
                              {slide.speaker_notes}
                            </p>
                          ) : null}
                        </>
                      )}
                    </div>
                    {!approved && !isEditing ? (
                      <div className="flex shrink-0 items-center gap-1 opacity-100 transition-opacity focus-within:opacity-100 sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100 print:hidden">
                        <EnhanceBubble
                          deckId={deck.id}
                          slideIndex={index}
                          label={label}
                          onApplied={applyDeck}
                        />
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-sm"
                              aria-label={`Edit ${label}`}
                              className="text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900"
                              onClick={() => startSlideEdit(index)}
                            >
                              <Pencil />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Edit {label}</TooltipContent>
                        </Tooltip>
                      </div>
                    ) : null}
                  </div>
                </div>
              </section>
            );
          })
        )}
      </div>
    </div>
  );
}
