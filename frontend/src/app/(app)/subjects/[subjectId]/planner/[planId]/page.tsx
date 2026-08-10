"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BookOpenCheck } from "lucide-react";
import { getPlan, listLectures } from "@/lib/api/planner";
import { queryKeys } from "@/lib/query/keys";
import { describeError, isNotFound } from "@/lib/errors";
import { usePlannerSocketContext } from "@/lib/planner/planner-socket-context";
import { CreateLectureDialog } from "@/components/planner/create-lecture-dialog";
import { LectureStatusBadge } from "@/components/planner/lecture-status-badge";
import { PlannerSocketStatusPill } from "@/components/planner/planner-socket-status";
import { StateCard } from "@/components/shared/state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";

export default function PlanDetailPage({
  params,
}: {
  params: Promise<{ subjectId: string; planId: string }>;
}) {
  const { subjectId, planId } = use(params);
  const { status: socketStatus } = usePlannerSocketContext();

  const { data: plan, isLoading: planLoading, isError: planIsError, error: planError } = useQuery({
    queryKey: queryKeys.plan(subjectId, planId),
    queryFn: () => getPlan(subjectId, planId),
  });

  const { data: lectures, isLoading: lecturesLoading } = useQuery({
    queryKey: queryKeys.lectures(subjectId, planId),
    queryFn: () => listLectures(subjectId, planId),
  });

  if (planLoading) return <Skeleton className="h-40 w-full" />;

  if (planIsError || !plan) {
    return (
      <StateCard
        title={isNotFound(planError) ? "Plan not found" : "Something went wrong"}
        description={isNotFound(planError) ? "It may have been deleted." : describeError(planError)}
      />
    );
  }

  const nextOrder = lectures && lectures.length > 0 ? Math.max(...lectures.map((l) => l.order)) + 1 : 0;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Link
          href={`/subjects/${subjectId}/planner`}
          className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Plans
        </Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold">{plan.title}</h2>
            {plan.description && <p className="mt-1 text-sm text-muted-foreground">{plan.description}</p>}
          </div>
          <PlannerSocketStatusPill status={socketStatus} />
        </div>
      </div>

      <div className="flex items-center justify-end">
        <CreateLectureDialog subjectId={subjectId} planId={planId} nextOrder={nextOrder} />
      </div>

      {lecturesLoading && <Skeleton className="h-40 w-full" />}

      {lectures && lectures.length === 0 && (
        <StateCard icon={BookOpenCheck} title="No lectures yet" description="Add one above to kick off AI generation." />
      )}

      {lectures && lectures.length > 0 && (
        <div className="flex flex-col gap-2">
          {[...lectures]
            .sort((a, b) => a.order - b.order)
            .map((lecture) => (
              <Link key={lecture.id} href={`/subjects/${subjectId}/planner/${planId}/lectures/${lecture.id}`}>
                <Card className="transition-colors hover:border-primary/50">
                  <CardContent className="flex items-center justify-between gap-4 py-4">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="text-sm text-muted-foreground">#{lecture.order}</span>
                      <div className="min-w-0">
                        <p className="truncate font-medium">{lecture.title}</p>
                        <p className="truncate text-xs text-muted-foreground">{lecture.topic}</p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <span className="text-xs text-muted-foreground">v{lecture.current_version || "—"}</span>
                      <LectureStatusBadge status={lecture.status} />
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
        </div>
      )}
    </div>
  );
}
