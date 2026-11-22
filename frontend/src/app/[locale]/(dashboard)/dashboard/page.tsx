"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ClickableTile, Column, Grid, InlineNotification, Tag, Tile } from "@carbon/react";
import {
  Document,
  Education,
  Flag,
  Certificate,
  PresentationFile,
  Report,
  User,
  Watson,
} from "@carbon/icons-react";
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
}

const CARDS = [
  { href: "/outline", title: "Subject outline", text: "Walk the faculty template and download the PDF.", icon: Document },
  { href: "/generate", title: "Assessments", text: "Pick outcomes. The council suggests a task and a rubric.", icon: Report },
  { href: "/studio", title: "Course studio", text: "Notes, objectives, and the materials the agents read.", icon: Education },
  { href: "/slides", title: "Slides", text: "A cited deck for the week you choose.", icon: PresentationFile },
  { href: "/grade", title: "Review and grade", text: "Council, your edit, then a recorded push.", icon: Certificate },
  { href: "/integrity", title: "Integrity", text: "Shared passages and viva questions. Not a verdict.", icon: Flag },
  { href: "/students", title: "Students", text: "The roster. Early warning is not trained.", icon: User },
  { href: "/style", title: "My style", text: "Your voice and the About this professor note.", icon: Watson },
];

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
    <Grid>
      {!home && !error && (
        <Column lg={16}>
          <p>Loading the workspace…</p>
        </Column>
      )}
      {error && (
        <Column sm={4} md={8} lg={16}>
          <InlineNotification kind="error" title="Could not load" subtitle={error} hideCloseButton />
        </Column>
      )}
      {home && (
        <Column sm={4} md={8} lg={16}>
          <InlineNotification kind="info" title="How this works" subtitle={home.principle} hideCloseButton lowContrast />
        </Column>
      )}
      {home &&
        [
          ["Course", course?.code || "None yet"],
          ["Submissions", String(home.submissions)],
          ["Open flags", String(home.open_flags)],
          ["Pushed", String(home.pushed)],
        ].map(([label, value]) => (
          <Column key={label} sm={2} md={2} lg={4}>
            <Tile>
              <div style={{ color: "#6f6f6f", fontSize: "0.75rem", letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</div>
              <div style={{ fontSize: "2rem", marginTop: "0.5rem" }}>{value}</div>
            </Tile>
          </Column>
        ))}
      {home && CARDS.map((card) => (
        <Column key={card.href} sm={4} md={4} lg={4}>
          <ClickableTile href={card.href} style={{ minHeight: "9rem" }}>
            <card.icon size={24} />
            <h2 style={{ fontSize: "1.1rem", margin: "0.75rem 0 0.25rem" }}>{card.title}</h2>
            <p style={{ margin: 0, color: "#525252" }}>{card.text}</p>
          </ClickableTile>
        </Column>
      ))}
      {home && (
      <Column sm={4} md={8} lg={16}>
        <Tag type="blue">Moodle {home.moodle_mode}</Tag>
        <Tag type={home?.llm_mode === "demo" ? "gray" : "green"}>Model {home?.llm_mode || "…"}</Tag>
        <Tag type="teal">{course?.title || "Course not seeded"}</Tag>
        <Link href="/outline" style={{ marginLeft: "0.5rem" }}>
          Open the subject outline
        </Link>
      </Column>
      )}
    </Grid>
  );
}
