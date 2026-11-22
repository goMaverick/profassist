"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Banner } from "@/components/profassist/bits";
import { pa } from "@/lib/profassist";

interface Home {
  courses: Array<{ id: string; code: string; title: string; term: string }>;
  submissions: number;
  drafts: number;
  approved: number;
  pushed: number;
  open_flags: number;
  moodle_mode: string;
  llm_mode: string;
  principle: string;
  calibrator: { status: string; message: string };
  early_warning: { status: string };
}

export default function HomePage() {
  const [home, setHome] = useState<Home | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    pa<Home>("/home")
      .then(setHome)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load home"));
  }, []);

  const course = home?.courses[0];

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div>
        <p className="text-foreground/50 text-xs tracking-[0.18em] uppercase">ProfAssist</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Good to see you, Professor.</h1>
        <p className="text-foreground/70 mt-2 max-w-2xl text-sm">
          Drafts for slides, rubrics, grades and feedback. You stay in charge.
        </p>
      </div>
      {error && <Banner>{error}</Banner>}
      {home && <Banner>{home.principle}</Banner>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Course", course ? `${course.code}` : "—"],
          ["Submissions", String(home?.submissions ?? "—")],
          ["Open flags", String(home?.open_flags ?? "—")],
          ["Pushed", String(home?.pushed ?? "—")],
        ].map(([label, value]) => (
          <div key={label} className="border-foreground/10 rounded-xl border p-4">
            <p className="text-foreground/50 text-xs tracking-wide uppercase">{label}</p>
            <p className="mt-2 text-2xl font-semibold">{value}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Link href="/studio" className="border-foreground/10 hover:bg-foreground/[0.03] rounded-xl border p-5">
          <h2 className="font-medium">Course studio</h2>
          <p className="text-foreground/65 mt-1 text-sm">Upload notes, approve objectives, draft slides and a rubric.</p>
        </Link>
        <Link href="/grade" className="border-foreground/10 hover:bg-foreground/[0.03] rounded-xl border p-5">
          <h2 className="font-medium">Review and grade</h2>
          <p className="text-foreground/65 mt-1 text-sm">
            Council, judge, and your edit. {home?.drafts ?? 0} drafts, {home?.approved ?? 0} approved.
          </p>
        </Link>
        <Link href="/integrity" className="border-foreground/10 hover:bg-foreground/[0.03] rounded-xl border p-5">
          <h2 className="font-medium">Integrity</h2>
          <p className="text-foreground/65 mt-1 text-sm">Same-topic passages side by side, with viva questions. Not a verdict.</p>
        </Link>
        <Link href="/students" className="border-foreground/10 hover:bg-foreground/[0.03] rounded-xl border p-5">
          <h2 className="font-medium">Students</h2>
          <p className="text-foreground/65 mt-1 text-sm">Roster from the fake Moodle connector. Early warning is not trained yet.</p>
        </Link>
        <Link href="/style" className="border-foreground/10 hover:bg-foreground/[0.03] rounded-xl border p-5">
          <h2 className="font-medium">My style</h2>
          <p className="text-foreground/65 mt-1 text-sm">soul.md. Feedback is written in this voice, and only you can change it.</p>
        </Link>
        <Link href="/quality" className="border-foreground/10 hover:bg-foreground/[0.03] rounded-xl border p-5">
          <h2 className="font-medium">Quality</h2>
          <p className="text-foreground/65 mt-1 text-sm">{home?.calibrator.message ?? "Grade calibrator is not trained yet."}</p>
        </Link>
      </div>
      {home && (
        <p className="text-foreground/50 text-xs">
          Workspace {course?.title ?? "not seeded"} · Moodle {home.moodle_mode} · model {home.llm_mode}
          {home.llm_mode === "demo" ? " (add an LLM key in .env for a live model)" : ""}
        </p>
      )}
    </div>
  );
}
