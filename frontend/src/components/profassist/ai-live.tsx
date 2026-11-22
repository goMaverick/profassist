"use client";

import { useState } from "react";
import { AILabel, Button } from "@carbon/react";

export function AiLive({
  title,
  reasoning,
  busy,
  action,
  onAction,
  children,
}: {
  title: string;
  reasoning?: string;
  sources?: Array<{ href: string; title: string }>;
  tasks?: string[];
  suggestions?: string[];
  busy?: boolean;
  action?: string;
  onAction?: () => void;
  children?: React.ReactNode;
}) {
  const [why, setWhy] = useState(false);
  return (
    <section className="pa-ai pa-ai-hero" aria-label={title}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <AILabel size="mini" aiText="AI" aria-label="AI suggestion" />
        <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 400 }}>{title}</h2>
      </div>
      {children}
      {onAction && action && (
        <Button kind="primary" size="md" onClick={onAction} disabled={busy}>
          {busy ? "Working…" : action}
        </Button>
      )}
      {reasoning && (
        <div>
          <button type="button" className="pa-why" onClick={() => setWhy((open) => !open)}>
            {why ? "Hide why" : "Why?"}
          </button>
          {why && <p className="pa-why-body">{reasoning}</p>}
        </div>
      )}
    </section>
  );
}
