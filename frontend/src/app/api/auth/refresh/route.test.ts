import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";
import { backendFetch, BackendApiError } from "@/lib/server-api";
import { POST } from "./route";

vi.mock("@/lib/server-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/server-api")>()),
  backendFetch: vi.fn(),
}));

function refreshRequest() {
  return new NextRequest("http://localhost/api/auth/refresh", {
    method: "POST",
    headers: { cookie: "refresh_token=current-token" },
  });
}

describe("refresh session", () => {
  it("retains refresh cookies when the backend is temporarily unavailable", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(new BackendApiError(503, "Unavailable"));
    const response = await POST(refreshRequest());
    expect(response.status).toBe(503);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("sets the rotated refresh cookie for 14 days", async () => {
    vi.mocked(backendFetch).mockResolvedValueOnce({
      access_token: "access-token",
      refresh_token: "rotated-token",
    });
    const response = await POST(refreshRequest());
    expect(response.status).toBe(200);
    expect(response.cookies.get("refresh_token")).toMatchObject({
      value: "rotated-token",
      httpOnly: true,
      maxAge: 14 * 24 * 60 * 60,
    });
  });
});
