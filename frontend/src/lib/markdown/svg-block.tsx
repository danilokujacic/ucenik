"use client";

import { useEffect, useState } from "react";
import { Spinner } from "@/components/ui/spinner";

/** Renders a ```svg fenced block (spec §3.6 point 10). Sanitized with
 * DOMPurify before insertion - lecture content ultimately comes from an
 * LLM, and raw markup shouldn't be trusted by default. Loaded dynamically
 * so it never runs during SSR (DOMPurify needs a real `window`). */
export function SvgBlock({ source }: { source: string }) {
  const [html, setHtml] = useState<string | null>(null);

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

  if (!html) {
    return (
      <div className="my-4 flex min-h-16 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="my-4 flex justify-center [&_svg]:h-auto [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: html }} />
  );
}
