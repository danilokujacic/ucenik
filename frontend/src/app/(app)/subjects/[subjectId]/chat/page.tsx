"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { MessageSquare, Plus, Trash2 } from "lucide-react";
import { createChatSession, deleteChatSession, listChatSessions } from "@/lib/api/chat";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { StateCard } from "@/components/shared/state-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

export default function ChatSessionsPage({ params }: { params: Promise<{ subjectId: string }> }) {
  const { subjectId } = use(params);
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: sessions, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.chatSessions(subjectId),
    queryFn: () => listChatSessions(subjectId),
  });

  const createMutation = useMutation({
    mutationFn: () => createChatSession(subjectId),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chatSessions(subjectId) });
      router.push(`/subjects/${subjectId}/chat/${session.id}`);
    },
    onError: (err) => toast.error(describeError(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: (sessionId: string) => deleteChatSession(subjectId, sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chatSessions(subjectId) });
      toast.success("Conversation deleted.");
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Your own conversations - private to you, even from your teacher.</p>
        <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
          {createMutation.isPending ? <Spinner className="size-4 text-current" /> : <Plus />}
          New conversation
        </Button>
      </div>

      {isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {isError && <p className="text-sm text-destructive">{describeError(error)}</p>}

      {sessions && sessions.length === 0 && (
        <StateCard
          icon={MessageSquare}
          title="No conversations yet"
          description="Start one to ask questions grounded in this subject's documents."
        />
      )}

      {sessions && sessions.length > 0 && (
        <div className="flex flex-col gap-2">
          {sessions.map((session) => (
            <Card
              key={session.id}
              className="cursor-pointer transition-colors hover:border-primary/50"
              onClick={() => router.push(`/subjects/${subjectId}/chat/${session.id}`)}
            >
              <CardContent className="flex items-center justify-between gap-4 py-4">
                <div className="min-w-0">
                  <p className="truncate font-medium">{session.title ?? "New conversation"}</p>
                  <p className="text-xs text-muted-foreground">
                    Updated {new Date(session.updated_at).toLocaleString()}
                  </p>
                </div>
                <div onClick={(e) => e.stopPropagation()}>
                  <ConfirmDialog
                    trigger={
                      <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive">
                        <Trash2 />
                      </Button>
                    }
                    title="Delete this conversation?"
                    description="Removes the session and its full message history."
                    onConfirm={() => deleteMutation.mutateAsync(session.id)}
                  />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
