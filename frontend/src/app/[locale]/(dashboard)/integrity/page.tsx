"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Column, Grid, InlineNotification, Tab, TabList, TabPanel, TabPanels, Tabs, Tile } from "@carbon/react";
import { pa, run, useWorkspace } from "@/components/profassist/bits";

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
