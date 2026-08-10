"use client";

import { useCallback, useRef, useState } from "react";
import { streamChatAnswer } from "@/lib/chat/sse";
import type { ChatDoneEvent } from "@/lib/types/api";

/** State machine mirrors spec §3.5 point 4: streaming -> answered | failed,
 * exactly one of the two terminal events ends a turn. */
export type ChatStreamState =
  | { status: "idle" }
  | { status: "streaming"; content: string }
  | { status: "answered"; content: string; done: ChatDoneEvent }
  | { status: "failed"; content: string; error: string };

export function useChatStream(subjectId: string, sessionId: string) {
  const [state, setState] = useState<ChatStreamState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  const ask = useCallback(
    async (question: string, onDone?: (data: ChatDoneEvent) => void) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setState({ status: "streaming", content: "" });

      try {
        for await (const evt of streamChatAnswer(subjectId, sessionId, question, controller.signal)) {
          if (evt.event === "token") {
            setState((prev) => ({
              status: "streaming",
              content: (prev.status === "streaming" ? prev.content : "") + evt.data.content,
            }));
          } else if (evt.event === "done") {
            setState((prev) => {
              const content = prev.status === "streaming" ? prev.content : "";
              return { status: "answered", content, done: evt.data };
            });
            onDone?.(evt.data);
            return;
          } else if (evt.event === "error") {
            setState((prev) => ({
              status: "failed",
              content: prev.status === "streaming" ? prev.content : "",
              error: evt.data.detail,
            }));
            return;
          }
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setState({
          status: "failed",
          content: "",
          error: err instanceof Error ? err.message : "the Tutor is temporarily unavailable, please try again",
        });
      }
    },
    [subjectId, sessionId],
  );

  const reset = useCallback(() => setState({ status: "idle" }), []);

  return { state, ask, reset };
}
