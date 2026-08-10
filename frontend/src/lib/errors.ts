/** FastAPI's own validation-layer shape - only ever seen on 422 (spec §4's note). */
export interface FieldError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/**
 * Normalized shape every failed request throws as, whether the body was the
 * app's flat `{"detail": "<message>"}` or FastAPI's 422 field-error list.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly fieldErrors: FieldError[] | null;
  readonly retryAfter: number | null;

  constructor(status: number, detail: string, fieldErrors: FieldError[] | null = null, retryAfter: number | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.fieldErrors = fieldErrors;
    this.retryAfter = retryAfter;
  }
}

/** A 429 can mean either the per-IP login rate limit or the daily token
 * quota - same status code, different copy (spec §3.7). Pass "quota" for
 * chat/planner endpoints (the only ones that can quota-429), "rate-limit"
 * everywhere else (login is the main one, per spec §3.1). */
export type RateLimitKind = "rate-limit" | "quota";

export function describeError(error: unknown, rateLimitKind: RateLimitKind = "rate-limit"): string {
  if (!(error instanceof ApiError)) {
    return "Something went wrong. Please try again.";
  }

  switch (error.status) {
    case 401:
      return "Invalid email or password.";
    case 403:
      return "You don't have permission to do that.";
    case 404:
      return "Not found.";
    case 409:
      return error.detail || "That conflicts with the current state.";
    case 413:
      return "File is too large (max 50MB).";
    case 415:
      return "That file type isn't supported.";
    case 422:
      return error.fieldErrors?.[0]?.msg ?? error.detail;
    case 429:
      if (rateLimitKind === "quota") {
        return "Daily usage limit reached. Try again after midnight UTC.";
      }
      return error.retryAfter
        ? `Too many attempts. Try again in ${error.retryAfter}s.`
        : "Too many attempts. Try again shortly.";
    case 500:
      return "Something went wrong on our end. Please try again.";
    default:
      return error.detail || "Something went wrong. Please try again.";
  }
}

/** 403 vs 404 read very differently on purpose (spec §3.7) - use this where
 * copy needs to distinguish "doesn't exist / no relationship to it" from
 * "exists, but you can't do this." */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}
