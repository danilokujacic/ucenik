import { authorizedRequest } from "@/lib/api/client";
import type { ChatDoneEvent, ChatErrorEvent } from "@/lib/types/api";

/**
 * POST .../messages returns `text/event-stream`, not JSON - the browser's
 * native EventSource can't be used at all (GET-only, no body, no custom
 * headers - spec §1), so this is a hand-rolled fetch + ReadableStream
 * reader that parses `event:`/`data:` frames itself.
 */
export type ChatStreamEvent =
  | { event: "token"; data: { content: string } }
  | { event: "done"; data: ChatDoneEvent }
  | { event: "error"; data: ChatErrorEvent };

function parseFrame(frame: string): ChatStreamEvent | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }
  if (!event || dataLines.length === 0) return null;
  const data = JSON.parse(dataLines.join("\n"));
  return { event, data } as ChatStreamEvent;
}

export async function* streamChatAnswer(
  subjectId: string,
  sessionId: string,
  question: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const res = await authorizedRequest(`/subjects/${subjectId}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    body: { question },
    signal,
  });

  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line.
      let separatorIndex: number;
      while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);
        const parsed = parseFrame(frame);
        if (parsed) yield parsed;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
