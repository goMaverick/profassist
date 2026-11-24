import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CollabRole } from "@/lib/profassist";

const { paMock } = vi.hoisted(() => ({ paMock: vi.fn() }));

vi.mock("@/lib/profassist", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/profassist")>();
  return { ...actual, pa: paMock };
});

import {
  applyCollabEvent,
  initialCollabState,
  StudioCollab,
  type CollabState,
} from "./studio-collab";

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }

  fail() {
    this.onerror?.();
  }
}

function renderCollab(onDone = vi.fn(), onCancel = vi.fn()) {
  return render(
    <StudioCollab
      courseId="course-1"
      week={1}
      instructions="Draft the week 1 deck."
      onDone={onDone}
      onCancel={onCancel}
    />,
  );
}

beforeEach(() => {
  vi.stubGlobal("EventSource", MockEventSource);
  MockEventSource.instances = [];
  paMock.mockReset();
  paMock.mockImplementation((path: string, init?: { method?: string }) => {
    if (path === "/courses/course-1/slides/collaborate" && init?.method === "POST") {
      return Promise.resolve({ job_id: "job-1" });
    }
    if (path === "/slides/collaborate/job-1/pause" && init?.method === "POST") {
      return Promise.resolve({ paused: true });
    }
    return Promise.reject(new Error(`Unexpected request: ${path}`));
  });
});

