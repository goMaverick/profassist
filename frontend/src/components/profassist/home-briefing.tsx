"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowRight, BookOpen, ExternalLink, Layers, ListChecks, Sparkles } from "lucide-react";

import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { pa } from "@/lib/profassist";
import { useAuthStore, useOrgStore } from "@/stores";

interface BriefingMemory {
  documents: number;
  topics: number;
  assessments: number;
  conflicts?: number;
}

interface Briefing {
  greeting: string;
  name: string;
  headline: string;
  bullets: string[];
  focus: string;
  focus_href?: string | null;
  trace_url?: string | null;
  memory: BriefingMemory;
  counts: Record<string, number>;
  degraded?: boolean;
}

const FOCUS_ROUTES = [
  { href: "/grade", words: ["grade", "draft", "submission", "approve"] },
  { href: "/assignments", words: ["assignment", "rubric", "assessment"] },
  { href: "/studio", words: ["studio", "slide", "deck", "material"] },
  { href: "/outline", words: ["outline", "clo", "outcome", "course"] },
];

function focusHref(briefing: Briefing): string {
  if (briefing.focus_href) return briefing.focus_href;
  const text = (briefing.focus + " " + briefing.headline).toLowerCase();
  const found = FOCUS_ROUTES.find((route) => route.words.some((word) => text.includes(word)));
  return found ? found.href : "/outline";
}

function MemoryStat({ icon, value, label }: { icon: ReactNode; value: number; label: string }) {
  return (
    <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
      {icon}
      <strong className="text-foreground font-medium">{value}</strong>
      {label}
    </span>
  );
}

export function HomeBriefing() {
  const userId = useAuthStore((state) => state.user?.id);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const { data: briefing, isPending: loading } = useQuery({
    queryKey: ["profassist", userId, orgId, "/home/briefing"],
    // Let an in-flight briefing finish so a quick return to Home can reuse it.
    queryFn: () => pa<Briefing>("/home/briefing", { method: "POST", body: "{}" }),
    enabled: Boolean(userId),
    staleTime: 60_000,
    retry: false,
    refetchOnReconnect: false,
  });

  if (loading) {
    return (
      <Card className="border-primary/10 bg-card/60 backdrop-blur">
        <CardContent className="space-y-3 p-6" aria-busy="true">
          <p className="text-muted-foreground text-sm">Reading your courses…</p>
          <Skeleton className="h-7 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-4/5" />
        </CardContent>
      </Card>
    );
  }

  if (!briefing) {
    return (
      <Card className="border-border/60">
        <CardContent className="text-muted-foreground p-6 text-sm">
          The briefing is unavailable right now. Your numbers below are still current.
        </CardContent>
      </Card>
    );
  }

  const href = focusHref(briefing);

  return (
    <Card className="border-primary/10 from-primary/5 via-card to-card relative overflow-hidden bg-gradient-to-br shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm">
              {briefing.greeting}
              {briefing.name ? ", " + briefing.name : ""}
            </p>
            {briefing.degraded && (
              <p className="text-muted-foreground text-xs">
                Brief unavailable &mdash; here is your day
              </p>
            )}
            <h2 className="text-2xl font-semibold tracking-tight text-balance">
              {briefing.headline}
            </h2>
          </div>
          <Badge variant="secondary" className="gap-1">
            <Sparkles className="h-3 w-3" aria-hidden="true" />
            Briefing
          </Badge>
        </div>

        <ul className="space-y-2">
          {briefing.bullets.map((bullet, index) => (
            <li key={index} className="flex gap-2 text-sm leading-relaxed">
              <span
                className="bg-primary mt-2 h-1.5 w-1.5 shrink-0 rounded-full"
                aria-hidden="true"
              />
              <span>{bullet}</span>
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap items-center gap-3">
          <Button asChild>
            <Link href={href}>
              {briefing.focus}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </Button>
          {briefing.trace_url && (
            <a
              href={briefing.trace_url}
              target="_blank"
              rel="noreferrer"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
            >
              Traced
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
          )}
        </div>

        <div className="border-border/60 flex flex-wrap items-center gap-x-5 gap-y-2 border-t pt-4">
          <MemoryStat
            icon={<BookOpen className="h-3.5 w-3.5" aria-hidden="true" />}
            value={briefing.memory.documents}
            label="documents read"
          />
          <MemoryStat
            icon={<Layers className="h-3.5 w-3.5" aria-hidden="true" />}
            value={briefing.memory.topics}
            label="topics"
          />
          <MemoryStat
            icon={<ListChecks className="h-3.5 w-3.5" aria-hidden="true" />}
            value={briefing.memory.assessments}
            label="assessments"
          />
        </div>
      </CardContent>
    </Card>
  );
}
