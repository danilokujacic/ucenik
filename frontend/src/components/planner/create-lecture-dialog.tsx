"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { createLecture } from "@/lib/api/planner";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { usePlannerSocketContext } from "@/lib/planner/planner-socket-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";

export function CreateLectureDialog({
  subjectId,
  planId,
  nextOrder,
}: {
  subjectId: string;
  planId: string;
  nextOrder: number;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [topic, setTopic] = useState("");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { waitUntilOpen } = usePlannerSocketContext();

  const mutation = useMutation({
    mutationFn: async () => {
      // Spec §3.6 point 3: connect before triggering the job, or its
      // progress events for this lecture are missed entirely (no replay).
      await waitUntilOpen();
      return createLecture(subjectId, planId, { title, topic, order: nextOrder });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.lectures(subjectId, planId) });
      toast.success("Generation started - watch its status update live.");
      setOpen(false);
      setTitle("");
      setTopic("");
    },
    onError: (err) => setError(describeError(err)),
  });

  return (
    <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (next) setError(null); }}>
      <DialogTrigger asChild>
        <Button>
          <Plus /> Add lecture
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a lecture</DialogTitle>
          <DialogDescription>
            Kicks off AI generation - it&apos;ll show as &quot;pending&quot; then &quot;generating&quot; until ready.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            mutation.mutate();
          }}
        >
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="lecture-title">Title</Label>
            <Input id="lecture-title" required value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="topic">Topic</Label>
            <Textarea
              id="topic"
              required
              maxLength={2000}
              placeholder="What should generation cover?"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? <Spinner className="size-4 text-current" /> : "Generate"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
