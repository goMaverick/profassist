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

const CAST = [
  { name: "Curriculum reviewer", color: "#6929c4", line: "I am checking the weekly outcomes against the course outcomes." },
  { name: "Assessment expert", color: "#8a3ffc", line: "The weights need to land on 100, and week 7 is carrying a summative task." },
  { name: "Integrity officer", color: "#007d79", line: "Write the integrity rule where a student can find it. A flag is not a verdict." },
  { name: "Student voice", color: "#b28600", line: "A student would ask where attendance and integrity are written down." },
  { name: "Chair", color: "#da1e28", line: "The council agrees on the evidence that is actually in the text." },
];

function CouncilCast() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setTick((value) => value + 1), 650);
    return () => window.clearInterval(timer);
  }, []);
  const speaker = Math.min(CAST.length - 1, Math.floor(tick / 5));
  const typed = Math.min(CAST[speaker].line.length, (tick % 5) * 18 + 8);
  const finished = tick > CAST.length * 5;
  const consensus = finished ? 100 : Math.round(((speaker + (tick % 5) / 5) / CAST.length) * 100);
  return (
    <div className="council-cast">
      <div className="council-avatars">
        {CAST.map((agent, index) => (
          <div key={agent.name} className={index === speaker && !finished ? "is-speaking" : ""}>
            <span className="council-avatar" style={{ background: agent.color }}>{agent.name.slice(0, 1)}</span>
            <strong>{agent.name}</strong>
          </div>
        ))}
      </div>
      <div className="council-bubbles">
        {CAST.slice(0, speaker).map((agent) => (
          <p key={agent.name}><b>{agent.name}.</b> {agent.line}</p>
        ))}
        {!finished && (
          <p className="is-live">
            <b>{CAST[speaker].name}.</b> {CAST[speaker].line.slice(0, typed)}
            <i className="council-caret" />
          </p>
        )}
      </div>
      <div className="council-meter" aria-label="Consensus">
        <span style={{ width: `${consensus}%` }} />
        <em>{finished ? "Consensus" : `${consensus}%`}</em>
      </div>
      <article className="council-verdict-card">
        <h3>Council says: approve with 2 changes</h3>
        <ul>
          <li>Say which outcomes week 7 assesses. <button type="button" className="pa-why">Accept</button></li>
          <li>Put the integrity rule next to the assignments. <button type="button" className="pa-why">Accept</button></li>
        </ul>
      </article>
    </div>
  );
}

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
      <CouncilCast />
      <style>{`
        .council-stage { display: grid; gap: 1rem; }
        .council-steps { display: flex; gap: 0.75rem; list-style: none; padding: 0; margin: 0; text-transform: capitalize; }
        .council-steps li { color: #8d8d8d; }
        .council-steps .is-active { color: #0f62fe; font-weight: 600; }
        .council-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; }
        .council-card { display: grid; gap: 0.4rem; }
        .council-cast { display: grid; gap: 12px; }
        .council-avatars { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; }
        .council-avatars > div { display: grid; justify-items: center; gap: 6px; text-align: center; font-size: 0.75rem; }
        .council-avatars .is-speaking .council-avatar { animation: pulse 1s ease-in-out infinite; box-shadow: 0 0 0 4px #e8daff, 0 0 0 7px #8a3ffc; }
        .council-bubbles p { margin: 0 0 6px; padding: 8px 12px; background: #f6f2ff; border-left: 3px solid #8a3ffc; }
        .council-caret { display: inline-block; width: 8px; height: 1em; margin-left: 2px; background: #8a3ffc; animation: blink 0.8s infinite; vertical-align: text-bottom; }
        .council-avatar { width: 2.5rem; height: 2.5rem; display: grid; place-items: center; color: white; border-radius: 999px; box-shadow: 0 0 0 3px #e8daff; font-weight: 600; }
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
