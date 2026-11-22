"use client";

import { useState } from "react";
import { Button } from "@carbon/react";
import { Close } from "@carbon/icons-react";
import { CopyIcon, RotateCcwIcon, ThumbsUpIcon } from "lucide-react";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputActionAddAttachments,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuTrigger,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSelect,
  PromptInputSelectContent,
  PromptInputSelectItem,
  PromptInputSelectTrigger,
  PromptInputSelectValue,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import {
  Confirmation,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRequest,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Source, Sources, SourcesContent, SourcesTrigger } from "@/components/ai-elements/sources";
import { Suggestion } from "@/components/ai-elements/suggestion";
import { Tool, ToolContent, ToolHeader } from "@/components/ai-elements/tool";
import {
  Queue,
  QueueItem,
  QueueItemContent,
  QueueList,
  QueueSection,
  QueueSectionContent,
  QueueSectionLabel,
  QueueSectionTrigger,
} from "@/components/ai-elements/queue";

interface ToolCard {
  name: string;
  state: "approval-requested" | "output-available" | "output-denied";
  input: unknown;
  output: unknown;
}

interface AssistantTurn {
  reasoning: string;
  text: string;
  tool?: ToolCard;
  sources: Array<{ href: string; title: string }>;
  needsConfirm: boolean;
  streaming: boolean;
}

interface UserTurn {
  text: string;
  files: string[];
}

const CHIPS = ["Sync Moodle", "List my courses", "Suggest an assessment", "Draft this week's slides"];

