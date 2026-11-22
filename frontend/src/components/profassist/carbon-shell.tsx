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
  GraduationCap,
  PresentationFile,
  Report,
  User,
  Watson,
} from "@carbon/icons-react";
import { ProfessorChat } from "@/components/profassist/professor-chat";

const LINKS = [
  { href: "/dashboard", label: "Home", icon: Dashboard },
  { href: "/outline", label: "Subject outline", icon: Document },
  { href: "/generate", label: "Assessments", icon: Report },
  { href: "/studio", label: "Studio", icon: Education },
  { href: "/slides", label: "Slides", icon: PresentationFile },
  { href: "/grade", label: "Grade", icon: GraduationCap },
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
          <img src={logo} alt="University of Wollongong in Dubai" style={{ height: 28, marginRight: 8 }} />
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
        {children}
        {!chat && (
          <Button className="pa-chat-fab" kind="primary" renderIcon={Chat} onClick={() => setChat(true)}>
            Ask ProfAssist
          </Button>
        )}
      </Content>
      {chat && <ProfessorChat onClose={() => setChat(false)} />}
      <style>{`
        .pa-content { min-height: 100vh; padding: 5rem 2rem 6rem 18rem; background: #f4f4f4; }
        .pa-chat-fab { position: fixed; right: 1.5rem; bottom: 1.5rem; z-index: 9000; }
        @media (max-width: 66rem) {
          .pa-content { padding-left: 2rem; }
        }
      `}</style>
    </Theme>
  );
}
