"use client";

import { useEffect, useRef, useState } from "react";
import { Tag, Tile } from "@carbon/react";
import { ChainOfThought, ChainOfThoughtContent, ChainOfThoughtHeader, ChainOfThoughtStep } from "@/components/ai-elements/chain-of-thought";
import { InlineCitation, InlineCitationText } from "@/components/ai-elements/inline-citation";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from "@/components/ai-elements/tool";
import {
  ChartColumn,
  Checkmark,
  Document,
  Education,
  Favorite,
  User,
  WarningAlt,
} from "@carbon/icons-react";

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
const ICONS: Record<string, typeof Education> = {
  education: Education,
  checkmark: Checkmark,
  chart: ChartColumn,
  user: User,
  document: Document,
  warning: WarningAlt,
  favorite: Favorite,
  gavel: WarningAlt,
};

export function CouncilStage({ scene, onDone }: { scene: string; onDone?: () => void }) {
  const [agents, setAgents] = useState<AgentEvent[]>([]);
  const [step, setStep] = useState("marking");
  const [arrows, setArrows] = useState<Array<{ from: string; to: string }>>([]);
  const [verdict, setVerdict] = useState("");
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    const source = new EventSource(`/api/profassist/council/stream?scene=${scene}`);
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as AgentEvent;
      if (event.type === "step" && event.step) setStep(event.step);
      if (event.type === "agent" && event.id) {
        setAgents((current) => {
          const rest = current.filter((item) => item.id !== event.id);
          return [...rest, event];
        });
      }
      if (event.type === "arrow" && event.from && event.to) {
        setArrows((current) => [...current, { from: event.from || "", to: event.to || "" }]);
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

  return (
    <section className="council-stage" aria-live="polite">
      <ol className="council-steps">
        {STEPS.map((item) => (
          <li key={item} className={item === step ? "is-active" : ""}>
            {item}
          </li>
        ))}
      </ol>
      <div className="council-grid">
        {agents.map((agent) => {
          const Icon = ICONS[agent.icon || "education"] || Education;
          return (
            <Tile key={agent.id} className={agent.state === "thinking" ? "is-thinking" : ""}>
              <div className="council-card" style={{ borderTop: `4px solid ${agent.color}` }}>
                <span className="council-avatar" style={{ background: agent.color }}>
                  <Icon size={18} />
                </span>
                <strong>{agent.name}</strong>
                {agent.state === "thinking" ? (
                  <span className="council-dots" aria-label="Thinking">
                    <i />
                    <i />
                    <i />
                  </span>
                ) : (
                  <p>{agent.text}</p>
                )}
              </div>
            </Tile>
          );
        })}
      </div>
      {arrows.length > 0 && (
        <p className="council-arrows">
          {arrows.slice(-3).map((arrow) => (
            <Tag key={`${arrow.from}-${arrow.to}`} type="purple">
              {arrow.from} → {arrow.to}
            </Tag>
          ))}
        </p>
      )}
      <div className="pa-ai council-thread">
        <Tool defaultOpen>
          <ToolHeader type="dynamic-tool" state="output-available" toolName="rubric_lookup" title="rubric_lookup" />
          <ToolContent>
            <ToolInput input={{ scene, step }} />
            <ToolOutput output={{ criteria: ["Evidence", "Limitation"] }} errorText={undefined} />
          </ToolContent>
        </Tool>
        {agents
          .filter((agent) => agent.state === "speaking" || agent.state === "thinking")
          .map((agent) => (
            <Message from="assistant" key={`${agent.id}-${agent.state}`}>
              <MessageContent>
                <strong>{agent.name}</strong>
                {agent.state === "thinking" ? (
                  <Reasoning isStreaming defaultOpen>
                    <ReasoningTrigger />
                    <ReasoningContent>{`${agent.name} is reading the section for this step.`}</ReasoningContent>
                  </Reasoning>
                ) : (
                  <MessageResponse>{agent.text || ""}</MessageResponse>
                )}
                {agent.text && (
                  <InlineCitation>
                    <InlineCitationText>submission evidence</InlineCitationText>
                  </InlineCitation>
                )}
              </MessageContent>
            </Message>
          ))}
        {step === "judge" && (
          <ChainOfThought defaultOpen>
            <ChainOfThoughtHeader>Judge</ChainOfThoughtHeader>
            <ChainOfThoughtContent>
              <ChainOfThoughtStep label="Marking" status="complete" description="Each persona quoted the work." />
              <ChainOfThoughtStep label="Debate" status={arrows.length ? "complete" : "active"} description="Disagreement stays visible." />
              <ChainOfThoughtStep label="Verdict" status={verdict ? "complete" : "pending"} description={verdict || "Waiting for the last voice."} />
            </ChainOfThoughtContent>
          </ChainOfThought>
        )}
      </div>
      <div className="council-meter" aria-label="Consensus">
        <span style={{ width: `${Math.min(100, agents.filter((agent) => agent.state === "speaking").length * 20)}%` }} />
        <em>{verdict ? "Consensus" : "Vote in progress"}</em>
      </div>
      {verdict && (
        <article className="council-verdict-card">
          <h3>Chair's verdict</h3>
          <p>{verdict} The council can see the evidence. Nothing is sent until you approve.</p>
          <ul>
            <li>Outcomes: map the thin program outcomes before accreditation.</li>
            <li>Assessments: keep the weights on 100, and do not pile week 7.</li>
            <li>Policies: write attendance and integrity where a student can find them.</li>
          </ul>
        </article>
      )}
      <style>{`
        .council-stage { display: grid; gap: 1rem; }
        .council-steps { display: flex; gap: 0.75rem; list-style: none; padding: 0; margin: 0; text-transform: capitalize; }
        .council-steps li { color: #8d8d8d; }
        .council-steps .is-active { color: #0f62fe; font-weight: 600; }
        .council-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; }
        .council-card { display: grid; gap: 0.4rem; }
        .council-avatar { width: 2rem; height: 2rem; display: grid; place-items: center; color: white; border-radius: 999px; box-shadow: 0 0 0 3px #e8daff; }
        .is-thinking { animation: pulse 1.2s ease-in-out infinite; box-shadow: 0 0 0 3px #8a3ffc; }
        .council-meter { position: relative; height: 12px; background: #e0e0e0; }
        .council-meter span { display: block; height: 100%; background: linear-gradient(90deg, #6929c4, #8a3ffc); }
        .council-meter em { position: absolute; right: 0; top: -18px; font-style: normal; font-size: 0.75rem; color: #6929c4; }
        .council-verdict-card { border: 1px solid #8a3ffc; background: #f6f2ff; padding: 12px 16px; }
        .council-verdict-card h3 { margin: 0 0 8px; font-weight: 600; }
        .council-verdict-card ul { margin: 8px 0 0; padding-left: 1.1rem; }
        .council-dots { display: flex; gap: 0.25rem; }
        .council-dots i { width: 0.4rem; height: 0.4rem; border-radius: 999px; background: #0f62fe; animation: blink 1s infinite; }
        .council-dots i:nth-child(2) { animation-delay: 0.15s; }
        .council-dots i:nth-child(3) { animation-delay: 0.3s; }
        .council-verdict { font-size: 1.25rem; color: #198038; }
        @keyframes pulse { 50% { transform: translateY(-2px); } }
        @keyframes blink { 50% { opacity: 0.25; } }
        @media (prefers-reduced-motion: reduce) {
          .is-thinking, .council-dots i { animation: none; }
        }
      `}</style>
    </section>
  );
}
