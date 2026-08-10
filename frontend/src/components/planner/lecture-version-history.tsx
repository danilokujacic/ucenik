"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { History, RotateCcw } from "lucide-react";
import { listLectureVersions, rollbackLectureVersion } from "@/lib/api/planner";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import type { LectureVersionSource } from "@/lib/types/api";
import { LectureContent } from "@/lib/markdown/renderer";
import { StateCard } from "@/components/shared/state-card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const SOURCE_LABEL: Record<LectureVersionSource, string> = {
  ai_generated: "AI generated",
  ai_refined: "AI refined",
  manual_edit: "Manual edit",
  rollback: "Rollback",
};

export function LectureVersionHistory({
  subjectId,
  planId,
  lectureId,
  currentVersion,
  canManage,
}: {
  subjectId: string;
  planId: string;
  lectureId: string;
  currentVersion: number;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);

  const { data: versions, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.lectureVersions(subjectId, planId, lectureId),
    queryFn: () => listLectureVersions(subjectId, planId, lectureId),
  });

  const rollbackMutation = useMutation({
    mutationFn: (version: number) => rollbackLectureVersion(subjectId, planId, lectureId, version),
    onSuccess: (_, version) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.lecture(subjectId, planId, lectureId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.lectureVersions(subjectId, planId, lectureId) });
      toast.success(`Rolled back to v${version} - recorded as a new version, nothing was undone in place.`);
    },
    onError: (err) => toast.error(describeError(err)),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (isError) return <p className="text-sm text-destructive">{describeError(error)}</p>;
  if (!versions || versions.length === 0) {
    return <StateCard icon={History} title="No versions yet" description="Nothing has been generated for this lecture." />;
  }

  const previewed = versions.find((v) => v.version === previewVersion);

  return (
    <>
      <div className="flex flex-col gap-2">
        {[...versions].reverse().map((v) => (
          <Card key={v.version}>
            <CardContent className="flex items-center justify-between gap-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium">v{v.version}</span>
                  {v.version === currentVersion && <Badge variant="success">Current</Badge>}
                  <Badge variant="outline">{SOURCE_LABEL[v.source]}</Badge>
                </div>
                <p className="mt-0.5 truncate text-xs text-muted-foreground">
                  {v.change_summary ?? "Initial generation"} · {new Date(v.created_at).toLocaleString()}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button variant="ghost" size="sm" onClick={() => setPreviewVersion(v.version)}>
                  View
                </Button>
                {canManage && v.version !== currentVersion && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={rollbackMutation.isPending}
                    onClick={() => rollbackMutation.mutate(v.version)}
                  >
                    <RotateCcw /> Roll back
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={previewVersion !== null} onOpenChange={(next) => !next && setPreviewVersion(null)}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Version {previewVersion}</DialogTitle>
            <DialogDescription>Read-only preview - old versions stay permanently inspectable.</DialogDescription>
          </DialogHeader>
          <Separator />
          {previewed && <LectureContent content={previewed.content} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
