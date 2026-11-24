"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  FileCheck,
  Gavel,
  GraduationCap,
  Layout,
  Pause,
  RefreshCw,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  pa,
  ProfassistError,
  type CollabDeck,
  type CollabEvent,
  type CollabIssue,
  type CollabReview,
  type CollabRole,
} from "@/lib/profassist";

interface StudioCollabProps {
  courseId: string;
  week: number;
  instructions: string;
  onDone: (deck: CollabDeck) => void;
  onCancel?: () => void;
}

export interface CollabMessage {
  id: number;
  role: CollabRole;
  text: string;
  kind?: string;
  severity?: string;
  verdict?: string;
  score?: number;
  issues?: CollabIssue[];
}

export type CollabStatus = "connecting" | "running" | "paused" | "done" | "error";

export interface CollabState {
  status: CollabStatus;
  creator: string;
  reviewer: string;
  messages: CollabMessage[];
  typing: CollabRole | null;
  paused: boolean;
  deck: CollabDeck | null;
  review: CollabReview | null;
  /** Reviewer seats from the saved council roster, once the review reports them. */
  roles: string[];
  traceUrl: string;
  error: string;
}

export function initialCollabState(): CollabState {
  return {
    status: "connecting",
    creator: "Creator",
    reviewer: "Chair",
    messages: [],
    typing: null,
    paused: false,
    deck: null,
    review: null,
    roles: [],
    traceUrl: "",
    error: "",
  };
}

const COLLAB_ROLES: CollabRole[] = [
  "creator",
  "curriculum",
  "evidence",
  "design",
  "chair",
  "reviewer",
];

function asCollabRole(role?: string): CollabRole | null {
  return COLLAB_ROLES.includes(role as CollabRole) ? (role as CollabRole) : null;
}

/** Pure reducer so the stream can be tested without a live EventSource. */
export function applyCollabEvent(state: CollabState, event: CollabEvent): CollabState {
  switch (event.type) {
    case "start":
      return {
        ...state,
        status: state.status === "connecting" ? "running" : state.status,
        creator: event.creator || state.creator,
        reviewer: event.reviewer || state.reviewer,
        typing: null,
      };
    case "typing":
      if (!event.role || state.status === "done" || state.status === "error") return state;
      return { ...state, typing: event.role };
    case "message": {
      if (!event.role || !event.text) return state;
      const message: CollabMessage = {
        id: state.messages.length + 1,
        role: event.role,
        text: event.text,
        kind: event.kind,
        severity: event.severity,
        verdict: event.verdict,
        score: event.score,
        issues: event.issues,
      };
      return {
        ...state,
        status: state.status === "connecting" ? "running" : state.status,
        typing: null,
        messages: [...state.messages, message],
      };
    }
    case "paused":
      return { ...state, status: "paused", paused: true, typing: null };
    case "final": {
      // A late final must not paper over an error the user already saw.
      if (state.status === "error") {
        return { ...state, typing: null };
      }
      const review = event.review ?? event.deck?.review ?? state.review;
      const roles = (review?.roles ?? []).filter((role): role is string => Boolean(role));
      // Reconnects can miss every live turn. The final review carries the full
      // transcript, so seed it instead of showing an empty council.
      const messages =
        state.messages.length === 0 && review?.messages?.length
          ? review.messages.map((message, index) => ({
              id: index + 1,
              role: asCollabRole(message.role) ?? "chair",
              text: message.text,
              severity: message.severity,
              verdict: message.verdict,
              score: message.score,
            }))
          : state.messages;
      return {
        ...state,
        status: "done",
        typing: null,
        paused: Boolean(event.paused),
        deck: event.deck ?? state.deck,
        review,
        roles: roles.length > 0 ? roles : state.roles,
        traceUrl: event.trace_url || state.traceUrl,
        error: "",
        messages,
      };
    }
    case "error":
      if (state.status === "done") return state;
      return {
        ...state,
        status: "error",
        typing: null,
        error: event.text || "The collaboration stopped unexpectedly.",
      };
    default:
      return state;
  }
}

function messageOf(err: unknown) {
  if (err instanceof ProfassistError) {
    return err.status ? `${err.message} (HTTP ${err.status})` : err.message;
  }
  return err instanceof Error ? err.message : "Could not start the collaboration.";
}

const STATUS_LABEL: Record<CollabStatus, string> = {
  connecting: "Connecting",
  running: "Working",
  paused: "Paused",
  done: "Finished",
  error: "Stopped",
};

