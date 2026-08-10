import { apiFetch, apiFetchBlob } from "@/lib/api/client";
import type { DocumentPublic } from "@/lib/types/api";

export function listDocuments(subjectId: string) {
  return apiFetch<DocumentPublic[]>(`/subjects/${subjectId}/documents`);
}

export function getDocument(subjectId: string, documentId: string) {
  return apiFetch<DocumentPublic>(`/subjects/${subjectId}/documents/${documentId}`);
}

export function uploadDocument(subjectId: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<DocumentPublic>(`/subjects/${subjectId}/documents`, {
    method: "POST",
    body: formData,
  });
}

export function deleteDocument(subjectId: string, documentId: string) {
  return apiFetch<void>(`/subjects/${subjectId}/documents/${documentId}`, { method: "DELETE" });
}

/** Live capability beyond the spec doc - see the frontend build plan's
 * Context section. Same access level as reading the document's metadata. */
export async function downloadDocument(subjectId: string, documentId: string, filename: string) {
  const blob = await apiFetchBlob(`/subjects/${subjectId}/documents/${documentId}/download`);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
