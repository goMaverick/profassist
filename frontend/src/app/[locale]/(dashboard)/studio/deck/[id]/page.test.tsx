import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const pa = vi.fn();

vi.mock("@/components/profassist/bits", () => ({
  pa: (...args: unknown[]) => pa(...args),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "deck-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/studio/deck/deck-1",
}));

import { TooltipProvider } from "@/components/ui";

import DeckArtifactPage from "./page";

const DECK = {
  id: "deck-1",
  course_id: "course-1",
  title: "Week 1: Foundations",
  status: "draft",
  week: 1,
  instructions: "Draft the first lecture from the course notes.",
  review: {},
  review_trace_url: "",
  slides: [
    {
      title: "Why this matters",
      bullets: ["Systems are everywhere", "Failures are costly"],
      speaker_notes: "Open with a short story.",
    },
    { title: "The model", bullets: ["Inputs", "Outputs"] },
  ],
};

type Call = [string, { method?: string; body?: string }?];

function callsTo(path: string, method: string) {
  return (pa.mock.calls as Call[]).filter(
    (entry) => entry[0] === path && entry[1]?.method === method,
  );
}

function renderPage() {
  return render(
    <TooltipProvider>
      <DeckArtifactPage />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  pa.mockReset();
  pa.mockImplementation((path: string, init?: { method?: string; body?: string }) => {
    if (path === "/slides/deck-1" && !init?.method) return Promise.resolve(DECK);
    if (path === "/slides/deck-1" && init?.method === "PUT") {
      const body = JSON.parse(init.body ?? "{}") as {
        title?: string;
        slides: typeof DECK.slides;
      };
      return Promise.resolve({ ...DECK, ...body });
    }
    if (path === "/slides/deck-1/assist" && init?.method === "POST") {
      return Promise.resolve({
        reply: "Added a concrete example.",
        changed_slides: [0],
        deck: {
          ...DECK,
          slides: DECK.slides.map((slide, index) =>
            index === 0 ? { ...slide, bullets: [...slide.bullets, "A concrete example"] } : slide,
          ),
        },
      });
    }
    if (path === "/slides/deck-1/approve" && init?.method === "POST") {
      return Promise.resolve({ ...DECK, status: "approved" });
    }
    return Promise.reject(new Error(`Unexpected request: ${path}`));
  });
});