function verdictMeta(verdict?: string) {
  if (verdict === "pass") {
    return { label: "Passed", className: "border-transparent bg-emerald-600 text-white" };
  }
  if (verdict === "revise") {
    return { label: "Needs revision", className: "border-transparent bg-amber-100 text-amber-800" };
  }
  return {
    label: verdict ? verdict.replace(/_/g, " ") : "Reviewed",
    className: "border-transparent bg-slate-100 text-slate-700",
  };
}

function severityMeta(severity?: string) {
  if (!severity) return null;
  const normalized = severity.toLowerCase();
  const className =
    normalized === "high"
      ? "border-transparent bg-red-100 text-red-800"
      : normalized === "medium"
        ? "border-transparent bg-amber-100 text-amber-800"
        : normalized === "low"
          ? "border-transparent bg-blue-100 text-blue-800"
          : "border-transparent bg-slate-100 text-slate-700";
  return {
    label: normalized.charAt(0).toUpperCase() + normalized.slice(1),
    className,
  };
}

type CanonicalRole = Exclude<CollabRole, "reviewer">;

interface RoleConfig {
  label: string;
  icon: typeof Sparkles;
  avatarClassName: string;
  bubbleClassName: string;
  side: "left" | "right";
}

const ROLE_CONFIG: Record<CanonicalRole, RoleConfig> = {
  creator: {
    label: "Creator",
    icon: Sparkles,
    avatarClassName: "border-violet-200 bg-violet-100 text-violet-700",
    bubbleClassName: "bg-background",
    side: "left",
  },
  curriculum: {
    label: "Curriculum",
    icon: GraduationCap,
    avatarClassName: "border-blue-200 bg-blue-100 text-blue-700",
    bubbleClassName: "border-blue-200 bg-blue-50",
    side: "right",
  },
  evidence: {
    label: "Evidence",
    icon: FileCheck,
    avatarClassName: "border-emerald-200 bg-emerald-100 text-emerald-700",
    bubbleClassName: "border-emerald-200 bg-emerald-50",
    side: "right",
  },
  design: {
    label: "Design",
    icon: Layout,
    avatarClassName: "border-amber-200 bg-amber-100 text-amber-700",
    bubbleClassName: "border-amber-200 bg-amber-50",
    side: "right",
  },
  chair: {
    label: "Chair",
    icon: Gavel,
    avatarClassName: "border-red-200 bg-red-100 text-red-700",
    bubbleClassName: "border-red-200 bg-red-50",
    side: "right",
  },
};

/** Legacy `reviewer` turns are the chair seat. */
function canonicalRole(role: CollabRole): CanonicalRole {
  return role === "reviewer" ? "chair" : role;
}

function roleConfig(role: CollabRole): RoleConfig {
  return ROLE_CONFIG[canonicalRole(role)];
}

function AgentAvatar({ role }: { role: CollabRole }) {
  const config = roleConfig(role);
  const Icon = config.icon;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border",
        config.avatarClassName,
      )}
    >
      <Icon size={14} />
    </span>
  );
}

function Dot({ index }: { index: number }) {
  return (
    <span
      aria-hidden="true"
      className="pa-collab-dot h-1.5 w-1.5 rounded-full bg-current"
      style={{ animationDelay: `${index * 0.15}s` }}
    />
  );
}

function Bubble({ message }: { message: CollabMessage }) {
  const config = roleConfig(message.role);
  const creator = canonicalRole(message.role) === "creator";
  const chair = canonicalRole(message.role) === "chair";
  const verdict = chair && message.verdict ? verdictMeta(message.verdict) : null;
  const severity = severityMeta(message.severity);
  return (
    <div
      className={cn(
        "pa-collab-bubble flex w-full items-start gap-2",
        creator ? "justify-start" : "justify-end",
      )}
    >
      {creator && <AgentAvatar role={message.role} />}
      <div
        className={cn(
          "max-w-[82%] rounded-2xl border px-3 py-2 text-sm leading-relaxed sm:max-w-[75%]",
          config.bubbleClassName,
        )}
      >
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <span className="text-muted-foreground text-[11px] font-semibold tracking-wide uppercase">
            {config.label}
          </span>
          {message.kind && (
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {message.kind.replace(/_/g, " ")}
            </Badge>
          )}
          {severity && (
            <Badge className={cn("px-1.5 py-0 text-[10px]", severity.className)}>
              {severity.label}
            </Badge>
          )}
          {verdict && (
            <Badge className={cn("px-1.5 py-0 text-[10px]", verdict.className)}>
              {verdict.label}
            </Badge>
          )}
          {chair && typeof message.score === "number" && (
            <span className="text-muted-foreground text-[11px] font-semibold">
              {message.score}/100
            </span>
          )}
        </div>
        <p className="whitespace-pre-wrap">{message.text}</p>
        {message.issues && message.issues.length > 0 && (
          <ul className="text-muted-foreground mt-2 list-disc space-y-1 pl-4 text-xs">
            {message.issues.slice(0, 3).map((issue, index) => (
              <li key={index}>
                {typeof issue.slide === "number" || typeof issue.slide === "string"
                  ? `Slide ${issue.slide}: `
                  : ""}
                {issue.issue ?? issue.fix ?? "Review note"}
              </li>
            ))}
          </ul>
        )}
      </div>
      {!creator && <AgentAvatar role={message.role} />}
    </div>
  );
}

