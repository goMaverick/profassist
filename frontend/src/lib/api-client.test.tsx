import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ApiError, apiClient } from "./api-client";
import { normalizeErrorMessage } from "./error-message";

// The real store pulls in every zustand slice; the client only needs setAccessToken.
vi.mock("@/stores", () => ({
  useAuthStore: {
    getState: () => ({ setAccessToken: vi.fn() }),
  },
}));

const rateLimitBody = {
  detail: {
    error: {
      code: "RATE_LIMIT_EXCEEDED",
      message: "Rate limit exceeded. Retry after 30 seconds.",
      details: { retry_after_seconds: 30 },
    },
  },
};

function errorResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return {
    ok: false,
    status,
    headers: {
      get: (name: string) => headers[name] ?? headers[name.toLowerCase()] ?? null,
    },
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

describe("normalizeErrorMessage", () => {
  it("extracts detail.error.message", () => {
    expect(normalizeErrorMessage(rateLimitBody, 429)).toBe(
      "Rate limit exceeded. Retry after 30 seconds.",
    );
  });

  it("extracts a plain string detail", () => {
    expect(normalizeErrorMessage({ detail: "Invalid email or password" }, 401)).toBe(
      "Invalid email or password",
    );
  });

  it("extracts detail.message", () => {
    expect(normalizeErrorMessage({ detail: { message: "Nope" } }, 400)).toBe("Nope");
  });

  it("extracts a top-level error.message", () => {
    expect(
      normalizeErrorMessage(
        { error: { code: "AUTHENTICATION_ERROR", message: "Invalid email or password" } },
        401,
      ),
    ).toBe("Invalid email or password");
  });

  it("always falls back to a readable string that includes the status", () => {
    expect(normalizeErrorMessage(null, 500)).toBe("Request failed (500)");
    expect(typeof normalizeErrorMessage({ detail: { error: {} } }, 502)).toBe("string");
  });
});

describe("ApiClient error handling", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("throws an ApiError with a string message and Retry-After for a 429 envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(errorResponse(429, rateLimitBody, { "Retry-After": "30" })),
    );

    const error = await apiClient.get("/demo").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(429);
    expect(typeof apiError.message).toBe("string");
    expect(apiError.message).toBe("Rate limit exceeded. Retry after 30 seconds.");
    expect(apiError.retryAfter).toBe(30);

    // Would throw "Objects are not valid as a React child" if message stayed an object.
    render(<p>{apiError.message}</p>);
    expect(screen.getByText(/Rate limit exceeded/)).toBeInTheDocument();
  });
});
