"use client";

import { useSyncExternalStore } from "react";
import { getPageContext } from "@/components/profassist/page-context";

export interface ToolCard {
  name: string;
  output: unknown;
  href?: string;
}

export interface ChatTurn {
  you: string;
  text: string;
  tool?: ToolCard;
  streaming: boolean;
}

interface Snapshot {
  turns: ChatTurn[];
  busy: boolean;
  error: string;
}

let snapshot: Snapshot = { turns: [], busy: false, error: "" };
const listeners = new Set<() => void>();

function emit(next: Snapshot) {
  snapshot = next;
  listeners.forEach((listener) => listener());
}

function patchLast(fn: (turn: ChatTurn) => ChatTurn) {
  const turns = snapshot.turns.slice();
  const last = turns[turns.length - 1];
  if (!last) return;
  turns[turns.length - 1] = fn(last);
  emit({ ...snapshot, turns });
}

export function useChat() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => snapshot,
    () => snapshot,
  );
}

export async function sendChat(message: string) {
  const trimmed = message.trim();
  if (!trimmed || snapshot.busy) return;
  emit({
    busy: true,
    error: "",
    turns: [...snapshot.turns, { you: trimmed, text: "", streaming: true }],
  });
  try {
    const response = await fetch("/api/profassist/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: trimmed, context: getPageContext() }),
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
        if (event === "text") patchLast((turn) => ({ ...turn, text: turn.text + String(data.delta || "") }));
        if (event === "tool") {
          patchLast((turn) => ({
            ...turn,
            tool: {
              name: String(data.name || ""),
              output: data.output,
              href: typeof data.href === "string" ? data.href : undefined,
            },
          }));
        }
        if (event === "done") {
          patchLast((turn) => ({ ...turn, streaming: false, text: String(data.reply || turn.text) }));
        }
      }
    }
    patchLast((turn) => ({ ...turn, streaming: false }));
    emit({ ...snapshot, busy: false });
  } catch (err) {
    emit({
      ...snapshot,
      busy: false,
      error: err instanceof Error ? err.message : "The assistant stopped.",
    });
    patchLast((turn) => ({ ...turn, streaming: false }));
  }
}
