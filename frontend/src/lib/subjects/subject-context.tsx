"use client";

import { createContext, useContext } from "react";
import type { SubjectPublic } from "@/lib/types/api";

interface SubjectContextValue {
  subject: SubjectPublic;
  /** Owning teacher or admin - mirrors the backend's require_subject_owner
   * dependency, which gates enrollments *and* every Planner route (spec
   * §2/§3.6: a non-owning teacher gets 403 there too, not just students). */
  canManage: boolean;
}

const SubjectContext = createContext<SubjectContextValue | null>(null);

export function SubjectProvider({ value, children }: { value: SubjectContextValue; children: React.ReactNode }) {
  return <SubjectContext.Provider value={value}>{children}</SubjectContext.Provider>;
}

export function useSubjectContext(): SubjectContextValue {
  const ctx = useContext(SubjectContext);
  if (!ctx) throw new Error("useSubjectContext must be used within a subject route");
  return ctx;
}
