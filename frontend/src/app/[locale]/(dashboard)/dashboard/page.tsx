"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { CheckmarkFilled, Flag, Incomplete, Send } from "@carbon/icons-react";
import { pa } from "@/lib/profassist";
import { HomeChat } from "@/components/profassist/home-chat";
import { AiLive } from "@/components/profassist/ai-live";

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

const WEEK = [
  { day: "Mon", views: 18 },
  { day: "Tue", views: 26 },
  { day: "Wed", views: 22 },
  { day: "Thu", views: 31 },
  { day: "Fri", views: 14 },
];
const GRADE_SLICES = [
  { name: "Draft", value: 6, color: "#0f62fe" },
  { name: "Approved", value: 3, color: "#78a9ff" },
  { name: "Pushed", value: 2, color: "#a6c8ff" },
];

export default function HomePage() {
  const [home, setHome] = useState<Home | null>(null);
  const [tasks, setTasks] = useState<Array<{ name: string; due?: string; number?: string }>>([]);
  const [error, setError] = useState("");
  const [courseId, setCourseId] = useState("");

  useEffect(() => {
    pa<Home>("/home")
      .then((data) => {
        setHome(data);
        setCourseId(data.courses[0]?.id || "");
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load home"));
    pa<{ items: Array<{ body?: { tasks?: Array<{ name: string; due?: string; number?: string }> } }> }>("/outlines")
      .then((data) => setTasks(data.items[0]?.body?.tasks || []))
      .catch(() => setTasks([]));
  }, []);

  const course = home?.courses.find((item) => item.id === courseId) || home?.courses[0];
  const waiting = Math.max(0, (home?.drafts || 0) - (home?.approved || 0));

  if (!home && !error) {
    return (
      <div className="pa-dash" aria-busy="true">
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
      {error && <p role="alert">{error}</p>}
      <HomeChat courses={home?.courses || []} courseId={course?.id} onCourse={setCourseId} />
      <div className="pa-split">
        <AiLive
          title="AI activity"
          reasoning="The drafter prepared a subject outline, flagged one similarity pair, and left four grade drafts for you. Nothing was pushed."
          sources={[{ href: "/outline", title: "MAAI 903 outline" }, { href: "/integrity", title: "Similarity scan" }]}
          tasks={["Drafted A2 from the outline", "Compared group submissions", "Held grades for approval"]}
          suggestions={["Open the outline", "Review the grade queue"]}
        >
          <ul className="pa-list">
            <li><span>Outline draft updated</span><Link href="/outline">Open</Link></li>
            <li><span>Similarity pair waiting</span><Link href="/integrity?tab=similarity">Open</Link></li>
            <li><span>{waiting} grade draft{waiting === 1 ? "" : "s"}</span><Link href="/grade">Review</Link></li>
          </ul>
        </AiLive>
        <AiLive
          title="AI insights"
          reasoning="Week 7 carries a summative task. Two program outcomes are thinly mapped. A student would look for the integrity policy next to the assessments."
          sources={[{ href: "/outline", title: "Instructions to AI" }]}
          tasks={["Checked the weight total", "Read the uploaded lecture note"]}
        />
      </div>
      <div className="pa-kpi-row">
        <Stat icon={<Incomplete size={16} />} label="Submissions" value={home?.submissions || 0} delta="in the queue" />
        <Stat icon={<CheckmarkFilled size={16} />} label="Awaiting you" value={waiting} delta="drafts not approved" />
        <Stat icon={<Flag size={16} />} label="Open flags" value={home?.open_flags || 0} delta="not a verdict" />
        <Stat icon={<Send size={16} />} label="Pushed" value={home?.pushed || 0} delta={`${home?.moodle_mode || "fake"} Moodle`} />
      </div>
      <div className="pa-chart-row">
        <section className="pa-panel">
          <h2>Grading progress</h2>
          <p style={{ margin: "-8px 0 12px", color: "#6f6f6f", fontSize: "0.75rem" }}>Synthetic term, demo only.</p>
          <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
            <Donut slices={GRADE_SLICES} />
            <ul className="pa-list" style={{ flex: 1 }}>
              {GRADE_SLICES.map((item) => (
                <li key={item.name}>
                  <span>{item.name}</span>
                  <strong style={{ color: item.color }}>{item.value}</strong>
                </li>
              ))}
            </ul>
          </div>
        </section>
        <section className="pa-panel">
          <h2>Weekly activity</h2>
          <p style={{ margin: "-8px 0 8px", color: "#6f6f6f", fontSize: "0.75rem" }}>Synthetic week, demo only.</p>
          <div className="pa-bars" aria-label="Views by weekday">
            {WEEK.map((item) => (
              <div key={item.day}>
                <div style={{ height: `${item.views * 4}px` }} />
                <span>{item.day}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
      <div className="pa-split">
        <section className="pa-panel">
          <h2>Needs your approval</h2>
          {waiting === 0 ? (
            <div className="pa-empty">
              <CheckmarkFilled size={20} />
              <span>Nothing is waiting. Drafts stay drafts until you approve them.</span>
            </div>
          ) : (
            <ul className="pa-list">
              <li>
                <span>{waiting} grade draft{waiting === 1 ? "" : "s"}</span>
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
    <svg width="148" height="148" viewBox="0 0 148 148" role="img" aria-label={slices.map((item) => `${item.name} ${item.value}`).join(", ")}>
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
