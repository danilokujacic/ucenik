import { apiFetch } from "@/lib/api/client";
import type { LecturePublic, LectureVersionPublic, PlanPublic, RefineTransform } from "@/lib/types/api";

// --- Plans ---

export function listPlans(subjectId: string) {
  return apiFetch<PlanPublic[]>(`/subjects/${subjectId}/plans`);
}

export function getPlan(subjectId: string, planId: string) {
  return apiFetch<PlanPublic>(`/subjects/${subjectId}/plans/${planId}`);
}

export function createPlan(subjectId: string, input: { title: string; description?: string }) {
  return apiFetch<PlanPublic>(`/subjects/${subjectId}/plans`, { method: "POST", body: input });
}

export function updatePlan(subjectId: string, planId: string, input: { title?: string; description?: string }) {
  return apiFetch<PlanPublic>(`/subjects/${subjectId}/plans/${planId}`, { method: "PATCH", body: input });
}

export function deletePlan(subjectId: string, planId: string) {
  return apiFetch<void>(`/subjects/${subjectId}/plans/${planId}`, { method: "DELETE" });
}

// --- Lectures ---

const lecturesBase = (subjectId: string, planId: string) => `/subjects/${subjectId}/plans/${planId}/lectures`;

export function listLectures(subjectId: string, planId: string) {
  return apiFetch<LecturePublic[]>(lecturesBase(subjectId, planId));
}

export function getLecture(subjectId: string, planId: string, lectureId: string) {
  return apiFetch<LecturePublic>(`${lecturesBase(subjectId, planId)}/${lectureId}`);
}

/** 202 - dispatches AI generation. Response's status is still "pending";
 * watch the plan's WebSocket (connected before this call) or poll for the
 * real outcome (spec §3.6 point 2/3). */
export function createLecture(subjectId: string, planId: string, input: { title: string; topic: string; order: number }) {
  return apiFetch<LecturePublic>(lecturesBase(subjectId, planId), { method: "POST", body: input });
}

/** Synchronous, no AI call - direct DB write (spec §3.6 point 7). */
export function editLectureContent(subjectId: string, planId: string, lectureId: string, content: string) {
  return apiFetch<LecturePublic>(`${lecturesBase(subjectId, planId)}/${lectureId}`, {
    method: "PATCH",
    body: { content },
  });
}

/** 202 - same WebSocket-progress pattern as generation (spec §3.6 point 6).
 * 409 if the lecture has no version yet or a job's already in flight. */
export function refineLecture(
  subjectId: string,
  planId: string,
  lectureId: string,
  input: { transform: RefineTransform; target_language?: string },
) {
  return apiFetch<LecturePublic>(`${lecturesBase(subjectId, planId)}/${lectureId}/refine`, {
    method: "POST",
    body: input,
  });
}

/** Live capability beyond the spec doc - see the frontend build plan's
 * Context section. Only valid when status is "failed"; replays the last
 * generate/refine attempt. */
export function retryLecture(subjectId: string, planId: string, lectureId: string) {
  return apiFetch<LecturePublic>(`${lecturesBase(subjectId, planId)}/${lectureId}/retry`, { method: "POST" });
}

export function deleteLecture(subjectId: string, planId: string, lectureId: string) {
  return apiFetch<void>(`${lecturesBase(subjectId, planId)}/${lectureId}`, { method: "DELETE" });
}

export function listLectureVersions(subjectId: string, planId: string, lectureId: string) {
  return apiFetch<LectureVersionPublic[]>(`${lecturesBase(subjectId, planId)}/${lectureId}/versions`);
}

/** Synchronous, no AI call - creates a new version copying the old one's
 * content (spec §3.6 point 8). */
export function rollbackLectureVersion(subjectId: string, planId: string, lectureId: string, version: number) {
  return apiFetch<LecturePublic>(`${lecturesBase(subjectId, planId)}/${lectureId}/versions/${version}/rollback`, {
    method: "POST",
  });
}