describe("StudioCollab", () => {
  it("runs creator, curriculum, evidence, design, and chair from start through pause to the final deck", async () => {
    const onDone = vi.fn();
    const { unmount } = renderCollab(onDone);

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0]!;
    expect(source.url).toBe("/api/profassist/slides/collaborate/job-1/stream");

    await act(async () => {
      source.emit({ type: "start", creator: "Creator", reviewer: "Chair" });
    });
    expect(screen.getByText("Working")).toBeInTheDocument();
    expect(screen.getByText("Creator \u2194 Council")).toBeInTheDocument();
    // The roster is not known until the review reports it.
    expect(screen.getByText("Council")).toBeInTheDocument();
    expect(screen.queryByText("5 agents")).toBeNull();
    expect(
      screen.getByText(/the enabled reviewers each check a different angle/),
    ).toBeInTheDocument();
    expect(screen.getByText("Round 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pause & keep this draft/ })).toBeEnabled();

    await act(async () => {
      source.emit({ type: "typing", role: "creator" });
    });
    expect(screen.getByText(/Creator is typing/)).toBeInTheDocument();
    await act(async () => {
      source.emit({
        type: "message",
        role: "creator",
        text: "Drafted six slides from the week 1 notes.",
        kind: "draft",
      });
    });
    expect(screen.getByText("Creator")).toBeInTheDocument();
    expect(screen.getByText("Drafted six slides from the week 1 notes.")).toBeInTheDocument();
    expect(screen.getByText("draft")).toBeInTheDocument();
    expect(screen.queryByText(/Creator is typing/)).toBeNull();

    await act(async () => {
      source.emit({ type: "typing", role: "curriculum" });
    });
    expect(screen.getByText(/Curriculum is typing/)).toBeInTheDocument();
    await act(async () => {
      source.emit({
        type: "message",
        role: "curriculum",
        text: "The deck covers CLO 1 and CLO 2 in order.",
        severity: "medium",
      });
    });
    expect(screen.getByText("Curriculum")).toBeInTheDocument();
    expect(screen.getByText("The deck covers CLO 1 and CLO 2 in order.")).toBeInTheDocument();
    expect(screen.getByText("Medium")).toBeInTheDocument();

    await act(async () => {
      source.emit({ type: "typing", role: "evidence" });
    });
    expect(screen.getByText(/Evidence is typing/)).toBeInTheDocument();
    await act(async () => {
      source.emit({
        type: "message",
        role: "evidence",
        text: "One claim is not in the lecture notes.",
        severity: "high",
      });
    });
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText("One claim is not in the lecture notes.")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();

    await act(async () => {
      source.emit({ type: "typing", role: "design" });
    });
    expect(screen.getByText(/Design is typing/)).toBeInTheDocument();
    await act(async () => {
      source.emit({
        type: "message",
        role: "design",
        text: "Slide 4 is text heavy; split it into two.",
        severity: "low",
      });
    });
    expect(screen.getByText("Design")).toBeInTheDocument();
    expect(screen.getByText("Slide 4 is text heavy; split it into two.")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();

    await act(async () => {
      source.emit({ type: "typing", role: "chair" });
    });
    expect(screen.getByText(/Chair is typing/)).toBeInTheDocument();
    await act(async () => {
      source.emit({
        type: "message",
        role: "chair",
        text: "Two bullets need citations before this ships.",
        verdict: "revise",
        score: 74,
        issues: [{ slide: 2, issue: "Missing citation" }],
      });
    });
    expect(screen.getByText("Chair")).toBeInTheDocument();
    expect(screen.getByText("Needs revision")).toBeInTheDocument();
    expect(screen.getByText("74/100")).toBeInTheDocument();
    expect(screen.getByText(/Slide 2: Missing citation/)).toBeInTheDocument();
    expect(screen.getByText("Round 2")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Pause & keep this draft/ }));
    });
    await waitFor(() =>
      expect(paMock).toHaveBeenCalledWith("/slides/collaborate/job-1/pause", {
        method: "POST",
      }),
    );
    expect(await screen.findByText(/The chair will not start a new pass/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pause & keep this draft/ })).toBeNull();

    const deck = {
      id: "deck-9",
      title: "Week 1: Foundations",
      week: 1,
      slides: [],
      review: { verdict: "revise", score: 74 },
    };
    await act(async () => {
      source.emit({
        type: "final",
        deck,
        review: {
          verdict: "revise",
          score: 74,
          roles: ["curriculum", "evidence", "design", "chair"],
        },
        paused: true,
        trace_url: "http://trace/9",
      });
    });

    expect(await screen.findByText("Deck ready")).toBeInTheDocument();
    // Creator plus the four enabled seats.
    expect(screen.getByText("5 agents")).toBeInTheDocument();
    expect(screen.getByText("Week 1: Foundations")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open deck" })).toHaveAttribute(
      "href",
      "/studio/deck/deck-9",
    );
    expect(screen.getByRole("link", { name: "View trace" })).toHaveAttribute(
      "href",
      "http://trace/9",
    );
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledWith(deck);

    unmount();
    expect(source.closed).toBe(true);
  });

  it("counts only the reviewers the saved roster left enabled", async () => {
    renderCollab();

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0]!;

    await act(async () => {
      source.emit({ type: "start", creator: "Creator", reviewer: "Chair" });
    });
    await act(async () => {
      source.emit({
        type: "message",
        role: "creator",
        text: "Drafted four slides for week 4.",
      });
    });
    await act(async () => {
      source.emit({
        type: "message",
        role: "chair",
        text: "Passed with the design seat off.",
        verdict: "pass",
        score: 90,
      });
    });
    await act(async () => {
      source.emit({
        type: "final",
        deck: { id: "deck-4", title: "Week 4: Review", week: 4 },
        review: { verdict: "pass", score: 90, roles: ["curriculum", "evidence", "chair"] },
        paused: false,
      });
    });

    expect(await screen.findByText("Deck ready")).toBeInTheDocument();
    // Creator + curriculum + evidence + chair: design was disabled.
    expect(screen.getByText("4 agents")).toBeInTheDocument();
    const description = screen.getByText(/drafts the deck/);
    expect(description).toHaveTextContent("the enabled reviewers");
    expect(description.textContent ?? "").not.toContain("curriculum, evidence, and design");
    expect(screen.queryByText("5 agents")).toBeNull();
  });

  it("seeds the transcript from review.messages when the stream skipped live turns", async () => {
    const onDone = vi.fn();
    renderCollab(onDone);

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0]!;

    await act(async () => {
      source.emit({ type: "start", creator: "Creator", reviewer: "Chair" });
    });

    const review = {
      verdict: "pass",
      score: 91,
      messages: [
        { role: "creator", text: "Drafted five slides for week 3." },
        { role: "curriculum", text: "Aligned with CLO 2.", severity: "low" },
        { role: "evidence", text: "Two citations were stale.", severity: "high" },
        { role: "design", text: "Slide 4 was too dense.", severity: "medium" },
        {
          role: "chair",
          text: "Approved after the fixes.",
          verdict: "pass",
          score: 91,
        },
      ],
    };
    const deck = {
      id: "deck-7",
      title: "Week 3: Evidence",
      week: 3,
      slides: [],
      review,
    };

    await act(async () => {
      source.emit({ type: "final", deck, review, paused: false, trace_url: "http://trace/7" });
    });

    expect(await screen.findByText("Deck ready")).toBeInTheDocument();
    expect(screen.getByText("Drafted five slides for week 3.")).toBeInTheDocument();
    expect(screen.getByText("Aligned with CLO 2.")).toBeInTheDocument();
    expect(screen.getByText("Two citations were stale.")).toBeInTheDocument();
    expect(screen.getByText("Slide 4 was too dense.")).toBeInTheDocument();
    expect(screen.getByText("Approved after the fixes.")).toBeInTheDocument();
    expect(screen.getByText("Curriculum")).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText("Design")).toBeInTheDocument();
    expect(screen.getByText("Chair")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText("Medium")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();
    expect(screen.getAllByText("Passed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("91/100").length).toBeGreaterThan(0);
    expect(screen.getByText("Round 2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open deck" })).toHaveAttribute(
      "href",
      "/studio/deck/deck-7",
    );
    expect(screen.getByRole("link", { name: "View trace" })).toHaveAttribute(
      "href",
      "http://trace/7",
    );
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledWith(deck);
  });

  it("keeps the paused note and the final link together until Close", async () => {
    const onDone = vi.fn();
    const onCancel = vi.fn();
    renderCollab(onDone, onCancel);

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0]!;

    await act(async () => {
      source.emit({ type: "start", creator: "Creator", reviewer: "Chair" });
    });
    await act(async () => {
      source.emit({
        type: "message",
        role: "creator",
        text: "Paused. I am keeping the current draft as-is.",
      });
    });
    await act(async () => {
      source.emit({
        type: "final",
        deck: { id: "deck-3", title: "Week 2: Retrieval", week: 2 },
        review: { verdict: "revise", score: 40 },
        paused: true,
      });
    });

    expect(await screen.findByText("Deck ready")).toBeInTheDocument();
    expect(screen.getByText(/The chair will not start a new pass/)).toBeInTheDocument();
    expect(screen.getByText("Paused. I am keeping the current draft as-is.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open deck" })).toHaveAttribute(
      "href",
      "/studio/deck/deck-3",
    );
    expect(onDone).toHaveBeenCalledTimes(1);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
    });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("shows an honest error with retry when the stream fails", async () => {
    renderCollab();

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0]!;

    await act(async () => {
      source.fail();
    });

    expect(
      await screen.findByText(/The live collaboration stream ended before the deck was ready/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    });
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(2));
  });

  it("closes the EventSource when unmounted mid-stream", async () => {
    const { unmount } = renderCollab();
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0]!;
    unmount();
    expect(source.closed).toBe(true);
  });
});

