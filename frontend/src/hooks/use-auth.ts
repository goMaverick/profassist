"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useAuthStore } from "@/stores";
import { apiClient, ApiError } from "@/lib/api-client";
import type { User, LoginRequest, RegisterRequest } from "@/types";
import { ROUTES } from "@/lib/constants";
import { isAppAdmin } from "@/lib/utils";

// Session-level singletons so /auth/me runs ONCE per page load no matter how
// many components mount useAuth(). Concurrent mounts share the in-flight
// promise; later mounts skip entirely (the store is persisted across the
// session). Reset on logout so the next login re-checks.
let authCheckPromise: Promise<void> | null = null;
let authChecked = false;

// Monotonic session generation. A /auth/me or /auth/refresh started before a
// login/logout belongs to an older session; when it settles it must not clobber
// the newer auth state. Without this, a stale /auth/me 401 landing right after
// login cleared the fresh user and the AuthGuard bounced back to /login.
let authEpoch = 0;

// Access tokens expire after 15 min. The in-memory token (used by the chat
// WebSocket and proxied API calls) is set once on load and would otherwise go
// stale while the tab stays open — causing WS auth failures / "Offline" chat.
// Refresh it ahead of expiry on a single shared interval. /auth/me
// transparently mints a fresh access token from the refresh cookie.
let tokenRefreshTimer: ReturnType<typeof setInterval> | null = null;
const TOKEN_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

function ensureTokenRefresh(): void {
  if (tokenRefreshTimer) return;
  tokenRefreshTimer = setInterval(() => {
    if (!useAuthStore.getState().isAuthenticated) return;
    void (async () => {
      try {
        const data = await apiClient.get<User & { access_token?: string }>("/auth/me");
        if (data.access_token) useAuthStore.getState().setAccessToken(data.access_token);
      } catch {
        // Ignore — the next real request (or its 401 → refresh) handles failure.
      }
    })();
  }, TOKEN_REFRESH_INTERVAL_MS);
}

function stopTokenRefresh(): void {
  if (tokenRefreshTimer) {
    clearInterval(tokenRefreshTimer);
    tokenRefreshTimer = null;
  }
}

function runAuthCheck(setUser: (u: User | null) => void): Promise<void> {
  if (authChecked) return Promise.resolve();
  if (authCheckPromise) return authCheckPromise;
  const epoch = authEpoch;
  authCheckPromise = (async () => {
    try {
      const data = await apiClient.get<User & { access_token?: string }>("/auth/me");
      if (epoch !== authEpoch) return; // superseded by login/logout - keep newer state
      const { access_token, ...userData } = data;
      setUser(userData as User);
      useAuthStore.getState().setAccessToken(access_token ?? null);
      authChecked = true;
    } catch (error) {
      if (epoch !== authEpoch) return; // stale 401 must not clear a newer session
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
        useAuthStore.getState().setAccessToken(null);
        authChecked = true;
      } else {
        throw error;
      }
    } finally {
      if (epoch === authEpoch) {
        authCheckPromise = null;
      }
    }
  })();
  return authCheckPromise;
}

export function useAuth() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading, setUser, setLoading, logout } = useAuthStore();

  const [sessionCheckFailed, setSessionCheckFailed] = useState(false);
  const checkSession = useCallback(async () => {
    setSessionCheckFailed(false);
    try {
      await runAuthCheck(setUser);
    } catch {
      setSessionCheckFailed(true);
    }
  }, [setUser]);

  useEffect(() => {
    void checkSession();
    ensureTokenRefresh();
  }, [checkSession]);

  const login = useCallback(
    async (credentials: LoginRequest) => {
      setLoading(true);
      try {
        const response = await apiClient.post<{
          user: User;
          access_token: string;
          message: string;
        }>("/auth/login", credentials);
        // Invalidate any /auth/me that started before this login so its stale
        // 401 (or user payload) can't overwrite this fresh session.
        authEpoch += 1;
        authCheckPromise = null;
        setUser(response.user);
        useAuthStore.getState().setAccessToken(response.access_token);
        authChecked = true; // login already populated user + token; skip /auth/me
        router.push(isAppAdmin(response.user) ? ROUTES.DASHBOARD : ROUTES.CHAT);
        return response;
      } finally {
        setLoading(false);
      }
    },
    [router, setUser, setLoading],
  );

  const register = useCallback(async (data: RegisterRequest) => {
    const response = await apiClient.post<{ id: string; email: string }>("/auth/register", data);
    return response;
  }, []);

  const handleLogout = useCallback(async () => {
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // Ignore logout errors
    } finally {
      authEpoch += 1; // invalidate in-flight checks/refreshes from the old session
      authChecked = false; // re-check on next login
      authCheckPromise = null;
      stopTokenRefresh();
      logout();
      toast.success("Logged out");
      router.push(ROUTES.LOGIN);
    }
  }, [logout, router]);

  const refreshToken = useCallback(async () => {
    const epoch = authEpoch;
    try {
      const refreshResponse = await apiClient.post<{ access_token: string; message: string }>(
        "/auth/refresh",
      );
      if (epoch !== authEpoch) return false;
      useAuthStore.getState().setAccessToken(refreshResponse.access_token);
      const userData = await apiClient.get<User>("/auth/me");
      if (epoch !== authEpoch) return false;
      setUser(userData);
      return true;
    } catch (error) {
      if (epoch !== authEpoch) return false; // a newer login owns auth state now
      if (error instanceof ApiError && error.status === 401) {
        logout();
        router.push(ROUTES.LOGIN);
      }
      return false;
    }
  }, [logout, router, setUser]);

  return {
    user,
    isAuthenticated,
    isLoading,
    sessionCheckFailed,
    checkSession,
    login,
    register,
    logout: handleLogout,
    refreshToken,
  };
}
