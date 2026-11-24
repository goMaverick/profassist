import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("@/components/layout/header", () => ({ Header: () => null }));
vi.mock("@/components/layout/app-nav", () => ({ APP_NAV_ITEMS: [], NavLinks: () => null }));
vi.mock("@/components/profassist/professor-chat", () => ({ ProfessorChat: () => null }));

vi.mock("@/components/ui", async () => {
  const React = await import("react");

  function Passthrough({ children }: { children?: ReactNode }) {
    return React.createElement(React.Fragment, null, children);
  }
  function Button({ children, onClick }: { children?: ReactNode; onClick?: () => void }) {
    return React.createElement("button", { type: "button", onClick }, children);
  }

  return {
    Button,
    Dialog: Passthrough,
    DialogContent: Passthrough,
    DialogDescription: Passthrough,
    DialogTitle: Passthrough,
    Input: (props: Record<string, unknown>) => React.createElement("input", props),
  };
});

import { PageHead, pageMeta } from "./app-shell";

const ASSIGNMENT_ID = "3f2a1b4c-9d8e-4f1a-b2c3-d4e5f6071829";
const DECK_ID = "7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f";

function renderHead(pathname: string, onChat = vi.fn()) {
  return render(<PageHead pathname={pathname} onChat={onChat} />);
}

/** The actions-only head: no title, no id, but the chat entry point stays. */
function expectArtifactBar(pathname: string) {
  const onChat = vi.fn();
  const { container } = renderHead(pathname, onChat);

  expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  expect(container).not.toHaveTextContent(ASSIGNMENT_ID);
  expect(container).not.toHaveTextContent(DECK_ID);
  expect(container.querySelector("#pa-page-tools")).not.toBeNull();

  const chat = screen.getByRole("button", { name: /ask profassist/i });
  fireEvent.click(chat);
  expect(onChat).toHaveBeenCalledTimes(1);
}

describe("PageHead", () => {
  it("keeps the chat button and drops the id on an assignment artifact route", () => {
    expectArtifactBar(`/assignments/${ASSIGNMENT_ID}`);
  });

  it("keeps the chat button and drops the id on a deck artifact route", () => {
    expectArtifactBar(`/studio/deck/${DECK_ID}`);
  });

  it("keeps the chat button and drops the id on a locale-prefixed artifact route", () => {
    expectArtifactBar(`/en/assignments/${ASSIGNMENT_ID}`);
  });

  it("keeps the assignment designer head on /assignments", () => {
    renderHead("/assignments");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Assignment Designer");
    expect(screen.getByRole("button", { name: /ask profassist/i })).toBeInTheDocument();
  });

  it("keeps the new assignment head on /assignments/new", () => {
    renderHead("/assignments/new");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("New");
  });

  it("keeps the material designer head on /studio", () => {
    renderHead("/studio");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Material Designer");
    expect(screen.getByRole("button", { name: /ask profassist/i })).toBeInTheDocument();
  });

  it("draws no head on /dashboard", () => {
    const { container } = renderHead("/dashboard");
    expect(container).toBeEmptyDOMElement();
  });

  it("labels artifact routes for the chat without the raw id", () => {
    expect(pageMeta(`/assignments/${ASSIGNMENT_ID}`).title).toBe("Assignment");
    expect(pageMeta(`/studio/deck/${DECK_ID}`).title).toBe("Deck");
    expect(pageMeta("/assignments").title).toBe("Assignment Designer");
    expect(pageMeta("/assignments/new").title).toBe("New");
  });
});