describe("applyCollabEvent", () => {
  it("accepts every council role and carries severity", () => {
    const roles: CollabRole[] = [
      "creator",
      "curriculum",
      "evidence",
      "design",
      "chair",
      "reviewer",
    ];
    let state = initialCollabState();
    for (const role of roles) {
      state = applyCollabEvent(state, { type: "typing", role });
      expect(state.typing).toBe(role);
      state = applyCollabEvent(state, {
        type: "message",
        role,
        text: `${role} turn`,
        severity: "high",
      });
      const last = state.messages[state.messages.length - 1];
      expect(last?.role).toBe(role);
      expect(last?.severity).toBe("high");
    }
    expect(state.messages).toHaveLength(6);
  });

  it("seeds review.messages on final when no live turns arrived", () => {
    const state = applyCollabEvent(initialCollabState(), {
      type: "final",
      deck: { id: "deck-1", title: "Week 1" },
      review: {
        verdict: "pass",
        score: 90,
        messages: [
          { role: "reviewer", text: "Legacy chair turn", severity: "low" },
          { role: "design", text: "Tighten slide 2", severity: "high" },
        ],
      },
    });
    expect(state.status).toBe("done");
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]).toMatchObject({
      role: "reviewer",
      text: "Legacy chair turn",
      severity: "low",
    });
    expect(state.messages[1]).toMatchObject({
      role: "design",
      text: "Tighten slide 2",
      severity: "high",
    });
  });

  it("does not overwrite live messages with review.messages", () => {
    let state = applyCollabEvent(initialCollabState(), {
      type: "message",
      role: "creator",
      text: "Live turn",
    });
    state = applyCollabEvent(state, {
      type: "final",
      deck: { id: "deck-1", title: "Week 1" },
      review: {
        verdict: "pass",
        score: 80,
        messages: [{ role: "chair", text: "Seeded turn" }],
      },
    });
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]?.text).toBe("Live turn");
  });

  it("keeps the deck and ignores late typing or errors once finished", () => {
    const done = applyCollabEvent(initialCollabState(), {
      type: "final",
      deck: { id: "deck-1", title: "Week 1" },
      review: { verdict: "pass", score: 91 },
      paused: false,
      trace_url: "http://trace/1",
    });
    expect(done.status).toBe("done");
    expect(done.deck?.id).toBe("deck-1");
    expect(done.review?.score).toBe(91);
    expect(done.traceUrl).toBe("http://trace/1");

    const state: CollabState = done;
    expect(applyCollabEvent(state, { type: "typing", role: "creator" })).toBe(state);
    expect(applyCollabEvent(state, { type: "error", text: "late" })).toBe(state);
  });

  it("keeps an existing error when a late final event arrives", () => {
    let state = applyCollabEvent(initialCollabState(), {
      type: "error",
      text: "The vector store went away.",
    });
    expect(state.status).toBe("error");

    state = applyCollabEvent(state, {
      type: "final",
      deck: { id: "deck-1", title: "Week 1" },
      paused: false,
    });
    expect(state.status).toBe("error");
    expect(state.error).toBe("The vector store went away.");
    expect(state.deck).toBeNull();
  });

  it("marks a paused draft without dropping earlier messages", () => {
    let state = applyCollabEvent(initialCollabState(), {
      type: "message",
      role: "creator",
      text: "First pass.",
    });
    state = applyCollabEvent(state, { type: "typing", role: "creator" });
    state = applyCollabEvent(state, { type: "paused" });
    expect(state.status).toBe("paused");
    expect(state.paused).toBe(true);
    expect(state.typing).toBeNull();
    expect(state.messages).toHaveLength(1);
  });

  it("ignores malformed messages and unknown events", () => {
    const state = initialCollabState();
    expect(applyCollabEvent(state, { type: "message", text: "No role" })).toBe(state);
    expect(applyCollabEvent(state, { type: "message", role: "creator" })).toBe(state);
    expect(applyCollabEvent(state, { type: "mystery" })).toBe(state);
  });
});
