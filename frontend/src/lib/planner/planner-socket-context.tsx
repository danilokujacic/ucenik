"use client";

import { createContext, useContext } from "react";
import { usePlannerSocket, type PlannerSocketStatus } from "@/lib/planner/use-planner-socket";
import type { PlannerWsEvent } from "@/lib/types/api";

interface PlannerSocketContextValue {
  status: PlannerSocketStatus;
  subscribe: (fn: (event: PlannerWsEvent) => void) => () => void;
  waitUntilOpen: () => Promise<boolean>;
}

const PlannerSocketContext = createContext<PlannerSocketContextValue | null>(null);

/** One WebSocket per plan (spec §3.6 point 3), owned at the plan's layout
 * level so it survives navigation between the plan overview and individual
 * lectures rather than reconnecting on every click. */
export function PlannerSocketProvider({
  subjectId,
  planId,
  children,
}: {
  subjectId: string;
  planId: string;
  children: React.ReactNode;
}) {
  const value = usePlannerSocket(subjectId, planId);
  return <PlannerSocketContext.Provider value={value}>{children}</PlannerSocketContext.Provider>;
}

export function usePlannerSocketContext(): PlannerSocketContextValue {
  const ctx = useContext(PlannerSocketContext);
  if (!ctx) throw new Error("usePlannerSocketContext must be used within a plan route");
  return ctx;
}
