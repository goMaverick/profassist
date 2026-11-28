import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

const { login } = vi.hoisted(() => ({ login: vi.fn() }));

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

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks", () => ({
  useAuth: () => ({ login }),
}));

vi.mock("@/components/auth/oauth-buttons", () => ({
  OAuthBlock: () => null,
}));

// The real store pulls in every zustand slice; the API client only needs
// setAccessToken for the error paths exercised here.
vi.mock("@/stores", () => ({
  useAuthStore: { getState: () => ({ setAccessToken: vi.fn() }) },
}));

import { LoginForm } from "./login-form";
import { ApiError } from "@/lib/api-client";

beforeEach(() => {
  login.mockReset();
});

describe("LoginForm", () => {
  it("renders email, password, and submit controls", () => {
    render(<LoginForm />);

    expect(screen.getByLabelText("email")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("password")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("password")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("button", { name: "login" })).toBeEnabled();
  });

  it("toggles password visibility", () => {
    render(<LoginForm />);

    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(screen.getByLabelText("password")).toHaveAttribute("type", "text");

    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(screen.getByLabelText("password")).toHaveAttribute("type", "password");
  });

  it("submits the entered credentials", async () => {
    login.mockResolvedValue({});
    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText("email"), {
      target: { value: "prof@example.edu" },
    });
    fireEvent.change(screen.getByLabelText("password"), { target: { value: "secret123" } });
    fireEvent.click(screen.getByRole("button", { name: "login" }));

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith({ email: "prof@example.edu", password: "secret123" }),
    );
  });

  it("shows an accessible error banner when login fails", async () => {
    login.mockRejectedValue(new ApiError(401, "Invalid email or password"));
    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText("email"), {
      target: { value: "prof@example.edu" },
    });
    fireEvent.change(screen.getByLabelText("password"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "login" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Invalid email or password");
    expect(alert).toHaveAttribute("aria-live", "assertive");
  });

  it("shows a loading state and disables the password toggle while signing in", async () => {
    let resolveLogin: () => void = () => {};
    login.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveLogin = resolve;
        }),
    );
    render(<LoginForm />);

    fireEvent.change(screen.getByLabelText("email"), {
      target: { value: "prof@example.edu" },
    });
    fireEvent.change(screen.getByLabelText("password"), { target: { value: "secret123" } });
    fireEvent.click(screen.getByRole("button", { name: "login" }));

    const submit = await screen.findByRole("button", { name: "loggingIn" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAttribute("aria-busy", "true");
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).toBeDisabled();

    await act(async () => {
      resolveLogin();
    });

    await waitFor(() => expect(toggle).toBeEnabled());
  });
});
