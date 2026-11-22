"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Button,
  Content,
  Header,
  HeaderGlobalAction,
  HeaderGlobalBar,
  SideNav,
  SideNavItems,
  SideNavLink,
  Theme,
} from "@carbon/react";
import {
  Certificate,
  Chat,
  Compare,
  Dashboard,
  Document,
  Education,
  Events,
  Flag,
  Notification,
  PresentationFile,
  Report,
  Search,
  UserMultiple,
  Watson,
} from "@carbon/icons-react";
import { ProfessorChat } from "@/components/profassist/professor-chat";

const PAGES: Record<string, { title: string; section: string; description: string }> = {
  "/dashboard": {
    title: "Home",
    section: "Workspace",
    description: "Drafts stay drafts. You approve the outline, the assessment, and the grade.",
  },
  "/outline": {
    title: "Subject outline",
    section: "Course",
    description: "Walk the faculty template. Download the PDF or DOCX when it is ready.",
  },
  "/generate": {
    title: "Assessment generator",
    section: "Course",
    description: "Choose outcomes. The council suggests a task. You accept it.",
  },
  "/assignments": {
    title: "Group assignments",
    section: "Course",
    description: "Several groups may share one idea. Each group submits its own work.",
  },
  "/similarity": {
    title: "Similarity",
    section: "Course",
    description: "Shared briefs are expected. The check compares the solution after that brief is removed.",
  },
  "/studio": {
    title: "Course studio",
    section: "Course",
    description: "Notes, objectives, and the materials the agents read.",
  },
  "/slides": {
    title: "Slides",
    section: "Course",
    description: "Each bullet stays next to the note it came from.",
  },
  "/grade": {
    title: "Review and grade",
    section: "Course",
    description: "The council drafts. You edit, approve, then record the push.",
  },
  "/integrity": {
    title: "Integrity",
    section: "Course",
    description: "Shared passages and viva questions. A flag is not a verdict.",
  },
  "/students": {
    title: "Students at risk",
    section: "Course",
    description: "A score is advice for you. It does not message a student or change a mark.",
  },
  "/style": {
    title: "My style",
    section: "Workspace",
    description: "Agents read this when they write. A reflection is not applied until you approve it.",
  },
  "/design": {
    title: "Course design",
    section: "Course",
    description: "Edit the weeks, outcomes, and assessment plan. Nothing is used until you approve it.",
  },
  "/rubric": {
    title: "Rubric builder",
    section: "Course",
    description: "Start blank, ask the model, or import. Approve the rubric onto the assignment.",
  },
  "/quality": {
    title: "Quality",
    section: "Workspace",
    description: "The grade calibrator is not trained. It will not change a level.",
  },
};

function pageMeta(pathname: string) {
  const path = pathname.replace(/^\/[a-z]{2}(?=\/)/, "") || "/dashboard";
  const key = Object.keys(PAGES).find((item) => path === item || path.endsWith(item));
  if (key && PAGES[key]) return PAGES[key];
  const name = path.split("/").filter(Boolean).pop() || "Page";
  return {
    title: name.replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()),
    section: "ProfAssist",
    description: "",
  };
}

const GROUPS: Array<{ label: string; items: Array<{ href: string; label: string; icon: typeof Dashboard }> }> = [
  { label: "", items: [{ href: "/dashboard", label: "Home", icon: Dashboard }] },
  {
    label: "Teach",
    items: [
      { href: "/outline", label: "Outline", icon: Document },
      { href: "/studio", label: "Studio", icon: Education },
      { href: "/slides", label: "Slides", icon: PresentationFile },
    ],
  },
  {
    label: "Assess",
    items: [
      { href: "/generate", label: "Assessments", icon: Report },
      { href: "/assignments", label: "Group work", icon: Events },
      { href: "/grade", label: "Grade", icon: Certificate },
      { href: "/integrity", label: "Integrity", icon: Flag },
      { href: "/similarity", label: "Similarity", icon: Compare },
    ],
  },
  { label: "Students", items: [{ href: "/students", label: "At risk", icon: UserMultiple }] },
  { label: "Me", items: [{ href: "/style", label: "My style", icon: Watson }] },
];

