"use client";

import { useEffect, useRef, useState } from "react";
import { Spinner } from "@/components/ui/spinner";

/** Renders a ```svg fenced block (spec §3.6 point 10) inside a sandboxed
 * iframe rather than directly into the page - defense in depth beyond
 * DOMPurify sanitization alone (docs/security-hardening.md item 12).
 * Lecture/chat content ultimately comes from an LLM whose prompt can be
 * steered by a sufficiently adversarial uploaded document (see
 * rag/prompt_safety.py) - DOMPurify below is a real, meaningful first
 * layer (strips <script>, event-handler attributes, javascript: URIs), not
 * doing nothing, but a bypass in it (these do surface periodically - it's
 * actively maintained *because* they get found) executing directly in
 * this page's own origin would have real blast radius: JWTs live in
 * `localStorage` (lib/auth/token-storage.ts), readable by any same-origin
 * script.
 *
 * `sandbox="allow-scripts"` WITHOUT `allow-same-origin` is the safe
 * configuration here, not a compromise. The combination of *both* flags
 * together on one sandboxed iframe is what re-enables full parent-origin
 * access for scripts inside it - `allow-scripts` alone still gives the
 * iframe an *opaque* origin with zero access to this page's
 * DOM/cookies/localStorage, while letting a small in-iframe script run
 * (used below purely to measure and postMessage the rendered content's
 * height back, so the iframe sizes itself instead of guessing a fixed
 * value). Just as important: a hypothetical DOMPurify-bypassed <script>
 * smuggled through inside the "sanitized" SVG runs in that exact same
 * contained, origin-less sandbox too - it cannot reach `localStorage`
 * either, regardless of what it tries.
 *
 * A Content-Security-Policy inside the iframe's own document closes a
 * separate, smaller gap the sandbox attribute alone doesn't: DOMPurify's
 * SVG profile legitimately allows `<image href="...">` (real SVGs use
 * external/data images), which without a CSP could still fire a passive
 * tracking-pixel-style request to an attacker-chosen URL on render, no
 * script needed. `default-src 'none'` blocks any network fetch from
 * inside this document entirely.
 */
export function SvgBlock({ source }: { source: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [height, setHeight] = useState(64);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    let cancelled = false;
    import("dompurify").then(({ default: DOMPurify }) => {
      if (cancelled) return;
      setHtml(DOMPurify.sanitize(source, { USE_PROFILES: { svg: true, svgFilters: true } }));
    });
    return () => {
      cancelled = true;
    };
  }, [source]);

  // Correlated by contentWindow, not an id - the only reliable way to tell
  // which of possibly several SvgBlocks on the page a given message came
  // from, since the sandboxed iframe has no origin of its own to key on.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const reportedHeight = (event.data as { svgBlockHeight?: unknown } | null)?.svgBlockHeight;
      if (typeof reportedHeight === "number") {
        setHeight(Math.max(16, Math.ceil(reportedHeight)));
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  if (!html) {
    return (
      <div className="my-4 flex min-h-16 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  // Self-contained document - the sanitized SVG plus a small fixed
  // resize-reporting script, nothing fetched from anywhere. This is the
  // *only* script this sandbox ever runs beyond whatever might have
  // survived sanitization inside `html` itself.
  const srcDoc = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; script-src 'unsafe-inline'">
<style>html,body{margin:0;padding:0;display:flex;justify-content:center;overflow:hidden}svg{max-width:100%;height:auto}</style>
</head><body>${html}<script>
(function () {
  function report() { parent.postMessage({ svgBlockHeight: document.body.scrollHeight }, "*"); }
  report();
  new ResizeObserver(report).observe(document.body);
})();
</script></body></html>`;

  return (
    <iframe
      ref={iframeRef}
      title="Rendered diagram"
      srcDoc={srcDoc}
      sandbox="allow-scripts"
      className="my-4 w-full border-0"
      style={{ height }}
    />
  );
}
