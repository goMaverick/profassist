"use client";

import { useState } from "react";
import { Button } from "@carbon/react";
import { Close } from "@carbon/icons-react";
import { ArrowUp, CopyIcon, RotateCcwIcon, ThumbsUpIcon } from "lucide-react";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
} from "@/components/ai-elements/conversation";
import { MessageAction, MessageActions } from "@/components/ai-elements/message";
import { AnswerText, AtRiskAnswer, IntegrityAnswer, QuietTool } from "@/components/profassist/quiet-chat";
import { sendChat, useChat } from "@/components/profassist/chat-store";
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

const CHIPS = ["Sync Moodle", "List my courses", "Suggest an assessment", "Draft this week's slides"];

export function ProfessorChat({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  const [liked, setLiked] = useState(false);
  const { turns, busy, error } = useChat();

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
        <Button kind="ghost" hasIconOnly renderIcon={Close} iconDescription="Close chat" onClick={onClose} />
      </div>
      <Conversation className="pa-chat-log">
        <ConversationContent>
          {turns.length === 0 && (
            <ConversationEmptyState title="Ask about a course" description="Sync, outline, slides, or a grade. A push waits for you." />
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
                {turn.text && turn.tool?.name !== "integrity_concerns" && turn.tool?.name !== "dropout_risk" && (
                  <MessageActions className="pa-msg-actions">
                    <MessageAction tooltip="Copy" label="Copy" onClick={() => navigator.clipboard.writeText(turn.text)}>
                      <CopyIcon />
                    </MessageAction>
                    <MessageAction tooltip="Retry" label="Retry" onClick={() => void sendChat(turn.you)}>
                      <RotateCcwIcon />
                    </MessageAction>
                    <MessageAction tooltip="Like" label="Like" aria-pressed={liked} onClick={() => setLiked((value) => !value)}>
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
