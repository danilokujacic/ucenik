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
  const contentRef = useRef<HTMLDivElement>(null);
  // Whether the viewport is currently at (or very near) the bottom of the
  // scrollable area - read by the ResizeObserver effect below to decide
  // whether new content should pull the view down with it. Starts true so
  // arriving on the page (or reopening a session) lands at the latest
  // message, matching the old effect's behavior for the initial render.
  const stickToBottomRef = useRef(true);
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

  // Tracks whether the user is currently scrolled near the bottom, so a
  // new token/diagram doesn't yank them back down if they've scrolled up
  // to reread something earlier - a deliberate UX call, not just a side
  // effect of the fix below.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    function onScroll() {
      if (!el) return;
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      stickToBottomRef.current = distanceFromBottom < 80;
    }
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Re-scrolls to bottom whenever the actual rendered content height
  // changes - not just when `messages`/`state` change. A streamed answer
  // containing a ```tikz/```svg block (rag/formatting.py) renders
  // asynchronously (tikz-block.tsx's own debounce + compile step can take
  // up to a few seconds) - well after the token that introduced the fenced
  // block already committed here. Scrolling only on [messages, state]
  // missed that: the diagram finishing later, and growing far taller than
  // its loading spinner, left the latest content below the visible area
  // with nothing left to trigger scrolling back down. A ResizeObserver on
  // the actual message-list wrapper catches every source of height change
  // uniformly - new tokens, KaTeX math, a diagram completing - instead of
  // this effect needing to know about each one individually.
  //
  // scrollTop = scrollHeight (instant), not scrollTo({behavior: "smooth"})
  // - the previous smooth-scroll call fired on every single token during
  // fast streaming, so a new call routinely interrupted the still-running
  // animation from the last one, and the visible position never quite
  // caught up to the true bottom until streaming paused. Production chat
  // UIs (this app's own inspiration included) pin instantly during active
  // streaming for exactly this reason.
  useEffect(() => {
    const content = contentRef.current;
    const container = scrollRef.current;
    if (!content || !container) return;
    const observer = new ResizeObserver(() => {
      if (!stickToBottomRef.current) return;
      container.scrollTop = container.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="flex h-[calc(100dvh-6.5rem)] flex-col gap-4">
      <Link
        href={`/subjects/${subjectId}/chat`}
        className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> Conversations
      </Link>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-border bg-card p-4">
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

        <div ref={contentRef} className="flex flex-col gap-6">
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
