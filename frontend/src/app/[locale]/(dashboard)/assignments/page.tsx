"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Plus } from "lucide-react";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  Card,
  Checkbox,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { pa, run, useWorkspace } from "@/components/profassist/bits";

interface CatalogItem {
  id: string;
  number: string;
  title: string;
  due: string;
  weight: number;
  status: string;
  lo_codes: string[];
  brief?: string;
  body?: string;
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
  assessment_id?: string;
  assessmentId?: string;
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

const NO_IDEA = "__none__";

function splitRoster(roster: Array<{ id: string; name: string }>, size: number) {
  const groups: Array<{ name: string; member_ids: string[] }> = [];
  for (let index = 0; index < roster.length; index += size) {
    groups.push({
      name: `Group ${groups.length + 1}`,
      member_ids: roster.slice(index, index + size).map((person) => person.id),
    });
  }
  return groups;
}

function DueChart({ items }: { items: CatalogItem[] }) {
  const marks = items.map((item) => {
    const week = /week\s+(\d+)/i.exec(item.due || "");
    return { ...item, week: week ? Number(week[1]) : 1 };
  });
  return (
    <svg
      viewBox="0 0 640 110"
      role="img"
      aria-label="Assignment due dates across twelve weeks"
      style={{ width: "100%", height: 110 }}
    >
      <line x1="20" y1="64" x2="620" y2="64" stroke="#c6c6c6" />
      {Array.from({ length: 12 }, (_, index) => (
        <text key={index} x={20 + index * 52} y="96" fontSize="11" fill="#525252">
          W{index + 1}
        </text>
      ))}
      {marks.map((item) => (
        <g key={item.number}>
          <circle
            cx={20 + (Math.min(12, Math.max(1, item.week)) - 1) * 52}
            cy="64"
            r="8"
            fill="#0f62fe"
          />
          <text
            x={20 + (Math.min(12, Math.max(1, item.week)) - 1) * 52}
            y="40"
            fontSize="12"
            textAnchor="middle"
            fill="#161616"
          >
            {item.number}
          </text>
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
  // ?tab=groups opens the Groups tab directly, so Set up groups lands on the right panel.
  const requestedTab = params.get("tab") === "groups" ? "groups" : "overview";
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [summary, setSummary] = useState<Summary>({
    submissions: 0,
    groups: 0,
    flags: 0,
    approved: 0,
    drafts: 0,
  });
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [roster, setRoster] = useState<Array<{ id: string; name: string }>>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [groupName, setGroupName] = useState("Group 1");
  const [draftGroups, setDraftGroups] = useState<Array<{ name: string; member_ids: string[] }>>([]);
  const [ideaFor, setIdeaFor] = useState<Record<string, string>>({});
  const [submissions, setSubmissions] = useState<
    Array<{ id: string; group_name: string; topic: string; excerpt: string }>
  >([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [tab, setTab] = useState("overview");

  useEffect(() => {
    if (!course) return;
    pa<{ items: CatalogItem[]; summary?: Summary }>(`/assignments?course_id=${course.id}`)
      .then((data) => {
        setItems(data.items);
        if (data.summary) setSummary(data.summary);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not list assignments"),
      );
    pa<{ items: Array<{ id: string; name: string }> }>(`/courses/${course.id}/roster`)
      .then((data) => setRoster(data.items))
      .catch(() => setRoster([]));
  }, [course]);

  useEffect(() => {
    if (!selected) {
      setAssignment(null);
      return;
    }
    setTab(requestedTab);
    pa<Assignment>(`/assignments/${selected}`)
      .then((data) => {
        setAssignment(data);
        setDraftGroups(
          data.groups.map((group) => ({ name: group.name, member_ids: group.member_ids })),
        );
        const next: Record<string, string> = {};
        for (const pair of data.allocations) next[pair.group_id] = pair.idea_id;
        setIdeaFor(next);
        pa<{ items: Array<{ id: string; group_name: string; topic: string; excerpt: string }> }>(
          `/assignments/${selected}/submissions`,
        )
          .then((rows) => setSubmissions(rows.items))
          .catch(() => setSubmissions([]));
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Could not open that assignment"),
      );
  }, [selected, requestedTab]);

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
            body: item.brief ?? item.body ?? "",
          }),
        }),
      setError,
    );
    if (!created) return;
    setItems((current) =>
      current.map((row) =>
        row.number === item.number ? { ...row, id: created.id, status: created.status } : row,
      ),
    );
    router.push(`/assignments?id=${created.id}`);
  }

  return (
    <div className="grid grid-cols-1 gap-4">
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Assignments</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div>
        {!selected && (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 style={{ fontWeight: 400, margin: 0 }}>Assignments</h2>
              <Button asChild size="sm">
                <Link href="/assignments/new">
                  <Plus className="h-4 w-4" />
                  Create assignment
                </Link>
              </Button>
            </div>
            <div className="pa-kpi-row">
              <Card className="p-4">
                <p className="pa-step-kicker">Submissions</p>
                <strong style={{ fontSize: "2rem" }}>{summary.submissions}</strong>
              </Card>
              <Card className="p-4">
                <p className="pa-step-kicker">Groups</p>
                <strong style={{ fontSize: "2rem" }}>{summary.groups}</strong>
              </Card>
              <Card className="p-4">
                <p className="pa-step-kicker">Approved grades</p>
                <strong style={{ fontSize: "2rem" }}>{summary.approved}</strong>
                <p>
                  {summary.drafts} draft{summary.drafts === 1 ? "" : "s"}
                </p>
              </Card>
              <Card className="p-4">
                <p className="pa-step-kicker">Open flags</p>
                <strong style={{ fontSize: "2rem" }}>{summary.flags}</strong>
              </Card>
            </div>
            <Card className="p-4">
              <h2 style={{ fontWeight: 400, marginTop: 0 }}>Due dates</h2>
              <DueChart items={items} />
            </Card>
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
            <Button variant="ghost" onClick={() => router.push("/assignments")}>
              All assignments
            </Button>
            <Tabs value={tab} onValueChange={setTab}>
              <TabsList aria-label="Assignment">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="ideas">Ideas</TabsTrigger>
                <TabsTrigger value="groups">Groups</TabsTrigger>
                <TabsTrigger value="exemplars">Exemplars</TabsTrigger>
                <TabsTrigger value="submissions">Submissions</TabsTrigger>
              </TabsList>
              <TabsContent value="overview">
                <h2 style={{ fontWeight: 400, marginTop: 0 }}>
                  {assignment.number} {assignment.title}
                </h2>
                <p>
                  Due {assignment.due || "date open"} · {assignment.weight}% · {assignment.status}
                </p>
                <div className="pa-kpi-row">
                  <Card className="p-4">
                    <p className="pa-step-kicker">Ideas</p>
                    <strong style={{ fontSize: "2rem" }}>{assignment.ideas.length}</strong>
                  </Card>
                  <Card className="p-4">
                    <p className="pa-step-kicker">Groups</p>
                    <strong style={{ fontSize: "2rem" }}>{assignment.groups.length}</strong>
                  </Card>
                  <Card className="p-4">
                    <p className="pa-step-kicker">Outcomes</p>
                    <strong style={{ fontSize: "2rem" }}>
                      {(assignment.lo_codes || []).length}
                    </strong>
                  </Card>
                  <Card className="p-4">
                    <p className="pa-step-kicker">Submissions</p>
                    <strong style={{ fontSize: "2rem" }}>{submissions.length}</strong>
                  </Card>
                </div>
                <p>{assignment.body}</p>
                <p>Maps to {(assignment.lo_codes || []).join(", ") || "no outcomes yet"}.</p>
                <div className="pa-meter" aria-label="Submissions received">
                  <span
                    style={{
                      width: `${Math.min(100, (submissions.length / Math.max(roster.length, submissions.length, 1)) * 100)}%`,
                      background: "#0f62fe",
                    }}
                  />
                </div>
                <p>
                  {submissions.length} received · {roster.length} students on the roster
                </p>
                <h3 style={{ fontWeight: 600 }}>Rubric</h3>
                {assignment.assessment_id || assignment.assessmentId ? (
                  <p>
                    <Link
                      className="underline"
                      href={`/rubric?assessment=${encodeURIComponent(assignment.assessment_id || assignment.assessmentId || "")}`}
                    >
                      Edit rubric
                    </Link>
                  </p>
                ) : (
                  <p>Rubric is created with the assignment.</p>
                )}
                {(items.find((item) => item.id === assignment.id)?.criteria || []).map((row) => (
                  <p key={row.name} style={{ margin: "4px 0" }}>
                    {row.name} · {row.weight}%
                  </p>
                ))}
                {(items.find((item) => item.id === assignment.id)?.criteria || []).length === 0 && (
                  <p>No rubric rows stored on this task yet.</p>
                )}
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16 }}>
                  <Button variant="outline" onClick={() => setTab("groups")}>
                    Set up groups
                  </Button>
                  <Button
                    variant="outline"
                    onClick={async () => {
                      const next = await run(
                        () =>
                          pa<Assignment & { message?: string }>(
                            `/assignments/${assignment.id}/class`,
                            { method: "POST" },
                          ),
                        setError,
                      );
                      if (next) {
                        setAssignment(next);
                        setNote(next.message || "Groups are ready.");
                      }
                    }}
                  >
                    Form groups of two
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={async () => {
                      const next = await run(
                        () =>
                          pa<Assignment>(`/assignments/${assignment.id}/publish`, {
                            method: "POST",
                          }),
                        setError,
                      );
                      if (next) {
                        setAssignment(next);
                        setNote("Published to Moodle. Moodle was not contacted.");
                      }
                    }}
                  >
                    Publish to Moodle
                  </Button>
                  <Button
                    onClick={async () => {
                      const next = await run(
                        () =>
                          pa<{
                            assignment: Assignment;
                            submissions: Array<{
                              id: string;
                              group_name: string;
                              topic: string;
                              excerpt: string;
                            }>;
                            message: string;
                          }>(`/assignments/${assignment.id}/receive`, { method: "POST" }),
                        setError,
                      );
                      if (next) {
                        setAssignment(next.assignment);
                        setSubmissions(next.submissions);
                        setNote(next.message);
                      }
                    }}
                  >
                    Sync student submissions
                  </Button>
                </div>
                {note && <p>{note}</p>}
              </TabsContent>
              <TabsContent value="ideas">
                <Button
                  variant="outline"
                  onClick={async () => {
                    const next = await run(
                      () =>
                        pa<Assignment>(`/assignments/${assignment.id}/ideas`, { method: "POST" }),
                      setError,
                    );
                    if (next) setAssignment(next);
                  }}
                >
                  Suggest ideas with council
                </Button>
                <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
                  {assignment.ideas.map((idea, index) => (
                    <Card key={idea.id} className="p-4">
                      <strong>
                        {index + 1}. {idea.title}
                      </strong>
                      <p>{idea.brief}</p>
                    </Card>
                  ))}
                  {assignment.ideas.length === 0 && (
                    <p>No ideas yet. Open an assignment and ask the council to suggest ideas.</p>
                  )}
                </div>
              </TabsContent>
              <TabsContent value="groups">
                <p>Pick students from the roster, name the group, then give that group one idea.</p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0 12px" }}>
                  <Button
                    variant="outline"
                    disabled={roster.length === 0}
                    onClick={() => {
                      setDraftGroups(splitRoster(roster, 3));
                      setNote(`${Math.ceil(roster.length / 3)} groups staged from the roster.`);
                    }}
                  >
                    Split roster into groups of 3
                  </Button>
                </div>
                <div style={{ display: "grid", gap: 8 }}>
                  {roster.map((person) => (
                    <div key={person.id} className="flex items-center gap-2">
                      <Checkbox
                        id={person.id}
                        checked={picked.includes(person.id)}
                        onCheckedChange={(checked) =>
                          setPicked((current) =>
                            checked === true
                              ? [...current, person.id]
                              : current.filter((id) => id !== person.id),
                          )
                        }
                      />
                      <Label htmlFor={person.id}>{person.name}</Label>
                    </div>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
                  <Input
                    aria-label="Group name"
                    value={groupName}
                    onChange={(event) => setGroupName(event.target.value)}
                  />
                  <Button
                    variant="secondary"
                    disabled={picked.length === 0}
                    onClick={() => {
                      setDraftGroups((current) => [
                        ...current,
                        { name: groupName || `Group ${current.length + 1}`, member_ids: picked },
                      ]);
                      setPicked([]);
                      setGroupName(`Group ${draftGroups.length + 2}`);
                    }}
                  >
                    Add group
                  </Button>
                </div>
                {draftGroups.map((group) => (
                  <p key={group.name}>
                    {group.name}:{" "}
                    {group.member_ids
                      .map((id) => roster.find((person) => person.id === id)?.name || id)
                      .join(", ")}
                  </p>
                ))}
                {assignment.groups.length > 0 && (
                  <div style={{ margin: "12px 0" }}>
                    <h3 style={{ fontWeight: 600 }}>Saved groups</h3>
                    {assignment.groups.map((group) => (
                      <p key={group.id}>
                        {group.name}:{" "}
                        {group.member_ids
                          .map((id) => roster.find((person) => person.id === id)?.name || id)
                          .join(", ") || "No members"}
                      </p>
                    ))}
                  </div>
                )}
                {assignment.groups.map((group) => (
                  <div key={group.id} className="space-y-1.5">
                    <Label htmlFor={`idea-${group.id}`}>{group.name} idea</Label>
                    <Select
                      value={ideaFor[group.id] || NO_IDEA}
                      onValueChange={(value) =>
                        setIdeaFor({ ...ideaFor, [group.id]: value === NO_IDEA ? "" : value })
                      }
                    >
                      <SelectTrigger id={`idea-${group.id}`}>
                        <SelectValue placeholder="Choose an idea" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NO_IDEA}>Choose an idea</SelectItem>
                        {assignment.ideas.map((idea) => (
                          <SelectItem key={idea.id} value={idea.id}>
                            {idea.title}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ))}
                <Button
                  disabled={!course || draftGroups.length === 0}
                  onClick={async () => {
                    const saved = await run(
                      () =>
                        pa<{ items: Group[] }>(`/assignments/${assignment.id}/groups`, {
                          method: "POST",
                          body: JSON.stringify({ groups: draftGroups }),
                        }),
                      setError,
                    );
                    if (!saved) return;
                    const next = await run(
                      () =>
                        pa<Assignment>(`/assignments/${assignment.id}/allocate`, {
                          method: "POST",
                        }),
                      setError,
                    );
                    if (next) {
                      setAssignment(next);
                      setDraftGroups(
                        next.groups.map((group) => ({
                          name: group.name,
                          member_ids: group.member_ids,
                        })),
                      );
                      const allocation: Record<string, string> = {};
                      for (const pair of next.allocations) allocation[pair.group_id] = pair.idea_id;
                      setIdeaFor(allocation);
                      setNote(`${next.groups.length} groups saved for this assignment.`);
                    }
                  }}
                >
                  Save groups
                </Button>
              </TabsContent>
              <TabsContent value="exemplars">
                <Button
                  variant="outline"
                  onClick={async () => {
                    const next = await run(
                      () =>
                        pa<Assignment>(`/assignments/${assignment.id}/exemplars`, {
                          method: "POST",
                        }),
                      setError,
                    );
                    if (next) setAssignment(next);
                  }}
                >
                  Write exemplar
                </Button>
                {assignment.ideas.map((idea) =>
                  idea.exemplar ? (
                    <Card key={idea.id} className="p-4">
                      <strong>{idea.title}</strong>
                      <p>Strong: {idea.exemplar.strong}</p>
                      <p>Average: {idea.exemplar.average}</p>
                      <p>Weak: {idea.exemplar.weak}</p>
                    </Card>
                  ) : null,
                )}
              </TabsContent>
              <TabsContent value="submissions">
                <Button
                  variant="ghost"
                  onClick={async () => {
                    const data = await run(
                      () =>
                        pa<{
                          items: Array<{
                            id: string;
                            group_name: string;
                            topic: string;
                            excerpt: string;
                          }>;
                        }>(`/assignments/${assignment.id}/submissions`),
                      setError,
                    );
                    if (data) setSubmissions(data.items);
                  }}
                >
                  Load submissions
                </Button>
                {submissions.map((item) => (
                  <Card key={item.id} className="p-4">
                    <strong>{item.group_name || "Ungrouped"}</strong>
                    <span> · {item.topic}</span>
                    <p>{item.excerpt}</p>
                  </Card>
                ))}
              </TabsContent>
            </Tabs>
          </div>
        )}
      </div>
    </div>
  );
}
