"use client";

import { use } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Users } from "lucide-react";
import { listEnrollments, unenrollStudent } from "@/lib/api/subjects";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { useSubjectContext } from "@/lib/subjects/subject-context";
import { EnrollStudentDialog } from "@/components/enrollments/enroll-student-dialog";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { StateCard } from "@/components/shared/state-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default function EnrollmentsPage({ params }: { params: Promise<{ subjectId: string }> }) {
  const { subjectId } = use(params);
  const { canManage } = useSubjectContext();
  const queryClient = useQueryClient();

  const { data: enrollments, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.enrollments(subjectId),
    queryFn: () => listEnrollments(subjectId),
    enabled: canManage,
  });

  const unenrollMutation = useMutation({
    mutationFn: (studentId: string) => unenrollStudent(subjectId, studentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.enrollments(subjectId) });
      toast.success("Student unenrolled.");
    },
  });

  if (!canManage) {
    return <StateCard title="Not permitted" description="Only the owning teacher or an admin can manage enrollments." />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-end">
        <EnrollStudentDialog subjectId={subjectId} />
      </div>

      {isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {isError && <p className="text-sm text-destructive">{describeError(error)}</p>}

      {enrollments && enrollments.length === 0 && (
        <StateCard icon={Users} title="No students enrolled yet" description="Enroll one by their email above." />
      )}

      {enrollments && enrollments.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Enrolled</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {enrollments.map((enrollment) => (
              <TableRow key={enrollment.student_id}>
                <TableCell className="font-medium">{enrollment.full_name}</TableCell>
                <TableCell className="text-muted-foreground">{enrollment.email}</TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(enrollment.enrolled_at).toLocaleDateString()}
                </TableCell>
                <TableCell>
                  <ConfirmDialog
                    trigger={
                      <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive">
                        Unenroll
                      </Button>
                    }
                    title={`Unenroll ${enrollment.full_name}?`}
                    description="They'll lose access to this subject's documents, Tutor chat, and any Planner content."
                    onConfirm={() => unenrollMutation.mutateAsync(enrollment.student_id)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
