"use client";

import { useState } from "react";
import { Checkmark } from "@carbon/icons-react";
import { MessageResponse } from "@/components/ai-elements/message";

interface CaseRow {
  groups: string[];
  percent: number;
  href: string;
  course: string;
  assignment: string;
  name: string;
}

export function toolLabel(name: string) {
  if (name === "integrity_concerns") return "Checked integrity";
  if (name === "assist_outline") return "Drafted outcomes";
  if (name === "moodle_sync") return "Checked Moodle";
  if (name === "list_courses") return "Listed courses";
  return name.replaceAll("_", " ");
}

function casesOf(output: unknown): CaseRow[] {
  if (!output || typeof output !== "object" || !("cases" in output)) return [];
  const rows = (output as { cases?: unknown }).cases;
  if (!Array.isArray(rows)) return [];
  return rows.flatMap((row) => {
    if (!row || typeof row !== "object") return [];
    const item = row as {
      groups?: unknown;
      percent?: unknown;
      href?: unknown;
      course?: unknown;
      assignment?: unknown;
      name?: unknown;
    };
    const groups = Array.isArray(item.groups) ? item.groups.map(String) : [];
    if (groups.length < 2 || typeof item.href !== "string") return [];
    return [
      {
        groups,
        percent: Number(item.percent) || 0,
        href: item.href,
        course: String(item.course || ""),
        assignment: String(item.assignment || ""),
        name: String(item.name || ""),
      },
    ];
  });
}

function badgeClass(percent: number) {
  if (percent >= 70) return "is-high";
  if (percent >= 50) return "is-mid";
  return "is-low";
}

function spokenCode(code: string) {
  const compact = code.replace(/[^A-Za-z0-9]/g, "");
  const match = compact.match(/^([A-Za-z]+)(\d+)$/);
  return match ? `${match[1].toUpperCase()} ${match[2]}` : code;
}

export function IntegrityAnswer({ output }: { output: unknown }) {
  const cases = casesOf(output);
  if (!cases.length) return null;
  const named = spokenCode(String((output as { course?: string }).course || ""));
  const own = cases.some((item) => spokenCode(item.course).replace(/\s/g, "") === named.replace(/\s/g, ""));
  const assignments = new Set(cases.map((item) => `${item.course}-${item.assignment}`)).size;
  const caseWord = `${cases.length} case${cases.length === 1 ? "" : "s"}`;
  const verb = cases.length === 1 ? "needs" : "need";
  const assignmentWord = `${assignments} assignment${assignments === 1 ? "" : "s"}`;
  const summary = own
    ? `${caseWord} ${verb} a look across ${assignmentWord}.`
    : `${named} has no copying cases yet. ${caseWord} ${verb} a look across ${assignmentWord} in other courses.`;
  return (
    <div className="pa-answer">
      <p className="pa-case-summary">{summary}</p>
      <div className="pa-cases" role="table">
        <div className="pa-case-head" role="row">
          <span role="columnheader">Assignment</span>
          <span role="columnheader">Groups</span>
          <span className="pa-case-end" role="columnheader">Similarity</span>
        </div>
        {cases.map((item) => (
          <div className="pa-case" role="row" key={item.href}>
            <span className="pa-case-assign" role="cell">{item.course} · {item.name || `Assignment ${item.assignment}`}</span>
            <span className="pa-case-groups" role="cell">Group {item.groups[0]} and Group {item.groups[1]}</span>
            <span className="pa-case-end" role="cell">
              <span className={`pa-sim ${badgeClass(item.percent)}`}>{item.percent}%</span>
              <a className="pa-open" href={item.href}>Open<span className="pa-open-chevron" aria-hidden="true"> ›</span></a>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function detailText(output: unknown) {
  if (!output || typeof output !== "object") return "The tool finished.";
  const message = (output as { message?: unknown }).message;
  if (typeof message === "string" && message.trim()) return message;
  return "The tool finished.";
}

export function QuietTool({ name, output }: { name: string; output: unknown }) {
  const [open, setOpen] = useState(false);
  const cases = casesOf(output);
  return (
    <div className="pa-quiet-tool">
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <Checkmark size={16} />
        <span>
          {toolLabel(name)} · details
        </span>
      </button>
      {open && (
        <div className="pa-quiet-detail">
          <p>{cases.length > 0 ? "The rows below are the same cases as the integrity page." : detailText(output)}</p>
        </div>
      )}
    </div>
  );
}

export function AnswerText({ text }: { text: string }) {
  if (!text) return null;
  return <MessageResponse className="pa-answer">{text}</MessageResponse>;
}
