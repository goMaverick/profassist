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
import { AiLive } from "@/components/profassist/ai-live";

const COUNCIL_IDEAS = [
  { title: "Clinic triage assistant", brief: "A group designs an intake model and a rollback plan for a campus clinic.", exemplar: "Strong work names the data version, the threshold, and one failure mode. Average work describes the model without the rollback. Weak work lists tools and stops." },
  { title: "Library occupancy forecast", brief: "Predict seat demand and publish the model card with the data version.", exemplar: "Strong work shows a week of forecasts against the actual count. Average work has the chart and no error. Weak work is a screenshot." },
  { title: "Energy dashboard", brief: "Stream building meters into a monitored pipeline with a drift check.", exemplar: "Strong work states what happens when the meter feed stops. Average work deploys the API. Weak work describes the dashboard only." },
  { title: "Exam integrity review", brief: "Compare submissions after the shared brief is removed. A flag is not a verdict.", exemplar: "Strong work quotes the shared sentence and the sentence that remains. Average work reports a score. Weak work calls it cheating." },
  { title: "Deployment rehearsal", brief: "Ship a small API, then write the runbook a mixed audience can follow.", exemplar: "Strong work includes the rollback command and who is called. Average work lists the steps. Weak work says it was deployed." },
];

interface CatalogItem {
  id: string;
  number: string;
  title: string;
  due: string;
  weight: number;
  status: string;
  lo_codes: string[];
  brief: string;
  criteria?: Array<{ name: string; weight: number }>;
}
interface Summary {
  submissions: number;
  groups: number;
  flags: number;
  approved: number;
  drafts: number;
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

function DueChart({ items }: { items: CatalogItem[] }) {
  const marks = items.map((item) => {
    const week = /week\s+(\d+)/i.exec(item.due || "");
    return { ...item, week: week ? Number(week[1]) : 1 };
  });
  return (
    <svg viewBox="0 0 640 110" role="img" aria-label="Assignment due dates across twelve weeks" style={{ width: "100%", height: 110 }}>
      <line x1="20" y1="64" x2="620" y2="64" stroke="#c6c6c6" />
      {Array.from({ length: 12 }, (_, index) => (
        <text key={index} x={20 + index * 52} y="96" fontSize="11" fill="#525252">W{index + 1}</text>
      ))}
      {marks.map((item) => (
        <g key={item.number}>
          <circle cx={20 + (Math.min(12, Math.max(1, item.week)) - 1) * 52} cy="64" r="8" fill="#0f62fe" />
          <text x={20 + (Math.min(12, Math.max(1, item.week)) - 1) * 52} y="40" fontSize="12" textAnchor="middle" fill="#161616">{item.number}</text>
        </g>
      ))}
    </svg>
  );
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
  const [summary, setSummary] = useState<Summary>({ submissions: 0, groups: 0, flags: 0, approved: 0, drafts: 0 });
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
    pa<{ items: CatalogItem[]; summary?: Summary }>(`/assignments?course_id=${course.id}`)
      .then((data) => {
        setItems(data.items);
        if (data.summary) setSummary(data.summary);
      })
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
        pa<{ items: Array<{ id: string; group_name: string; topic: string; excerpt: string }> }>(`/assignments/${selected}/submissions`)
          .then((rows) => setSubmissions(rows.items))
          .catch(() => setSubmissions([]));
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
          <>
          <div className="pa-kpi-row">
            <Tile><p className="pa-step-kicker">Submissions</p><strong style={{ fontSize: "2rem" }}>{summary.submissions}</strong></Tile>
            <Tile><p className="pa-step-kicker">Groups</p><strong style={{ fontSize: "2rem" }}>{summary.groups}</strong></Tile>
            <Tile><p className="pa-step-kicker">Approved grades</p><strong style={{ fontSize: "2rem" }}>{summary.approved}</strong><p>{summary.drafts} drafts</p></Tile>
            <Tile><p className="pa-step-kicker">Open flags</p><strong style={{ fontSize: "2rem" }}>{summary.flags}</strong></Tile>
          </div>
          <Tile>
            <h2 style={{ fontWeight: 400, marginTop: 0 }}>Due dates</h2>
            <DueChart items={items} />
          </Tile>
          <AiLive
            title="Suggest ideas with council"
            reasoning="Five ideas for the group project. Several groups may share one idea. Each group still submits its own work."
            sources={[{ href: "/outline", title: "MAAI 903 outcomes" }, { href: "/assignments", title: "A3 Group project" }]}
            tasks={["Read LO1 to LO6", "Prefer a project a group can build in four weeks", "Auto-suggest groups of two from the roster"]}
            suggestions={COUNCIL_IDEAS.map((idea) => idea.title)}
          >
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {COUNCIL_IDEAS.map((idea, index) => (
                <Tile key={idea.title}>
                  <strong>{index + 1}. {idea.title}</strong>
                  <p>{idea.brief}</p>
                  <p><b>Exemplar.</b> {idea.exemplar}</p>
                </Tile>
              ))}
            </div>
            <p>Groups auto-suggest: pair the roster in twos, then give each pair one of these ideas.</p>
          </AiLive>
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
          </>
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
                  <div className="pa-kpi-row">
                    <Tile><p className="pa-step-kicker">Ideas</p><strong style={{ fontSize: "2rem" }}>{assignment.ideas.length}</strong></Tile>
                    <Tile><p className="pa-step-kicker">Groups</p><strong style={{ fontSize: "2rem" }}>{assignment.groups.length}</strong></Tile>
                    <Tile><p className="pa-step-kicker">Outcomes</p><strong style={{ fontSize: "2rem" }}>{(assignment.lo_codes || []).length}</strong></Tile>
                    <Tile><p className="pa-step-kicker">Submissions</p><strong style={{ fontSize: "2rem" }}>{submissions.length}</strong></Tile>
                  </div>
                  <p>{assignment.body}</p>
                  <p>Maps to {(assignment.lo_codes || []).join(", ") || "no outcomes yet"}.</p>
                  <div className="pa-meter" aria-label="Submissions received">
                    <span style={{ width: `${Math.min(100, (submissions.length / Math.max(roster.length, submissions.length, 1)) * 100)}%`, background: "#0f62fe" }} />
                  </div>
                  <p>{submissions.length} received · {roster.length} students on the roster</p>
                  <h3 style={{ fontWeight: 600 }}>Rubric</h3>
                  {(items.find((item) => item.id === assignment.id)?.criteria || []).map((row) => (
                    <p key={row.name} style={{ margin: "4px 0" }}>{row.name} · {row.weight}%</p>
                  ))}
                  {(items.find((item) => item.id === assignment.id)?.criteria || []).length === 0 && <p>No rubric rows stored on this task yet.</p>}
                </TabPanel>
                <TabPanel>
                  <Button
                    kind="tertiary"
                    onClick={async () => {
                      const next = await run(() => pa<Assignment>(`/assignments/${assignment.id}/ideas`, { method: "POST" }), setError);
                      if (next) setAssignment(next);
                    }}
                  >
                    Suggest ideas with council
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
                    Write exemplar
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
