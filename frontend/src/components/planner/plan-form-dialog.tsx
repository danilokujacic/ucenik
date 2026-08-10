"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { createPlan, updatePlan } from "@/lib/api/planner";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import type { PlanPublic } from "@/lib/types/api";
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

export function PlanFormDialog({
  subjectId,
  plan,
  trigger,
  onSaved,
}: {
  subjectId: string;
  plan?: PlanPublic;
  trigger: React.ReactNode;
  onSaved?: (plan: PlanPublic) => void;
}) {
  const isEdit = !!plan;
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(plan?.title ?? "");
  const [description, setDescription] = useState(plan?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () =>
      isEdit ? updatePlan(subjectId, plan.id, { title, description }) : createPlan(subjectId, { title, description }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.plans(subjectId) });
      if (isEdit) queryClient.invalidateQueries({ queryKey: queryKeys.plan(subjectId, plan.id) });
      toast.success(isEdit ? "Plan updated." : "Plan created.");
      setOpen(false);
      onSaved?.(result);
    },
    onError: (err) => setError(describeError(err)),
  });

  return (
    <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (next) setError(null); }}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit plan" : "New plan"}</DialogTitle>
          <DialogDescription>An ordered container of lectures for this subject.</DialogDescription>
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
            <Label htmlFor="title">Title</Label>
            <Input id="title" required value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="description">Description (optional)</Label>
            <Textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? <Spinner className="size-4 text-current" /> : isEdit ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
