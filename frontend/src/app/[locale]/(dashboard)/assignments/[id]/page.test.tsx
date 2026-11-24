import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ProfassistError } from "@/lib/profassist";

const pa = vi.fn();

vi.mock("@/components/profassist/bits", () => ({
  pa: (...args: unknown[]) => pa(...args),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "asg-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/assignments/asg-1",
}));

import { TooltipProvider } from "@/components/ui";

import AssignmentArtifactPage from "./page";

function renderPage() {
  return render(
    <TooltipProvider>
      <AssignmentArtifactPage />
    </TooltipProvider>,
  );
}

const REPORT_SECTIONS: Array<[string, string, string]> = [
  ["1", "Executive Summary", "Readable on its own by a non-technical executive."],
  ["2", "Problem Definition", "The context, the baseline, and the target."],
  ["3", "Solution Overview", "The end-to-end architecture diagram."],
  ["4", "Data Strategy", "Sources, quality checks, and access controls."],
  ["5", "AI Workflow Design", "Pipeline stages and experiment tracking."],
  ["6", "Tool and Technology Stack", "Tools and the alternatives rejected."],
  ["7", "Deployment", "Serving pattern, rollout, and rollback."],
  ["8", "Monitoring", "Drift, alerts, and who is called."],
  ["9", "Security and Privacy", "Data protection and least privilege."],
  ["10", "Evaluation", "Metrics and the test plan."],
  ["11", "Conclusion", "The one decision that matters."],
];

const ARTIFACT = {
  assignment: {
    id: "asg-1",
    number: "2",
    title: "Solutions Architecture Report",
    status: "draft",
    course_code: "MAAI903",
  },
  document: {
    class_details: {
      institution: "University of Wollongong in Dubai",
      course: "MAAI903 AI Solutions Design",
      lecturer: "Dr Patrick Mukala",
      assessment: "Assessment 2: Solutions Architecture Report",
      weight: "25%",
      report_due: "Week 7",
    },
    overview: ["Design an AI solution architecture for a real business problem."],
    problem_choices: [
      { problem: "Bank fraud detection", description: "Real-time scoring in the auth window." },
    ],
    deliverables: [{ title: "Technical report", description: "At most 2,500 words." }],
    report_sections: REPORT_SECTIONS.map(([number, section, guidelines]) => ({
      number,
      section,
      guidelines,
    })),
  },
  review: null,
  rubric: {
    id: "asm-1",
    status: "draft",
    brief: "The rubric brief",
    criteria: [
      {
        id: "c1",
        name: "Evidence",
        weight: 60,
        levels: {
          advanced: "Names limits",
          proficient: "Quotes one",
          developing: "Partly",
          beginning: "Lists",
        },
      },
      {
        id: "c2",
        name: "Insight",
        weight: 30,
        levels: { advanced: "A", proficient: "B", developing: "C", beginning: "D" },
      },
    ],
  },
};

const REVIEW = {
  verdict: "revise" as const,
  score: 78,
  issues: [
    {
      reviewer: "alignment",
      severity: "high",
      section: "Overview",
      issue: "Learning outcome CLO3 is never addressed.",
      fix: "Map the problem choices to CLO3 explicitly.",
    },
    {
      reviewer: "rubric",
      severity: "medium",
      section: 5,
      issue: "The rubric weights total 90%.",
      fix: "Make the weights total 100%.",
    },
  ],
  strengths: ["The deliverables match the 25% assessment weight."],
  messages: [
    { role: "alignment", text: "The overview drifts from CLO3." },
    { role: "brief", text: "Audience and report length are clear." },
    { role: "rubric", text: "Weights do not total 100.", severity: "medium" },
    { role: "chair", text: "Revise before publishing.", severity: "high" },
  ],
  trace_url: "http://trace/council/1",
  degraded: false,
};

type Call = [string, { method?: string; body?: string }?];

function callsTo(path: string, method: string) {
  return (pa.mock.calls as Call[]).filter(
    (entry) => entry[0] === path && entry[1]?.method === method,
  );
}

