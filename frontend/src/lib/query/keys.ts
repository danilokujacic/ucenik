/** Central query-key factory so invalidation call sites (mutations, the
 * Planner WebSocket handler) agree with the hooks that fetch each resource. */
export const queryKeys = {
  me: () => ["me"] as const,
  quota: () => ["quota"] as const,

  adminUsers: () => ["admin-users"] as const,

  subjects: () => ["subjects"] as const,
  subject: (subjectId: string) => ["subjects", subjectId] as const,

  enrollments: (subjectId: string) => ["subjects", subjectId, "enrollments"] as const,

  documents: (subjectId: string) => ["subjects", subjectId, "documents"] as const,
  document: (subjectId: string, documentId: string) => ["subjects", subjectId, "documents", documentId] as const,

  chatSessions: (subjectId: string) => ["subjects", subjectId, "chat-sessions"] as const,
  chatMessages: (subjectId: string, sessionId: string) =>
    ["subjects", subjectId, "chat-sessions", sessionId, "messages"] as const,

  plans: (subjectId: string) => ["subjects", subjectId, "plans"] as const,
  plan: (subjectId: string, planId: string) => ["subjects", subjectId, "plans", planId] as const,

  lectures: (subjectId: string, planId: string) => ["subjects", subjectId, "plans", planId, "lectures"] as const,
  lecture: (subjectId: string, planId: string, lectureId: string) =>
    ["subjects", subjectId, "plans", planId, "lectures", lectureId] as const,
  lectureVersions: (subjectId: string, planId: string, lectureId: string) =>
    ["subjects", subjectId, "plans", planId, "lectures", lectureId, "versions"] as const,
};
