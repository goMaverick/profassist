import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { User } from "@/types";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: mocks.push }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Minimal functional store so the hook mutates auth state for real.
vi.mock("@/stores", async () => {
  const { create } = await import("zustand");
  const useAuthStore = create<{
    user: User | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    accessToken: string | null;
    setUser: (user: User | null) => void;
    setLoading: (loading: boolean) => void;
    setAccessToken: (token: string | null) => void;
    logout: () => void;
  }>()((set) => ({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    accessToken: null,
    setUser: (user) => set({ user, isAuthenticated: user !== null, isLoading: false }),
    setLoading: (isLoading) => set({ isLoading }),
    setAccessToken: (accessToken) => set({ accessToken }),
    logout: () => set({ user: null, isAuthenticated: false, isLoading: false, accessToken: null }),
  }));
  return { useAuthStore };
});

vi.mock("@/lib/api-client", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message);
      this.name = "ApiError";
    }
  }
  return { ApiError, apiClient: { get: mocks.get, post: mocks.post } };
});

const LOGIN_USER: User = {
  id: "prof-1",
  email: "prof@uowd.edu",
  is_active: true,
  created_at: "2026-01-01T00:00:00.000Z",
};

describe("useAuth auth-check race", () => {
  beforeEach(() => {
    vi.resetModules(); // fresh module-level authChecked/authEpoch per test
    vi.clearAllMocks();
  });

  it("keeps the freshly logged-in user when an older /auth/me check resolves 401", async () => {
    const { useAuthStore } = await import("@/stores");
    const { useAuth } = await import("./use-auth");

    let rejectStaleCheck!: (error: unknown) => void;
    const staleCheck = new Promise<never>((_, reject) => {
      rejectStaleCheck = reject;
    });

    mocks.get.mockImplementation((endpoint: string) =>
      endpoint === "/auth/me" ? staleCheck : Promise.resolve(null),
    );
    mocks.post.mockResolvedValue({ user: LOGIN_USER, access_token: "token-1", message: "ok" });

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/auth/me"));

    // Login wins the race: the store now holds the authenticated user.
    await act(async () => {
      await result.current.login({ email: LOGIN_USER.email, password: "secret" });
    });
    expect(useAuthStore.getState().user).toEqual(LOGIN_USER);

    // The check that started before login now 401s.
    await act(async () => {
      rejectStaleCheck(new Error("401"));
      await staleCheck.catch(() => undefined);
    });

    expect(useAuthStore.getState().user).toEqual(LOGIN_USER);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);

    // Stop the shared token-refresh interval started by the mount effect.
    await act(async () => {
      await result.current.logout();
    });
  });

  it("ignores a stale refresh 401 instead of logging out a newer session", async () => {
    const { useAuthStore } = await import("@/stores");
    const { ApiError } = await import("@/lib/api-client");
    const { useAuth } = await import("./use-auth");

    let rejectRefresh!: (error: unknown) => void;
    const failedRefresh = new Promise<never>((_, reject) => {
      rejectRefresh = reject;
    });

    mocks.get.mockRejectedValue(new Error("401"));
    mocks.post.mockImplementation((endpoint: string) => {
      if (endpoint === "/auth/refresh") return failedRefresh;
      if (endpoint === "/auth/login") {
        return Promise.resolve({ user: LOGIN_USER, access_token: "token-1", message: "ok" });
      }
      return Promise.resolve(null);
    });

    const { result } = renderHook(() => useAuth());
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/auth/me"));

    let refresh!: Promise<boolean>;
    act(() => {
      refresh = result.current.refreshToken(); // starts before login
    });
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/auth/refresh"));

    await act(async () => {
      await result.current.login({ email: LOGIN_USER.email, password: "secret" });
    });
    expect(useAuthStore.getState().user).toEqual(LOGIN_USER);

    let refreshResult: boolean | undefined;
    await act(async () => {
      rejectRefresh(new ApiError(401, "unauthorized"));
      refreshResult = await refresh;
    });

    expect(refreshResult).toBe(false);
    expect(useAuthStore.getState().user).toEqual(LOGIN_USER);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(mocks.push).not.toHaveBeenCalledWith("/login");

    await act(async () => {
      await result.current.logout();
    });
  });
});
