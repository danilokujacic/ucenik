"use client";

import { Children, isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { TikzBlock } from "@/lib/markdown/tikz-block";
import { SvgBlock } from "@/lib/markdown/svg-block";

function extractLanguage(className?: string): string | undefined {
  return /language-(\w+)/.exec(className ?? "")?.[1];
}

function extractText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return extractText(node.props.children);
  return "";
}

/**
 * Renders lecture content: markdown + LaTeX (`$...$` / `$$...$$`) +
 * ```tikz / ```svg diagram blocks (spec §3.6 point 10). Plain markdown
 * alone would show raw LaTeX/TikZ source instead of the rendered thing.
 */
export function LectureContent({ content }: { content: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none prose-pre:bg-muted prose-pre:text-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          pre({ children, ...props }) {
            const child = Children.toArray(children)[0];
            const className = isValidElement<{ className?: string }>(child) ? child.props.className : undefined;
            const lang = extractLanguage(className);

            if (lang === "tikz" || lang === "svg") {
              const text = extractText(child).replace(/\n$/, "");
              return lang === "tikz" ? <TikzBlock source={text} /> : <SvgBlock source={text} />;
            }

            // Explicit, not relying on the browser's <pre> default: this is
            // the fallback for any fenced block that isn't tikz/svg,
            // including a last-resort ASCII-art diagram if the model ever
            // ignores the "always use TikZ" instruction (rag/formatting.py)
            // - alignment there depends entirely on whitespace surviving
            // exactly as written.
            return (
              <pre {...props} className={`${props.className ?? ""} whitespace-pre overflow-x-auto`}>
                {children}
              </pre>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
