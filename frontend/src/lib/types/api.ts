/**
 * Every entity/event shape the backend actually returns, per
 * docs/frontend-spec.md §4 plus the four capabilities the live API has that
 * the spec doc predates (see the frontend build's plan): document download,
 * admin user list/edit/delete, lecture retry, and GET /users/me/quota.
 */

export type UserRole = "admin" | "teacher" | "student";

export interface UserPublic {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
}

export interface StudentLookupPublic {
  id: string;
  email: string;
  full_name: string;
}

export interface QuotaPublic {
  used_tokens: number;
  limit: number;
  resets_at: string; // ISO 8601, UTC midnight
}

export interface SubjectPublic {
  id: string;
  name: string;
  description: string | null;
  teacher_id: string;
}

export interface EnrollmentPublic {
  student_id: string;
  email: string;
  full_name: string;
  enrolled_at: string;
}

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface DocumentPublic {
  id: string;
  filename: string;
  content_type: string;
  status: DocumentStatus;
  error: string | null;
  chunk_count: number;
}

export interface PlanPublic {
  id: string;
  subject_id: string;
  title: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export type LectureStatus = "pending" | "generating" | "ready" | "failed";

export interface LecturePublic {
  id: string;
  plan_id: string;
  order: number;
  title: string;
  topic: string;
  status: LectureStatus;
  error: string | null;
  current_version: number;
  content: string | null;
}

export type LectureVersionSource = "ai_generated" | "ai_refined" | "manual_edit" | "rollback";

export interface LectureVersionPublic {
  version: number;
  content: string;
  source: LectureVersionSource;
  change_summary: string | null;
  created_at: string;
}

export type RefineTransform = "shorten" | "extend" | "regenerate" | "translate";

/** Frames on ws://<host>/ws/plans/{plan_id}?token=... - every message is one event. */
export type PlannerWsEvent =
  | { type: "lecture.generating"; lecture_id: string }
  | { type: "lecture.refining"; lecture_id: string; transform: RefineTransform }
  | { type: "lecture.ready"; lecture_id: string; version: number }
  | { type: "lecture.failed"; lecture_id: string; error: string };

export interface ChatSessionPublic {
  id: string;
  subject_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatSource {
  document_id: string;
  source_filename: string;
}

export type ChatRole = "user" | "assistant";

export interface ChatMessagePublic {
  id: string;
  role: ChatRole;
  content: string;
  sources: ChatSource[];
  created_at: string;
}

export interface ChatUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

/** Terminal SSE event data shapes from POST .../messages. */
export interface ChatDoneEvent {
  message_id: string;
  sources: ChatSource[];
  usage: ChatUsage;
  /** Live extra field beyond spec §4: true when replayed from the
   * subject's first-question cache rather than freshly generated. */
  cached?: boolean;
}

export interface ChatErrorEvent {
  detail: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

/** POST /auth/ws-ticket - a short-lived, single-use ticket for
 * `/ws/plans/{plan_id}` (lib/planner/use-planner-socket.ts), not the real
 * access token. See backend services/ws_tickets.py for why. */
export interface WsTicketResponse {
  ticket: string;
}