beforeEach(() => {
  pa.mockReset();
  pa.mockImplementation((path: string, init?: { method?: string; body?: string }) => {
    if (path === "/assignments/asg-1/artifact") return Promise.resolve(ARTIFACT);
    if (path === "/assignments/asg-1" && init?.method === "PUT") {
      const document = JSON.parse(init.body ?? "{}").document;
      return Promise.resolve({
        assignment: ARTIFACT.assignment,
        document,
        rubric: ARTIFACT.rubric,
      });
    }
    if (path === "/assessments/asm-1/rubric") return Promise.resolve({ ...ARTIFACT.rubric });
    if (path === "/assessments/asm-1/approve") {
      return Promise.resolve({ ...ARTIFACT.rubric, status: "approved" });
    }
    return Promise.resolve({
      reply: "Tightened the overview.",
      changed: true,
      changed_sections: ["overview"],
    });
  });
});

describe("assignment artifact page", () => {
  it("renders the council verdict, messages, issues, strengths, and trace", async () => {
    pa.mockImplementation((path: string) => {
      if (path === "/assignments/asg-1/artifact") {
        return Promise.resolve({ ...ARTIFACT, review: REVIEW });
      }
      return Promise.resolve({ ...ARTIFACT.rubric });
    });

    renderPage();

    const panel = await screen.findByRole("region", { name: "Council review" });
    expect(within(panel).getByText("Needs revision")).toBeInTheDocument();
    expect(within(panel).getByText("78/100")).toBeInTheDocument();
    expect(within(panel).getByText("2 issues")).toBeInTheDocument();
    // One group per role, each with its label and avatar.
    for (const role of ["Alignment", "Brief", "Rubric", "Chair"]) {
      expect(within(panel).getAllByText(role).length).toBeGreaterThan(0);
    }
    expect(within(panel).getByText("The overview drifts from CLO3.")).toBeInTheDocument();
    expect(within(panel).getByText("Revise before publishing.")).toBeInTheDocument();
    // Issues carry a severity, a section, the problem, and the fix.
    expect(within(panel).getByText("high")).toBeInTheDocument();
    expect(within(panel).getByText("Overview")).toBeInTheDocument();
    expect(within(panel).getByText("Section 5")).toBeInTheDocument();
    expect(
      within(panel).getByText("Learning outcome CLO3 is never addressed."),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText("Fix: Map the problem choices to CLO3 explicitly."),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText("The deliverables match the 25% assessment weight."),
    ).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Trace" })).toHaveAttribute(
      "href",
      "http://trace/council/1",
    );
    // The panel is advisory: it does not touch the toolbars or publish.
    expect(callsTo("/assignments/asg-1", "PUT")).toHaveLength(0);
    expect(callsTo("/assignments/asg-1/finish", "POST")).toHaveLength(0);
  });

  it("posts a council review and refreshes the artifact", async () => {
    let artifactCalls = 0;
    pa.mockImplementation((path: string, init?: { method?: string }) => {
      if (path === "/assignments/asg-1/artifact") {
        artifactCalls += 1;
        return Promise.resolve(artifactCalls > 1 ? { ...ARTIFACT, review: REVIEW } : ARTIFACT);
      }
      if (path === "/assignments/asg-1/review" && init?.method === "POST") {
        return Promise.resolve({ review: REVIEW, trace_url: "http://trace/council/1" });
      }
      return Promise.resolve({ ...ARTIFACT.rubric });
    });

    renderPage();

    const empty = await screen.findByRole("region", { name: "Council review" });
    expect(
      within(empty).getByText(
        "No council review yet. Review alignment, brief, and rubric before publishing.",
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Review with council" }));

    await waitFor(() => expect(callsTo("/assignments/asg-1/review", "POST")).toHaveLength(1));
    // The POST is followed by a fresh artifact read so the persisted row is on screen.
    await waitFor(() => expect(artifactCalls).toBe(2));
    const panel = await screen.findByRole("region", { name: "Council review" });
    expect(within(panel).getByText("Needs revision")).toBeInTheDocument();
    expect(within(panel).getByText("78/100")).toBeInTheDocument();
    expect(callsTo("/assignments/asg-1", "PUT")).toHaveLength(0);
    expect(callsTo("/assignments/asg-1/finish", "POST")).toHaveLength(0);
  });

  it("shows the empty council state before the first review", async () => {
    renderPage();

    const panel = await screen.findByRole("region", { name: "Council review" });
    expect(
      within(panel).getByText(
        "No council review yet. Review alignment, brief, and rubric before publishing.",
      ),
    ).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Review with council" })).toBeInTheDocument();
    expect(within(panel).queryByText("Needs revision")).not.toBeInTheDocument();
  });

  it("renders every section of the document", async () => {
    renderPage();

    expect(
      (await screen.findAllByText("Assessment 2: Solutions Architecture Report")).length,
    ).toBeGreaterThan(0);
    for (const heading of [
      "Class details",
      "Overview",
      "Choosing your problem",
      "Deliverables",
      "Technical report sections",
      "Rubric",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText("Bank fraud detection")).toBeInTheDocument();
    expect(screen.getByText("Technical report:")).toBeInTheDocument();
    expect(screen.getByText("Executive Summary")).toBeInTheDocument();
    expect(screen.getByText("11 report sections")).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText("Names limits")).toBeInTheDocument();
  });

  it("shows the rubric weight total and warns when it is not 100", async () => {
    renderPage();

    expect(await screen.findByText("Total 90%")).toBeInTheDocument();
    expect(screen.getByText(/Weights total 90%, not 100%/)).toBeInTheDocument();
  });

  it("stacks rubric criteria as blocks instead of a wide table", async () => {
    const { container } = renderPage();

    await screen.findByText("Evidence");
    const rubric = container.querySelector("#doc-section-rubric");
    expect(rubric).not.toBeNull();
    // The six-column table clipped inside the A4 paper, so the rubric is now stacked blocks.
    expect(rubric?.querySelector("table")).toBeNull();
    expect(within(rubric as HTMLElement).getByText("Insight")).toBeInTheDocument();
    expect(within(rubric as HTMLElement).getByText("60%")).toBeInTheDocument();
    expect(within(rubric as HTMLElement).getByText("30%")).toBeInTheDocument();
    for (const level of ["Excellent", "Good", "Satisfactory", "Needs improvement"]) {
      expect(within(rubric as HTMLElement).getAllByText(level)).toHaveLength(2);
    }
  });

  it("links the toolbar to the document downloads and the Groups tab", async () => {
    renderPage();

    const pdf = await screen.findByRole("link", { name: /download pdf/i });
    expect(pdf).toHaveAttribute("href", "/api/profassist/assignments/asg-1/document?kind=pdf");
    expect(screen.getByRole("link", { name: /download docx/i })).toHaveAttribute(
      "href",
      "/api/profassist/assignments/asg-1/document?kind=docx",
    );
    expect(screen.getByRole("link", { name: /set up groups/i })).toHaveAttribute(
      "href",
      "/assignments?id=asg-1&tab=groups",
    );
  });

  it("saves edited prose and keeps every report row", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    expect(screen.getByLabelText("Report section 11 guidelines")).toHaveValue(
      "The one decision that matters.",
    );
    fireEvent.change(screen.getByLabelText("Overview paragraph 1"), {
      target: { value: "A tightened overview." },
    });
    fireEvent.change(screen.getByLabelText("Report section 11 guidelines"), {
      target: { value: "State the decision and its trade-off." },
    });
    fireEvent.change(screen.getByLabelText("Lecturer"), { target: { value: "Dr New" } });

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(callsTo("/assignments/asg-1", "PUT")).toHaveLength(1));
    const body = JSON.parse(callsTo("/assignments/asg-1", "PUT")[0]?.[1]?.body ?? "{}");
    expect(body.document.overview).toEqual(["A tightened overview."]);
    expect(body.document.class_details.lecturer).toBe("Dr New");
    expect(body.document.report_sections).toHaveLength(11);
    expect(body.document.report_sections.map((row: { number: string }) => row.number)).toEqual([
      "1",
      "2",
      "3",
      "4",
      "5",
      "6",
      "7",
      "8",
      "9",
      "10",
      "11",
    ]);
    expect(body.document.report_sections[10].guidelines).toBe(
      "State the decision and its trade-off.",
    );
    expect(body.title).toBeUndefined();
    // The rubric did not change, so it is not rewritten.
    expect(callsTo("/assessments/asm-1/rubric", "PUT")).toHaveLength(0);

    // The response is merged, so the saved wording is what the reader now sees.
    expect(await screen.findByText("Assignment saved.")).toBeInTheDocument();
    expect(screen.getByText("A tightened overview.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("keeps the draft and shows a real 400 when the document is refused", async () => {
    pa.mockImplementation((path: string, init?: { method?: string }) => {
      if (path === "/assignments/asg-1/artifact") return Promise.resolve(ARTIFACT);
      if (path === "/assignments/asg-1" && init?.method === "PUT") {
        return Promise.reject(
          new ProfassistError("document.report_sections must keep the eleven template rows", 400),
        );
      }
      return Promise.resolve({ ...ARTIFACT.rubric });
    });

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Overview paragraph 1"), {
      target: { value: "This must survive the failure." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/must keep the eleven template rows/)).toBeInTheDocument();
    // Edit mode is still on and the typed text is untouched.
    expect(screen.getByLabelText("Overview paragraph 1")).toHaveValue(
      "This must survive the failure.",
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(callsTo("/assessments/asm-1/rubric", "PUT")).toHaveLength(0);
    expect(screen.queryByText("Assignment saved.")).not.toBeInTheDocument();
  });

  it("saves the edited rubric together with the document", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    fireEvent.change(screen.getByRole("spinbutton", { name: "Weight for criterion 2" }), {
      target: { value: "40" },
    });
    expect(screen.getByText("Total 100%")).toBeInTheDocument();
    expect(screen.queryByText(/Weights total/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(callsTo("/assessments/asm-1/rubric", "PUT")).toHaveLength(1));
    expect(callsTo("/assignments/asg-1", "PUT")).toHaveLength(1);

    const payload = JSON.parse(callsTo("/assessments/asm-1/rubric", "PUT")[0]?.[1]?.body ?? "{}");
    expect(payload.brief).toBe("The rubric brief");
    expect(payload.criteria.map((row: { weight: number }) => row.weight)).toEqual([60, 40]);
    expect(payload.criteria[0].levels).toEqual({
      advanced: "Names limits",
      proficient: "Quotes one",
      developing: "Partly",
      beginning: "Lists",
    });
  });

  it("saves only the rubric when it is not being edited", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Save rubric" }));

    await waitFor(() => expect(callsTo("/assessments/asm-1/rubric", "PUT")).toHaveLength(1));
    const payload = JSON.parse(callsTo("/assessments/asm-1/rubric", "PUT")[0]?.[1]?.body ?? "{}");
    expect(payload.criteria.map((row: { weight: number }) => row.weight)).toEqual([60, 30]);
    expect(callsTo("/assignments/asg-1", "PUT")).toHaveLength(0);
    expect(await screen.findByText("Rubric saved.")).toBeInTheDocument();
  });

  it("posts a section refine and shows the reply", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Enhance Overview" }));
    const box = await screen.findByLabelText("Change for Overview");
    fireEvent.change(box, { target: { value: "tighten it to two paragraphs" } });
    fireEvent.click(screen.getByRole("button", { name: "Enhance" }));

    await waitFor(() =>
      expect(pa).toHaveBeenCalledWith("/assignments/asg-1/assist", expect.anything()),
    );
    const call = pa.mock.calls.find((entry) => entry[0] === "/assignments/asg-1/assist");
    const payload = JSON.parse((call?.[1] as { body: string }).body);
    expect(payload.mode).toBe("refine");
    expect(payload.message).toBe("In the Overview section: tighten it to two paragraphs");

    expect(
      await screen.findByText(/Tightened the overview\. Changed: Overview\./),
    ).toBeInTheDocument();
  });

  it("never shows a raw assignment UUID as the heading or the edit draft", async () => {
    const uuid = "3f2a1b4c-9d8e-4f2a-8b6c-1d2e3f4a5b6c";
    pa.mockImplementation((path: string) => {
      if (path === "/assignments/asg-1/artifact") {
        return Promise.resolve({
          ...ARTIFACT,
          assignment: { ...ARTIFACT.assignment, title: uuid },
          document: {
            ...ARTIFACT.document,
            class_details: {
              institution: ARTIFACT.document.class_details.institution,
              course: ARTIFACT.document.class_details.course,
              weight: ARTIFACT.document.class_details.weight,
            },
          },
        });
      }
      return Promise.resolve({ ...ARTIFACT.rubric });
    });

    renderPage();

    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Assignment 2");
    expect(heading).not.toHaveTextContent(uuid);
    expect(screen.queryByText(uuid)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Assignment title")).toHaveValue("");
  });

  it("paginates the artifact into five A4 sheets", async () => {
    const { container } = renderPage();

    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelectorAll(".pa-paper-page")).toHaveLength(5);
    expect(screen.getByText("Page 1 of 5")).toBeInTheDocument();
    expect(screen.getByText("Page 5 of 5")).toBeInTheDocument();
    // Report sections split 1-6 and 7-11 across two pages.
    expect(screen.getByText("Executive Summary")).toBeInTheDocument();
    expect(screen.getByText("Tool and Technology Stack")).toBeInTheDocument();
    expect(screen.getByText("Conclusion")).toBeInTheDocument();
  });
});
