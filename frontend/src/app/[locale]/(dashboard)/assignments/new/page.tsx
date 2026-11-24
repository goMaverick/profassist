"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Loader2, WandSparkles } from "lucide-react";

import { pa } from "@/components/profassist/bits";
import { ProfassistError } from "@/lib/profassist";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  Card,
  CardContent,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";

interface CourseOption {
  id: string;
  code: string;
  title: string;
  term?: string;
}

interface CreatedAssignment {
  id?: string;
  title?: string;
  status?: string;
}

interface CreateResponse {
  reply?: string;
  assignment?: CreatedAssignment | null;
  document?: unknown;
  rubric?: unknown;
}

/** Phases shown while the request is in flight. They describe the request, not a percentage. */
const PHASES = [
  "Reading this course's notes",
  "Drafting the assignment brief",
  "Writing the rubric",
  "Laying out the artifact",
];

function describeError(error: unknown, fallback: string): string {
  if (error instanceof ProfassistError) {
    if (error.status === 503) {
      return error.message + " (503: the AI provider is unavailable, so nothing was created.)";
    }
    if (error.status === 401 || error.status === 403) {
      return error.message || "Sign in again to design an assignment.";
    }
    return error.message || fallback;
  }
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}

export default function NewAssignmentPage() {
  const router = useRouter();
  const [courses, setCourses] = useState<CourseOption[]>([]);
  const [courseId, setCourseId] = useState("");
  const [message, setMessage] = useState("");
  const [loadingCourses, setLoadingCourses] = useState(true);
  const [designing, setDesigning] = useState(false);
  const [phase, setPhase] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    pa<{ courses?: CourseOption[] }>("/home")
      .then((data) => {
        if (!live) return;
        const items = Array.isArray(data?.courses) ? data.courses : [];
        setCourses(items);
        const saved = window.sessionStorage.getItem("pa-course") || "";
        const preferred = items.find((item) => item.id === saved) ?? items[0];
        setCourseId(preferred?.id ?? "");
        if (!items.length) {
          setError(
            "No course is connected to this workspace yet. Sync Moodle or add a course first.",
          );
        }
      })
      .catch((err: unknown) => {
        if (!live) return;
        setError(describeError(err, "Could not load this workspace's courses."));
      })
      .finally(() => {
        if (live) setLoadingCourses(false);
      });
    return () => {
      live = false;
    };
  }, []);

  // Naming the phase makes a slow draft explainable without inventing a percentage.
  useEffect(() => {
    if (!designing) return;
    setPhase(0);
    const timer = window.setInterval(() => {
      setPhase((current) => Math.min(current + 1, PHASES.length - 1));
    }, 2500);
    return () => window.clearInterval(timer);
  }, [designing]);

  async function design() {
    if (designing) return;
    const text = message.trim();
    if (!courseId) {
      setError("Choose a course first.");
      return;
    }
    if (!text) {
      setError("Describe the assignment you want to create first.");
      return;
    }
    setError("");
    setDesigning(true);
    try {
      const data = await pa<CreateResponse>("/assignments/assist", {
        method: "POST",
        body: JSON.stringify({ course_id: courseId, message: text, mode: "create" }),
      });
      const id = typeof data?.assignment?.id === "string" ? data.assignment.id : "";
      if (!id) {
        // A 200 without an assignment is not an artifact. Say so instead of opening a blank page.
        const reply = typeof data?.reply === "string" && data.reply.trim() ? " " + data.reply : "";
        setError("The designer returned no assignment, so there is nothing to open." + reply);
        return;
      }
      window.sessionStorage.setItem("pa-course", courseId);
      router.push(`/assignments/${id}`);
    } catch (err) {
      setError(describeError(err, "The assignment could not be designed."));
    } finally {
      setDesigning(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <div>
        <Link
          href="/assignments"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          All assignments
        </Link>
      </div>

      <div>
        <h1 className="text-xl font-semibold">New assignment</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Describe the task. ProfAssist drafts the brief, the report sections, and the rubric, then
          opens the artifact so you can edit it.
        </p>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Nothing was created</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardContent className="space-y-5 p-6">
          <div className="space-y-2">
            <Label htmlFor="course">Course</Label>
            <Select
              value={courseId}
              onValueChange={setCourseId}
              disabled={loadingCourses || designing}
            >
              <SelectTrigger id="course" aria-label="Course">
                <SelectValue
                  placeholder={loadingCourses ? "Loading courses..." : "Choose a course"}
                />
              </SelectTrigger>
              <SelectContent>
                {courses.map((course) => (
                  <SelectItem key={course.id} value={course.id}>
                    {course.code} - {course.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="ask">What assignment do you want to create?</Label>
            <Textarea
              id="ask"
              rows={6}
              value={message}
              disabled={designing}
              placeholder="e.g. Assessment 2 for MAAI903: a 2,500-word solutions architecture report, 25%, due week 7, with a 10-minute presentation and a four-level rubric."
              onChange={(event) => setMessage(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              Include the weight, the due week, and anything the rubric must reward.
            </p>
          </div>

          {designing ? (
            <div className="space-y-2" role="status" aria-live="polite">
              <div className="bg-muted h-1 w-full overflow-hidden rounded-full">
                <div className="bg-primary h-full w-1/3 animate-pulse rounded-full" />
              </div>
              <p className="text-muted-foreground flex items-center gap-2 text-xs">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Designing... {PHASES[Math.min(phase, PHASES.length - 1)]}
              </p>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" onClick={() => void design()} disabled={designing || !courseId}>
              {designing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <WandSparkles className="h-4 w-4" />
              )}
              {designing ? "Designing..." : "Generate assignment"}
            </Button>
            <Button asChild type="button" variant="ghost">
              <Link href="/assignments">Cancel</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
