"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Column, Grid, InlineNotification, Tab, TabList, TabPanel, TabPanels, Tabs, Tile } from "@carbon/react";
import { pa, run, useWorkspace } from "@/components/profassist/bits";
import { AiLive } from "@/components/profassist/ai-live";

const HEAT = [
  ["", "A", "B", "C", "D"],
  ["A", "1", "0.91", "0.22", "0.18"],
  ["B", "0.91", "1", "0.31", "0.14"],
  ["C", "0.22", "0.31", "1", "0.44"],
  ["D", "0.18", "0.14", "0.44", "1"],
];

interface Flag {
  id: string;
  section: string;
  passage_a: string;
  passage_b: string;
  score: number;
  kind: string;
  viva: string[];
  rare_details: string[];
  status: string;
  note: string;
}
interface Pair {
  left_group: string;
  right_group: string;
  same_idea: boolean;
  score: number;
  left_excerpt: string;
  right_excerpt: string;
}
interface Report {
  model: string;
  trained: boolean;
  threshold: number;
  note: string;
  pairs: Pair[];
}

export default function IntegrityPage() {
  return (
    <Suspense fallback={<p>Loading integrity…</p>}>
      <IntegrityBody />
    </Suspense>
  );
}

function heatColor(value: string) {
  const score = Number(value);
  if (!Number.isFinite(score)) return "transparent";
  if (score >= 0.8) return "#e8daff";
  if (score >= 0.4) return "#d0e2ff";
  return "#f4f4f4";
}

