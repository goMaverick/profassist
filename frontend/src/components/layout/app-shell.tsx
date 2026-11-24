"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { MessageSquare, Search } from "lucide-react";

import { APP_NAV_ITEMS, NavLinks } from "@/components/layout/app-nav";
import { Header } from "@/components/layout/header";
import { ProfessorChat } from "@/components/profassist/professor-chat";
import { resetPageContext } from "@/components/profassist/page-context";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Input,
} from "@/components/ui";
import { stripLocale } from "@/lib/active-route";

const PAGES: Record<string, { title: string; section: string; description: string }> = {
  "/dashboard": {
    title: "Home",
    section: "Workspace",
    description: "See what needs you, then open it.",
  },
  "/outline": {
    title: "Course Designer",
    section: "Course",
    description: "Create the course, generate the syllabus, then edit the document.",
  },
  "/generate": {
    title: "Assessment generator",
    section: "Course",
    description: "Choose outcomes. The council suggests a task. You accept it.",
  },
  "/assignments": {
    title: "Assignment Designer",
    section: "Assess",
    description: "Choose a course, then create the assignment and its rubric.",
  },
  "/group-work": {
    title: "Assignments",
    section: "Assess",
    description: "Group work now lives on Assignments.",
  },
  "/similarity": {
    title: "Integrity",
    section: "Assess",
    description: "Similarity now lives on the Integrity page.",
  },
  "/studio": {
    title: "Material Designer",
    section: "Course",
    description: "Upload notes, ask for materials, and generate decks.",
  },
  "/slides": {
    title: "Slides",
    section: "Course",
    description: "Make this week's slides from your notes.",
  },
  "/grade": {
    title: "Grading",
    section: "Assess",
    description: "Choose a course, then an assignment, then review the results.",
  },
  "/integrity": {
    title: "Integrity",
    section: "Assess",
    description: "Look at work that may be too similar. You decide what to do.",
  },
  "/students": {
    title: "Students at risk",
    section: "Course",
    description: "Students who may need a check-in. This does not change their mark.",
  },
  "/style": {
    title: "My style",
    section: "Workspace",
    description: "How you like feedback written. Nothing changes until you save it.",
  },
  "/admin/ai": {
    title: "AI settings",
    section: "Admin",
    description: "Models, prompts, and the servers the assistant talks to. Keys stay hidden.",
  },
  "/design": {
    title: "Course design",
    section: "Course",
    description:
      "Edit the weeks, outcomes, and assessment plan. Nothing is used until you approve it.",
  },
  "/rubric": {
    title: "Assignment rubric",
    section: "Course",
    description: "Rubrics are edited inside an assignment.",
  },
  "/quality": {
    title: "Quality",
    section: "Workspace",
    description: "The grade calibrator is not trained. It will not change a level.",
  },
};

/**
 * Pages that draw their own heading and toolbar: an assignment or a deck opened
 * by id. The shell renders no title there, so a raw id is never title-cased into
 * the header; it keeps the page-tools slot and the chat button in an
 * actions-only bar.
 */
const ARTIFACT_ROUTES: Array<{ pattern: RegExp; title: string; section: string }> = [
  // /assignments/<id>, but not /assignments and not /assignments/new.
  {
    pattern: /^\/assignments\/(?!new\/?$)[^/]+\/?$/,
    title: "Assignment",
    section: "Assess",
  },
  { pattern: /^\/studio\/deck\/[^/]+\/?$/, title: "Deck", section: "Course" },
];

function artifactRoute(path: string) {
  return ARTIFACT_ROUTES.find((route) => route.pattern.test(path)) ?? null;
}

/** Path with the locale segment removed, defaulting to the home route. */
function currentPath(pathname: string): string {
  const path = stripLocale(pathname || "/dashboard");
  return !path || path === "/" ? "/dashboard" : path;
}

