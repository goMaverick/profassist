"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Dropdown, Tag, TextArea, Tile } from "@carbon/react";
import { pa, run } from "@/components/profassist/bits";

interface CourseOption {
  code: string;
  slug: string;
  title: string;
}
interface Card {
  course: string;
  slug: string;
  title: string;
  number: string;
  name: string;
  groups: number;
  flagged_pairs: number;
  highest: number;
  writing_flags: number;
  status: string;
}
interface Overview {
  courses: CourseOption[];
  summary: { courses: number; assignments: number; groups: number; review: number; concern: number };
  items: Card[];
}
interface PairRow {
  left: string;
  right: string;
  percent: number;
  shared: number;
  writing: boolean;
  status: string;
}
interface Matrix {
  course: string;
  slug: string;
  assignment: string;
  name: string;
  groups: string[];
  matrix: number[][];
  pairs: PairRow[];
}
interface Passage {
  id: string;
  percent: number;
  common: boolean;
  writing: string;
  left: string;
  right: string;
}
interface PairDetail {
  course: string;
  slug: string;
  assignment: string;
  name: string;
  left: string;
  right: string;
  percent: number;
  status: string;
  left_text: Array<{ id: string; text: string }>;
  right_text: Array<{ id: string; text: string }>;
  passages: Passage[];
  why: string;
}

export default function IntegrityPage() {
  return (
    <Suspense fallback={<p>Opening integrity…</p>}>
      <IntegrityDrill />
    </Suspense>
  );
}

function statusType(status: string): "green" | "blue" | "red" | "gray" {
  if (status === "Clear") return "green";
  if (status === "Review") return "blue";
  if (status === "Concern") return "red";
  return "gray";
}

function heat(percent: number) {
  if (percent >= 100) return "#e0e0e0";
  if (percent >= 75) return "#ffd7d9";
  if (percent >= 40) return "#d0e2ff";
  return "#defbe6";
}