export function CarbonShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [chat, setChat] = useState(false);
  const [palette, setPalette] = useState(false);
  const [notes, setNotes] = useState(false);
  const [account, setAccount] = useState(false);
  const [query, setQuery] = useState("");
  const [logo, setLogo] = useState("/brand/uowd-logo.svg");

  useEffect(() => {
    const open = () => setChat(true);
    window.addEventListener("pa-open-chat", open);
    return () => window.removeEventListener("pa-open-chat", open);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    fetch("/api/profassist/brand")
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { logo_url?: string } | null) => {
        if (data?.logo_url) setLogo(data.logo_url);
      })
      .catch(() => undefined);
  }, []);

  return (
    <Theme theme="g10">
      <Header aria-label="ProfAssist">
        <a className="pa-brand" href="/dashboard" onClick={(event) => { event.preventDefault(); router.push("/dashboard"); }}>
          <img src={logo} alt="University of Wollongong in Dubai" />
          <span className="pa-brand-rule" />
          <strong>ProfAssist</strong>
        </a>
        <button className="pa-search" type="button" onClick={() => setPalette(true)}>
          <Search size={16} />
          Search
          <kbd>⌘K</kbd>
        </button>
        <HeaderGlobalBar>
          <HeaderGlobalAction aria-label="Notifications" onClick={() => { setNotes((open) => !open); setAccount(false); }} tooltipAlignment="end">
            <Notification size={20} />
          </HeaderGlobalAction>
          <button className="pa-avatar" type="button" aria-label="Account menu" onClick={() => { setAccount((open) => !open); setNotes(false); }}>
            LH
          </button>
        </HeaderGlobalBar>
      </Header>
      {notes && (
        <div className="pa-menu" role="dialog" aria-label="Notifications">
          <p style={{ margin: 0, padding: "8px 16px", color: "#525252", fontSize: "0.875rem" }}>You are up to date.</p>
        </div>
      )}
      {account && (
        <div className="pa-menu" role="menu" aria-label="Account">
          <a href="/style" onClick={(event) => { event.preventDefault(); setAccount(false); router.push("/style"); }}>My style</a>
          <button type="button" onClick={() => setAccount(false)}>Close</button>
        </div>
      )}
      <SideNav aria-label="Professor navigation" isFixedNav expanded>
        <SideNavItems>
          {GROUPS.map((group) => (
            <div key={group.label || "home"}>
              {group.label ? <div className="pa-nav-label">{group.label}</div> : null}
              {group.items.map((item) => (
                <SideNavLink
                  key={item.href}
                  renderIcon={item.icon}
                  href={item.href}
                  isActive={pathname === item.href || pathname?.endsWith(item.href)}
                  onClick={(event) => {
                    event.preventDefault();
                    router.push(item.href);
                  }}
                >
                  {item.label}
                </SideNavLink>
              ))}
            </div>
          ))}
        </SideNavItems>
      </SideNav>
      <Content id="main" className="pa-content">
        <div className="pa-frame">
          <PageHead pathname={pathname || "/dashboard"} onChat={() => setChat(true)} />
          {children}
        </div>
      </Content>
      {chat && <ProfessorChat onClose={() => setChat(false)} />}
      {palette && (
        <div className="pa-palette" onClick={() => setPalette(false)}>
          <form
            onClick={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault();
              const match = GROUPS.flatMap((group) => group.items).find((item) => item.label.toLowerCase().includes(query.toLowerCase()));
              if (match) router.push(match.href);
              setPalette(false);
            }}
          >
            <input autoFocus placeholder="Search pages" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search pages" />
            {GROUPS.flatMap((group) => group.items)
              .filter((item) => item.label.toLowerCase().includes(query.toLowerCase()))
              .map((item) => (
                <button key={item.href} type="button" onClick={() => { router.push(item.href); setPalette(false); }}>
                  {item.label}
                </button>
              ))}
          </form>
        </div>
      )}
    </Theme>
  );
}

function PageHead({ pathname, onChat }: { pathname: string; onChat: () => void }) {
  const path = pathname.replace(/^\/[a-z]{2}(?=\/)/, "");
  if (path === "/dashboard" || path.endsWith("/dashboard")) return null;
  const meta = pageMeta(pathname);
  return (
    <header className="pa-page-head">
      <div>
        <p className="pa-crumb">ProfAssist / {meta.section}</p>
        <h1>{meta.title}</h1>
        {meta.description ? <p>{meta.description}</p> : null}
      </div>
      <Button kind="primary" size="md" renderIcon={Chat} onClick={onChat}>
        Ask ProfAssist
      </Button>
    </header>
  );
}
