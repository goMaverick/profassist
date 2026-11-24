"use client";

import { useSyncExternalStore } from "react";

export interface PageContext {
  page: string;
  title: string;
  outline_id?: string;
  course_id?: string;
  course_name?: string;
  section?: string;
  rubric_id?: string;
}

const EMPTY: PageContext = { page: "", title: "" };

let snapshot: PageContext = EMPTY;
const listeners = new Set<() => void>();

function same(a: PageContext, b: PageContext): boolean {
  return (
    a.page === b.page &&
    a.title === b.title &&
    a.outline_id === b.outline_id &&
    a.course_id === b.course_id &&
    a.course_name === b.course_name &&
    a.section === b.section &&
    a.rubric_id === b.rubric_id
  );
}

function emit(next: PageContext) {
  if (same(snapshot, next)) return;
  snapshot = next;
  listeners.forEach((listener) => listener());
}

/** Current context for non-React callers such as the chat transport. */
export function getPageContext(): PageContext {
  return snapshot;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Merge `next` into the current context and notify subscribers.
 * Passing `undefined` for a field clears it.
 */
export function setPageContext(next: Partial<PageContext>): PageContext {
  emit({ ...snapshot, ...next });
  return snapshot;
}

/**
 * Start a new page. Entity ids (outline, course, rubric, section) belong to the
 * page that published them, so they are dropped. When the page is unchanged the
 * ids are kept: pages publish them from an effect that runs before the shell's
 * pathname effect, and the shell must not wipe context for the page it is on.
 */
export function resetPageContext(page: string, title: string): PageContext {
  if (snapshot.page === page) {
    setPageContext({ title });
    return snapshot;
  }
  setPageContext({
    page,
    title,
    outline_id: undefined,
    course_id: undefined,
    course_name: undefined,
    section: undefined,
    rubric_id: undefined,
  });
  return snapshot;
}

export function usePageContext(): PageContext {
  return useSyncExternalStore(subscribe, getPageContext, getPageContext);
}
