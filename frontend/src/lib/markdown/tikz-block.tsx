"use client";

import { useEffect, useRef, useState } from "react";
import { loadTikzJax, triggerTikzRender } from "@/lib/markdown/tikz-loader";
import { Spinner } from "@/components/ui/spinner";

const RENDER_TIMEOUT_MS = 8000;

// Chat answers stream in token-by-token (see use-chat-stream.ts), and
// ReactMarkdown re-parses the whole growing message on every token - so
// while a ```tikz block is still being generated, `source` here changes
// dozens of times before it's actually complete/valid TikZ. Without this
// debounce, every one of those partial (often syntactically broken, e.g.
// missing \end{tikzpicture}) sources would kick off its own real tikzjax
// compile attempt; tikzjax has no way to cancel a job we've already
// abandoned client-side, so a fast-streaming block can flood it with a
// backlog of stale compiles that's still being worked through by the time
// the actual final source arrives - burning through RENDER_TIMEOUT_MS on
// jobs that were never going to be shown, not the one that matters. Only
// spending a real attempt once `source` has been unchanged for this long
// sidesteps that entirely.
//
// Deliberately unconditional - an earlier version skipped the debounce on
// a component's first render (to avoid latency for the common static
// case: a persisted message, lecture content). That assumed a mounted
// TikzBlock instance persists across a message's re-parses during
// streaming, so only the *first* mount is "fresh." Verified against a
// real streaming answer that assumption doesn't hold: react-markdown can
// reasonably remount the element (its position in the tree shifts as
// surrounding content grows), so *every* remount saw isFirstRun=true and
// skipped the debounce - reproducing the exact flooding this was meant to
// prevent. Debouncing unconditionally costs one render's worth of latency
// (~500ms) even in the static case, which is a fair trade against a
// diagram that silently never renders.
const SOURCE_STABLE_DEBOUNCE_MS = 500;

// Real-world failure mode (found by actually reproducing "renderer
// unavailable" against a live LLM answer, not guessed): the model
// sometimes emits bare \draw/\node/\fill commands without the
// \begin{tikzpicture}...\end{tikzpicture} environment they have to live
// inside - not valid standalone LaTeX, so tikzjax never produces an <svg>
// no matter how long you wait. rag/formatting.py's CONTENT_FORMATTING_
// INSTRUCTIONS now tells the model to always include the wrapper, but an
// instruction is never a guarantee - this is the belt to that prompt's
// suspenders, so one model slip-up doesn't still end up as a dead diagram.
function ensureTikzpictureEnvironment(source: string): string {
  if (source.includes("\\begin{tikzpicture}")) return source;
  return `\\begin{tikzpicture}\n${source}\n\\end{tikzpicture}`;
}

/** Renders a ```tikz fenced block (spec §3.6 point 10) via tikzjax. Doesn't
 * trust any specific completion event from the (minified, third-party)
 * library - watches its own container for an <svg> to appear and times out
 * to the raw source rather than spinning forever if the CDN is unreachable
 * or the source doesn't compile. */
export function TikzBlock({ source }: { source: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "rendered" | "failed">("loading");
  // null until the debounce settles at least once - the render-attempt
  // effect below waits for a real value, so a fresh mount never fires a
  // compile attempt against a `source` that's about to change again.
  const [debouncedSource, setDebouncedSource] = useState<string | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebouncedSource(source), SOURCE_STABLE_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [source]);

  useEffect(() => {
    if (debouncedSource === null) return;

    let cancelled = false;
    let observer: MutationObserver | undefined;
    let timeoutId: ReturnType<typeof setTimeout>;

    loadTikzJax()
      .then(() => {
        if (cancelled || !containerRef.current) return;

        const el = document.createElement("script");
        el.type = "text/tikz";
        el.text = ensureTikzpictureEnvironment(debouncedSource);
        containerRef.current.replaceChildren(el);
        // tikzjax has no ongoing watcher for newly-inserted tags in an SPA
        // - see tikz-loader.ts's triggerTikzRender() docstring for why this
        // call is required, not optional.
        triggerTikzRender();

        observer = new MutationObserver(() => {
          if (containerRef.current?.querySelector("svg")) {
            setState("rendered");
            observer?.disconnect();
            clearTimeout(timeoutId);
          }
        });
        observer.observe(containerRef.current, { childList: true, subtree: true });

        timeoutId = setTimeout(() => {
          if (!cancelled && !containerRef.current?.querySelector("svg")) setState("failed");
        }, RENDER_TIMEOUT_MS);
      })
      .catch(() => {
        if (!cancelled) setState("failed");
      });

    return () => {
      cancelled = true;
      observer?.disconnect();
      clearTimeout(timeoutId);
    };
  }, [debouncedSource]);

  if (state === "failed") {
    return (
      <div className="my-4 rounded-md border border-border bg-muted/50 p-3">
        <p className="mb-2 text-xs text-muted-foreground">Diagram source (TikZ) - renderer unavailable</p>
        <pre className="overflow-x-auto text-xs">
          <code>{source}</code>
        </pre>
      </div>
    );
  }

  return (
    <div className="tikz-diagram relative">
      {state === "loading" && (
        <div className="flex min-h-16 items-center justify-center">
          <Spinner />
        </div>
      )}
      <div ref={containerRef} />
    </div>
  );
}
