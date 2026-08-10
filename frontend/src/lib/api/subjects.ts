import { apiFetch } from "@/lib/api/client";
import type { EnrollmentPublic, StudentLookupPublic, SubjectPublic } from "@/lib/types/api";

export function listSubjects() {
  return apiFetch<SubjectPublic[]>("/subjects");
}

export function getSubject(subjectId: string) {
  return apiFetch<SubjectPublic>(`/subjects/${subjectId}`);
}

export function createSubject(input: { name: string; description?: string }) {
  return apiFetch<SubjectPublic>("/subjects", { method: "POST", body: input });
}

export function updateSubject(subjectId: string, input: { name?: string; description?: string }) {
  return apiFetch<SubjectPublic>(`/subjects/${subjectId}`, { method: "PATCH", body: input });
}

export function deleteSubject(subjectId: string) {
  return apiFetch<void>(`/subjects/${subjectId}`, { method: "DELETE" });
}

export function lookupStudentByEmail(email: string) {
  return apiFetch<StudentLookupPublic>(`/users/students/lookup?email=${encodeURIComponent(email)}`);
}

export function listEnrollments(subjectId: string) {
  return apiFetch<EnrollmentPublic[]>(`/subjects/${subjectId}/enrollments`);
}

export function enrollStudent(subjectId: string, studentId: string) {
  return apiFetch<EnrollmentPublic>(`/subjects/${subjectId}/enrollments`, {
    method: "POST",
    body: { student_id: studentId },
  });
}

export function unenrollStudent(subjectId: string, studentId: string) {
  return apiFetch<void>(`/subjects/${subjectId}/enrollments/${studentId}`, { method: "DELETE" });
}
