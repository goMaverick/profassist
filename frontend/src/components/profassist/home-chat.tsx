"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  PromptInput,
  PromptInputActionAddAttachments,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuTrigger,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { Suggestion } from "@/components/ai-elements/suggestion";
import { Dropdown } from "@carbon/react";

interface CourseOption {
  id: string;
  code: string;
  title: string;
}
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Tool, ToolContent, ToolHeader } from "@/components/ai-elements/tool";

const CHIPS = [
  "Create a course outline",
  "Generate assessments",
  "Create assignment 2 for MAAI 903 due 15 Dec",
  "Check dropout risk",
  "Form groups for the project",
  "What is the Moodle sync status?",
];

interface ToolCard {
  name: string;
  output: unknown;
  href?: string;
}

interface Turn {
  you: string;
  reasoning: string;
  text: string;
  tool?: ToolCard;
  streaming: boolean;
}

export function HomeChat({
  courses = [],
  courseId,
  onCourse,
}: {
  courses?: CourseOption[];
  courseId?: string;
  onCourse?: (id: string) => void;
}) {
  const [name, setName] = useState("Professor");
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/auth/me")
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { full_name?: string } | null) => {
        const first = data?.full_name?.split(" ")[0];
        if (first) setName(first);
      })
      .catch(() => undefined);
  }, []);

  async function send(message: string) {
    const trimmed = message.trim();
    if (!trimmed) return;
    setBusy(true);
    setError("");
    setText("");
    setTurns((current) => [...current, { you: trimmed, reasoning: "", text: "", streaming: true }]);
    const patch = (fn: (turn: Turn) => Turn) => {
      setTurns((current) => {
        const next = current.slice();
        const last = next[next.length - 1];
        if (!last) return current;
        next[next.length - 1] = fn(last);
        return next;
      });
    };
    try {
      const response = await fetch("/api/profassist/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed }),
      });
      if (!response.ok || !response.body) throw new Error("The assistant could not start.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const event = part.match(/^event: (.+)$/m)?.[1];
          const raw = part.match(/^data: (.+)$/m)?.[1];
          if (!event || !raw) continue;
          const data = JSON.parse(raw) as Record<string, unknown>;
          if (event === "reasoning") patch((turn) => ({ ...turn, reasoning: String(data.text || "") }));
          if (event === "text") patch((turn) => ({ ...turn, text: turn.text + String(data.delta || "") }));
          if (event === "tool") {
            patch((turn) => ({
              ...turn,
              tool: {
                name: String(data.name || ""),
                output: data.output,
                href: typeof data.href === "string" ? data.href : undefined,
              },
            }));
          }
          if (event === "done") patch((turn) => ({ ...turn, streaming: false, text: String(data.reply || turn.text) }));
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "The assistant stopped.");
      patch((turn) => ({ ...turn, streaming: false }));
    }
    setBusy(false);
  }

  return (
    <section className="pa-hero" aria-label="Ask ProfAssist">
      <div className="pa-greet">
        <h2>Hi Professor {name}, what do you want to do?</h2>
        {courses.length > 0 && onCourse && (
          <Dropdown
            id="course-switcher"
            titleText="Course"
            label="Choose a course"
            items={courses}
            itemToString={(item) => (item ? `${item.code} · ${item.title}` : "")}
            selectedItem={courses.find((item) => item.id === courseId) || courses[0]}
            onChange={({ selectedItem }) => {
              if (selectedItem) onCourse(selectedItem.id);
            }}
          />
        )}
      </div>
      <PromptInput
        onSubmit={(message: PromptInputMessage) => send(message.text)}
      >
        <PromptInputBody>
          <PromptInputTextarea
            value={text}
            placeholder="Ask anything — create a course outline, generate assessments, check dropout risk…"
            onChange={(event) => setText(event.target.value)}
          />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools>
            <PromptInputActionMenu>
              <PromptInputActionMenuTrigger />
              <PromptInputActionMenuContent>
                <PromptInputActionAddAttachments />
              </PromptInputActionMenuContent>
            </PromptInputActionMenu>
          </PromptInputTools>
          <PromptInputSubmit status={busy ? "streaming" : "ready"} />
        </PromptInputFooter>
      </PromptInput>
      <div className="pa-chips">
        {CHIPS.map((chip) => (
          <Suggestion key={chip} suggestion={chip} onClick={(value) => send(value)} />
        ))}
      </div>
      {error && <p role="alert">{error}</p>}
      {turns.map((turn) => (
        <div key={turn.you} className="pa-hero-turn">
          <Message from="user">
            <MessageContent>
              <p>{turn.you}</p>
            </MessageContent>
          </Message>
          <Message from="assistant">
            <MessageContent>
              {turn.reasoning && (
                <Reasoning defaultOpen isStreaming={turn.streaming && !turn.text}>
                  <ReasoningTrigger />
                  <ReasoningContent>{turn.reasoning}</ReasoningContent>
                </Reasoning>
              )}
              {turn.tool && (
                <Tool defaultOpen>
                  <ToolHeader type="dynamic-tool" state="output-available" toolName={turn.tool.name} title={turn.tool.name} />
                  <ToolContent>
                    <ResultCard output={turn.tool.output} href={turn.tool.href} />
                  </ToolContent>
                </Tool>
              )}
              {turn.text && <MessageResponse>{turn.text}</MessageResponse>}
            </MessageContent>
          </Message>
        </div>
      ))}
      {turns.length > 0 && (
        <button type="button" className="pa-search" onClick={() => window.dispatchEvent(new Event("pa-open-chat"))}>
          Open the full chat
        </button>
      )}
    </section>
  );
}

function ResultCard({ output, href }: { output: unknown; href?: string }) {
  const row = output && typeof output === "object" ? (output as Record<string, unknown>) : null;
  if (!row) return <p>The tool finished.</p>;
  return (
    <article>
      <strong>{String(row.title || row.message || "Done")}</strong>
      {row.code ? <p style={{ margin: "4px 0", color: "#525252" }}>{String(row.code)}{row.due ? ` · due ${String(row.due)}` : ""} · {String(row.status || "draft")}</p> : null}
      {href ? <Link href={href}>Open it</Link> : null}
    </article>
  );
}
