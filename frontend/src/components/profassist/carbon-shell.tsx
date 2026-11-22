"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Button,
  Content,
  Header,
  HeaderGlobalAction,
  HeaderGlobalBar,
  HeaderName,
  SideNav,
  SideNavItems,
  SideNavLink,
  Theme,
} from "@carbon/react";
import {
  Chat,
  Dashboard,
  Document,
  Education,
  Flag,
  Certificate,
  PresentationFile,
  Report,
  User,
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

const LINKS = [
  { href: "/dashboard", label: "Home", icon: Dashboard },
  { href: "/outline", label: "Subject outline", icon: Document },
  { href: "/generate", label: "Assessments", icon: Report },
  { href: "/assignments", label: "Group work", icon: Education },
  { href: "/similarity", label: "Similarity", icon: Flag },
  { href: "/studio", label: "Studio", icon: Education },
  { href: "/slides", label: "Slides", icon: PresentationFile },
  { href: "/grade", label: "Grade", icon: Certificate },
  { href: "/integrity", label: "Integrity", icon: Flag },
  { href: "/students", label: "Students", icon: User },
  { href: "/style", label: "My style", icon: Watson },
];

export function CarbonShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [chat, setChat] = useState(false);
  const [logo, setLogo] = useState("/brand/uowd-logo.svg");

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
        <HeaderName href="/dashboard" prefix="">
          <img src={logo} alt="University of Wollongong in Dubai" style={{ height: 36, width: "auto", maxWidth: 220, marginRight: 12 }} />
          ProfAssist
        </HeaderName>
        <HeaderGlobalBar>
          <HeaderGlobalAction aria-label="Open chat" onClick={() => setChat(true)} tooltipAlignment="end">
            <Chat size={20} />
          </HeaderGlobalAction>
        </HeaderGlobalBar>
      </Header>
      <SideNav aria-label="Professor navigation" isFixedNav expanded>
        <SideNavItems>
          {LINKS.map((item) => (
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
        </SideNavItems>
      </SideNav>
      <Content id="main" className="pa-content">
        <PageHead pathname={pathname || "/dashboard"} onChat={() => setChat(true)} />
        {children}
      </Content>
      {chat && <ProfessorChat onClose={() => setChat(false)} />}
    </Theme>
  );
}

function PageHead({ pathname, onChat }: { pathname: string; onChat: () => void }) {
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
