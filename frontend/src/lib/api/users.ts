import { apiFetch } from "@/lib/api/client";
import type { QuotaPublic } from "@/lib/types/api";

/** Live capability beyond the spec doc - see the frontend build plan's
 * Context section. Per-user daily token usage, not per-subject. */
export function getMyQuota() {
  return apiFetch<QuotaPublic>("/users/me/quota");
}
