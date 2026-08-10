"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { lookupStudentByEmail, enrollStudent } from "@/lib/api/subjects";
import { queryKeys } from "@/lib/query/keys";
import { describeError, isNotFound } from "@/lib/errors";
import type { StudentLookupPublic } from "@/lib/types/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { Card, CardContent } from "@/components/ui/card";

export function EnrollStudentDialog({ subjectId }: { subjectId: string }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [found, setFound] = useState<StudentLookupPublic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const lookupMutation = useMutation({
    mutationFn: () => lookupStudentByEmail(email),
    onSuccess: (student) => {
      setFound(student);
      setError(null);
    },
    onError: (err) => {
      setFound(null);
      // Spec §4: a real teacher/admin email 404s here too, same as a
      // nonexistent one - the endpoint can't be used to probe staff emails.
      setError(isNotFound(err) ? "No student found with that email." : describeError(err));
    },
  });

  const enrollMutation = useMutation({
    mutationFn: () => enrollStudent(subjectId, found!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.enrollments(subjectId) });
      toast.success(`${found?.full_name} enrolled.`);
      setOpen(false);
      setEmail("");
      setFound(null);
    },
    onError: (err) => setError(describeError(err)),
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setEmail("");
          setFound(null);
          setError(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button>Enroll student</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Enroll a student</DialogTitle>
          <DialogDescription>Look them up by email, then confirm.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setFound(null);
              setError(null);
              lookupMutation.mutate();
            }}
          >
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="student-email">Student email</Label>
              <Input
                id="student-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <Button type="submit" variant="secondary" disabled={lookupMutation.isPending}>
              {lookupMutation.isPending ? <Spinner className="size-4 text-current" /> : "Look up"}
            </Button>
          </form>

          {found && (
            <Card>
              <CardContent className="flex items-center justify-between py-4">
                <div>
                  <p className="font-medium">{found.full_name}</p>
                  <p className="text-sm text-muted-foreground">{found.email}</p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
        <DialogFooter>
          <Button disabled={!found || enrollMutation.isPending} onClick={() => enrollMutation.mutate()}>
            {enrollMutation.isPending ? <Spinner className="size-4 text-current" /> : "Enroll"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
