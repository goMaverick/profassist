"use client";

import { useEffect, useState } from "react";
import { ArrowUp } from "lucide-react";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface CourseOption {
  id: string;
  code: string;
  title: string;
}
import { AnswerText, AtRiskAnswer, IntegrityAnswer, QuietTool } from "@/components/profassist/quiet-chat";
import { sendChat, useChat } from "@/components/profassist/chat-store";

const CHIPS = [
  "Create a course outline",
  "Generate assessments",
  "Create an assignment",
  "Check dropout risk",
  "Form groups for the project",
  "What is the Moodle sync status?",
];

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
  const { turns, busy, error } = useChat();

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
    setText("");
    await sendChat(message);
  }

  return (
    <section className="pa-hero" aria-label="Ask ProfAssist">
      <div className="pa-greet">
        <h2>Hi Professor {name}, what do you want to do?</h2>
        {courses.length > 0 && onCourse && (
          <div className="grid gap-2">
            <Label htmlFor="course-switcher">Course</Label>
            <Select
              value={(courses.find((item) => item.id === courseId) || courses[0])?.id}
              onValueChange={(id) => {
                const next = courses.find((item) => item.id === id);
                if (next) onCourse(next.id);
              }}
            >
              <SelectTrigger id="course-switcher" aria-label="Course">
                <SelectValue placeholder="Choose a course" />
              </SelectTrigger>
              <SelectContent>
                {courses.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {`${item.code} · ${item.title}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
      <div className="pa-chat-column">
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
          <PromptInputSubmit className="pa-send" status={busy ? "streaming" : "ready"}>
            <ArrowUp className="size-4" />
          </PromptInputSubmit>
        </PromptInputFooter>
      </PromptInput>
      {turns.length === 0 && (
        <div className="pa-chips">
          {CHIPS.map((chip) => (
            <Suggestion key={chip} suggestion={chip} onClick={(value) => send(value)} />
          ))}
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {turns.length > 0 && (() => {
        const last = turns[turns.length - 1];
        if (!last) return null;
        return (
          <div className="pa-thread">
            <div className="pa-user-bubble">
              <p>{last.you}</p>
            </div>
            {last.tool && <QuietTool name={last.tool.name} output={last.tool.output} />}
            {last.tool?.name === "integrity_concerns" ? (
              <IntegrityAnswer output={last.tool.output} />
            ) : last.tool?.name === "dropout_risk" ? (
              <AtRiskAnswer output={last.tool.output} />
            ) : (
              <AnswerText text={last.text} />
            )}
            <button type="button" className="pa-text-link" onClick={() => window.dispatchEvent(new Event("pa-open-chat"))}>
              Open the full chat
            </button>
          </div>
        );
      })()}
      </div>
    </section>
  );
}

