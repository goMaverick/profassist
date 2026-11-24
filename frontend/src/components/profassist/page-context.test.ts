import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  getPageContext,
  resetPageContext,
  setPageContext,
  subscribe,
  usePageContext,
} from "@/components/profassist/page-context";

function clear() {
  setPageContext({
    page: "",
    title: "",
    outline_id: undefined,
    course_id: undefined,
    course_name: undefined,
    section: undefined,
    rubric_id: undefined,
  });
}

describe("page context store", () => {
  beforeEach(clear);

  it("starts empty", () => {
    expect(getPageContext()).toEqual({ page: "", title: "" });
  });

  it("merges later fields into earlier ones", () => {
    setPageContext({ page: "/outline", title: "Subject outline", course_id: "c-1" });
    setPageContext({ outline_id: "o-1", section: "Outcomes" });

    expect(getPageContext()).toMatchObject({
      page: "/outline",
      title: "Subject outline",
      course_id: "c-1",
      outline_id: "o-1",
      section: "Outcomes",
    });
  });

  it("notifies subscribers on change and stops after unsubscribe", () => {
    const listener = vi.fn();
    const off = subscribe(listener);

    setPageContext({ page: "/outline", title: "Subject outline" });
    expect(listener).toHaveBeenCalledTimes(1);

    off();
    setPageContext({ page: "/rubric", title: "Rubric builder" });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("does not notify when the context is unchanged", () => {
    setPageContext({ page: "/outline", title: "Subject outline" });
    const listener = vi.fn();
    const off = subscribe(listener);

    setPageContext({ page: "/outline", outline_id: undefined });
    expect(listener).not.toHaveBeenCalled();

    off();
  });

  it("reset moves to a new page and drops entity ids", () => {
    setPageContext({
      page: "/outline",
      title: "Subject outline",
      outline_id: "o-1",
      course_id: "c-1",
      course_name: "MAAI903",
      section: "Outcomes",
      rubric_id: "r-1",
    });

    resetPageContext("/rubric", "Rubric builder");

    expect(getPageContext()).toEqual({
      page: "/rubric",
      title: "Rubric builder",
      outline_id: undefined,
      course_id: undefined,
      course_name: undefined,
      section: undefined,
      rubric_id: undefined,
    });
  });

  it("reset keeps context the page already published for the same page", () => {
    // Pages publish from an effect that runs before the shell's pathname effect.
    setPageContext({ page: "/outline", title: "Subject outline", outline_id: "o-1", section: "Outcomes" });

    resetPageContext("/outline", "Subject outline");

    expect(getPageContext().outline_id).toBe("o-1");
    expect(getPageContext().section).toBe("Outcomes");
  });

  it("re-renders subscribers through usePageContext", () => {
    const { result } = renderHook(() => usePageContext());
    expect(result.current.page).toBe("");

    act(() => {
      setPageContext({ page: "/rubric", title: "Rubric builder", rubric_id: "r-1" });
    });

    expect(result.current.page).toBe("/rubric");
    expect(result.current.rubric_id).toBe("r-1");
  });
});