function IntegrityBody() {
  const { course } = useWorkspace();
  const router = useRouter();
  const params = useSearchParams();
  const tab = params.get("tab") === "similarity" ? 0 : 1;
  const [error, setError] = useState("");
  const [flags, setFlags] = useState<Flag[]>([]);
  const [assignments, setAssignments] = useState<Array<{ id: string; number: string; title: string }>>([]);
  const [report, setReport] = useState<Report | null>(null);

  useEffect(() => {
    if (!course) return;
    pa<{ items: Flag[] }>(`/courses/${course.id}/integrity`)
      .then((data) => setFlags(data.items))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load flags"));
    pa<{ items: Array<{ id: string; number: string; title: string }> }>(`/assignments?course_id=${course.id}`)
      .then((data) => setAssignments(data.items.filter((item) => item.id)))
      .catch(() => setAssignments([]));
  }, [course]);

  useEffect(() => {
    const id = params.get("id");
    if (!id) return;
    pa<Report>(`/assignments/${id}/similarity`)
      .then(setReport)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "No similarity report"));
  }, [params]);

  return (
    <Grid>
      {error && (
        <Column lg={16}>
          <InlineNotification kind="error" title="Integrity" subtitle={error} hideCloseButton />
        </Column>
      )}
      <Column lg={16}>
        <Tabs
          selectedIndex={tab}
          onChange={({ selectedIndex }) => {
            router.replace(selectedIndex === 0 ? "/integrity?tab=similarity" : "/integrity?tab=flags");
          }}
        >
          <TabList aria-label="Integrity">
            <Tab>Similarity</Tab>
            <Tab>AI & policy flags</Tab>
          </TabList>
          <TabPanels>
            <TabPanel>
              <AiLive
                title="Similarity"
                reasoning="Group A and Group B share a method sentence after the common brief is removed. The writing signal is a demo score, not a verdict."
                sources={[{ href: "/integrity", title: "Submission pairs" }]}
                tasks={["Drop the shared idea brief", "Score the remaining solution text", "Show the pair side by side"]}
              >
                <table className="pa-matrix" aria-label="Similarity heatmap">
                  <tbody>
                    {HEAT.map((row, index) => (
                      <tr key={index}>
                        {row.map((cell, cellIndex) => (
                          <td key={cellIndex} style={{ background: heatColor(cell) }}>{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="pa-legend"><i style={{ background: "#f4f4f4" }} /> under 0.4 <i style={{ background: "#d0e2ff" }} /> 0.4–0.8 <i style={{ background: "#e8daff" }} /> 0.8 and above</p>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <p>A: The pipeline versions the dataset before training and records the threshold.</p>
                  <p>B: The pipeline versions the dataset before training and records the same threshold.</p>
                </div>
                <p>AI-writing score 0.37. Synthetic, demo only. Not a verdict.</p>
              </AiLive>
              <p>Shared briefs are removed before the comparison. A high score is a reason to read the work, not a verdict.</p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "12px 0" }}>
                {assignments.map((item) => (
                  <Button key={item.id} kind="tertiary" size="sm" onClick={() => router.replace(`/integrity?tab=similarity&id=${item.id}`)}>
                    {item.number} {item.title}
                  </Button>
                ))}
                {assignments.length === 0 && <p>Open an assignment and add ideas before running similarity.</p>}
              </div>
              {report && (
                <div>
                  <p>
                    {report.model} · threshold {report.threshold} · {report.trained ? "trained" : "baseline, not a trained model"}
                  </p>
                  <p>{report.note}</p>
                  {report.pairs.length === 0 && <p>No pair is over the threshold.</p>}
                  {report.pairs.map((pair) => (
                    <Tile key={`${pair.left_group}-${pair.right_group}`}>
                      <strong>
                        {pair.left_group} and {pair.right_group}
                      </strong>
                      <span> · {pair.score} · {pair.same_idea ? "same idea" : "different ideas"}</span>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                        <p>{pair.left_excerpt}</p>
                        <p>{pair.right_excerpt}</p>
                      </div>
                    </Tile>
                  ))}
                </div>
              )}
            </TabPanel>
            <TabPanel>
              <p>{course?.code}. A flag is evidence for a conversation. AI-text detection is not used.</p>
              <Button
                kind="primary"
                disabled={!course}
                onClick={async () => {
                  if (!course) return;
                  const data = await run(() => pa<{ items: Flag[] }>(`/courses/${course.id}/integrity/scan`, { method: "POST" }), setError);
                  if (data) setFlags(data.items);
                }}
              >
                Scan submissions
              </Button>
              {flags.length === 0 && <p>No flags yet.</p>}
              {flags.map((flag) => (
                <Tile key={flag.id}>
                  <strong>
                    {flag.section} · {flag.kind.replaceAll("_", " ")}
                  </strong>
                  <span> · {flag.status} · overlap {flag.score}</span>
                  <p>{flag.note}</p>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                    <p>{flag.passage_a}</p>
                    <p>{flag.passage_b}</p>
                  </div>
                  {flag.rare_details.length > 0 && <p>Shared details: {flag.rare_details.join(", ")}</p>}
                  <ol>
                    {flag.viva.map((question) => (
                      <li key={question}>{question}</li>
                    ))}
                  </ol>
                  <div style={{ display: "flex", gap: 8 }}>
                    <Button
                      kind="danger--ghost"
                      size="sm"
                      onClick={async () => {
                        if (!course) return;
                        await run(() => pa(`/integrity/${flag.id}`, { method: "POST", body: JSON.stringify({ status: "confirmed" }) }), setError);
                        const data = await pa<{ items: Flag[] }>(`/courses/${course.id}/integrity`);
                        setFlags(data.items);
                      }}
                    >
                      Confirm as worth a viva
                    </Button>
                    <Button
                      kind="ghost"
                      size="sm"
                      onClick={async () => {
                        if (!course) return;
                        await run(() => pa(`/integrity/${flag.id}`, { method: "POST", body: JSON.stringify({ status: "dismissed" }) }), setError);
                        const data = await pa<{ items: Flag[] }>(`/courses/${course.id}/integrity`);
                        setFlags(data.items);
                      }}
                    >
                      Dismiss
                    </Button>
                  </div>
                </Tile>
              ))}
            </TabPanel>
          </TabPanels>
        </Tabs>
      </Column>
    </Grid>
  );
}
