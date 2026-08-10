import { apiFetch } from "@/lib/api/client";
import type { UserPublic, UserRole } from "@/lib/types/api";

/** Live capability beyond the spec doc (list/edit/delete) - see the
 * frontend build plan's Context section. Creation matches spec §3.2. */

export function listUsers() {
  return apiFetch<UserPublic[]>("/admin/users");
}

export function createUser(input: { email: string; password: string; full_name: string; role: UserRole }) {
  return apiFetch<UserPublic>("/admin/users", { method: "POST", body: input });
}

export function updateUser(
  userId: string,
  input: { full_name?: string; role?: UserRole; password?: string },
) {
  return apiFetch<UserPublic>(`/admin/users/${userId}`, { method: "PATCH", body: input });
}

export function deleteUser(userId: string) {
  return apiFetch<void>(`/admin/users/${userId}`, { method: "DELETE" });
}
