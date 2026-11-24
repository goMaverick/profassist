"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { CheckCircle2, CircleDashed, Flag, Send } from "lucide-react";
import { pa } from "@/lib/profassist";
import { HomeBriefing } from "@/components/profassist/home-briefing";
import { HomeChat } from "@/components/profassist/home-chat";

interface Home {
  courses: Array<{ id: string; code: string; title: string; term: string }>;
  submissions: number;
  drafts: number;
  approved: number;
  pushed: number;
  open_flags: number;
  moodle_mode: string;
  principle: string;
}

export default function HomePage() {
  const [home, setHome] = useState<Home | null>(null);
  const [tasks, setTasks] = useState<Array<{ name: string; due?: string; number?: string }>>([]);
  const [error, setError] = useState("");
  const [courseId, setCourseId] = useState("");
  const [board, setBoard] = useState<
    Array<{ course: string; slug: string; status: string; flagged_pairs: number }>
  >([]);

  useEffect(() => {
    pa<Home>("/home")
      .then((data) => {
        setHome(data);
        setCourseId(data.courses[0]?.id || "");
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not load home"),
      );
    pa<{
      items: Array<{ body?: { tasks?: Array<{ name: string; due?: string; number?: string }> } }>;
    }>("/outlines")
      .then((data) => setTasks(data.items[0]?.body?.tasks || []))
      .catch(() => setTasks([]));
    pa<{ items: Array<{ course: string; slug: string; status: string; flagged_pairs: number }> }>(
      "/integrity/overview?course=all",
    )
      .then((data) => setBoard(data.items || []))
      .catch(() => setBoard([]));
  }, []);

  const course = home?.courses.find((item) => item.id === courseId) || home?.courses[0];
  const waiting = Math.max(0, (home?.drafts || 0) - (home?.approved || 0));
  const compact = (value?: string) => (value || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  const flagged = board.filter((item) => item.status !== "Clear");
  const cases = flagged.reduce((sum, item) => sum + (item.flagged_pairs || 0), 0);
  const selected = compact(course?.code);
  const inThisCourse = flagged.some(
    (item) => compact(item.slug) === selected || compact(item.course) === selected,
  );
  const copyingLabel =
    cases === 0
      ? "No copying cases"
      : inThisCourse
        ? `${cases} possible copying case${cases === 1 ? "" : "s"}`
        : `${cases} copying cases in other courses`;

  const progress = [
    { name: "Draft", value: home?.drafts || 0, color: "#0f62fe" },
    { name: "Approved", value: home?.approved || 0, color: "#78a9ff" },
    { name: "Pushed", value: home?.pushed || 0, color: "#a6c8ff" },
  ];
  const hasProgress = progress.some((item) => item.value > 0);

  if (!home && !error) {
    return (
      <div className="pa-dash" aria-busy="true">
        <h1 className="sr-only">Home</h1>
        <div className="pa-skel" />
        <div className="pa-kpi-row">
          <div className="pa-skel" />
          <div className="pa-skel" />
          <div className="pa-skel" />
          <div className="pa-skel" />
        </div>
      </div>
    );
  }

  return (
    <div className="pa-dash">
      <h1 className="sr-only">Home</h1>
      {error && <p role="alert">{error}</p>}
      <HomeBriefing />
      <HomeChat courses={home?.courses || []} courseId={course?.id} onCourse={setCourseId} />
      <section>
        <h2 style={{ margin: "0 0 8px", fontSize: "1.25rem", fontWeight: 400 }}>To do</h2>
        <div className="pa-todo">
          <Link href="/grade">
            <span>
              {waiting} grade{waiting === 1 ? "" : "s"} waiting for approval
            </span>
            <strong>Review</strong>
          </Link>
          <Link href="/integrity">
            <span>{copyingLabel}</span>
            <strong>Look</strong>
          </Link>
          <Link href="/outline">
            <span>
              {course?.code
                ? `Outline ${course.code} needs learning outcomes`
                : "Continue your course outline"}
            </span>
            <strong>Continue</strong>
          </Link>
        </div>
      </section>
      <div className="pa-kpi-row">
        <Stat
          icon={<CircleDashed className="h-4 w-4" />}
          label="Submissions"
          value={home?.submissions || 0}
          delta="in the queue"
        />
        <Stat
          icon={<CheckCircle2 className="h-4 w-4" />}
          label="Awaiting you"
          value={waiting}
          delta="drafts not approved"
        />
        <Stat
          icon={<Flag className="h-4 w-4" />}
          label="Open flags"
          value={cases}
          delta="for you to look at"
        />
        <Stat
          icon={<Send className="h-4 w-4" />}
          label="Pushed"
          value={home?.pushed || 0}
          delta="marked pushed"
        />
      </div>
      <div className="pa-chart-row">
        <section className="pa-panel">
          <h2>Grading progress</h2>
          {hasProgress ? (
            <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
              <Donut slices={progress} />
              <ul className="pa-list" style={{ flex: 1 }}>
                {progress.map((item) => (
                  <li key={item.name}>
                    <span>{item.name}</span>
                    <strong style={{ color: item.color }}>{item.value}</strong>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="pa-empty">
              <span>No grade data yet.</span>
            </div>
          )}
        </section>
        <section className="pa-panel">
          <h2>Weekly activity</h2>
          <div className="pa-empty">
            <span>No activity data yet.</span>
          </div>
        </section>
      </div>
      <div className="pa-split">
        <section className="pa-panel">
          <h2>Needs your approval</h2>
          {waiting === 0 ? (
            <div className="pa-empty">
              <CheckCircle2 className="h-5 w-5" />
              <span>Nothing is waiting. Drafts stay drafts until you approve them.</span>
            </div>
          ) : (
            <ul className="pa-list">
              <li>
                <span>
                  {waiting} grade draft{waiting === 1 ? "" : "s"}
                </span>
                <Link href="/grade">Review</Link>
              </li>
            </ul>
          )}
        </section>
        <section className="pa-panel">
          <h2>Upcoming deadlines</h2>
          {tasks.length === 0 ? (
            <div className="pa-empty">
              <span>No dated tasks on the outline yet.</span>
            </div>
          ) : (
            <ul className="pa-list">
              {tasks.slice(0, 4).map((task) => (
                <li key={task.number || task.name}>
                  <span>
                    {task.number} {task.name}
                  </span>
                  <span>{task.due || "Date not set"}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function Donut({ slices }: { slices: Array<{ name: string; value: number; color: string }> }) {
  const total = slices.reduce((sum, item) => sum + item.value, 0) || 1;
  const radius = 46;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const arcs = slices.map((item) => {
    const length = (item.value / total) * circumference;
    const arc = { ...item, length, offset };
    offset += length;
    return arc;
  });
  return (
    <svg
      width="148"
      height="148"
      viewBox="0 0 148 148"
      role="img"
      aria-label={slices.map((item) => `${item.name} ${item.value}`).join(", ")}
    >
      {arcs.map((item) => (
        <circle
          key={item.name}
          cx="74"
          cy="74"
          r={radius}
          fill="none"
          stroke={item.color}
          strokeWidth="18"
          strokeDasharray={`${item.length} ${circumference - item.length}`}
          strokeDashoffset={-item.offset}
          transform="rotate(-90 74 74)"
        />
      ))}
    </svg>
  );
}

function Stat({
  icon,
  label,
  value,
  delta,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  delta: string;
}) {
  return (
    <article className="pa-stat">
      <span>
        {icon} {label}
      </span>
      <strong>{value}</strong>
      <em>{delta}</em>
    </article>
  );
}
