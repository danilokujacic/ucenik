import { memo } from "react";
import { FileText } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { LectureContent } from "@/lib/markdown/renderer";
import type { ChatSource } from "@/lib/types/api";

// memo()'d: a bubble's own content/sources/role rarely change once
// rendered (the one exception is the live streaming bubble, whose content
// grows on purpose - memo doesn't stop that, it just skips work when
// nothing actually changed). Without this, every already-persisted message
// re-runs LectureContent's full ReactMarkdown + remark-math/rehype-katex
// parse whenever the parent page re-renders for an unrelated reason (e.g.
// every keystroke in the chat input, before that was moved into its own
// component - see ChatComposer) - cost scales with message count, which is
// exactly what made typing feel slower the longer a conversation got.
export const ChatMessageBubble = memo(function ChatMessageBubble({
  role,
  content,
  sources,
}: {
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
}) {
  const isUser = role === "user";

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <Avatar className="mt-0.5 size-7 shrink-0">
        <AvatarFallback className="text-[10px]">{isUser ? "You" : "AI"}</AvatarFallback>
      </Avatar>
      {/* max-w-[90%] on small screens, [80%] from sm: up - 80% of a narrow
          phone screen wastes proportionally more space than 80% of a
          desktop viewport does. */}
      <div className={`flex max-w-[90%] flex-col gap-2 sm:max-w-[80%] ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={
            isUser
              ? "rounded-2xl rounded-tr-sm bg-primary px-4 py-2 text-sm text-primary-foreground"
              : "rounded-2xl rounded-tl-sm bg-secondary px-4 py-2 text-sm"
          }
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{content}</p>
          ) : (
            <LectureContent content={content} />
          )}
        </div>

        {!isUser && sources && (
          <SourcesRow sources={sources} />
        )}
      </div>
    </div>
  );
});

function SourcesRow({ sources }: { sources: ChatSource[] }) {
  if (sources.length === 0) {
    // Spec §3.5 point 5: honest "I don't know" - shown distinctly, not as
    // an equally-confident, citation-free answer.
    return (
      <p className="px-1 text-xs text-muted-foreground italic">
        No source material found for this in the subject&apos;s documents.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap gap-1 px-1">
      {sources.map((s, i) => (
        <Badge key={`${s.document_id}-${i}`} variant="outline" className="gap-1">
          <FileText className="size-3" />
          {s.source_filename}
        </Badge>
      ))}
    </div>
  );
}
