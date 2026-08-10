"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useQueryState } from "nuqs";
import { toast } from "sonner";
import { ArrowLeft, RotateCw, Trash2 } from "lucide-react";
import { deleteLecture, getLecture, retryLecture } from "@/lib/api/planner";
import { queryKeys } from "@/lib/query/keys";
import { describeError, isNotFound } from "@/lib/errors";
import { useSubjectContext } from "@/lib/subjects/subject-context";
import { usePlannerSocketContext } from "@/lib/planner/planner-socket-context";
import { LectureStatusBadge } from "@/components/planner/lecture-status-badge";
import { RefineLectureDialog } from "@/components/planner/refine-lecture-dialog";
import { ManualEditLecture } from "@/components/planner/manual-edit-lecture";
import { LectureVersionHistory } from "@/components/planner/lecture-version-history";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { StateCard } from "@/components/shared/state-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Spinner } from "@/components/ui/spinner";
import { useRouter } from "next/navigation";
import type { RefineTransform } from "@/lib/types/api";

function transformLabel(transform: RefineTransform) {
  return { shorten: "Shortening", extend: "Extending", regenerate: "Regenerating", translate: "Translating" }[transform];
}

export default function LectureDetailPage({
  params,
}: {
  params: Promise<{ subjectId: string; planId: string; lectureId: string }>;
}) {
  const { subjectId, planId, lectureId } = use(params);
  const { canManage } = useSubjectContext();
  const { subscribe } = usePlannerSocketContext();
  const queryClient = useQueryClient();
  const router = useRouter();
  const [tab, setTab] = useQueryState("tab", { defaultValue: "content" });
  const [liveActivity, setLiveActivity] = useState<string | null>(null);

  const { data: lecture, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.lecture(subjectId, planId, lectureId),
    queryFn: () => getLecture(subjectId, planId, lectureId),
  });

  // Live status text beyond the plain "generating" badge (e.g. which
  // refine transform is running) - the REST response alone doesn't carry
  // that, only the WS event does (spec §3.6's event table).
  useEffect(() => {
    return subscribe((event) => {
      if (event.lecture_id !== lectureId) return;
      if (event.type === "lecture.generating") setLiveActivity("Generating…");
      else if (event.type === "lecture.refining") setLiveActivity(`${transformLabel(event.transform)}…`);
      else setLiveActivity(null);
    });
  }, [subscribe, lectureId]);

  const retryMutation = useMutation({
    mutationFn: () => retryLecture(subjectId, planId, lectureId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.lecture(subjectId, planId, lectureId) });
      toast.success("Retrying.");
    },
    onError: (err) => toast.error(describeError(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteLecture(subjectId, planId, lectureId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.lectures(subjectId, planId) });
      toast.success("Lecture deleted.");
      router.replace(`/subjects/${subjectId}/planner/${planId}`);
    },
  });

  if (isLoading) return <Skeleton className="h-96 w-full" />;

  if (isError || !lecture) {
    return (
      <StateCard
        title={isNotFound(error) ? "Lecture not found" : "Something went wrong"}
        description={isNotFound(error) ? "It may have been deleted." : describeError(error)}
      />
    );
  }

  const isBusy = lecture.status === "generating";

  return (
    <div className="flex flex-col gap-6">
      <Link
        href={`/subjects/${subjectId}/planner/${planId}`}
        className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> Lectures
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold">{lecture.title}</h2>
            <LectureStatusBadge status={lecture.status} />
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{lecture.topic}</p>
        </div>

        {canManage && (
          <div className="flex shrink-0 gap-2">
            {lecture.status === "failed" && (
              <Button variant="secondary" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate()}>
                {retryMutation.isPending ? <Spinner className="size-4 text-current" /> : <RotateCw />}
                Retry
              </Button>
            )}
            <RefineLectureDialog
              subjectId={subjectId}
              planId={planId}
              lectureId={lectureId}
              disabled={lecture.current_version === 0 || isBusy}
            />
            <ConfirmDialog
              trigger={
                <Button variant="outline" className="text-destructive hover:text-destructive">
                  <Trash2 />
                </Button>
              }
              title={`Delete ${lecture.title}?`}
              description="Removes it and its entire version history."
              onConfirm={() => deleteMutation.mutateAsync()}
            />
          </div>
        )}
      </div>

      {isBusy && (
        <Alert>
          <Spinner className="size-4" />
          <AlertDescription>{liveActivity ?? "In progress…"}</AlertDescription>
        </Alert>
      )}

      {lecture.status === "failed" && lecture.error && (
        <Alert variant="destructive">
          <AlertDescription>{lecture.error}</AlertDescription>
        </Alert>
      )}

      <Tabs value={tab ?? "content"} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="content">Content</TabsTrigger>
          <TabsTrigger value="versions">Version history</TabsTrigger>
        </TabsList>
        <TabsContent value="content" className="pt-4">
          <ManualEditLecture
            subjectId={subjectId}
            planId={planId}
            lectureId={lectureId}
            content={lecture.content}
            canManage={canManage && !isBusy}
          />
        </TabsContent>
        <TabsContent value="versions" className="pt-4">
          <LectureVersionHistory
            subjectId={subjectId}
            planId={planId}
            lectureId={lectureId}
            currentVersion={lecture.current_version}
            canManage={canManage}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
