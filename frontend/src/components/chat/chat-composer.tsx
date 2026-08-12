"use client";

import { useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";

/** The chat input box, split out of the session page on purpose: `input`
 * used to live as state on the page component that also renders the whole
 * message list, so every keystroke re-rendered every ChatMessageBubble
 * (each running a full ReactMarkdown + math/TikZ/SVG parse) along with it -
 * cost scaling with conversation length, which is what made typing feel
 * slower the more messages there were. Owning `input` here instead means a
 * keystroke only re-renders this small component - the message list next
 * to it isn't touched at all.
 */
export function ChatComposer({
  onSubmit,
  disabled,
}: {
  onSubmit: (question: string) => void;
  disabled: boolean;
}) {
  const [input, setInput] = useState("");

  function submit() {
    const question = input.trim();
    if (!question || disabled) return;
    setInput("");
    onSubmit(question);
  }

  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <Textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="Ask a question..."
        maxLength={4000}
        // text-base (16px), not the Textarea default text-sm (14px): iOS
        // Safari auto-zooms the whole page in when focusing any input
        // whose computed font-size is under 16px - on a phone, that's a
        // jarring zoom-and-shift the instant you tap the box, which can
        // itself push the input out of the visible area right when you're
        // about to type. 16px is the documented threshold that avoids it.
        // min-h-11/size-11 on this and the button below match each other
        // and clear the ~44px minimum comfortable touch-target size.
        className="min-h-11 resize-none text-base"
        disabled={disabled}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <Button type="submit" size="icon" className="size-11 shrink-0" disabled={disabled || !input.trim()}>
        {disabled ? <Spinner className="size-4 text-current" /> : <Send />}
      </Button>
    </form>
  );
}
