"use client";

import { useEffect, useState } from "react";
import { Column, Grid, InlineNotification, Tile } from "@carbon/react";
import { pa } from "@/components/profassist/bits";

interface Pair {
  left_group: string;
  right_group: string;
  same_idea: boolean;
  score: number;
  left_excerpt: string;
  right_excerpt: string;
  model: string;
}
interface Report {
  model: string;
  trained: boolean;
  threshold: number;
  note: string;
  pairs: Pair[];
}

export default function SimilarityPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    pa<{ items: Array<{ id: string }> }>("/outlines")
      .then(async () => {
        setError("Open Group work, create an assignment, then paste its id into the address as /similarity?id=…");
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) return;
    pa<Report>(`/assignments/${id}/similarity`)
      .then(setReport)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "No similarity report"));
  }, []);

  return (
    <Grid>
      {error && !report && (
        <Column lg={16}>
          <InlineNotification kind="info" title="How to open a report" subtitle={error} hideCloseButton lowContrast />
        </Column>
      )}
      {report && (
        <Column lg={16}>
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
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                <p>{pair.left_excerpt}</p>
                <p>{pair.right_excerpt}</p>
              </div>
            </Tile>
          ))}
        </Column>
      )}
    </Grid>
  );
}
