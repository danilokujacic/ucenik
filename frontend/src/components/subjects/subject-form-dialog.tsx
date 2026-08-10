"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { createSubject, updateSubject } from "@/lib/api/subjects";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import type { SubjectPublic } from "@/lib/types/api";
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

export function SubjectFormDialog({
  subject,
  trigger,
  onSaved,
}: {
  subject?: SubjectPublic;
  trigger: React.ReactNode;
  onSaved?: (subject: SubjectPublic) => void;
}) {
  const isEdit = !!subject;
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(subject?.name ?? "");
  const [description, setDescription] = useState(subject?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () =>
      isEdit ? updateSubject(subject.id, { name, description }) : createSubject({ name, description }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.subjects() });
      if (isEdit) queryClient.invalidateQueries({ queryKey: queryKeys.subject(subject.id) });
      toast.success(isEdit ? "Subject updated." : "Subject created.");
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
          <DialogTitle>{isEdit ? "Edit subject" : "New subject"}</DialogTitle>
          <DialogDescription>
            {isEdit ? "Update the name or description." : "Students are enrolled separately once it exists."}
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
            <Label htmlFor="name">Name</Label>
            <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
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
