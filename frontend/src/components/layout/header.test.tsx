import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { Header } from "./header";
import { APP_NAME } from "@/lib/constants";

vi.mock("next/link", async () => {
  const React = await import("react");
  return {
    default: ({
      href,
      children,
      ...rest
    }: { href: string; children?: ReactNode } & Record<string, unknown>) =>
      React.createElement("a", { href, ...rest }, children),
  };
});

vi.mock("@/components/ui", async () => {
  const React = await import("react");

  function Passthrough({ children }: { children?: ReactNode }) {
    return React.createElement(React.Fragment, null, children);
  }
  function Button({ children }: { children?: ReactNode }) {
    return React.createElement("button", { type: "button" }, children);
  }
  function AvatarImage() {
    return null;
  }

  return {
    Avatar: Passthrough,
    AvatarFallback: Passthrough,
    AvatarImage,
    Button,
    DropdownMenu: Passthrough,
    DropdownMenuContent: Passthrough,
    DropdownMenuItem: Passthrough,
    DropdownMenuLabel: Passthrough,
    DropdownMenuSeparator: Passthrough,
    DropdownMenuTrigger: Passthrough,
  };
});

vi.mock("@/components/theme", async () => {
  const React = await import("react");
  return {
    ThemeToggle: ({ className }: { className?: string }) =>
      React.createElement("button", { type: "button", "aria-label": "Toggle theme", className }),
  };
});

vi.mock("@/components/teams", () => ({
  OrgSwitcher: () => null,
}));

vi.mock("@/hooks", () => ({
  useAuth: () => ({
    user: {
      id: "user-1",
      email: "prof@example.edu",
      full_name: "Prof One",
      role: "user",
      avatar_url: null,
    },
    isAuthenticated: true,
    logout: vi.fn(),
  }),
}));

vi.mock("@/stores", () => ({
  useAuthStore: (selector: (state: { avatarVersion: number }) => unknown) =>
    selector({ avatarVersion: 0 }),
  useSidebarStore: () => ({ toggle: vi.fn() }),
}));

const REMOVED_NAV_LABELS = [
  "Course Designer",
  "Material Designer",
  "Assignment Designer",
  "Integrity",
  "Students",
  "My style",
  "Workspace",
  "Organizations",
  "Course files",
  "Quality",
];

describe("Header", () => {
  it("renders no primary navigation or destination links in the header", () => {
    render(<Header />);
    const banner = screen.getByRole("banner");

    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
    expect(within(banner).queryByRole("link", { name: "Home" })).not.toBeInTheDocument();
    expect(within(banner).queryByRole("link", { name: "Grading" })).not.toBeInTheDocument();
  });

  it("leaves the full workspace nav to the sidebar", () => {
    render(<Header />);
    for (const name of REMOVED_NAV_LABELS) {
      expect(screen.queryByRole("link", { name })).not.toBeInTheDocument();
    }
  });

  it("keeps the brand and right controls from wrapping or shrinking", () => {
    render(<Header />);
    const row = screen.getByRole("banner").firstElementChild as HTMLElement;
    const left = row.firstElementChild as HTMLElement;
    const right = row.lastElementChild as HTMLElement;
    const brand = screen.getByRole("link", { name: APP_NAME });

    expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
    expect(row).toHaveClass("overflow-hidden");
    expect(left).toHaveClass("min-w-0");
    for (const element of [brand, right]) {
      expect(element).toHaveClass("shrink-0");
      expect(element).toHaveClass("whitespace-nowrap");
    }
  });

  it("keeps the mobile menu toggle, search and theme controls", () => {
    render(<Header />);
    expect(screen.getByRole("button", { name: "Toggle menu" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Search" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Toggle theme" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Login" })).not.toBeInTheDocument();
  });
});
