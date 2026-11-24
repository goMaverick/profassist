"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, Send } from "lucide-react";

import { Banner, pa, run } from "@/components/profassist/bits";
import { CourseFiles, type CourseFile } from "@/components/profassist/course-files";
import { CourseMemoryPanel } from "@/components/profassist/course-memory-panel";
import { StudioCollab } from "@/components/profassist/studio-collab";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import { ProfassistError, type CollabDeck, type Course } from "@/lib/profassist";

interface Material {
  id: string;
  filename: string;
  status: string;
  pii_report?: { quarantined?: boolean; uncertain?: string[] };
}

/** Cited decks store bullets as objects; older decks store plain strings. */
type DeckBullet = string | { text?: string; citation?: unknown };

interface Deck {
  id: string;
  title: string;
  status: string;
  week?: number;
  slides: Array<{ title: string; bullets: DeckBullet[] }>;
  review?: { verdict?: string } | null;
}

interface OutlineSummary {
  id: string;
  code: string;
  name: string;
  course_id?: string;
  body?: {
    clos?: unknown[];
    weeks?: Array<{ week?: string | number; topic?: string }>;
    readings?: unknown[];
    basics?: { code?: string };
  };
}

interface Turn {
  role: "assistant" | "user";
  text: string;
  tone?: "error";
}

interface RequestPlan {
  weeks: number[];
  label: string;
}

const MAX_WEEK_CALLS = 24;
const INTRO = "What materials do you need, and how many decks?";

