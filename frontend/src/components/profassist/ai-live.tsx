"use client";

import { AILabel, Button, Tag } from "@carbon/react";
import { MagicWand } from "@carbon/icons-react";
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Sources, SourcesContent, SourcesTrigger, Source } from "@/components/ai-elements/sources";
import { Suggestion } from "@/components/ai-elements/suggestion";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Task, TaskContent, TaskItem, TaskTrigger } from "@/components/ai-elements/task";

export function AiLive({
  title,
  reasoning,
  sources,
  tasks,
  suggestions,
  busy,
  action,
  onAction,
  children,
}: {
  title: string;
  reasoning: string;
  sources: Array<{ href: string; title: string }>;
  tasks: string[];
  suggestions?: string[];
  busy?: boolean;
  action?: string;
  onAction?: () => void;
  children?: React.ReactNode;
}) {
  return (
    <section className="pa-ai pa-ai-hero" aria-label={title}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <AILabel size="mini" aiText="AI" aria-label="AI" />
        <h2 style={{ margin: 0, fontSize: "1rem" }}>{title}</h2>
      </div>
      {onAction && action && (
        <Button kind="tertiary" size="sm" renderIcon={MagicWand} onClick={onAction} disabled={busy}>
          {busy ? "Drafting…" : action}
        </Button>
      )}
      {busy ? <Shimmer>Reading the course files and your instructions…</Shimmer> : null}
      <Reasoning defaultOpen isStreaming={busy}>
        <ReasoningTrigger />
        <ReasoningContent>{reasoning}</ReasoningContent>
      </Reasoning>
      <Task defaultOpen>
        <TaskTrigger title="What the agent is doing" />
        <TaskContent>
          {tasks.map((item) => (
            <TaskItem key={item}>{item}</TaskItem>
          ))}
        </TaskContent>
      </Task>
      <Sources>
        <SourcesTrigger count={sources.length}>
          {sources.length === 1 ? "Used 1 source" : `Used ${sources.length} sources`}
        </SourcesTrigger>
        <SourcesContent>
          {sources.map((source) => (
            <Source key={source.href} href={source.href} title={source.title} />
          ))}
        </SourcesContent>
      </Sources>
      {suggestions && suggestions.length > 0 && (
        <div className="pa-chips">
          {suggestions.map((item) => (
            <Suggestion key={item} suggestion={item} />
          ))}
        </div>
      )}
      {children}
      <Tag type="purple" size="sm">Demo drafter · purple AI accent</Tag>
    </section>
  );
}
