/**
 * Convert any backend error payload into a human-readable string.
 *
 * The API does not use a single error envelope:
 *   - `{ "detail": "text" }`                              plain FastAPI detail
 *   - `{ "detail": { "error": { "message": "text" } } }`  rate limits / HTTPException
 *   - `{ "detail": { "message": "text" } }`
 *   - `{ "detail": [{ "msg": "text" }] }`                 FastAPI 422 validation errors
 *   - `{ "error": { "message": "text" } }`                AppException handler
 *   - `{ "message": "text" }`
 *
 * Always returns a string: the result is rendered directly in JSX, and passing
 * an object through `Error.message` crashes React with "Objects are not valid
 * as a React child".
 */
export function normalizeErrorMessage(payload: unknown, status?: number): string {
  const fallback = status === undefined ? "Request failed" : `Request failed (${status})`;

  if (typeof payload === "string") {
    return payload.trim() || fallback;
  }
  if (!payload || typeof payload !== "object") {
    return fallback;
  }

  const root = payload as Record<string, unknown>;

  // 1. `{ detail: ... }` - the most common shape.
  const detail = root.detail;
  if (typeof detail === "string") {
    if (detail.trim()) return detail;
  } else if (Array.isArray(detail)) {
    // FastAPI validation errors: [{ loc, msg, type }]
    const messages = detail
      .map((item) =>
        item && typeof item === "object" ? (item as Record<string, unknown>).msg : undefined,
      )
      .filter((msg): msg is string => typeof msg === "string" && msg.trim().length > 0);
    if (messages.length) return messages.join("; ");
  } else if (detail && typeof detail === "object") {
    const nested = messageFromObject(detail as Record<string, unknown>);
    if (nested) return nested;
  }

  // 2. top-level `{ error: { message } }` or `{ message }`.
  const direct = messageFromObject(root);
  if (direct) return direct;

  return fallback;
}

/** Pull `error.message`, `message`, or a plain string `error` out of an object. */
function messageFromObject(obj: Record<string, unknown>): string | null {
  const error = obj.error;
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  if (error && typeof error === "object") {
    const message = (error as Record<string, unknown>).message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }
  if (typeof obj.message === "string" && obj.message.trim()) {
    return obj.message;
  }
  return null;
}
