"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import * as authApi from "@/lib/api/auth";
import { API_BASE_URL } from "@/lib/api/client";
import { tokenStorage } from "@/lib/auth/token-storage";
import { ApiError } from "@/lib/errors";
import type { UserPublic } from "@/lib/types/api";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  user: UserPublic | null;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const router = useRouter();

  // On app boot with a stored token, validate it's still good before
  // rendering anything role-gated (spec §3.1 point 4).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = tokenStorage.getAccessToken();
      if (!token) {
        if (!cancelled) setStatus("unauthenticated");
        return;
      }
      try {
        const me = await authApi.getMe();
        if (!cancelled) {
          setUser(me);
          setStatus("authenticated");
        }
      } catch (err) {
        // A network-level failure (lib/api/client.ts's ApiError with
        // status 0 - the refresh fetch itself never completed, not the
        // server rejecting the refresh token) does NOT mean the stored
        // tokens are actually bad - don't destroy a possibly-still-valid
        // session over what could be a momentary connectivity blip on
        // page load. Any other failure genuinely does mean the session is
        // over (and if it came from a real invalid-refresh-token 401,
        // lib/api/client.ts already ran tokenStorage.forceLogout() before
        // this ever threw - clearing again here is just a safe fallback
        // for any other kind of failure).
        if (!(err instanceof ApiError && err.status === 0)) {
          tokenStorage.clear();
        }
        if (!cancelled) {
          setUser(null);
          setStatus("unauthenticated");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Fired by the fetch client when a 401's refresh attempt also fails -
  // the only reliable "the session is really over" signal (spec §3.7).
  useEffect(() => {
    return tokenStorage.onLogout(() => {
      setUser(null);
      setStatus("unauthenticated");
      router.replace("/login");
    });
  }, [router]);

  // Best-effort: revoke the refresh token server-side on tab close too, not
  // just on an explicit logout click (spec §3.1 point 3). `keepalive` lets
  // the request survive page teardown; this is best-effort by nature (the
  // browser can still drop it), not something to block on.
  useEffect(() => {
    const handleUnload = () => {
      const refreshToken = tokenStorage.getRefreshToken();
      if (!refreshToken) return;
      fetch(`${API_BASE_URL}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
        keepalive: true,
      }).catch(() => {});
    };
    window.addEventListener("pagehide", handleUnload);
    return () => window.removeEventListener("pagehide", handleUnload);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await authApi.login(email, password);
    tokenStorage.setTokens(tokens.access_token, tokens.refresh_token);
    const me = await authApi.getMe();
    setUser(me);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    const refreshToken = tokenStorage.getRefreshToken();
    try {
      if (refreshToken) await authApi.logout(refreshToken);
    } catch {
      // Best-effort - the local session ends regardless (spec §3.1 point 3).
    }
    tokenStorage.clear();
    setUser(null);
    setStatus("unauthenticated");
    router.replace("/login");
  }, [router]);

  return <AuthContext.Provider value={{ user, status, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
