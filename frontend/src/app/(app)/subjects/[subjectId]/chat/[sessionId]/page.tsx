"use client";

import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RotateCcw } from "lucide-react";
import { listChatMessages } from "@/lib/api/chat";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { useChatStream } from "@/lib/chat/use-chat-stream";
import { ChatMessageBubble } from "@/components/chat/chat-message-bubble";
import { ChatComposer } from "@/components/chat/chat-composer";
import { StateCard } from "@/components/shared/state-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";

export default function ChatSessionPage({
  params,
}: {
  params: Promise<{ subjectId: string; sessionId: string }>;
}) {
  const { subjectId, sessionId } = use(params);
  const queryClient = useQueryClient();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);

  const { data: messages, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.chatMessages(subjectId, sessionId),
    queryFn: () => listChatMessages(subjectId, sessionId),
  });

  const { state, ask, reset } = useChatStream(subjectId, sessionId);

  async function submit(question: string) {
    if (!question.trim() || state.status === "streaming") return;
    setLastQuestion(question);
    await ask(question, () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chatMessages(subjectId, sessionId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.chatSessions(subjectId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.quota() });
      reset();
    });
  }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, state]);

  return (
    <div className="flex h-[calc(100vh-13rem)] flex-col gap-4">
      <Link
        href={`/subjects/${subjectId}/chat`}
        className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> Conversations
      </Link>

      <div ref={scrollRef} className="flex-1 overflow-y-auto rounded-lg border border-border bg-card p-4">
        {isLoading && (
          <div className="flex flex-col gap-4">
            <Skeleton className="h-12 w-2/3" />
            <Skeleton className="ml-auto h-12 w-2/3" />
          </div>
        )}

        {isError && <p className="text-sm text-destructive">{describeError(error)}</p>}

        {messages && messages.length === 0 && state.status === "idle" && (
          <StateCard title="Ask anything about this subject" description="Answers are grounded in its ingested documents, with sources cited." />
        )}

        <div className="flex flex-col gap-6">
          {messages?.map((m) => (
            <ChatMessageBubble key={m.id} role={m.role} content={m.content} sources={m.role === "assistant" ? m.sources : undefined} />
          ))}

          {state.status === "streaming" && (
            <ChatMessageBubble role="assistant" content={state.content || "…"} />
          )}

          {state.status === "failed" && (
            <div className="flex flex-col gap-2">
              <Alert variant="destructive">
                <AlertDescription>{state.error}</AlertDescription>
              </Alert>
              <Button
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() => lastQuestion && submit(lastQuestion)}
              >
                <RotateCcw /> Retry
              </Button>
            </div>
          )}
        </div>
      </div>

      <ChatComposer onSubmit={submit} disabled={state.status === "streaming"} />
    </div>
  );
}
