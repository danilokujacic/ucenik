import { apiFetch } from "@/lib/api/client";
import type { ChatMessagePublic, ChatSessionPublic } from "@/lib/types/api";

export function listChatSessions(subjectId: string) {
  return apiFetch<ChatSessionPublic[]>(`/subjects/${subjectId}/chat/sessions`);
}

export function createChatSession(subjectId: string) {
  return apiFetch<ChatSessionPublic>(`/subjects/${subjectId}/chat/sessions`, { method: "POST" });
}

export function deleteChatSession(subjectId: string, sessionId: string) {
  return apiFetch<void>(`/subjects/${subjectId}/chat/sessions/${sessionId}`, { method: "DELETE" });
}

export function listChatMessages(subjectId: string, sessionId: string) {
  return apiFetch<ChatMessagePublic[]>(`/subjects/${subjectId}/chat/sessions/${sessionId}/messages`);
}
