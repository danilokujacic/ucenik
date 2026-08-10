"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Pencil, X } from "lucide-react";
import { editLectureContent } from "@/lib/api/planner";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { LectureContent } from "@/lib/markdown/renderer";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";

/** Direct DB write, no AI call, no WebSocket involved (spec §3.6 point 7) -
 * for the "just let me fix the text" case rather than routing every small
 * edit through refine. */
export function ManualEditLecture({
  subjectId,
  planId,
  lectureId,
  content,
  canManage,
}: {
  subjectId: string;
  planId: string;
  lectureId: string;
  content: string | null;
  canManage: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(content ?? "");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => editLectureContent(subjectId, planId, lectureId, draft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.lecture(subjectId, planId, lectureId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.lectureVersions(subjectId, planId, lectureId) });
      toast.success("Saved as a new version.");
      setEditing(false);
    },
    onError: (err) => toast.error(describeError(err)),
  });

  if (!content && !editing) {
    return <p className="text-sm text-muted-foreground">Nothing generated yet.</p>;
  }

  if (editing) {
    return (
      <div className="flex flex-col gap-3">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="min-h-96 font-mono text-sm"
          autoFocus
        />
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => { setEditing(false); setDraft(content ?? ""); }}>
            <X /> Cancel
          </Button>
          <Button size="sm" disabled={mutation.isPending || !draft.trim()} onClick={() => mutation.mutate()}>
            {mutation.isPending ? <Spinner className="size-4 text-current" /> : "Save"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {canManage && (
        <div className="flex justify-end">
          <Button variant="outline" size="sm" onClick={() => { setDraft(content ?? ""); setEditing(true); }}>
            <Pencil /> Edit
          </Button>
        </div>
      )}
      <LectureContent content={content!} />
    </div>
  );
}
