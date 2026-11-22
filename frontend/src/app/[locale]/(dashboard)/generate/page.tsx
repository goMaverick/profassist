"use client";

import { useEffect, useState } from "react";
import { Button, Checkbox, Column, Grid, InlineNotification, Tag, Tile } from "@carbon/react";
import { Add, MagicWand } from "@carbon/icons-react";
import { pa, run } from "@/components/profassist/bits";
import { CouncilStage } from "@/components/profassist/council-stage";

interface Outline {
  id: string;
  code: string;
  name: string;
  body: { clos?: Array<{ code: string; text: string }>; tasks?: Array<{ number: string; name: string; weight: number }> };
}
interface Suggestion {
  number: string;
  name: string;
  task_type: string;
  weight: number;
  due: string;
  lo_codes: string[];
  brief: string;
  criteria: Array<{ name: string; weight: number }>;
}

export default function GeneratePage() {
  const [outlines, setOutlines] = useState<Outline[]>([]);
  const [current, setCurrent] = useState<Outline | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [talking, setTalking] = useState(false);

  useEffect(() => {
    pa<{ items: Outline[] }>("/outlines")
      .then((data) => {
        setOutlines(data.items);
        setCurrent(data.items[0] || null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "No courses yet"));
  }, []);

  const clos = current?.body.clos || [];

  return (
    <Grid>
      <Column lg={16}>
        <h1 style={{ fontWeight: 400 }}>Assessment generator</h1>
        <p style={{ color: "#525252" }}>Choose a course, choose the outcomes, then accept the council’s suggestion.</p>
      </Column>
      {error && (
        <Column lg={16}>
          <InlineNotification kind="error" title="Assessments" subtitle={error} hideCloseButton />
        </Column>
      )}
      {note && (
        <Column lg={16}>
          <InlineNotification kind="success" title="Saved" subtitle={note} hideCloseButton lowContrast />
        </Column>
      )}
      <Column lg={5} md={4} sm={4}>
        <h2 style={{ fontSize: "1rem" }}>Course</h2>
        {outlines.map((item) => (
          <Tile key={item.id} style={{ marginBottom: "0.5rem", outline: current?.id === item.id ? "2px solid #0f62fe" : undefined }}>
            <button
              style={{ all: "unset", cursor: "pointer" }}
              onClick={() => {
                setCurrent(item);
                setSelected([]);
                setSuggestions([]);
              }}
            >
              <strong>{item.code}</strong>
              <div>{item.name}</div>
            </button>
          </Tile>
        ))}
      </Column>
      <Column lg={11} md={4} sm={4}>
        <h2 style={{ fontSize: "1rem" }}>Course learning outcomes</h2>
        {clos.map((item) => (
          <Checkbox
            key={item.code}
            id={item.code}
            labelText={`${item.code} ${item.text}`}
            checked={selected.includes(item.code)}
            onChange={(_, { checked }) =>
              setSelected((currentCodes) =>
                checked ? [...currentCodes, item.code] : currentCodes.filter((code) => code !== item.code),
              )
            }
          />
        ))}
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
          <Button
            kind="primary"
            renderIcon={MagicWand}
            disabled={!current || selected.length === 0}
            onClick={async () => {
              if (!current) return;
              setTalking(true);
              const data = await run(
                () =>
                  pa<{ suggestions: Suggestion[] }>(`/outlines/${current.id}/assessments/suggest`, {
                    method: "POST",
                    body: JSON.stringify({ lo_codes: selected }),
                  }),
                setError,
              );
              if (data) setSuggestions(data.suggestions);
              setTalking(false);
            }}
          >
            Ask the council
          </Button>
          <Button
            kind="secondary"
            renderIcon={Add}
            disabled={!current || suggestions.length === 0}
            onClick={async () => {
              if (!current) return;
              const next = await run(
                () =>
                  pa<Outline>(`/outlines/${current.id}/assessments/accept`, {
                    method: "POST",
                    body: JSON.stringify({ tasks: suggestions }),
                  }),
                setError,
              );
              if (next) {
                setCurrent(next);
                setOutlines((items) => items.map((item) => (item.id === next.id ? next : item)));
                setNote("The assignment is numbered and linked to the outcomes. Open Rubric or Grade to use it.");
              }
            }}
          >
            Accept
          </Button>
        </div>
        {talking && <CouncilStage scene="assessment" />}
        {suggestions.map((item) => (
          <Tile key={item.name} style={{ marginTop: "1rem" }}>
            <Tag type="purple">{item.task_type}</Tag>
            <Tag type="blue">{item.weight}%</Tag>
            <Tag type="teal">{item.due}</Tag>
            <h3 style={{ marginBottom: "0.25rem" }}>{item.name}</h3>
            <p>{item.brief}</p>
            <p style={{ color: "#525252" }}>Outcomes: {item.lo_codes.join(", ")}</p>
            <ul>
              {item.criteria.map((criterion) => (
                <li key={criterion.name}>
                  {criterion.name} ({criterion.weight}%)
                </li>
              ))}
            </ul>
          </Tile>
        ))}
        <h2 style={{ fontSize: "1rem", marginTop: "1.5rem" }}>Already on this course</h2>
        {(current?.body.tasks || []).map((item) => (
          <Tag key={item.number} type="green">
            {item.number} {item.name} {item.weight}%
          </Tag>
        ))}
      </Column>
    </Grid>
  );
}
