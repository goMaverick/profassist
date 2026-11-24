import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ProfassistError } from "@/lib/profassist";

const pa = vi.fn();

vi.mock("@/components/profassist/bits", () => ({
  pa: (...args: unknown[]) => pa(...args),
}));

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/assignments/new",
  useParams: () => ({}),
}));

import NewAssignmentPage from "./page";

const COURSE = { id: "course-1", code: "MAAI903", title: "AI Solutions Design" };

beforeEach(() => {
  pa.mockReset();
  push.mockReset();
  window.sessionStorage.clear();
});

describe("new assignment page", () => {
  it("posts the course and the description, then opens the artifact", async () => {
    pa.mockImplementation((path: string) => {
      if (path === "/home") return Promise.resolve({ courses: [COURSE] });
      return Promise.resolve({ reply: "Draft ready.", assignment: { id: "asg-9" } });
    });

    render(<NewAssignmentPage />);

    const box = await screen.findByLabelText("What assignment do you want to create?");
    fireEvent.change(box, { target: { value: "Assessment 2: a 2,500-word architecture report" } });
    fireEvent.click(screen.getByRole("button", { name: /generate assignment/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/assignments/asg-9"));

    const call = pa.mock.calls.find((entry) => entry[0] === "/assignments/assist");
    expect(call).toBeTruthy();
    const payload = JSON.parse((call?.[1] as { body: string }).body);
    expect(payload).toEqual({
      course_id: "course-1",
      message: "Assessment 2: a 2,500-word architecture report",
      mode: "create",
    });
    expect(window.sessionStorage.getItem("pa-course")).toBe("course-1");
  });

  it("surfaces a real 503 and never opens a fake artifact", async () => {
    pa.mockImplementation((path: string) => {
      if (path === "/home") return Promise.resolve({ courses: [COURSE] });
      return Promise.reject(new ProfassistError("The language model is not configured", 503));
    });

    render(<NewAssignmentPage />);

    const box = await screen.findByLabelText("What assignment do you want to create?");
    fireEvent.change(box, { target: { value: "Assessment 2" } });
    fireEvent.click(screen.getByRole("button", { name: /generate assignment/i }));

    expect(await screen.findByText(/AI provider is unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Nothing was created")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("shows the workspace error when the course list cannot load", async () => {
    pa.mockRejectedValue(new ProfassistError("Not authenticated", 401));

    render(<NewAssignmentPage />);

    expect(
      await screen.findByText(/Sign in again to design an assignment|Not authenticated/),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
