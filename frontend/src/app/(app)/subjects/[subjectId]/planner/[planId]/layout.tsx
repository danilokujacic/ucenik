"use client";

import { use } from "react";
import { PlannerSocketProvider } from "@/lib/planner/planner-socket-context";

export default function PlanLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ subjectId: string; planId: string }>;
}) {
  const { subjectId, planId } = use(params);
  return (
    <PlannerSocketProvider subjectId={subjectId} planId={planId}>
      {children}
    </PlannerSocketProvider>
  );
}