function IntegrityDrill() {
  const router = useRouter();
  const params = useSearchParams();
  const course = params.get("course") || "all";
  const assignment = params.get("assignment") || "";
  const pair = params.get("pair") || "";
  const [overview, setOverview] = useState<Overview | null>(null);
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [detail, setDetail] = useState<PairDetail | null>(null);
  const [sort, setSort] = useState<"percent" | "shared">("percent");
  const [why, setWhy] = useState(false);
  const [note, setNote] = useState("");
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    pa<Overview>(`/integrity/overview?course=${encodeURIComponent(course)}`)
      .then(setOverview)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not open integrity"));
  }, [course]);

  useEffect(() => {
    if (!assignment) {
      setMatrix(null);
      return;
    }
    pa<Matrix>(`/integrity/matrix?course=${encodeURIComponent(course)}&number=${assignment}`)
      .then(setMatrix)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not open that assignment"));
  }, [course, assignment]);

  useEffect(() => {
    if (!assignment || !pair) {
      setDetail(null);
      return;
    }
    const [left, right] = pair.split("-");
    pa<PairDetail>(`/integrity/pair?course=${encodeURIComponent(course)}&number=${assignment}&left=${left}&right=${right}`)
      .then(setDetail)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not open that pair"));
  }, [course, assignment, pair]);

  const pairs = useMemo(() => {
    const rows = matrix?.pairs ? [...matrix.pairs] : [];
    rows.sort((a, b) => (sort === "shared" ? b.shared - a.shared : b.percent - a.percent));
    return rows;
  }, [matrix, sort]);

  function go(next: { course?: string; assignment?: string; pair?: string }) {
    const query = new URLSearchParams();
    const chosen = next.course ?? course;
    if (chosen && chosen !== "all") query.set("course", chosen);
    if (next.assignment) query.set("assignment", next.assignment);
    if (next.pair) query.set("pair", next.pair);
    router.push(`/integrity${query.toString() ? `?${query}` : ""}`);
  }

  async function act(action: "ok" | "flag" | "note") {
    if (!detail) return;
    const result = await run(
      () =>
        pa<{ message: string }>("/integrity/pair", {
          method: "POST",
          body: JSON.stringify({
            course: detail.slug,
            number: detail.assignment,
            left: detail.left,
            right: detail.right,
            action,
            note,
          }),
        }),
      setError,
    );
    if (result) setSaved(result.message);
  }

  const courseItems = [{ code: "All courses", slug: "all", title: "" }, ...(overview?.courses || [])];

  return (
    <div className="pa-dash">
      <nav className="pa-crumb" aria-label="Integrity">
        <button type="button" className="pa-why" onClick={() => go({ course, assignment: "", pair: "" })}>Course</button>
        {assignment && (
          <>
            {" / "}
            <button type="button" className="pa-why" onClick={() => go({ course, assignment, pair: "" })}>
              Assignment {assignment}
            </button>
          </>
        )}
        {detail && <> / Group {detail.left} and Group {detail.right}</>}
      </nav>
      {error && <p role="alert">{error}</p>}
      {!assignment && (
        <>
          <div style={{ maxWidth: 320 }}>
            <Dropdown
              id="integrity-course"
              titleText="Course"
              label="All courses"
              items={courseItems}
              itemToString={(item) => (item ? (item.slug === "all" ? "All courses" : `${item.code} · ${item.title}`) : "")}
              selectedItem={courseItems.find((item) => item.slug === course) || courseItems[0]}
              onChange={({ selectedItem }) => go({ course: selectedItem?.slug || "all" })}
            />
          </div>
          {overview && (
            <div className="pa-kpi-row">
              <Tile><p className="pa-step-kicker">Assignments</p><strong style={{ fontSize: "2rem" }}>{overview.summary.assignments}</strong></Tile>
              <Tile><p className="pa-step-kicker">Groups</p><strong style={{ fontSize: "2rem" }}>{overview.summary.groups}</strong></Tile>
              <Tile><p className="pa-step-kicker">Needs a look</p><strong style={{ fontSize: "2rem" }}>{overview.summary.review}</strong></Tile>
              <Tile><p className="pa-step-kicker">Concern</p><strong style={{ fontSize: "2rem" }}>{overview.summary.concern}</strong></Tile>
            </div>
          )}
          {overview && overview.items.length === 0 && <p>No assignments in this course yet.</p>}
          <div style={{ display: "grid", gap: 12 }}>
            {(overview?.items || []).map((item) => (
              <button
                key={`${item.slug}-${item.number}`}
                type="button"
                className="pa-panel"
                style={{ textAlign: "left", cursor: "pointer" }}
                onClick={() => go({ course: item.slug, assignment: item.number })}
              >
                <strong>{item.course} · Assignment {item.number}</strong>
                <span> {item.name}</span>
                <p style={{ margin: "8px 0" }}>
                  {item.groups} groups · {item.flagged_pairs} pairs to read · highest {item.highest}% · {item.writing_flags} writing flags
                </p>
                <Tag type={statusType(item.status)} size="sm">{item.status}</Tag>
              </button>
            ))}
          </div>
        </>
      )}
      {assignment && !pair && matrix && (
        <>
          <h2 style={{ margin: 0, fontWeight: 400 }}>{matrix.course} · Assignment {matrix.assignment} {matrix.name}</h2>
          <table className="pa-matrix" aria-label="Similarity between groups">
            <thead>
              <tr>
                <th />
                {matrix.groups.map((group) => <th key={group}>Group {group}</th>)}
              </tr>
            </thead>
            <tbody>
              {matrix.groups.map((left, row) => (
                <tr key={left}>
                  <th>Group {left}</th>
                  {matrix.groups.map((right, column) => (
                    <td key={right} style={{ background: left === right ? "#e0e0e0" : heat(matrix.matrix[row][column]) }}>
                      {left === right ? "—" : (
                        <button type="button" className="pa-why" onClick={() => go({ course: matrix.slug, assignment, pair: `${left}-${right}` })}>
                          {matrix.matrix[row][column]}%
                        </button>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <table className="pa-matrix">
            <thead>
              <tr>
                <th>Pair</th>
                <th><button type="button" className="pa-why" onClick={() => setSort("percent")}>Similar</button></th>
                <th><button type="button" className="pa-why" onClick={() => setSort("shared")}>Shared passages</button></th>
                <th>AI flag</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((item) => (
                <tr key={`${item.left}-${item.right}`} onClick={() => go({ course: matrix.slug, assignment, pair: `${item.left}-${item.right}` })} style={{ cursor: "pointer" }}>
                  <td>Group {item.left} vs Group {item.right}</td>
                  <td>{item.percent}%</td>
                  <td>{item.shared}</td>
                  <td>{item.writing ? "Yes" : "No"}</td>
                  <td><Tag type={statusType(item.status)} size="sm">{item.status}</Tag></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {detail && (
        <>
          <h2 style={{ margin: 0, fontWeight: 400 }}>Group {detail.left} and Group {detail.right}</h2>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span>{detail.percent}% similar</span>
            <Tag type={statusType(detail.status)} size="sm">{detail.status}</Tag>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <article id="left-submission">
              {detail.left_text.map((block, index) => (
                <p key={`${block.id}-${index}`} id={block.id ? `left-${block.id}` : undefined}>
                  {block.id ? (
                    <a href={`#right-${block.id}`}><mark>{block.text}</mark></a>
                  ) : block.text}
                </p>
              ))}
            </article>
            <article id="right-submission">
              {detail.right_text.map((block, index) => (
                <p key={`${block.id}-${index}`} id={block.id ? `right-${block.id}` : undefined}>
                  {block.id ? <mark>{block.text}</mark> : block.text}
                </p>
              ))}
            </article>
          </div>
          <h3 style={{ fontWeight: 600 }}>Shared passages</h3>
          {detail.passages.length === 0 && <p>No shared sentences. This looks like separate work.</p>}
          <ul>
            {detail.passages.map((item) => (
              <li key={item.id}>
                {item.percent}% · {item.common ? "Also in the assignment brief, so it is not counted as copying" : "Not in the brief or the readings"} · writing {item.writing}
              </li>
            ))}
          </ul>
          <button type="button" className="pa-why" style={{ display: "block", margin: "12px 0", textAlign: "left" }} onClick={() => setWhy((open) => !open)}>{why ? "Hide why" : "Why?"}</button>
          {why && <p id="integrity-why" className="pa-why-body">{detail.why}</p>}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16 }}>
            <Button kind="primary" onClick={() => act("ok")}>Mark as OK</Button>
            <Button kind="danger--tertiary" onClick={() => act("flag")}>Flag for follow-up</Button>
          </div>
          <TextArea id="integrity-note" labelText="Add a note" rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
          <Button kind="tertiary" onClick={() => act("note")}>Save note</Button>
          {saved && <p>{saved}</p>}
        </>
      )}
    </div>
  );
}