describe("deck artifact", () => {
  it("edits one slide and saves the whole slide list with PUT", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Week 1: Foundations" });

    fireEvent.click(screen.getByRole("button", { name: "Edit slide 1" }));
    fireEvent.change(screen.getByLabelText("Slide title"), {
      target: { value: "Why this matters, revised" },
    });
    fireEvent.change(screen.getByLabelText("Slide 1 bullet 2"), {
      target: { value: "Failures are expensive" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(callsTo("/slides/deck-1", "PUT")).toHaveLength(1));
    const body = JSON.parse(callsTo("/slides/deck-1", "PUT")[0]?.[1]?.body ?? "{}") as {
      slides: Array<{ title: string; bullets: string[] }>;
    };
    expect(body.slides).toHaveLength(2);
    expect(body.slides[0]?.title).toBe("Why this matters, revised");
    expect(body.slides[0]?.bullets).toEqual(["Systems are everywhere", "Failures are expensive"]);
    expect(body.slides[1]?.title).toBe("The model");
    expect(await screen.findByText("Deck saved.")).toBeInTheDocument();
  });

  it("renders cited bullets with their source and round-trips the citation", async () => {
    const cited = {
      ...DECK,
      slides: [
        {
          title: "Cited",
          bullets: [
            {
              text: "Corruption is a collective action problem",
              citation: {
                filename: "week1-notes.pdf",
                quote: "Corruption is a collective action problem",
                chunk_id: "c-1",
                section: "Section 2",
              },
            },
            { text: "No source on this one" },
            "A legacy string bullet",
            { bullet: "A bullet under the old key" },
            { text: "   " },
          ],
        },
      ],
    };
    pa.mockImplementation((path: string, init?: { method?: string; body?: string }) => {
      if (path === "/slides/deck-1" && !init?.method) return Promise.resolve(cited);
      if (path === "/slides/deck-1" && init?.method === "PUT") {
        return Promise.resolve({ ...cited, ...JSON.parse(init.body ?? "{}") });
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    renderPage();

    const citedBullet = await screen.findByText("Corruption is a collective action problem");
    expect(citedBullet).toBeInTheDocument();
    expect(screen.getByText(/source: week1-notes\.pdf/)).toHaveAttribute(
      "title",
      "Section 2 — Corruption is a collective action problem",
    );
    expect(screen.getByText("No source on this one")).toBeInTheDocument();
    expect(screen.getByText("A legacy string bullet")).toBeInTheDocument();
    expect(screen.getByText("A bullet under the old key")).toBeInTheDocument();
    expect(screen.queryByText("No bullets.")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Edit slide 1" }));
    expect(screen.getByLabelText("Slide 1 bullet 1")).toHaveValue(
      "Corruption is a collective action problem",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(callsTo("/slides/deck-1", "PUT")).toHaveLength(1));
    const body = JSON.parse(callsTo("/slides/deck-1", "PUT")[0]?.[1]?.body ?? "{}") as {
      slides: Array<{ bullets: unknown[] }>;
    };
    expect(body.slides[0]?.bullets).toEqual([
      {
        text: "Corruption is a collective action problem",
        citation: {
          filename: "week1-notes.pdf",
          quote: "Corruption is a collective action problem",
          section: "Section 2",
          chunk_id: "c-1",
        },
      },
      "No source on this one",
      "A legacy string bullet",
      "A bullet under the old key",
    ]);
  });

  it("drops a citation when the bullet text is edited", async () => {
    const cited = {
      ...DECK,
      slides: [
        {
          title: "Cited",
          bullets: [
            {
              text: "Original claim",
              citation: { filename: "notes.pdf", quote: "Original claim" },
            },
          ],
        },
      ],
    };
    pa.mockImplementation((path: string, init?: { method?: string; body?: string }) => {
      if (path === "/slides/deck-1" && !init?.method) return Promise.resolve(cited);
      if (path === "/slides/deck-1" && init?.method === "PUT") {
        return Promise.resolve({ ...cited, ...JSON.parse(init.body ?? "{}") });
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    renderPage();
    await screen.findByText("Original claim");
    fireEvent.click(screen.getByRole("button", { name: "Edit slide 1" }));
    fireEvent.change(screen.getByLabelText("Slide 1 bullet 1"), {
      target: { value: "Rewritten claim" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(callsTo("/slides/deck-1", "PUT")).toHaveLength(1));
    const body = JSON.parse(callsTo("/slides/deck-1", "PUT")[0]?.[1]?.body ?? "{}") as {
      slides: Array<{ bullets: unknown[] }>;
    };
    expect(body.slides[0]?.bullets).toEqual(["Rewritten claim"]);
  });

  it("keeps citations for untouched bullets when adding and removing", async () => {
    const cited = {
      ...DECK,
      slides: [
        {
          title: "Cited",
          bullets: [
            {
              text: "First claim",
              citation: { filename: "notes.pdf", quote: "First claim" },
            },
            {
              text: "Second claim",
              citation: { filename: "notes.pdf", quote: "Second claim" },
            },
          ],
        },
      ],
    };
    pa.mockImplementation((path: string, init?: { method?: string; body?: string }) => {
      if (path === "/slides/deck-1" && !init?.method) return Promise.resolve(cited);
      if (path === "/slides/deck-1" && init?.method === "PUT") {
        return Promise.resolve({ ...cited, ...JSON.parse(init.body ?? "{}") });
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    renderPage();
    await screen.findByText("First claim");
    fireEvent.click(screen.getByRole("button", { name: "Edit slide 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Add bullet" }));
    fireEvent.change(screen.getByLabelText("Slide 1 bullet 3"), {
      target: { value: "New point" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove slide 1 bullet 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(callsTo("/slides/deck-1", "PUT")).toHaveLength(1));
    const body = JSON.parse(callsTo("/slides/deck-1", "PUT")[0]?.[1]?.body ?? "{}") as {
      slides: Array<{ bullets: unknown[] }>;
    };
    expect(body.slides[0]?.bullets).toEqual([
      {
        text: "First claim",
        citation: { filename: "notes.pdf", quote: "First claim" },
      },
      "New point",
    ]);
  });

  it("renders speaker notes stored under the legacy notes key", async () => {
    pa.mockImplementation((path: string) => {
      if (path === "/slides/deck-1") {
        return Promise.resolve({
          ...DECK,
          slides: [{ title: "One", bullets: ["A point"], notes: "Legacy note." }],
        });
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    renderPage();

    expect(await screen.findByText(/Legacy note\./)).toBeInTheDocument();
  });

  it("sends a slide-scoped enhance request and applies the returned deck", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Week 1: Foundations" });

    fireEvent.click(screen.getByRole("button", { name: "Enhance slide 1" }));
    fireEvent.change(screen.getByLabelText("Change for slide 1"), {
      target: { value: "add a concrete example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enhance" }));

    await screen.findByText(/Added a concrete example\. Changed: slide 1\./);
    const body = JSON.parse(callsTo("/slides/deck-1/assist", "POST")[0]?.[1]?.body ?? "{}") as {
      message: string;
      slide_index: number;
    };
    expect(body).toEqual({ message: "add a concrete example", slide_index: 0 });
    expect(screen.getByText("A concrete example")).toBeInTheDocument();
  });

  it("becomes read-only after approval", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Week 1: Foundations" });

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Approved" })).toBeDisabled());
    expect(screen.queryByRole("button", { name: "Edit slide 1" })).toBeNull();
    expect(screen.getByText("approved and read-only", { exact: false })).toBeInTheDocument();
  });

  it("names a UUID-titled deck from its week and first slide", async () => {
    const uuid = "3f2a1b4c-9d8e-4f2a-8b6c-1d2e3f4a5b6c";
    pa.mockImplementation((path: string) => {
      if (path === "/slides/deck-1") return Promise.resolve({ ...DECK, title: uuid });
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    renderPage();

    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Week 1 \u2014 Why this matters");
    expect(heading).not.toHaveTextContent(uuid);

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Deck title")).toHaveValue("");
  });

  it("renders one landscape sheet per slide with a slide folio", async () => {
    const { container } = renderPage();

    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelectorAll(".pa-paper-page.is-landscape")).toHaveLength(2);
    expect(screen.getByText("Slide 1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Slide 2 of 2")).toBeInTheDocument();
  });

  it("reviews a deck and renders the advisory findings with a trace link", async () => {
    const review = {
      verdict: "revise",
      score: 55,
      issues: [
        {
          slide: "Why this matters",
          severity: "high",
          issue: "The bullet has no citation.",
          fix: "Cite the source filename.",
        },
      ],
      strengths: ["Clear slide titles."],
      checks: [],
      degraded: false,
    };
    let reviewed = false;
    pa.mockImplementation((path: string, init?: { method?: string }) => {
      if (path === "/slides/deck-1" && !init?.method) {
        return Promise.resolve(
          reviewed ? { ...DECK, review, review_trace_url: "http://trace/1" } : DECK,
        );
      }
      if (path === "/slides/deck-1/review" && init?.method === "POST") {
        reviewed = true;
        return Promise.resolve({ review, trace_url: "http://trace/1" });
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    renderPage();
    await screen.findByRole("heading", { name: "Week 1: Foundations" });
    expect(screen.getByText(/No review yet/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Review deck" }));

    const panel = await screen.findByRole("region", { name: "Deck review" });
    expect(await within(panel).findByText("Needs revision")).toBeInTheDocument();
    expect(within(panel).getByText("55/100")).toBeInTheDocument();
    expect(within(panel).getByText("Why this matters")).toBeInTheDocument();
    expect(within(panel).getByText("The bullet has no citation.")).toBeInTheDocument();
    expect(within(panel).getByText("Fix: Cite the source filename.")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Traced" })).toHaveAttribute(
      "href",
      "http://trace/1",
    );
  });
});
