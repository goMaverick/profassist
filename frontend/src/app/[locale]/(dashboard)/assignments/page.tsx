"use client";

import { useEffect, useState } from "react";
import { Button, Column, Grid, InlineNotification, Tag, Tile } from "@carbon/react";
import { Education, Group, MagicWand } from "@carbon/icons-react";
import { pa, run, useWorkspace } from "@/components/profassist/bits";

interface Outline {
  id: string;
  code: string;
  body: { tasks?: Array<{ number: string; name: string; weight: number; due: string; lo_codes: string[] }> };
}
interface Idea {
  id: string;
  title: string;
  brief: string;
  exemplar?: { model_answer: string; strong: string; average: string; weak: string } | null;
}
interface Assignment {
  id: string;
  title: string;
  body: string;
  status: string;
  ideas: Idea[];
  groups: Array<{ id: string; name: string; member_ids: string[] }>;
  allocations: Array<{ group_id: string; idea_id: string }>;
}

export default function AssignmentsPage() {
  const { course } = useWorkspace();
  const [outline, setOutline] = useState<Outline | null>(null);
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [roster, setRoster] = useState<Array<{ id: string; name: string }>>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    pa<{ items: Outline[] }>("/outlines")
      .then((data) => setOutline(data.items[0] || null))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "No outline"));
  }, []);

  useEffect(() => {
    if (!course) return;
    pa<{ items: Array<{ id: string; name: string }> }>(`/courses/${course.id}/roster`)
      .then((data) => setRoster(data.items))
      .catch(() => setRoster([]));
  }, [course]);

  const task = outline?.body.tasks?.[0];

  return (
    <Grid>
      {error && (
        <Column lg={16}>
          <InlineNotification kind="error" title="Assignments" subtitle={error} hideCloseButton />
        </Column>
      )}
      {note && (
        <Column lg={16}>
          <InlineNotification kind="success" title="Saved" subtitle={note} hideCloseButton lowContrast />
        </Column>
      )}
      <Column lg={16}>
        <Button
          kind="primary"
          renderIcon={Education}
          disabled={!course || !task}
          onClick={async () => {
            if (!course || !outline || !task) return;
            const created = await run(
              () =>
                pa<Assignment>("/assignments", {
                  method: "POST",
                  body: JSON.stringify({
                    course_id: course.id,
                    number: task.number,
                    title: task.name,
                    weight: task.weight,
                    due: task.due,
                    lo_codes: task.lo_codes,
                    instructions: "Prefer a project a group can build.",
                  }),
                }),
              setError,
            );
            if (created) setAssignment(created);
          }}
        >
          Draft from {task ? `${task.number} ${task.name}` : "the outline"}
        </Button>
      </Column>
      {assignment && (
        <>
          <Column lg={16}>
            <Tile>
              <h2>{assignment.title}</h2>
              <p>{assignment.body}</p>
              <Tag type="gray">{assignment.status}</Tag>
            </Tile>
          </Column>
          <Column lg={16}>
            <Button
              kind="tertiary"
              renderIcon={MagicWand}
              onClick={async () => {
                const next = await run(
                  () => pa<Assignment>(`/assignments/${assignment.id}/ideas`, { method: "POST" }),
                  setError,
                );
                if (next) setAssignment(next);
              }}
            >
              Generate 5 ideas
            </Button>
            <Button
              kind="tertiary"
              onClick={async () => {
                const next = await run(
                  () => pa<Assignment>(`/assignments/${assignment.id}/exemplars`, { method: "POST" }),
                  setError,
                );
                if (next) {
                  setAssignment(next);
                  setNote("Exemplars saved. The council can use them as calibration.");
                }
              }}
            >
              Write exemplars
            </Button>
          </Column>
          {assignment.ideas.map((idea) => (
            <Column key={idea.id} lg={8} md={4} sm={4}>
              <Tile>
                <h3>{idea.title}</h3>
                <p>{idea.brief}</p>
                {idea.exemplar && (
                  <p>
                    Strong: {idea.exemplar.strong}
                    <br />
                    Average: {idea.exemplar.average}
                    <br />
                    Weak: {idea.exemplar.weak}
                  </p>
                )}
              </Tile>
            </Column>
          ))}
          <Column lg={16}>
            <h2 style={{ fontWeight: 400 }}>Roster from the last Moodle sync</h2>
            <p>{roster.map((person) => person.name).join(", ") || "No students synced yet."}</p>
            <Button
              kind="secondary"
              renderIcon={Group}
              disabled={!course || roster.length === 0}
              onClick={async () => {
                if (!course) return;
                const groups = [];
                for (let index = 0; index < roster.length; index += 2) {
                  groups.push({
                    name: `Group ${index / 2 + 1}`,
                    member_ids: roster.slice(index, index + 2).map((person) => person.id),
                  });
                }
                await run(
                  () =>
                    pa(`/courses/${course.id}/groups`, {
                      method: "PUT",
                      body: JSON.stringify({ course_id: course.id, groups }),
                    }),
                  setError,
                );
                const next = await run(
                  () => pa<Assignment>(`/assignments/${assignment.id}/allocate`, { method: "POST" }),
                  setError,
                );
                if (next) {
                  setAssignment(next);
                  setNote("Groups were balanced from the roster and allocated round-robin.");
                }
              }}
            >
              Balance groups and allocate ideas
            </Button>
            <p>
              {assignment.groups.length} groups · {assignment.allocations.length} allocations
            </p>
          </Column>
        </>
      )}
    </Grid>
  );
}
