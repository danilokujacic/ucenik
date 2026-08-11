import { apiFetch } from "@/lib/api/client";
import type { AccessTokenResponse, TokenResponse, UserPublic, WsTicketResponse } from "@/lib/types/api";

export function login(email: string, password: string) {
  return apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
    skipAuth: true,
  });
}

export function refresh(refreshToken: string) {
  return apiFetch<AccessTokenResponse>("/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
    skipAuth: true,
  });
}

export function logout(refreshToken: string) {
  return apiFetch<void>("/auth/logout", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
}

export function getMe() {
  return apiFetch<UserPublic>("/auth/me");
}

/** Exchanges the real (Authorization-header) access token for a short-lived,
 * single-use ticket - see lib/planner/use-planner-socket.ts, backend
 * services/ws_tickets.py. */
export function requestWsTicket() {
  return apiFetch<WsTicketResponse>("/auth/ws-ticket", { method: "POST" });
}