export function pageMeta(pathname: string) {
  const path = currentPath(pathname);
  const key = Object.keys(PAGES).find((item) => path === item || path.endsWith(item));
  if (key && PAGES[key]) return PAGES[key];
  // The chat labels the page it answers for; an artifact id is not a label.
  const artifact = artifactRoute(path);
  if (artifact) return { title: artifact.title, section: artifact.section, description: "" };
  const name = path.split("/").filter(Boolean).pop() || "Page";
  return {
    title: name.replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()),
    section: "ProfAssist",
    description: "",
  };
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/dashboard";
  const router = useRouter();
  const [chat, setChat] = useState(false);
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState("");
  const pageOnRecord = useRef("");

  // The chat always answers for the page it is opened on. Context a page
  // publishes for itself (outline id, section) is kept: reset only drops
  // entity ids when the pathname actually moves to another page.
  useEffect(() => {
    const page = currentPath(pathname);
    if (pageOnRecord.current === page) return;
    pageOnRecord.current = page;
    resetPageContext(page, pageMeta(page).title);
  }, [pathname]);

  useEffect(() => {
    const open = () => setChat(true);
    window.addEventListener("pa-open-chat", open);
    return () => window.removeEventListener("pa-open-chat", open);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((open) => !open);
      }
    };
    const openPalette = () => setPalette(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("command-palette:open", openPalette);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("command-palette:open", openPalette);
    };
  }, []);

  const needle = query.trim().toLowerCase();
  const matches = APP_NAV_ITEMS.filter((item) => item.label.toLowerCase().includes(needle));

  function go(href: string) {
    setPalette(false);
    setQuery("");
    router.push(href);
  }

  return (
    <div className="bg-background text-foreground flex min-h-screen flex-col">
      <Header />
      <div className="flex flex-1">
        <aside className="border-border hidden w-60 shrink-0 border-r lg:block">
          <div className="sticky top-14 max-h-[calc(100vh-3.5rem)] overflow-y-auto">
            <NavLinks />
          </div>
        </aside>
        <main id="main" className="min-w-0 flex-1">
          <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">
            <PageHead pathname={pathname} onChat={() => setChat(true)} />
            {children}
          </div>
        </main>
      </div>
      {chat ? <ProfessorChat onClose={() => setChat(false)} /> : null}
      <Dialog open={palette} onOpenChange={setPalette}>
        <DialogContent className="gap-0 p-0 sm:max-w-lg">
          <DialogTitle className="sr-only">Search pages</DialogTitle>
          <DialogDescription className="sr-only">
            Filter the workspace pages and press Enter to open one.
          </DialogDescription>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (matches[0]) go(matches[0].href);
            }}
          >
            <div className="border-border flex items-center gap-2 border-b px-3 py-2">
              <Search className="text-muted-foreground h-4 w-4" aria-hidden />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search pages…"
                aria-label="Search pages"
                className="h-8 border-0 pr-8 shadow-none focus-visible:ring-0"
              />
            </div>
            <ul className="max-h-80 overflow-y-auto p-2">
              {matches.map((item) => (
                <li key={item.href}>
                  <button
                    type="button"
                    onClick={() => go(item.href)}
                    className="hover:bg-accent hover:text-accent-foreground flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors"
                  >
                    <item.icon className="text-muted-foreground h-4 w-4" aria-hidden />
                    {item.label}
                  </button>
                </li>
              ))}
              {matches.length === 0 ? (
                <li className="text-muted-foreground px-3 py-6 text-center text-sm">
                  No pages match that search.
                </li>
              ) : null}
            </ul>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function PageHead({ pathname, onChat }: { pathname: string; onChat: () => void }) {
  const path = currentPath(pathname);
  if (path === "/dashboard" || path.endsWith("/dashboard")) return null;
  // The artifact page carries its own title and toolbar. The shell still owns
  // the chat entry point and the page-tools slot, so it renders that bar with
  // no heading: a head here would title-case the id above the artifact.
  const artifact = artifactRoute(path);
  const meta = pageMeta(pathname);
  return (
    <header
      className={`border-border mb-6 flex flex-wrap items-start gap-4 border-b pb-4 ${
        artifact ? "justify-end" : "justify-between"
      }`}
    >
      {artifact ? null : (
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            ProfAssist / {meta.section}
          </p>
          <h1 className="font-display mt-1 text-2xl font-semibold tracking-tight">{meta.title}</h1>
          {meta.description ? (
            <p className="text-muted-foreground mt-1 max-w-2xl text-sm">{meta.description}</p>
          ) : null}
        </div>
      )}
      <div className="flex items-center gap-2">
        <div id="pa-page-tools" className="flex items-center gap-2" />
        <Button type="button" onClick={onChat}>
          <MessageSquare className="h-4 w-4" />
          Ask ProfAssist
        </Button>
      </div>
    </header>
  );
}
