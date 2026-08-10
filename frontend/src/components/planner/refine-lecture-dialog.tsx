"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Sparkles } from "lucide-react";
import { refineLecture } from "@/lib/api/planner";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { usePlannerSocketContext } from "@/lib/planner/planner-socket-context";
import type { RefineTransform } from "@/lib/types/api";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";

const TRANSFORMS: { value: RefineTransform; label: string }[] = [
  { value: "shorten", label: "Shorten" },
  { value: "extend", label: "Extend" },
  { value: "regenerate", label: "Regenerate" },
  { value: "translate", label: "Translate" },
];

export function RefineLectureDialog({
  subjectId,
  planId,
  lectureId,
  disabled,
}: {
  subjectId: string;
  planId: string;
  lectureId: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [transform, setTransform] = useState<RefineTransform>("shorten");
  const [targetLanguage, setTargetLanguage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { waitUntilOpen } = usePlannerSocketContext();

  const mutation = useMutation({
    mutationFn: async () => {
      // Validated client-side too (spec §3.6 point 6) rather than relying
      // on the round trip to catch it - a 422 here is FastAPI's own list
      // shape, not worth a network call to discover.
      if (transform === "translate" && !targetLanguage.trim()) {
        throw new Error("target_language is required when transform is 'translate'");
      }
      await waitUntilOpen();
      return refineLecture(subjectId, planId, lectureId, {
        transform,
        target_language: transform === "translate" ? targetLanguage.trim() : undefined,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.lecture(subjectId, planId, lectureId) });
      toast.success("Refine started - watch its status update live.");
      setOpen(false);
    },
    onError: (err) => setError(err instanceof Error && !("status" in err) ? err.message : describeError(err)),
  });

  return (
    <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (next) setError(null); }}>
      <DialogTrigger asChild>
        <Button variant="secondary" disabled={disabled}>
          <Sparkles /> Refine
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Refine this lecture</DialogTitle>
          <DialogDescription>Creates a new version - nothing is overwritten in place.</DialogDescription>
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
            <Label>Transform</Label>
            <Select value={transform} onValueChange={(v) => setTransform(v as RefineTransform)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TRANSFORMS.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {transform === "translate" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="target-language">Target language</Label>
              <Input
                id="target-language"
                required
                placeholder="e.g. French"
                value={targetLanguage}
                onChange={(e) => setTargetLanguage(e.target.value)}
              />
            </div>
          )}
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? <Spinner className="size-4 text-current" /> : "Start"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
