"use client";

import { use } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, FileWarning, Pencil, Trash2 } from "lucide-react";
import { getSubject, deleteSubject } from "@/lib/api/subjects";
import { queryKeys } from "@/lib/query/keys";
import { describeError, isNotFound } from "@/lib/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { SubjectProvider } from "@/lib/subjects/subject-context";
import { cn } from "@/lib/utils";
import { SubjectFormDialog } from "@/components/subjects/subject-form-dialog";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { StateCard } from "@/components/shared/state-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export default function SubjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ subjectId: string }>;
}) {
  const { subjectId } = use(params);
  const { user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: subject, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.subject(subjectId),
    queryFn: () => getSubject(subjectId),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteSubject(subjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.subjects() });
      toast.success("Subject deleted.");
      router.replace("/subjects");
    },
  });

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-10 w-full max-w-md" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (isError || !subject) {
    // Spec §3.3/§3.7: a subject that doesn't exist and one the caller has
    // no relationship to both 404 identically - existence isn't leaked.
    return (
      <StateCard
        icon={FileWarning}
        title={isNotFound(error) ? "Subject not found" : "Something went wrong"}
        description={
          isNotFound(error)
            ? "It doesn't exist, or you don't have access to it."
            : describeError(error)
        }
      />
    );
  }

  const canManage = user?.role === "admin" || subject.teacher_id === user?.id;

  const tabs = [
    { href: `/subjects/${subjectId}/documents`, label: "Documents" },
    { href: `/subjects/${subjectId}/chat`, label: "Tutor Chat" },
    ...(canManage ? [{ href: `/subjects/${subjectId}/enrollments`, label: "Enrollments" }] : []),
    // Planner is gated on ownership, not just role (spec §2/§3.6): even a
    // non-owning teacher gets 403 on every Planner route server-side.
    ...(canManage ? [{ href: `/subjects/${subjectId}/planner`, label: "Planner" }] : []),
  ];

  return (
    <SubjectProvider value={{ subject, canManage }}>
      <div className="flex flex-col gap-6">
        <div>
          <Link href="/subjects" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-3.5" /> Subjects
          </Link>
          <div className="mt-1 flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold">{subject.name}</h1>
              {subject.description && (
                <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{subject.description}</p>
              )}
            </div>
            {canManage && (
              <div className="flex shrink-0 gap-2">
                <SubjectFormDialog
                  subject={subject}
                  trigger={
                    <Button variant="outline" size="sm">
                      <Pencil /> Edit
                    </Button>
                  }
                />
                <ConfirmDialog
                  trigger={
                    <Button variant="outline" size="sm" className="text-destructive hover:text-destructive">
                      <Trash2 /> Delete
                    </Button>
                  }
                  title={`Delete ${subject.name}?`}
                  description="This cascades - it deletes all enrollments, documents, their vector chunks, and any now-unreferenced stored files."
                  onConfirm={() => deleteMutation.mutateAsync()}
                />
              </div>
            )}
          </div>
        </div>

        <nav className="flex gap-1 border-b border-border">
          {tabs.map((tab) => (
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                "border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                pathname.startsWith(tab.href) && "border-primary text-foreground",
              )}
            >
              {tab.label}
            </Link>
          ))}
        </nav>

        {children}
      </div>
    </SubjectProvider>
  );
}
