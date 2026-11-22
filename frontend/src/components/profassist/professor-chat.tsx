"use client";

import { useState } from "react";
import { Button, TextArea, Tile } from "@carbon/react";
import { Chat, Close, Send } from "@carbon/icons-react";
import { pa, run } from "@/components/profassist/bits";

interface Turn {
  role: "you" | "assistant";
  text: string;
  tool?: string;
}

export function ProfessorChat({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("Sync Moodle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(confirmed = false) {
    setBusy(true);
    const message = confirmed ? "confirm" : text;
    const reply = await run(
      () =>
        pa<{ reply: string; tool?: string; needs_confirm?: boolean }>("/chat", {
          method: "POST",
          body: JSON.stringify({ message, confirmed, pending_tool: pending }),
        }),
      setError,
    );
    if (reply) {
      setTurns((current) => [
        ...current,
        { role: "you", text: message },
        { role: "assistant", text: reply.reply, tool: reply.tool },
      ]);
      setPending(reply.needs_confirm && reply.tool ? reply.tool : "");
      if (!confirmed) setText("");
    }
    setBusy(false);
  }

  return (
    <aside
      style={{
        position: "fixed",
        top: "3rem",
        right: 0,
        bottom: 0,
        width: "24rem",
        background: "#fff",
        borderLeft: "1px solid #e0e0e0",
        zIndex: 9000,
        display: "flex",
        flexDirection: "column",
        padding: "1rem",
        gap: "0.75rem",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <Chat /> Ask ProfAssist
        </strong>
        <Button kind="ghost" hasIconOnly renderIcon={Close} iconDescription="Close" onClick={onClose} />
      </div>
      <p style={{ margin: 0, color: "#525252", fontSize: "0.875rem" }}>
        One chat for courses, the outline, slides, grading, and Moodle. A push or a delete waits for your confirm.
      </p>
      <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
        {turns.length === 0 && <Tile>Try “Sync Moodle” or “Suggest an assessment”.</Tile>}
        {turns.map((turn, index) => (
          <Tile key={`${turn.role}-${index}`}>
            <div style={{ fontSize: "0.75rem", letterSpacing: "0.08em", textTransform: "uppercase", color: "#6f6f6f" }}>
              {turn.role}
              {turn.tool ? ` · ${turn.tool}` : ""}
            </div>
            <p style={{ margin: "0.35rem 0 0" }}>{turn.text}</p>
          </Tile>
        ))}
        {error && <p style={{ color: "#da1e28" }}>{error}</p>}
      </div>
      <TextArea labelText="Message" value={text} onChange={(event) => setText(event.target.value)} rows={3} />
      <div style={{ display: "flex", gap: "0.5rem" }}>
        <Button kind="primary" renderIcon={Send} disabled={busy} onClick={() => send(false)}>
          Send
        </Button>
        {pending && (
          <Button kind="danger" disabled={busy} onClick={() => send(true)}>
            Confirm {pending.replaceAll("_", " ")}
          </Button>
        )}
      </div>
    </aside>
  );
}
