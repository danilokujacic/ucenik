"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Plus, BookOpen } from "lucide-react";
import { listSubjects } from "@/lib/api/subjects";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { SubjectFormDialog } from "@/components/subjects/subject-form-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function SubjectsPage() {
  const { user } = useAuth();
  const canCreate = user?.role === "teacher" || user?.role === "admin";

  const { data: subjects, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.subjects(),
    queryFn: listSubjects,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Subjects</h1>
          <p className="text-sm text-muted-foreground">
            {user?.role === "student" ? "Subjects you're enrolled in." : "Subjects you own, or all of them as an admin."}
          </p>
        </div>
        {canCreate && (
          <SubjectFormDialog
            trigger={
              <Button>
                <Plus /> New subject
              </Button>
            }
          />
        )}
      </div>

      {isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      )}

      {isError && <p className="text-sm text-destructive">{describeError(error)}</p>}

      {subjects && subjects.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
            <BookOpen className="size-8" />
            <p>
              {user?.role === "student"
                ? "You're not enrolled in any subjects yet - ask your teacher to enroll you."
                : "No subjects yet."}
            </p>
          </CardContent>
        </Card>
      )}

      {subjects && subjects.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {subjects.map((subject) => (
            <Link key={subject.id} href={`/subjects/${subject.id}`}>
              <Card className="h-full transition-colors hover:border-primary/50">
                <CardHeader>
                  <CardTitle>{subject.name}</CardTitle>
                  <CardDescription className="line-clamp-2">
                    {subject.description || "No description."}
                  </CardDescription>
                </CardHeader>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