function messageOf(err: unknown) {
  if (err instanceof ProfassistError) {
    return err.status ? `${err.message} (HTTP ${err.status})` : err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

function normalizeCode(value?: string) {
  return (value || "").trim().toLowerCase();
}

function findOutline(outlines: OutlineSummary[], course: Course) {
  const linked = outlines.find((item) => item.course_id && item.course_id === course.id);
  if (linked) return linked;
  const byCode = outlines.find((item) => normalizeCode(item.code) === normalizeCode(course.code));
  if (byCode) return byCode;
  return (
    outlines.find(
      (item) => normalizeCode(item.body?.basics?.code) === normalizeCode(course.code),
    ) ?? null
  );
}

function weekRange(start: number, end: number) {
  return Array.from({ length: end - start + 1 }, (_, index) => start + index);
}

function uniqueSorted(weeks: number[]) {
  return Array.from(new Set(weeks)).sort((left, right) => left - right);
}

function validateWeeks(
  weeks: number[],
  knownWeeks: number,
  label: string,
): RequestPlan | { problem: string } {
  if (weeks.length > MAX_WEEK_CALLS) {
    return { problem: `I can draft up to ${MAX_WEEK_CALLS} week decks at a time.` };
  }
  if (weeks.some((week) => week < 1)) {
    return { problem: "Weeks start at 1." };
  }
  if (knownWeeks > 0) {
    const beyond = weeks.find((week) => week > knownWeeks);
    if (beyond !== undefined) {
      return { problem: `The outline has ${knownWeeks} weeks, so I cannot draft week ${beyond}.` };
    }
  }
  return { weeks, label };
}

/**
 * Parses the weekly decks the professor asked for. The studio route takes one week
 * per call, so a request always resolves to a concrete list of week numbers.
 */
function planRequest(text: string, knownWeeks: number): RequestPlan | { problem: string } {
  const lower = text.toLowerCase();
  if (!/deck|slide|week|lecture|material|note/.test(lower)) {
    return {
      problem: 'Tell me what to build, for example "3 decks: weeks 1-3" or "one deck per week".',
    };
  }

  const total = lower.match(/weeks?\s*(\d+)\s*(?:-|\u2013|\u2014|to)\s*(\d+)/);
  if (total) {
    const start = Number(total[1]);
    const end = Number(total[2]);
    if (start < 1 || end < start) {
      return { problem: 'That week range runs backwards. Try "weeks 1-3".' };
    }
    return validateWeeks(weekRange(start, end), knownWeeks, `weeks ${start}-${end}`);
  }

  const listed = lower.match(/weeks?\s*(\d+(?:\s*(?:,|and|&)\s*\d+)+)/);
  if (listed) {
    const weeks = uniqueSorted(((listed[1] ?? "").match(/\d+/g) ?? []).map(Number));
    return validateWeeks(weeks, knownWeeks, `weeks ${weeks.join(", ")}`);
  }

  if (/per\s+week|each\s+week/.test(lower)) {
    if (!knownWeeks) {
      return {
        problem:
          "I need the outline's week count to make one deck per week. Add the schedule in Course Designer first.",
      };
    }
    return validateWeeks(weekRange(1, knownWeeks), knownWeeks, `${knownWeeks} weeks`);
  }

  const single = lower.match(/week\s*(\d+)/);
  if (single) {
    const week = Number(single[1]);
    return validateWeeks([week], knownWeeks, `week ${week}`);
  }

  const counted = lower.match(/(\d+)\s*(?:lecture\s+|slide\s+)?decks?/);
  if (counted) {
    const wanted = Math.max(1, Number(counted[1]));
    const count = knownWeeks > 0 ? Math.min(wanted, knownWeeks) : wanted;
    if (count > MAX_WEEK_CALLS) {
      return { problem: `I can draft up to ${MAX_WEEK_CALLS} week decks at a time.` };
    }
    return {
      weeks: weekRange(1, count),
      label: `${count} deck${count === 1 ? "" : "s"}`,
    };
  }

  return { weeks: [1], label: "one deck" };
}

function instructionsFor(
  message: string,
  course: Course,
  week: number,
  outline: OutlineSummary | null,
) {
  const topic = outline?.body?.weeks?.[week - 1]?.topic?.trim();
  return [
    `Material Designer request: ${message}`,
    `Draft the week ${week} lecture deck for ${course.code} ${course.title}.`,
    topic ? `Outline topic for week ${week}: ${topic}.` : "",
    outline
      ? `Use the approved outline (${outline.code}) and cite the lecture notes in this course.`
      : "Use the lecture notes in this course.",
  ]
    .filter(Boolean)
    .join(" ");
}

function studioPath(courseId: string, week: number, instructions: string) {
  const params = new URLSearchParams({ week: String(week), instructions });
  return `/courses/${courseId}/slides/studio?${params.toString()}`;
}

function missingRoute(err: unknown) {
  return err instanceof ProfassistError && (err.status === 404 || err.status === 405);
}

function reviewBadge(review?: { verdict?: string } | null) {
  if (review?.verdict === "pass") {
    return { label: "Passed", className: "border-transparent bg-green-100 text-green-800" };
  }
  if (review?.verdict === "revise") {
    return { label: "Needs review", className: "border-transparent bg-amber-100 text-amber-800" };
  }
  return { label: "Not reviewed", className: "border-transparent bg-slate-100 text-slate-700" };
}

export default function StudioPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState("");
  const [outlines, setOutlines] = useState<OutlineSummary[] | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [decks, setDecks] = useState<Deck[]>([]);
  const [thread, setThread] = useState<Turn[]>([{ role: "assistant", text: INTRO }]);
  const [request, setRequest] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [collab, setCollab] = useState<{ week: number; instructions: string } | null>(null);
  const [collabDeck, setCollabDeck] = useState<CollabDeck | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  const course = useMemo(
    () => courses.find((item) => item.id === courseId) ?? null,
    [courses, courseId],
  );
  const outline = useMemo(
    () => (course && outlines ? findOutline(outlines, course) : null),
    [course, outlines],
  );
  const cloCount = outline?.body?.clos?.length ?? 0;
  const weekCount = outline?.body?.weeks?.length ?? 0;
  const readingCount = outline?.body?.readings?.length ?? 0;

  const refresh = useCallback(async (id: string) => {
    const [notes, slides] = await Promise.all([
      pa<{ items: Material[] }>(`/courses/${id}/materials`),
      pa<{ items: Deck[] }>(`/courses/${id}/slides`),
    ]);
    setMaterials(notes.items);
    setDecks(slides.items);
  }, []);

  useEffect(() => {
    let active = true;
    pa<{ courses: Course[] }>("/home")
      .then((home) => {
        if (!active) return;
        setCourses(home.courses);
        const saved = window.sessionStorage.getItem("pa-course") || "";
        const initial = home.courses.find((item) => item.id === saved) ?? home.courses[0] ?? null;
        setCourseId(initial?.id ?? "");
      })
      .catch((err: unknown) => {
        if (active) setError(messageOf(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    pa<{ items: OutlineSummary[] }>("/outlines")
      .then((data) => {
        if (active) setOutlines(data.items);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setOutlines([]);
        setError((current) => current || messageOf(err));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!courseId) return;
    window.sessionStorage.setItem("pa-course", courseId);
    setMaterials([]);
    setDecks([]);
    let active = true;
    refresh(courseId).catch((err: unknown) => {
      if (active) setError(messageOf(err));
    });
    return () => {
      active = false;
    };
  }, [courseId, refresh]);

  useEffect(() => {
    const node = threadRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [thread, busy]);

  function say(text: string, tone?: "error") {
    setThread((current) => [...current, { role: "assistant", text, tone }]);
  }

  async function submit() {
    const message = request.trim();
    if (!message || busy || !course || collab) return;
    setRequest("");
    setThread((current) => [...current, { role: "user", text: message }]);

    const plan = planRequest(message, weekCount);
    if ("problem" in plan) {
      say(plan.problem);
      return;
    }
    if (materials.length === 0) {
      say(
        "There are no course notes in this course yet. Upload a note below first - a deck only keeps bullets that appear in your notes.",
      );
      return;
    }

    if (plan.weeks.length === 1) {
      const week = plan.weeks[0] ?? 1;
      setCollab({ week, instructions: instructionsFor(message, course, week, outline) });
      return;
    }

    setBusy(true);
    let created = 0;
    let failure = "";
    let usedFallback = false;
    const createdWeeks: number[] = [];

    for (const week of plan.weeks) {
      try {
        const instructions = instructionsFor(message, course, week, outline);
        await pa<Deck>(studioPath(course.id, week, instructions), { method: "POST" });
        created += 1;
        createdWeeks.push(week);
      } catch (err) {
        if (!missingRoute(err)) {
          failure = messageOf(err);
          break;
        }
        // Older deployments do not have the per-week route. Draft one whole-course
        // deck once instead of repeating the same draft for every requested week.
        usedFallback = true;
        try {
          await pa<Deck>(`/courses/${course.id}/slides/draft`, { method: "POST" });
          created = 1;
        } catch (fallbackErr) {
          failure = messageOf(fallbackErr);
        }
        break;
      }
    }

    try {
      await refresh(course.id);
    } catch (err) {
      failure = failure || messageOf(err);
    }
    setBusy(false);

    if (failure) {
      say(
        created > 0
          ? `Drafted ${created} of ${plan.weeks.length} week decks. ${failure}`
          : `I could not draft a deck. ${failure}`,
        "error",
      );
      return;
    }

    const outlineNote = outline
      ? ""
      : " I do not see a course outline for this course, so the deck can only use your notes and approved outcomes.";
    if (usedFallback) {
      say(
        `The per-week studio route is not available on this deployment, so I drafted one whole-course deck instead of ${plan.label}. Review it below, download the PPTX, and approve when it looks right.${outlineNote}`,
      );
      return;
    }
    const weekLabel =
      createdWeeks.length === 1 ? `week ${createdWeeks[0]}` : `weeks ${createdWeeks.join(", ")}`;
    const plural = created === 1 ? "deck" : "decks";
    say(
      `Drafted ${created} ${plural} from the notes in ${course.code}: ${weekLabel}. Review below, download the PPTX, and approve when ready.${outlineNote}`,
    );
  }

  if (loading) return <p className="text-sm">Loading the studio...</p>;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      {error && <Banner>{error}</Banner>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Which course are we building materials for?</CardTitle>
          <CardDescription>
            Decks are drafted from this course&apos;s notes and approved outcomes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {courses.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              No course in this workspace yet.{" "}
              <Link className="underline" href="/outline">
                Create one in Course Designer
              </Link>
              .
            </p>
          ) : (
            <div className="grid gap-2">
              <Label htmlFor="studio-course" className="sr-only">
                Course
              </Label>
              <Select value={courseId} onValueChange={setCourseId}>
                <SelectTrigger id="studio-course">
                  <SelectValue placeholder="Choose a course" />
                </SelectTrigger>
                <SelectContent>
                  {courses.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {`${item.code} \u00b7 ${item.title}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </CardContent>
      </Card>

      {course && (
        <>
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
              <div className="space-y-1">
                <CardTitle className="text-base">
                  {outlines === null
                    ? "Looking for the course outline..."
                    : outline
                      ? "Using the course outline"
                      : "No course outline found"}
                </CardTitle>
                <CardDescription>
                  {outline
                    ? `${outline.code} \u00b7 ${outline.name}`
                    : outlines === null
                      ? "Checking the Course Designer."
                      : "Decks will use only the notes below. Add outcomes and a schedule in Course Designer."}
                </CardDescription>
              </div>
              <Button asChild variant="link" size="sm" className="shrink-0">
                <Link href="/outline">{outline ? "Open outline" : "Build outline"}</Link>
              </Button>
            </CardHeader>
            {outline && (
              <CardContent className="flex flex-col gap-2">
                <div className="flex flex-wrap gap-1">
                  <Badge variant="secondary">
                    {cloCount} CLO{cloCount === 1 ? "" : "s"}
                  </Badge>
                  <Badge variant="secondary">
                    {weekCount} week{weekCount === 1 ? "" : "s"}
                  </Badge>
                  <Badge variant="secondary">
                    {readingCount} reading{readingCount === 1 ? "" : "s"}
                  </Badge>
                </div>
                {cloCount + weekCount + readingCount === 0 ? (
                  <p className="text-muted-foreground text-xs">
                    The outline is linked but has no outcomes, schedule, or readings yet.
                  </p>
                ) : (
                  <p className="text-muted-foreground text-xs">
                    The week count sizes a &ldquo;one deck per week&rdquo; request. Decks still cite
                    the notes below.
                  </p>
                )}
              </CardContent>
            )}
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Materials</CardTitle>
              <CardDescription>
                Say what you need. I will draft with this course&apos;s notes.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <p className="text-muted-foreground text-xs">
                Single-week requests run a Creator + Council pass before the deck reaches you.
              </p>
              {collab && course && (
                <StudioCollab
                  courseId={course.id}
                  week={collab.week}
                  instructions={collab.instructions}
                  onDone={(deck) => {
                    // Keep the panel mounted: the "Deck ready" card and its link
                    // must stay visible until the professor closes it.
                    setCollabDeck(deck);
                    say("Creator and council finished. Open the deck to keep editing.");
                    refresh(course.id).catch((err: unknown) => setError(messageOf(err)));
                  }}
                  onCancel={() => setCollab(null)}
                />
              )}
              {collabDeck && !collab && (
                <p className="text-muted-foreground text-xs">
                  Latest draft:{" "}
                  <Link className="underline" href={`/studio/deck/${collabDeck.id}`}>
                    {collabDeck.title || "open the deck"}
                  </Link>
                  .
                </p>
              )}
              <div
                ref={threadRef}
                className="border-border/70 bg-muted/30 flex max-h-72 flex-col gap-2 overflow-y-auto rounded-lg border p-3"
                aria-live="polite"
              >
                {thread.map((turn, index) => (
                  <div
                    key={`${index}-${turn.role}`}
                    className={cn(
                      "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                      turn.role === "user"
                        ? "bg-primary text-primary-foreground self-end"
                        : "bg-background self-start border",
                      turn.tone === "error" && "border-destructive/40 text-destructive",
                    )}
                  >
                    {turn.text}
                  </div>
                ))}
                {busy && (
                  <div className="bg-background self-start rounded-lg border px-3 py-2 text-sm">
                    Drafting the deck...
                  </div>
                )}
              </div>
              <form
                className="flex flex-col gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submit();
                }}
              >
                <Label htmlFor="material-request" className="sr-only">
                  Material request
                </Label>
                <Textarea
                  id="material-request"
                  rows={2}
                  value={request}
                  placeholder="3 decks: weeks 1-3, or one deck per week"
                  disabled={busy || Boolean(collab)}
                  onChange={(event) => setRequest(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void submit();
                    }
                  }}
                />
                <div className="flex items-center justify-between gap-3">
                  <p className="text-muted-foreground text-xs">
                    Enter sends. Shift + Enter starts a new line.
                  </p>
                  <Button
                    type="submit"
                    size="sm"
                    disabled={busy || Boolean(collab) || !request.trim()}
                  >
                    <Send />
                    {busy ? "Drafting..." : "Send"}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Course notes</CardTitle>
              <CardDescription>
                These are the lecture notes the material generator reads for {course.code}.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {materials.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {materials.map((file) => (
                    <Badge
                      key={file.id}
                      variant={file.status === "quarantined" ? "destructive" : "outline"}
                    >
                      {file.status === "quarantined"
                        ? `${file.filename} \u00b7 needs another look`
                        : file.filename}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  No lecture notes yet. Upload a PDF, DOCX, PPTX, or TXT file - decks only keep
                  bullets that appear in your notes.
                </p>
              )}
              <CourseFiles
                files={materials as CourseFile[]}
                onUpload={async (file) => {
                  const body = new FormData();
                  body.append("file", file);
                  await pa(`/courses/${course.id}/materials`, { method: "POST", body });
                  await refresh(course.id);
                }}
                onRemove={async (file) => {
                  await run(async () => {
                    await pa(`/courses/${course.id}/materials/${file.id}`, { method: "DELETE" });
                    await refresh(course.id);
                  }, setError);
                }}
              />
            </CardContent>
          </Card>
          <CourseMemoryPanel courseId={course.id} />
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-medium">Decks</h2>
              <span className="text-muted-foreground text-sm">
                {decks.length} deck{decks.length === 1 ? "" : "s"}
              </span>
            </div>
            {decks.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No decks yet. Ask for materials above.
              </p>
            ) : (
              decks.map((deck) => {
                const reviewState = reviewBadge(deck.review);
                return (
                  <Card key={deck.id}>
                    <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
                      <div className="space-y-1">
                        <CardTitle className="text-base">
                          <Link className="hover:underline" href={`/studio/deck/${deck.id}`}>
                            {deck.title}
                          </Link>
                        </CardTitle>
                        <CardDescription>
                          {deck.week ? `Week ${deck.week} \u00b7 ` : ""}
                          {deck.slides.length} slide{deck.slides.length === 1 ? "" : "s"}
                        </CardDescription>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <Badge variant={deck.status === "approved" ? "default" : "secondary"}>
                          {deck.status}
                        </Badge>
                        <Badge className={reviewState.className}>{reviewState.label}</Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="flex flex-col gap-3">
                      <ul className="text-muted-foreground list-disc space-y-1 pl-5 text-sm">
                        {deck.slides
                          .flatMap((slide) => slide.bullets)
                          .map((bullet) =>
                            typeof bullet === "string" ? bullet : (bullet?.text ?? ""),
                          )
                          .filter((bullet) => bullet.trim() !== "")
                          .slice(0, 4)
                          .map((bullet, index) => (
                            <li key={`${deck.id}-${index}`}>{bullet}</li>
                          ))}
                      </ul>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={async () => {
                            await run(async () => {
                              const blob = await pa<Blob>(`/slides/${deck.id}/pptx`);
                              const url = URL.createObjectURL(blob);
                              const link = document.createElement("a");
                              link.href = url;
                              link.download = `${deck.title.replace(/[\\/:*?<>|]/g, "-")}.pptx`;
                              link.click();
                              URL.revokeObjectURL(url);
                            }, setError);
                          }}
                        >
                          <Download />
                          PPTX
                        </Button>
                        {deck.status !== "approved" && (
                          <Button
                            size="sm"
                            onClick={async () => {
                              await run(async () => {
                                await pa(`/slides/${deck.id}/approve`, { method: "POST" });
                                await refresh(course.id);
                              }, setError);
                            }}
                          >
                            Approve
                          </Button>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                );
              })
            )}
          </section>
        </>
      )}
    </div>
  );
}
