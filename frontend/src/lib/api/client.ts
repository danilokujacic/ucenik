import { tokenStorage } from "@/lib/auth/token-storage";
import { ApiError, type FieldError } from "@/lib/errors";
import type { AccessTokenResponse } from "@/lib/types/api";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? API_BASE_URL.replace(/^http/, "ws");

// A single in-flight refresh is shared across concurrent 401s so a burst of
// requests whose access token just expired doesn't fire N refresh calls.
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const refreshToken = tokenStorage.getRefreshToken();
    if (!refreshToken) return null;

    try {
      const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return null;
      const data: AccessTokenResponse = await res.json();
      tokenStorage.setTokens(data.access_token);
      return data.access_token;
    } catch {
      return null;
    }
  })();

  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

/** Exposed so a long-lived connection (Planner WS) can proactively get a
 * fresh token before connecting rather than reacting to a failure. */
export async function ensureFreshAccessToken(): Promise<string | null> {
  const current = tokenStorage.getAccessToken();
  if (current) return current;
  return refreshAccessToken();
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown; // JSON-serialized unless it's already FormData
  skipAuth?: boolean; // /auth/login, /auth/refresh
  isRetry?: boolean; // internal: prevents infinite refresh loops
}

async function buildError(res: Response): Promise<ApiError> {
  const retryAfterHeader = res.headers.get("Retry-After");
  const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : null;

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // no body / not JSON - fall through with a generic message
  }

  if (res.status === 422 && body && typeof body === "object" && Array.isArray((body as { detail?: unknown }).detail)) {
    const fieldErrors = (body as { detail: FieldError[] }).detail;
    return new ApiError(422, fieldErrors[0]?.msg ?? "Validation failed", fieldErrors, retryAfter);
  }

  const detail =
    body && typeof body === "object" && typeof (body as { detail?: unknown }).detail === "string"
      ? (body as { detail: string }).detail
      : res.statusText || "Request failed";

  return new ApiError(res.status, detail, null, retryAfter);
}

/** Low-level: performs one authorized request, transparently refreshing and
 * retrying once on 401 (spec §1/§3.7), returns the raw Response so callers
 * that need a stream (SSE) or a blob (document download) aren't forced
 * through JSON parsing. Throws ApiError on any other non-2xx status. */
export async function authorizedRequest(path: string, options: RequestOptions = {}): Promise<Response> {
  const { body, skipAuth, isRetry, headers, ...rest } = options;

  const finalHeaders = new Headers(headers);
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;

  if (body !== undefined && !isFormData) {
    finalHeaders.set("Content-Type", "application/json");
  }

  if (!skipAuth) {
    const token = tokenStorage.getAccessToken();
    if (token) finalHeaders.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: body === undefined ? undefined : isFormData ? (body as FormData) : JSON.stringify(body),
  });

  if (res.status === 401 && !skipAuth && !isRetry) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      return authorizedRequest(path, { ...options, isRetry: true });
    }
    tokenStorage.forceLogout();
    throw new ApiError(401, "Session expired. Please log in again.");
  }

  if (!res.ok) {
    throw await buildError(res);
  }

  return res;
}

/** High-level: parses the JSON body. Use for every plain REST call. */
export async function apiFetch<T>(path: string, options?: RequestOptions): Promise<T> {
  const res = await authorizedRequest(path, options);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function apiFetchBlob(path: string, options?: RequestOptions): Promise<Blob> {
  const res = await authorizedRequest(path, options);
  return res.blob();
}