function TypingBubble({ role }: { role: CollabRole }) {
  const config = roleConfig(role);
  const creator = canonicalRole(role) === "creator";
  return (
    <div className={cn("flex w-full items-start gap-2", creator ? "justify-start" : "justify-end")}>
      {creator && <AgentAvatar role={role} />}
      <div
        className={cn(
          "max-w-[82%] rounded-2xl border px-3 py-2 text-sm sm:max-w-[75%]",
          config.bubbleClassName,
        )}
      >
        <span className="text-muted-foreground text-[11px] font-semibold tracking-wide uppercase">
          {config.label} is typing
        </span>
        <span className="text-foreground mt-1 flex items-center gap-1" aria-hidden="true">
          {[0, 1, 2].map((index) => (
            <Dot key={index} index={index} />
          ))}
        </span>
      </div>
      {!creator && <AgentAvatar role={role} />}
    </div>
  );
}

export function StudioCollab({
  courseId,
  week,
  instructions,
  onDone,
  onCancel,
}: StudioCollabProps) {
  const [state, setState] = useState<CollabState>(initialCollabState);
  const [jobId, setJobId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [pausing, setPausing] = useState(false);
  const [pauseError, setPauseError] = useState("");
  const done = useRef(onDone);
  done.current = onDone;

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    setState(initialCollabState());
    setJobId(null);
    setPauseError("");

    async function start() {
      try {
        const created = await pa<{ job_id: string }>(`/courses/${courseId}/slides/collaborate`, {
          method: "POST",
          body: JSON.stringify({ week, instructions }),
        });
        if (cancelled) return;
        setJobId(created.job_id);
        source = new EventSource(`/api/profassist/slides/collaborate/${created.job_id}/stream`);
        source.onmessage = (message) => {
          if (cancelled) return;
          let event: CollabEvent;
          try {
            event = JSON.parse(message.data) as CollabEvent;
          } catch {
            return;
          }
          setState((current) => applyCollabEvent(current, event));
          if (event.type === "final") {
            source?.close();
            if (event.deck) done.current?.(event.deck);
          }
          if (event.type === "error") source?.close();
        };
        source.onerror = () => {
          if (cancelled) return;
          source?.close();
          setState((current) =>
            applyCollabEvent(current, {
              type: "error",
              text: "The live collaboration stream ended before the deck was ready.",
            }),
          );
        };
      } catch (err) {
        if (cancelled) return;
        setState((current) => applyCollabEvent(current, { type: "error", text: messageOf(err) }));
      }
    }

    void start();
    return () => {
      cancelled = true;
      source?.close();
    };
  }, [courseId, week, instructions, attempt]);

  async function pause() {
    if (!jobId || pausing || state.status === "done" || state.status === "error") return;
    setPausing(true);
    setPauseError("");
    try {
      await pa(`/slides/collaborate/${jobId}/pause`, { method: "POST" });
      setState((current) => applyCollabEvent(current, { type: "paused" }));
    } catch (err) {
      setPauseError(messageOf(err));
    } finally {
      setPausing(false);
    }
  }

  const live = state.status === "connecting" || state.status === "running";
  const round =
    state.messages.filter((message) => canonicalRole(message.role) === "chair").length + 1;
  const dotClass =
    state.status === "error"
      ? "bg-destructive"
      : state.status === "paused"
        ? "bg-amber-500"
        : "bg-emerald-500";
  const deckReview = state.review ?? state.deck?.review ?? null;
  const finalVerdict = deckReview?.verdict ? verdictMeta(deckReview.verdict) : null;
  // The review names the seats that actually spoke (reviewers, chair last).
  // The creator drafts in front of them, so the roster is one larger. Until the
  // review arrives, say "Council" rather than promise a count that may be wrong.
  const agentCount = state.roles.length > 0 ? state.roles.length + 1 : null;
  const agentLabel = agentCount === null ? "Council" : `${agentCount} agents`;

  return (
    <Card className="border-primary/20 overflow-hidden">
      <CardHeader className="bg-primary/[0.03] border-b">
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span
              aria-hidden="true"
              className={cn("h-2 w-2 rounded-full", dotClass, live && "motion-safe:animate-pulse")}
            />
            <CardTitle className="text-base">Creator &harr; Council</CardTitle>
            <Badge variant="secondary">{agentLabel}</Badge>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Badge variant="secondary">Round {round}</Badge>
            <span className="text-muted-foreground text-xs" aria-live="polite">
              {STATUS_LABEL[state.status]}
            </span>
          </div>
        </div>
        <CardDescription>
          Week {week}. The {state.creator} drafts the deck, then the enabled reviewers each check a
          different angle before the chair gives a verdict.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-4">
        <div
          className="border-border/70 bg-muted/20 flex max-h-80 flex-col gap-3 overflow-y-auto rounded-lg border p-3"
          aria-live="polite"
        >
          {state.messages.length === 0 && live && (
            <p className="text-muted-foreground flex items-center gap-2 px-1 text-sm">
              The {state.creator} is reading the week {week} notes{"\u2026"}
              <span className="flex items-center gap-1" aria-hidden="true">
                {[0, 1, 2].map((index) => (
                  <Dot key={index} index={index} />
                ))}
              </span>
            </p>
          )}
          {state.messages.map((message) => (
            <Bubble key={message.id} message={message} />
          ))}
          {state.typing && <TypingBubble role={state.typing} />}
        </div>
        {state.paused && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            Paused {"\u2014"} keeping the current draft. The chair will not start a new pass.
          </p>
        )}
        {live && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed px-3 py-2">
            <p className="text-muted-foreground text-xs">
              You can stop the pass at any point and keep whatever has been drafted so far.
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void pause()}
              disabled={pausing || !jobId}
            >
              <Pause />
              {pausing ? "Pausing\u2026" : "Pause & keep this draft"}
            </Button>
          </div>
        )}

        {pauseError && (
          <p role="alert" className="text-destructive text-xs">
            Could not pause: {pauseError}
          </p>
        )}

        {state.status === "done" && state.deck && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <CheckCircle2 className="text-emerald-600" size={16} aria-hidden="true" />
              <p className="text-sm font-semibold">Deck ready</p>
              {finalVerdict && (
                <Badge className={cn("px-1.5 py-0 text-[10px]", finalVerdict.className)}>
                  {finalVerdict.label}
                </Badge>
              )}
              {typeof deckReview?.score === "number" && (
                <span className="text-muted-foreground text-xs font-semibold">
                  {deckReview.score}/100
                </span>
              )}
            </div>
            <p className="mt-1 text-sm">
              {state.deck.title || `Week ${state.deck.week ?? week} deck`}
            </p>
            <p className="text-muted-foreground mt-1 text-xs">
              Keep editing: open the deck to revise slides, then approve it when it looks right.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button asChild size="sm">
                <Link href={`/studio/deck/${state.deck.id}`}>Open deck</Link>
              </Button>
              {state.traceUrl && (
                <Button asChild variant="outline" size="sm">
                  <a href={state.traceUrl} target="_blank" rel="noreferrer">
                    View trace
                  </a>
                </Button>
              )}
              {onCancel && (
                <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
                  Close
                </Button>
              )}
            </div>
          </div>
        )}
        {state.status === "error" && (
          <div
            role="alert"
            className="border-destructive/30 bg-destructive/5 flex flex-col gap-2 rounded-lg border p-3"
          >
            <p className="text-destructive flex items-start gap-2 text-sm">
              <TriangleAlert className="mt-0.5 shrink-0" size={15} aria-hidden="true" />
              <span>{state.error}</span>
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setAttempt((value) => value + 1)}
              >
                <RefreshCw />
                Try again
              </Button>
              {onCancel && (
                <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
                  Cancel
                </Button>
              )}
            </div>
          </div>
        )}
      </CardContent>
      <style>{`
        .pa-collab-bubble { animation: pa-collab-in 0.28s ease-out both; }
        .pa-collab-dot { animation: pa-collab-pulse 1s ease-in-out infinite; }
        @keyframes pa-collab-in {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: none; }
        }
        @keyframes pa-collab-pulse {
          0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
          40% { opacity: 1; transform: translateY(-2px); }
        }
        @media (prefers-reduced-motion: reduce) {
          .pa-collab-bubble, .pa-collab-dot { animation: none; }
        }
      `}</style>
    </Card>
  );
}
