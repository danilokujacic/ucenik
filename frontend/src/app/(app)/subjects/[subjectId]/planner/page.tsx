"use client";

import { use } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ClipboardList, Plus, Trash2 } from "lucide-react";
import { deletePlan, listPlans } from "@/lib/api/planner";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { useSubjectContext } from "@/lib/subjects/subject-context";
import { PlanFormDialog } from "@/components/planner/plan-form-dialog";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { StateCard } from "@/components/shared/state-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function PlannerPage({ params }: { params: Promise<{ subjectId: string }> }) {
  const { subjectId } = use(params);
  const { canManage } = useSubjectContext();
  const queryClient = useQueryClient();

  const { data: plans, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.plans(subjectId),
    queryFn: () => listPlans(subjectId),
    enabled: canManage,
  });

  const deleteMutation = useMutation({
    mutationFn: (planId: string) => deletePlan(subjectId, planId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.plans(subjectId) });
      toast.success("Plan deleted.");
    },
  });

  if (!canManage) {
    return <StateCard title="Not permitted" description="Planner is a drafting tool for the owning teacher or an admin only." />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-end">
        <PlanFormDialog
          subjectId={subjectId}
          trigger={
            <Button>
              <Plus /> New plan
            </Button>
          }
        />
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      )}

      {isError && <p className="text-sm text-destructive">{describeError(error)}</p>}

      {plans && plans.length === 0 && (
        <StateCard icon={ClipboardList} title="No plans yet" description="Create one, then add lectures to it - each triggers AI generation." />
      )}

      {plans && plans.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {plans.map((plan) => (
            <Card key={plan.id} className="flex flex-col justify-between transition-colors hover:border-primary/50">
              <Link href={`/subjects/${subjectId}/planner/${plan.id}`}>
                <CardHeader>
                  <CardTitle>{plan.title}</CardTitle>
                  <CardDescription className="line-clamp-2">{plan.description || "No description."}</CardDescription>
                </CardHeader>
              </Link>
              <CardContent className="flex justify-end pt-0">
                <ConfirmDialog
                  trigger={
                    <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive">
                      <Trash2 /> Delete
                    </Button>
                  }
                  title={`Delete ${plan.title}?`}
                  description="This cascades - removes every lecture in it and their full version history."
                  onConfirm={() => deleteMutation.mutateAsync(plan.id)}
                />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
