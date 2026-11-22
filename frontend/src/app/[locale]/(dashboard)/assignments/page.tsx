"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Button,
  Checkbox,
  Column,
  Grid,
  InlineNotification,
  Select,
  SelectItem,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Tag,
  Tile,
} from "@carbon/react";
import { pa, run, useWorkspace } from "@/components/profassist/bits";

interface CatalogItem {
  id: string;
  number: string;
  title: string;
  due: string;
  weight: number;
  status: string;
  lo_codes: string[];
  brief: string;
}
interface Idea {
  id: string;
  title: string;
  brief: string;
  exemplar?: { model_answer: string; strong: string; average: string; weak: string } | null;
}
interface Group {
  id: string;
  name: string;
  member_ids: string[];
}
interface Assignment {
  id: string;
  number: string;
  title: string;
  body: string;
  due: string;
  weight: number;
  status: string;
  lo_codes: string[];
  ideas: Idea[];
  groups: Group[];
  allocations: Array<{ group_id: string; idea_id: string }>;
}

export default function AssignmentsPage() {
  return (
    <Suspense fallback={<p>Loading assignments…</p>}>
      <AssignmentsBody />
    </Suspense>
  );
}

function AssignmentsBody() {
  const { course } = useWorkspace();
  const router = useRouter();
  const params = useSearchParams();
  const selected = params.get("id") || "";
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [roster, setRoster] = useState<Array<{ id: string; name: string }>>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [groupName, setGroupName] = useState("Group 1");
  const [draftGroups, setDraftGroups] = useState<Array<{ name: string; member_ids: string[] }>>([]);
  const [ideaFor, setIdeaFor] = useState<Record<string, string>>({});
  const [submissions, setSubmissions] = useState<Array<{ id: string; group_name: string; topic: string; excerpt: string }>>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!course) return;
    pa<{ items: CatalogItem[] }>(`/assignments?course_id=${course.id}`)
      .then((data) => setItems(data.items))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not list assignments"));
    pa<{ items: Array<{ id: string; name: string }> }>(`/courses/${course.id}/roster`)
      .then((data) => setRoster(data.items))
      .catch(() => setRoster([]));
  }, [course]);

  useEffect(() => {
    if (!selected) {
      setAssignment(null);
      return;
    }
    pa<Assignment>(`/assignments/${selected}`)
      .then((data) => {
        setAssignment(data);
        setDraftGroups(data.groups.map((group) => ({ name: group.name, member_ids: group.member_ids })));
        const next: Record<string, string> = {};
        for (const pair of data.allocations) next[pair.group_id] = pair.idea_id;
        setIdeaFor(next);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not open that assignment"));
  }, [selected]);

  async function open(item: CatalogItem) {
    if (!course) return;
    if (item.id) {
      router.push(`/assignments?id=${item.id}`);
      return;
    }
    const created = await run(
      () =>
        pa<Assignment>("/assignments", {
          method: "POST",
          body: JSON.stringify({
            course_id: course.id,
            number: item.number,
            title: item.title,
            weight: item.weight,
            due: item.due,
            lo_codes: item.lo_codes,
            body: item.brief,
          }),
        }),
      setError,
    );
    if (!created) return;
    setItems((current) => current.map((row) => (row.number === item.number ? { ...row, id: created.id, status: created.status } : row)));
    router.push(`/assignments?id=${created.id}`);
  }

  return (
    <Grid>
      {error && (
        <Column lg={16}>
          <InlineNotification kind="error" title="Assignments" subtitle={error} hideCloseButton />
        </Column>
      )}
      <Column lg={16}>
        {!selected && (
          <table className="pa-assign-table">
            <thead>
              <tr>
                <th>Number</th>
                <th>Assignment</th>
                <th>Due</th>
                <th>Weight</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={`${item.number}-${item.title}`}>
                  <td>{item.number}</td>
                  <td>
                    <button type="button" className="pa-assign-open" onClick={() => open(item)}>
                      {item.title}
                    </button>
                  </td>
                  <td>{item.due || "Date open"}</td>
                  <td>{item.weight}%</td>
                  <td>{item.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {selected && assignment && (
          <div>
            <Button kind="ghost" onClick={() => router.push("/assignments")}>
              All assignments
            </Button>
            <Tabs>
              <TabList aria-label="Assignment">
                <Tab>Overview</Tab>
                <Tab>Ideas</Tab>
                <Tab>Groups</Tab>
                <Tab>Exemplars</Tab>
                <Tab>Submissions</Tab>
              </TabList>
              <TabPanels>
                <TabPanel>
                  <h2 style={{ fontWeight: 400, marginTop: 0 }}>
                    {assignment.number} {assignment.title}
                  </h2>
                  <p>
                    Due {assignment.due || "date open"} · {assignment.weight}% · {assignment.status}
                  </p>
                  <p>{assignment.body}</p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {(assignment.lo_codes || []).map((code) => (
                      <Tag key={code} type="blue">{code}</Tag>
                    ))}
                  </div>
                </TabPanel>
                <TabPanel>
                  <Button
                    kind="tertiary"
                    onClick={async () => {
                      const next = await run(() => pa<Assignment>(`/assignments/${assignment.id}/ideas`, { method: "POST" }), setError);
                      if (next) setAssignment(next);
                    }}
                  >
                    Generate 4–5 ideas
                  </Button>
                  <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
                    {assignment.ideas.map((idea, index) => (
                      <Tile key={idea.id}>
                        <strong>{index + 1}. {idea.title}</strong>
                        <p>{idea.brief}</p>
                      </Tile>
                    ))}
                    {assignment.ideas.length === 0 && <p>No ideas yet. Generate a set of four or five.</p>}
                  </div>
                </TabPanel>
                <TabPanel>
                  <p>Pick students from the roster, name the group, then give that group one idea.</p>
                  <div style={{ display: "grid", gap: 8 }}>
                    {roster.map((person) => (
                      <Checkbox
                        key={person.id}
                        id={person.id}
                        labelText={person.name}
                        checked={picked.includes(person.id)}
                        onChange={(_, { checked }) =>
                          setPicked((current) => (checked ? [...current, person.id] : current.filter((id) => id !== person.id)))
                        }
                      />
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
                    <input aria-label="Group name" value={groupName} onChange={(event) => setGroupName(event.target.value)} />
                    <Button
                      kind="secondary"
                      disabled={picked.length === 0}
                      onClick={() => {
                        setDraftGroups((current) => [...current, { name: groupName || `Group ${current.length + 1}`, member_ids: picked }]);
                        setPicked([]);
                        setGroupName(`Group ${draftGroups.length + 2}`);
                      }}
                    >
                      Add group
                    </Button>
                  </div>
                  {draftGroups.map((group) => (
                    <p key={group.name}>
                      {group.name}: {group.member_ids.map((id) => roster.find((person) => person.id === id)?.name || id).join(", ")}
                    </p>
                  ))}
                  {assignment.groups.map((group) => (
                    <Select
                      key={group.id}
                      id={`idea-${group.id}`}
                      labelText={`${group.name} idea`}
                      value={ideaFor[group.id] || ""}
                      onChange={(event) => setIdeaFor({ ...ideaFor, [group.id]: event.target.value })}
                    >
                      <SelectItem value="" text="Choose an idea" />
                      {assignment.ideas.map((idea) => (
                        <SelectItem key={idea.id} value={idea.id} text={idea.title} />
                      ))}
                    </Select>
                  ))}
                  <Button
                    kind="primary"
                    disabled={!course}
                    onClick={async () => {
                      if (!course) return;
                      await run(
                        () =>
                          pa(`/courses/${course.id}/groups`, {
                            method: "PUT",
                            body: JSON.stringify({ course_id: course.id, groups: draftGroups }),
                          }),
                        setError,
                      );
                      const next = await run(() => pa<Assignment>(`/assignments/${assignment.id}/allocate`, { method: "POST" }), setError);
                      if (next) setAssignment(next);
                    }}
                  >
                    Save groups
                  </Button>
                </TabPanel>
                <TabPanel>
                  <Button
                    kind="tertiary"
                    onClick={async () => {
                      const next = await run(() => pa<Assignment>(`/assignments/${assignment.id}/exemplars`, { method: "POST" }), setError);
                      if (next) setAssignment(next);
                    }}
                  >
                    Write exemplars
                  </Button>
                  {assignment.ideas.map((idea) =>
                    idea.exemplar ? (
                      <Tile key={idea.id}>
                        <strong>{idea.title}</strong>
                        <p>Strong: {idea.exemplar.strong}</p>
                        <p>Average: {idea.exemplar.average}</p>
                        <p>Weak: {idea.exemplar.weak}</p>
                      </Tile>
                    ) : null,
                  )}
                </TabPanel>
                <TabPanel>
                  <Button
                    kind="ghost"
                    onClick={async () => {
                      const data = await run(
                        () => pa<{ items: Array<{ id: string; group_name: string; topic: string; excerpt: string }> }>(`/assignments/${assignment.id}/submissions`),
                        setError,
                      );
                      if (data) setSubmissions(data.items);
                    }}
                  >
                    Load submissions
                  </Button>
                  {submissions.map((item) => (
                    <Tile key={item.id}>
                      <strong>{item.group_name || "Ungrouped"}</strong>
                      <span> · {item.topic}</span>
                      <p>{item.excerpt}</p>
                    </Tile>
                  ))}
                </TabPanel>
              </TabPanels>
            </Tabs>
          </div>
        )}
      </Column>
    </Grid>
  );
}
