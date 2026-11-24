import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

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
      allow_custom: true,
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

function inspector() {
  return screen.getByTestId("role-inspector");
}

async function selectTab(name: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name }));
}

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

    fireEvent.click(within(inspector()).getByRole("button", { name: "Move Creator down" }));
    const rail = screen.getByRole("group", { name: "Material Studio flow" });
    fireEvent.click(within(rail).getByRole("button", { name: "Chair" }));
    fireEvent.click(within(inspector()).getByRole("switch", { name: "Chair enabled" }));
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

  it("renders the flow rail in node order and marks disabled roles", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    const rail = await screen.findByRole("group", { name: "Material Studio flow" });
    const nodes = within(rail).getAllByRole("button", {
      name: /^(Creator|Curriculum|Chair)$/,
    });
    expect(nodes.map((node) => node.getAttribute("data-role-key"))).toEqual([
      "creator",
      "curriculum",
      "chair",
    ]);
    for (const node of nodes) expect(node).toHaveAttribute("data-enabled", "true");

    fireEvent.click(within(rail).getByRole("button", { name: "Curriculum" }));
    fireEvent.click(within(inspector()).getByRole("switch", { name: "Curriculum enabled" }));

    expect(screen.getByTestId("flow-node-curriculum")).toHaveAttribute("data-enabled", "false");
    expect(screen.getByTestId("flow-node-curriculum").className).toContain("line-through");
    expect(within(inspector()).getAllByText("Code check").length).toBeGreaterThan(0);
    expect(
      within(inspector()).getByText(/This reviewer runs deterministic backend rules/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Persona prompt for Curriculum")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Model for Curriculum")).not.toBeInTheDocument();
  });

  it("selects a node and highlights the inspector", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    const rail = await screen.findByRole("group", { name: "Material Studio flow" });
    const chair = within(rail).getByRole("button", { name: "Chair" });
    fireEvent.click(chair);

    expect(chair).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("role-card-chair")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("flow-node-creator")).toHaveAttribute("aria-pressed", "false");
    expect(within(inspector()).getByRole("heading", { name: "Chair" })).toBeInTheDocument();
  });

  it("adds an LLM reviewer to the outline council from the rail", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    await screen.findByRole("heading", { name: "Creator" });
    await selectTab("Outline");

    const rail = await screen.findByRole("group", { name: "Outline flow" });
    fireEvent.click(within(rail).getByRole("button", { name: "Add agent" }));

    expect(await screen.findByRole("heading", { name: "Reviewer 1" })).toBeInTheDocument();
    expect(screen.getByTestId("flow-node-reviewer_1")).toHaveAttribute("aria-pressed", "true");

    const row = screen.getByTestId("agent-row-reviewer_1");
    expect(within(row).getByText("Reviewer 1")).toBeInTheDocument();
    expect(within(row).getByText("reviewer_1")).toBeInTheDocument();
    expect(within(row).getByText("LLM")).toBeInTheDocument();
    expect(within(row).getByText("custom")).toBeInTheDocument();
  });

  it("saves custom reviewers before the chair in node order", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    await screen.findByRole("heading", { name: "Creator" });
    fireEvent.click(screen.getByTestId("list-add-agent"));
    fireEvent.change(await screen.findByLabelText("Persona prompt for Reviewer 1"), {
      target: { value: "Review the material carefully." },
    });
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
      "creator",
      "curriculum",
      "reviewer_1",
      "chair",
    ]);
    expect(payload.roles.map((role: { position: number }) => role.position)).toEqual([0, 1, 2, 3]);
  });

  it("reorders a custom reviewer from the inspector and keeps the chair last", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    await screen.findByRole("heading", { name: "Creator" });
    fireEvent.click(screen.getByTestId("list-add-agent"));
    fireEvent.change(await screen.findByLabelText("Persona prompt for Reviewer 1"), {
      target: { value: "Review the material carefully." },
    });
    fireEvent.click(within(inspector()).getByRole("button", { name: "Move Reviewer 1 up" }));
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
      "creator",
      "reviewer_1",
      "curriculum",
      "chair",
    ]);
  });

  it("requires a persona prompt for a custom reviewer before saving", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    await screen.findByRole("heading", { name: "Creator" });
    fireEvent.click(screen.getByTestId("list-add-agent"));
    fireEvent.click(screen.getByRole("button", { name: "Save council" }));

    expect(
      await screen.findByText("Reviewer 1 needs a persona prompt before you can save."),
    ).toBeInTheDocument();
    expect(pa).toHaveBeenCalledTimes(1);
  });

  it("shows an unsaved notice and clears it after saving", async () => {
    pa.mockResolvedValue(VIEW);
    render(<CouncilsAdminPage />);

    await screen.findByRole("heading", { name: "Creator" });
    expect(screen.getByTestId("save-state")).toHaveTextContent("All changes saved.");

    fireEvent.change(screen.getByLabelText("Model for Creator"), {
      target: { value: "openai/gpt-4.1" },
    });

    expect(screen.getByTestId("save-state")).toHaveTextContent("Unsaved changes.");
    expect(screen.getByTestId("unsaved-badge")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save council" }));

    await waitFor(() =>
      expect(screen.getByTestId("save-state")).toHaveTextContent("All changes saved."),
    );
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
    fireEvent.click(screen.getByTestId("list-add-agent"));

    expect(await screen.findByRole("heading", { name: "Reviewer 1" })).toBeInTheDocument();
    const model = screen.getByLabelText("Model for Reviewer 1");
    expect(model).toHaveValue("");
    fireEvent.change(model, { target: { value: "openai/gpt-4.1" } });
    expect(screen.getByLabelText("Model for Reviewer 1")).toHaveValue("openai/gpt-4.1");

    fireEvent.click(within(inspector()).getByRole("button", { name: "Delete Reviewer 1" }));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Reviewer 1" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByTestId("agent-row-reviewer_1")).not.toBeInTheDocument();
  });

  it("shows a real load error instead of fake roles", async () => {
    pa.mockRejectedValue(new ProfassistError("Admins only", 403));
    render(<CouncilsAdminPage />);

    expect(await screen.findByText("Admins only")).toBeInTheDocument();
    expect(screen.getByText("Council settings")).toBeInTheDocument();
  });
});
