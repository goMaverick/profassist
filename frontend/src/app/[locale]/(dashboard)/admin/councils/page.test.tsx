import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ProfassistError } from "@/lib/profassist";

const pa = vi.fn();

vi.mock("@/components/profassist/bits", () => ({
  pa: (...args: unknown[]) => pa(...args),
  run: async (action: () => Promise<unknown>, setError: (value: string) => void) => {
    try {
      setError("");
      return await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      return null;
    }
  },
}));

import CouncilsAdminPage from "./page";

const VIEW = {
  councils: [
    {
      key: "material",
      label: "Material Studio",
      description: "Builds and checks course material.",
      allow_custom: true,
      roles: [
        {
          role_key: "creator",
          label: "Creator",
          kind: "llm",
          persona_prompt: "Draft the material.",
          agent_key: "course_designer",
          model: "gemini/gemini-3.5-flash-lite",
          position: 0,
          enabled: true,
          custom: false,
          config: {},
        },
        {
          role_key: "curriculum",
          label: "Curriculum",
          kind: "deterministic",
          persona_prompt: "",
          agent_key: "curriculum",
          model: "",
          position: 1,
          enabled: true,
          custom: false,
          config: {},
        },
        {
          role_key: "chair",
          label: "Chair",
          kind: "chair",
          persona_prompt: "Decide.",
          agent_key: "chair",
          model: "gemini/gemini-3.5-flash-lite",
          position: 2,
          enabled: true,
          custom: false,
          config: {},
        },
      ],
    },
    {
      key: "assignment",
      label: "Assignment",
      description: "Reviews assignment drafts.",
      allow_custom: true,
      roles: [
        {
          role_key: "brief",
          label: "Brief",
          kind: "llm",
          persona_prompt: "Check the brief.",
          agent_key: "brief",
          model: "",
          position: 0,
          enabled: true,
          custom: false,
          config: {},
        },
      ],
    },
    {
      key: "grading",
      label: "Grading",
      description: "Grades with evidence and a chair.",
      allow_custom: false,
      roles: [
        {
          role_key: "evidence",
          label: "Evidence",
          kind: "llm",
          persona_prompt: "Quote the submission.",
          agent_key: "persona_evidence",
          model: "",
          position: 0,
          enabled: true,
          custom: false,
          config: {},
        },
      ],
    },
    {
      key: "outline",
      label: "Outline",
      description: "Reviews subject outlines.",
      allow_custom: false,
      roles: [
        {
          role_key: "alignment",
          label: "Alignment",
          kind: "llm",
          persona_prompt: "Check alignment.",
          agent_key: "alignment",
          model: "",
          position: 0,
          enabled: true,
          custom: false,
          config: {},
        },
      ],
    },
  ],
};

beforeEach(() => {
  pa.mockReset();
});
describe("councils admin page", () => {
  it("loads every council and saves a reordered, disabled role payload", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    expect(await screen.findByRole("heading", { name: "Creator" })).toBeInTheDocument();
    for (const name of ["Material Studio", "Assignment", "Grading", "Outline"]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole("button", { name: "Move Creator down" }));
    fireEvent.click(screen.getByRole("switch", { name: "Chair enabled" }));
    fireEvent.click(screen.getByRole("button", { name: "Save council" }));

    await waitFor(() =>
      expect(pa).toHaveBeenCalledWith(
        "/admin/councils/material",
        expect.objectContaining({ method: "PUT" }),
      ),
    );

    const call = pa.mock.calls.find(
      ([path, init]) => path === "/admin/councils/material" && init?.method === "PUT",
    );
    const payload = JSON.parse((call?.[1] as { body: string }).body);
    expect(payload.roles.map((role: { role_key: string }) => role.role_key)).toEqual([
      "curriculum",
      "creator",
      "chair",
    ]);
    expect(payload.roles.map((role: { position: number }) => role.position)).toEqual([0, 1, 2]);
    expect(
      payload.roles.find((role: { role_key: string }) => role.role_key === "chair").enabled,
    ).toBe(false);
    expect(await screen.findByText("Material Studio saved.")).toBeInTheDocument();
  });

  it("resets the active council to defaults", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    await screen.findByRole("heading", { name: "Creator" });
    fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));

    await waitFor(() =>
      expect(pa).toHaveBeenCalledWith(
        "/admin/councils/material/reset",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText("Material Studio restored to defaults.")).toBeInTheDocument();
  });

  it("adds and removes a custom reviewer", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    await screen.findByRole("heading", { name: "Creator" });
    fireEvent.click(screen.getByRole("button", { name: "Add reviewer" }));

    expect(await screen.findByRole("heading", { name: "Reviewer 1" })).toBeInTheDocument();
    const model = screen.getByLabelText("Model for Reviewer 1");
    expect(model).toHaveValue("");
    fireEvent.change(model, { target: { value: "openai/gpt-4.1" } });
    expect(screen.getByLabelText("Model for Reviewer 1")).toHaveValue("openai/gpt-4.1");

    fireEvent.click(screen.getByRole("button", { name: "Delete Reviewer 1" }));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Reviewer 1" })).not.toBeInTheDocument(),
    );
  });

  it("shows a real load error instead of fake roles", async () => {
    pa.mockRejectedValue(new ProfassistError("Admins only", 403));
    render(<CouncilsAdminPage />);

    expect(await screen.findByText("Admins only")).toBeInTheDocument();
    expect(screen.getByText("Council settings")).toBeInTheDocument();
  });
});
