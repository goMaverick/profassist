"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, Card } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  BarChart3,
  Check,
  FileText,
  GraduationCap,
  Heart,
  Scale,
  TriangleAlert,
  User,
  type LucideIcon,
} from "lucide-react";

interface AgentEvent {
  type: string;
  id?: string;
  name?: string;
  color?: string;
  state?: string;
  icon?: string;
  text?: string;
  step?: string;
  from?: string;
  to?: string;
  delay?: number;
}

const STEPS = ["marking", "debate", "judge", "feedback"];
const ICONS: Record<string, LucideIcon> = {
  education: GraduationCap,
  checkmark: Check,
  chart: BarChart3,
  user: User,
  document: FileText,
  warning: TriangleAlert,
  favorite: Heart,
  gavel: Scale,
};

const STATE_BADGE: Record<string, string> = {
  thinking: "border-transparent bg-secondary text-secondary-foreground",
  speaking: "border-transparent bg-primary text-primary-foreground",
  done: "border-border bg-muted text-muted-foreground",
};

function agentIcon(icon?: string) {
  return (icon && ICONS[icon]) || User;
}

export function CouncilStage({ scene, onDone }: { scene: string; onDone?: () => void }) {
  const [agents, setAgents] = useState<AgentEvent[]>([]);
  const [step, setStep] = useState("marking");
  const [arrows, setArrows] = useState<Array<{ from: string; to: string }>>([]);
  const [verdict, setVerdict] = useState("");
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    setAgents([]);
    setStep("marking");
    setArrows([]);
    setVerdict("");
    const source = new EventSource(`/api/profassist/council/stream?scene=${scene}`);
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as AgentEvent;
      if (event.type === "step" && event.step) setStep(event.step);
      if (event.type === "agent" && event.id) {
        setAgents((current) => {
          const index = current.findIndex((item) => item.id === event.id);
          if (index === -1) return [...current, event];
          const next = [...current];
          next[index] = { ...next[index], ...event };
          return next;
        });
      }
      if (event.type === "arrow" && event.from && event.to) {
        const from = event.from;
        const to = event.to;
        setArrows((current) =>
          current.some((item) => item.from === from && item.to === to)
            ? current
            : [...current, { from, to }],
        );
      }
      if (event.type === "verdict") {
        setVerdict(event.text || "Verdict reached.");
        source.close();
        done.current?.();
      }
    };
    source.onerror = () => {
      source.close();
      done.current?.();
    };
    return () => source.close();
  }, [scene]);

  const names = new Map<string, string>();
  for (const agent of agents) {
    if (agent.id) names.set(agent.id, agent.name || agent.id);
  }

  return (
    <section className="grid gap-4" aria-live="polite">
      <ol className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        {STEPS.map((item) => {
          const active = item === step;
          return (
            <li
              key={item}
              aria-current={active ? "step" : undefined}
              className={cn(
                "flex items-center gap-1.5 capitalize transition-colors",
                active ? "text-foreground font-semibold" : "text-muted-foreground",
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  active ? "bg-primary" : "bg-muted-foreground/40",
                )}
              />
              {item}
            </li>
          );
        })}
      </ol>

      {agents.length === 0 && !verdict && (
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          The council is joining…
          <span className="flex items-center gap-1" aria-hidden="true">
            {[0, 1, 2].map((index) => (
              <span
                key={index}
                className="council-dot bg-muted-foreground h-1.5 w-1.5 rounded-full"
                style={{ animationDelay: `${index * 0.15}s` }}
              />
            ))}
          </span>
        </p>
      )}

      {agents.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent, index) => {
            const Icon = agentIcon(agent.icon);
            const state = agent.state || "";
            const speaking = state === "speaking" && Boolean(agent.text);
            return (
              <Card key={agent.id ?? `agent-${index}`} className="flex flex-col gap-2 p-4">
                <div className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full border"
                    style={{ color: agent.color, borderColor: agent.color }}
                  >
                    <Icon size={16} />
                  </span>
                  <p className="min-w-0 flex-1 truncate text-sm font-medium">
                    {agent.name || agent.id || "Council member"}
                  </p>
                  <span
                    aria-hidden="true"
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: agent.color }}
                  />
                </div>
                {state && (
                  <div>
                    <Badge variant="outline" className={cn("capitalize", STATE_BADGE[state])}>
                      {state}
                    </Badge>
                  </div>
                )}
                {state === "thinking" && (
                  <span
                    className="text-muted-foreground flex items-center gap-1"
                    aria-hidden="true"
                  >
                    {[0, 1, 2].map((dot) => (
                      <span
                        key={dot}
                        className="council-dot h-1.5 w-1.5 rounded-full bg-current"
                        style={{ animationDelay: `${dot * 0.15}s` }}
                      />
                    ))}
                  </span>
                )}
                {speaking && (
                  <p className="bg-muted/50 rounded-lg border px-3 py-2 text-sm leading-relaxed">
                    {agent.text}
                    <span
                      aria-hidden="true"
                      className="council-caret bg-primary ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px]"
                    />
                  </p>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {arrows.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {arrows.map((arrow, index) => (
            <span
              key={`${arrow.from}-${arrow.to}-${index}`}
              className="text-muted-foreground bg-muted/50 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs"
            >
              {names.get(arrow.from) ?? arrow.from}
              <span aria-hidden="true">→</span>
              {names.get(arrow.to) ?? arrow.to}
            </span>
          ))}
        </div>
      )}

      {verdict && (
        <Card className="border-primary/40 bg-primary/5 p-4">
          <p className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
            Verdict
          </p>
          <p className="mt-1 text-sm font-medium">{verdict}</p>
        </Card>
      )}

      <style>{`
        .council-dot { animation: council-pulse 1.1s ease-in-out infinite; }
        .council-caret { animation: council-blink 0.8s step-end infinite; }
        @keyframes council-pulse { 50% { opacity: 0.2; transform: translateY(-1px); } }
        @keyframes council-blink { 50% { opacity: 0; } }
        @media (prefers-reduced-motion: reduce) {
          .council-dot, .council-caret { animation: none; }
        }
      `}</style>
    </section>
  );
}
