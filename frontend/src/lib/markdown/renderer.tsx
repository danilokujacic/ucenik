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

// remark-math requires a multi-line $$...$$ block's closing $$ to be on its
// OWN line, separate from the preceding content - confirmed directly against
// the actual parser (not assumed): `$$\begin{cases}...\end{cases}$$` (closing
// $$ glued onto the same line as \end{cases}) makes it fail to recognize the
// close at all, and the "math" node it produces just keeps consuming
// everything afterward - every following line, list item, and inline $...$
// - until it eventually finds some other $$-shaped boundary, or runs out of
// content. rag/formatting.py's CONTENT_FORMATTING_INSTRUCTIONS now tells the
// model to always put both delimiters on their own line for multi-line math,
// but an instruction is never a guarantee (same reasoning as tikz-block.tsx's
// ensureTikzpictureEnvironment) - this normalizes it defensively regardless.
// Single-line $$...$$ (no internal newline) is left untouched - it already
// parses correctly as-is, and forcing it onto three lines would be a
// needless rewrite of something that was never broken.
function normalizeDisplayMath(content: string): string {
  return content.replace(/\$\$([\s\S]*?)\$\$/g, (match, inner: string) => {
    if (!inner.includes("\n")) return match;
    return `$$\n${inner.trim()}\n$$`;
  });
}

// rag/formatting.py's CONTENT_FORMATTING_INSTRUCTIONS tells the model to
// always write fractions as \frac{a}{b} and logarithms as \log_b(x), inside
// $...$ - verified live against the actual deployed model (Groq,
// llama-3.3-70b-versatile) that this instruction alone is NOT reliably
// followed once a RAG context block with plain-text math (e.g. course
// material extracted from a PDF, which is essentially never hand-written in
// LaTeX) is present: the model answers with flat "2/3", "log_2(8)" instead,
// even with the instruction repeated immediately after the context block.
// Backend post-processing isn't an option here either - rag/generator.py
// streams tokens to the browser live as they're generated (the whole
// point of the streaming UX), so there's no "wait for the full answer,
// then fix it" step available server-side without buffering the entire
// response and losing that live-typing effect. This is the deterministic
// fallback: pattern-match flat notation in the actual rendered text and
// rewrite it into real LaTeX before handing content to ReactMarkdown -
// same "an instruction is never a guarantee" reasoning as
// normalizeDisplayMath above, just for a different failure mode.
//
// Deliberately narrow, not a general slash-to-fraction converter: only
// N/N (pure digits on both sides) and log_B(...)/logB(...) - the two
// concrete shapes actually observed from the live model. Never touches
// anything already inside $...$/$$...$$ math delimiters or a fenced/inline
// code block (transformOutsideMathAndCode below skips those entirely) -
// getting this wrong inside a real code sample (`x = 1/2`) would be worse
// than leaving a flat fraction alone. The digit/digit rule also has a
// known, accepted false-positive: a bare two-part date-like "3/15" with no
// year reads identically to a fraction and there's no way to tell them
// apart from the text alone - a three-part date ("12/25/2024") is
// excluded via lookahead/lookbehind since that shape is unambiguous, but
// the two-part case is treated as a fraction, which is the right call in
// a math-tutoring context even if occasionally not what was meant.
function transformOutsideMathAndCode(content: string, transform: (text: string) => string): string {
  const protectedPattern = /\$\$[\s\S]*?\$\$|\$[^$\n]*?\$|```[\s\S]*?```|`[^`\n]*?`/g;
  let result = "";
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = protectedPattern.exec(content)) !== null) {
    result += transform(content.slice(lastIndex, match.index));
    result += match[0];
    lastIndex = match.index + match[0].length;
  }
  result += transform(content.slice(lastIndex));
  return result;
}

function fixFlatLogarithms(text: string): string {
  return text.replace(/\blog_?(\d+|\{[^}]+\})\(([^()]*)\)/g, (_match, base: string, arg: string) => {
    const cleanBase = base.replace(/[{}]/g, "");
    return `$\\log_{${cleanBase}}(${arg})$`;
  });
}

function fixFlatFractions(text: string): string {
  return text.replace(/(?<!\d\/)\b(\d+)\/(\d+)\b(?!\/)/g, (_match, num: string, den: string) => `$\\frac{${num}}{${den}}$`);
}

function normalizeFlatMath(content: string): string {
  return transformOutsideMathAndCode(content, (text) => fixFlatFractions(fixFlatLogarithms(text)));
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
          pre({ children, node, ...props }) {
            const child = Children.toArray(children)[0];
            const className = isValidElement<{ className?: string }>(child) ? child.props.className : undefined;
            const lang = extractLanguage(className);

            if (lang === "tikz" || lang === "svg") {
              const text = extractText(child).replace(/\n$/, "");
              // Stable across streaming re-renders even though `text` itself
              // changes on every token: react-markdown re-parses the whole
              // document into a fresh AST on every content change, and
              // without an explicit key React can end up unmounting and
              // remounting this element instead of just updating its
              // `source` prop as surrounding content shifts its position in
              // the tree - see tikz-block.tsx's own comment on that exact
              // remounting behavior. A remount wipes TikzBlock/SvgBlock's
              // internal render state (their debounce timer, their
              // loading/rendered/failed status) and restarts the whole
              // render cycle from scratch, which is what shows up as the
              // loading spinner blinking instead of settling. The fenced
              // block's start offset in the raw markdown source is stable
              // across re-renders (streaming only ever appends text, never
              // edits earlier characters), so it survives as a key even
              // while `text` keeps growing.
              const key = node?.position?.start.offset ?? text;
              return lang === "tikz" ? <TikzBlock key={key} source={text} /> : <SvgBlock key={key} source={text} />;
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
        {normalizeDisplayMath(normalizeFlatMath(content))}
      </ReactMarkdown>
    </div>
  );
}