export function ProfessorChat({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("Sync Moodle");
  const [model, setModel] = useState("demo");
  const [users, setUsers] = useState<UserTurn[]>([]);
  const [assistants, setAssistants] = useState<AssistantTurn[]>([]);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [liked, setLiked] = useState(false);

  async function send(message: string, confirmed = false, files: string[] = []) {
    const trimmed = message.trim();
    if (!trimmed && !confirmed) return;
    setBusy(true);
    setError("");
    if (!confirmed) {
      setUsers((current) => [...current, { text: trimmed, files }]);
      setAssistants((current) => [
        ...current,
        { reasoning: "", text: "", sources: [], needsConfirm: false, streaming: true },
      ]);
    }
    try {
      const response = await fetch("/api/profassist/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: confirmed ? "confirm" : trimmed,
          confirmed,
          pending_tool: pending,
          model,
        }),
      });
      if (!response.ok || !response.body) {
        throw new Error("The assistant could not start.");
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const apply = (patch: (turn: AssistantTurn) => AssistantTurn) => {
        setAssistants((current) => {
          if (!current.length) return current;
          const next = current.slice();
          const last = next[next.length - 1];
          if (!last) return current;
          next[next.length - 1] = patch(last);
          return next;
        });
      };
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
          if (event === "reasoning") {
            apply((turn) => ({ ...turn, reasoning: String(data.text || "") }));
          }
          if (event === "text") {
            apply((turn) => ({ ...turn, text: turn.text + String(data.delta || "") }));
          }
          if (event === "tool") {
            apply((turn) => ({
              ...turn,
              tool: {
                name: String(data.name || ""),
                state: (data.state as ToolCard["state"]) || "output-available",
                input: data.input,
                output: data.output,
              },
            }));
          }
          if (event === "source") {
            apply((turn) => ({
              ...turn,
              sources: [...turn.sources, { href: String(data.href || ""), title: String(data.title || "Source") }],
            }));
          }
          if (event === "done") {
            const toolName = String(data.tool || "");
            const needs = Boolean(data.needs_confirm);
            setPending(needs && toolName ? toolName : "");
            apply((turn) => ({ ...turn, needsConfirm: needs, streaming: false, text: String(data.reply || turn.text) }));
          }
        }
      }
      if (!confirmed) setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "The assistant stopped.");
      setAssistants((current) => current.map((turn, index) => (index === current.length - 1 ? { ...turn, streaming: false } : turn)));
    }
    setBusy(false);
  }

  async function onSubmit(message: PromptInputMessage) {
    const names = message.files.map((file) => file.filename || "file");
    const body = names.length ? `${message.text}\nAttached: ${names.join(", ")}` : message.text;
    await send(body, false, names);
  }

  return (
    <aside className="pa-ai pa-chat-sheet" aria-label="ProfAssist chat">
      <div className="pa-chat-bar">
        <strong>Ask ProfAssist</strong>
        <Button kind="ghost" hasIconOnly renderIcon={Close} iconDescription="Close chat" onClick={onClose} />
      </div>
      <Conversation className="pa-chat-log">
        <ConversationContent>
          {users.length === 0 && (
            <ConversationEmptyState title="Ask about a course" description="Sync, outline, slides, or a grade. A push waits for you." />
          )}
          {users.map((turn, index) => {
            const reply = assistants[index];
            return (
              <div key={`${turn.text}-${index}`} className="contents">
                <div className="pa-bubble-row is-user">
                <span className="pa-mini-avatar" aria-hidden>LH</span>
                <Message from="user">
                  <MessageContent>
                    <p>{turn.text}</p>
                    {turn.files.length > 0 && <p>Files: {turn.files.join(", ")}</p>}
                  </MessageContent>
                </Message>
                </div>
                {reply && (
                  <div className="pa-bubble-row">
                  <span className="pa-mini-avatar" aria-hidden>AI</span>
                  <Message from="assistant">
                    <MessageContent>
                      {reply.reasoning && (
                        <Reasoning isStreaming={reply.streaming && !reply.text} defaultOpen>
                          <ReasoningTrigger />
                          <ReasoningContent>{reply.reasoning}</ReasoningContent>
                        </Reasoning>
                      )}
                      {reply.tool && (
                        <Tool defaultOpen>
                          <ToolHeader type="dynamic-tool" state={reply.tool.state} toolName={reply.tool.name} title={reply.tool.name} />
                          <ToolContent>
                            <p style={{ margin: "0 0 0.5rem", color: "#525252" }}>Called {reply.tool.name.replaceAll("_", " ")}.</p>
                            <ToolResult value={reply.tool.output} />
                            <Confirmation
                              approval={reply.needsConfirm ? { id: reply.tool.name } : { id: reply.tool.name, approved: true }}
                              state={reply.tool.state}
                            >
                              <ConfirmationRequest>
                                <ConfirmationTitle>This step changes Moodle or deletes data. Confirm to continue.</ConfirmationTitle>
                                <ConfirmationActions>
                                  <ConfirmationAction onClick={() => send(text, true)} disabled={busy}>
                                    Confirm
                                  </ConfirmationAction>
                                  <ConfirmationAction
                                    variant="outline"
                                    onClick={() => {
                                      setPending("");
                                      setAssistants((current) =>
                                        current.map((item, itemIndex) =>
                                          itemIndex === index && item.tool
                                            ? { ...item, needsConfirm: false, tool: { ...item.tool, state: "output-denied" } }
                                            : item,
                                        ),
                                      );
                                    }}
                                  >
                                    Cancel
                                  </ConfirmationAction>
                                </ConfirmationActions>
                              </ConfirmationRequest>
                            </Confirmation>
                          </ToolContent>
                        </Tool>
                      )}
                      {reply.text && <MessageResponse>{reply.text}</MessageResponse>}
                      {reply.sources.length > 0 && (
                        <Sources>
                          <SourcesTrigger count={reply.sources.length}>
                            <p className="font-medium">
                              Used {reply.sources.length} {reply.sources.length === 1 ? "source" : "sources"}
                            </p>
                          </SourcesTrigger>
                          <SourcesContent>
                            {reply.sources.map((source) => (
                              <Source key={source.href} href={source.href} title={source.title} />
                            ))}
                          </SourcesContent>
                        </Sources>
                      )}
                      <MessageActions>
                        <MessageAction tooltip="Copy" label="Copy" onClick={() => navigator.clipboard.writeText(reply.text)}>
                          <CopyIcon />
                        </MessageAction>
                        <MessageAction tooltip="Retry" label="Retry" onClick={() => send(turn.text)}>
                          <RotateCcwIcon />
                        </MessageAction>
                        <MessageAction tooltip="Like" label="Like" aria-pressed={liked} onClick={() => setLiked((value) => !value)}>
                          <ThumbsUpIcon />
                        </MessageAction>
                      </MessageActions>
                    </MessageContent>
                  </Message>
                  </div>
                )}
              </div>
            );
          })}
        </ConversationContent>
      </Conversation>
      {pending && (
        <Queue>
          <QueueSection>
            <QueueSectionTrigger>
              <QueueSectionLabel label="Needs a confirm" count={1} />
            </QueueSectionTrigger>
            <QueueSectionContent>
              <QueueList>
                <QueueItem>
                  <QueueItemContent>{pending.replaceAll("_", " ")}</QueueItemContent>
                </QueueItem>
              </QueueList>
            </QueueSectionContent>
          </QueueSection>
        </Queue>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="pa-chips">
        {CHIPS.map((chip) => (
          <Suggestion key={chip} suggestion={chip} onClick={(value) => setText(value)} />
        ))}
      </div>
      <PromptInput accept=".pdf,.docx,.pptx,.txt,.md" maxFiles={4} onSubmit={onSubmit}>
        <PromptInputBody>
          <PromptInputTextarea value={text} onChange={(event) => setText(event.target.value)} />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools>
            <PromptInputActionMenu>
              <PromptInputActionMenuTrigger />
              <PromptInputActionMenuContent>
                <PromptInputActionAddAttachments />
              </PromptInputActionMenuContent>
            </PromptInputActionMenu>
            <PromptInputSelect value={model} onValueChange={setModel}>
              <PromptInputSelectTrigger>
                <PromptInputSelectValue placeholder="Model" />
              </PromptInputSelectTrigger>
              <PromptInputSelectContent>
                <PromptInputSelectItem value="demo">Practice answers</PromptInputSelectItem>
                <PromptInputSelectItem value="council">Council</PromptInputSelectItem>
              </PromptInputSelectContent>
            </PromptInputSelect>
          </PromptInputTools>
          <PromptInputSubmit status={busy ? "streaming" : "ready"} />
        </PromptInputFooter>
      </PromptInput>
    </aside>
  );
}

interface CourseCard {
  code?: string;
  title?: string;
  term?: string;
  clos?: unknown;
  last_sync_at?: string;
  last_sync_status?: string;
}

function ToolResult({ value }: { value: unknown }) {
  const courses = courseCards(value);
  if (courses) {
    return (
      <div style={{ display: "grid", gap: "0.5rem" }}>
        {courses.map((course) => (
          <article key={course.code || course.title} style={{ border: "1px solid #e0e0e0", padding: "0.75rem" }}>
            <strong>
              {course.code} {course.title}
            </strong>
            <p style={{ margin: "0.25rem 0", color: "#525252" }}>
              {course.term || "This session"}
              {course.last_sync_at ? ` · Last sync ${humanDate(course.last_sync_at)}` : ""}
              {course.last_sync_status ? ` · ${course.last_sync_status}` : ""}
            </p>
            <p style={{ margin: "0.35rem 0 0.15rem", fontSize: "0.75rem", letterSpacing: "0.06em", textTransform: "uppercase", color: "#525252" }}>
              Course learning outcomes
            </p>
            <ol style={{ margin: 0, paddingLeft: "1.1rem" }}>
              {outcomeLines(course.clos).map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ol>
          </article>
        ))}
      </div>
    );
  }
  return <p style={{ margin: 0 }}>{summaryLine(value)}</p>;
}

function courseCards(value: unknown): CourseCard[] | null {
  const rows = Array.isArray(value) ? value : [value];
  if (!rows.length || !rows.every((row) => row && typeof row === "object" && "code" in row && "title" in row)) {
    return null;
  }
  return rows as CourseCard[];
}

function outcomeLines(clos: unknown): string[] {
  if (!Array.isArray(clos) || clos.length === 0) return ["No outcomes stored on this course yet."];
  return clos.slice(0, 8).map((item, index) => {
    if (typeof item === "string") return item;
    if (item && typeof item === "object") {
      const row = item as { code?: string; text?: string };
      return [row.code, row.text].filter(Boolean).join(" ");
    }
    return `Outcome ${index + 1}`;
  });
}

function humanDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function summaryLine(value: unknown) {
  if (value == null) return "Waiting for a result.";
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return `${value.length} rows.`;
  return "The tool finished.";
}
