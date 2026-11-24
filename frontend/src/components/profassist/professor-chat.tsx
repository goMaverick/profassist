"use client";

import { useState } from "react";
import { Button } from "@/components/ui";
import { ArrowUp, CopyIcon, RotateCcwIcon, ThumbsUpIcon, X } from "lucide-react";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
} from "@/components/ai-elements/conversation";
import { MessageAction, MessageActions } from "@/components/ai-elements/message";
import {
  AnswerText,
  AtRiskAnswer,
  IntegrityAnswer,
  QuietTool,
} from "@/components/profassist/quiet-chat";
import { sendChat, useChat } from "@/components/profassist/chat-store";
import { usePageContext, type PageContext } from "@/components/profassist/page-context";
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

const CHIPS = [
  "Sync Moodle",
  "List my courses",
  "Suggest an assessment",
  "Draft this week's slides",
];

const OUTLINE_ACTIONS = [
  { label: "Review this outline", prompt: "Review this outline" },
  { label: "Give me your opinion", prompt: "What do you think?" },
  { label: "Re-review", prompt: "Re-review the outline" },
];

const RUBRIC_ACTIONS = [{ label: "Review this rubric", prompt: "Review this rubric" }];

function contextChip(context: PageContext): string {
  const parts = [
    context.title || context.page,
    context.course_name || context.course_id,
    context.section,
  ];
  return parts.filter(Boolean).join(" \u00b7 ") || "Workspace";
}

function contextActions(context: PageContext) {
  const actions: Array<{ label: string; prompt: string }> = [];
  if (context.outline_id) actions.push(...OUTLINE_ACTIONS);
  if (context.rubric_id) actions.push(...RUBRIC_ACTIONS);
  return actions;
}

export function ProfessorChat({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  const [liked, setLiked] = useState(false);
  const { turns, busy, error } = useChat();
  const context = usePageContext();
  const actions = contextActions(context);

  async function onSubmit(message: PromptInputMessage) {
    const names = message.files.map((file) => file.filename || "file");
    const body = names.length ? `${message.text}\nAttached: ${names.join(", ")}` : message.text;
    setText("");
    await sendChat(body);
  }

  return (
    <aside className="pa-ai pa-chat-sheet" aria-label="ProfAssist chat">
      <div className="pa-chat-bar">
        <strong>Ask ProfAssist</strong>
        <Button variant="ghost" size="icon-sm" aria-label="Close chat" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <p className="truncate px-4 pb-2 text-xs text-[#525252]" aria-live="polite">
        {contextChip(context)}
      </p>
      <Conversation className="pa-chat-log">
        <ConversationContent>
          {turns.length === 0 && (
            <ConversationEmptyState
              title="Ask about a course"
              description="Sync, outline, slides, or a grade. A push waits for you."
            />
          )}
          <div className="pa-chat-column">
            {turns.map((turn, index) => (
              <div key={`${turn.you}-${index}`} className="pa-turn">
                <div className="pa-user-bubble">
                  <p>{turn.you}</p>
                </div>
                {turn.tool && <QuietTool name={turn.tool.name} output={turn.tool.output} />}
                {turn.tool?.name === "integrity_concerns" ? (
                  <IntegrityAnswer output={turn.tool.output} />
                ) : turn.tool?.name === "dropout_risk" ? (
                  <AtRiskAnswer output={turn.tool.output} />
                ) : (
                  <AnswerText text={turn.text} />
                )}
                {turn.text &&
                  turn.tool?.name !== "integrity_concerns" &&
                  turn.tool?.name !== "dropout_risk" && (
                    <MessageActions className="pa-msg-actions">
                      <MessageAction
                        tooltip="Copy"
                        label="Copy"
                        onClick={() => navigator.clipboard.writeText(turn.text)}
                      >
                        <CopyIcon />
                      </MessageAction>
                      <MessageAction
                        tooltip="Retry"
                        label="Retry"
                        onClick={() => void sendChat(turn.you)}
                      >
                        <RotateCcwIcon />
                      </MessageAction>
                      <MessageAction
                        tooltip="Like"
                        label="Like"
                        aria-pressed={liked}
                        onClick={() => setLiked((value) => !value)}
                      >
                        <ThumbsUpIcon />
                      </MessageAction>
                    </MessageActions>
                  )}
              </div>
            ))}
          </div>
        </ConversationContent>
      </Conversation>
      {error && <p role="alert">{error}</p>}
      <div className="pa-chat-dock">
        {actions.length > 0 && (
          <div className="pa-chips">
            {actions.map((action) => (
              <Suggestion
                key={action.label}
                suggestion={action.label}
                onClick={() => void sendChat(action.prompt)}
              />
            ))}
          </div>
        )}
        {turns.length === 0 && (
          <div className="pa-chips">
            {CHIPS.map((chip) => (
              <Suggestion key={chip} suggestion={chip} onClick={(value) => setText(value)} />
            ))}
          </div>
        )}
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
            </PromptInputTools>
            <PromptInputSubmit className="pa-send" status={busy ? "streaming" : "ready"}>
              <ArrowUp className="size-4" />
            </PromptInputSubmit>
          </PromptInputFooter>
        </PromptInput>
      </div>
    </aside>
  );
}
