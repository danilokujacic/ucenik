"""Shared notation contract for every LLM prompt whose output ends up
rendered by frontend/src/lib/markdown/renderer.tsx's `LectureContent`
component - lecture generation/refine (rag/refiner.py) *and* Tutor chat
answers (rag/generator.py). One constant so the two prompts can't drift
apart from each other or from what the renderer actually supports.

What the renderer supports, and nothing more (see renderer.tsx):
  - GFM markdown (remark-gfm) - headings, lists, tables, bold/italic, etc.
  - Math (remark-math + rehype-katex) - inline `$...$`, display `$$...$$`.
  - ```tikz fenced blocks, compiled client-side to SVG via tikzjax.
  - ```svg fenced blocks, inserted as raw markup (sanitized with DOMPurify).
  - Any other fenced code block (```python, ...) - plain <pre>, no syntax
    highlighter wired up, so a language tag doesn't change how it looks.
  - No image component override - a markdown image (`![...](...)`) just
    becomes a plain <img> pointed at whatever the model wrote, and there's
    no image-generation or asset-upload step anywhere in this pipeline to
    have put a real file at that URL. Broken image, every time.

Update this docstring (and the instructions below) if renderer.tsx's
supported set changes - it's the frontend source of truth this is meant to
track.
"""

CONTENT_FORMATTING_INSTRUCTIONS = (
    "Formatting: this is rendered as markdown with math and diagram "
    "support, not plain text - use the actual notation below instead of a "
    "plain-text stand-in for it. "
    "Math: LaTeX, wrapped in $...$ for inline or $$...$$ for a standalone "
    "equation - never written as plain prose outside those delimiters. "
    "Use real LaTeX commands for structure, not flattened-to-one-line "
    "approximations: superscripts with ^ ($x^2$, $x^{10}$), subscripts "
    "with _ ($\\log_2 x$, $a_{n+1}$), fractions with \\frac{a}{b} (never "
    "a/b - e.g. $\\frac{1}{2}$), roots with \\sqrt{...} or \\sqrt[n]{...} "
    "($\\sqrt{x}$, $\\sqrt[3]{8}$), and logarithms with \\log, \\ln, or "
    "\\log_b ($\\log_2(x)$, $\\ln(x)$) - braces {} group anything more "
    "than a single character in an exponent or subscript. "
    "Diagrams, shapes, and drawings - ALWAYS use LaTeX TikZ, with no "
    "exception, for anything visual/spatial: geometric shapes and figures, "
    "graphs and plots, number lines, coordinate planes, flowcharts, trees, "
    "circuits, or any other drawing, no matter how simple. Put it in a "
    "```tikz fenced code block (preferred), or a ```svg fenced code block "
    "only if TikZ genuinely can't express it. Never fall back to ASCII "
    "art (dashes, slashes, pipes, spaces standing in for lines and shapes) "
    "and never a plain-text description standing in for the actual "
    "drawing - not even for a single triangle, circle, or line segment. If "
    "asked to draw or show something visual, always draw it with TikZ, "
    "never describe it in words instead. A ```tikz block's content must "
    "be a COMPLETE \\begin{tikzpicture} ... \\end{tikzpicture} "
    "environment, never bare \\draw/\\node/\\fill commands on their own - "
    "those aren't valid standalone LaTeX and won't render, only the full "
    "environment will (e.g. \\begin{tikzpicture}\\draw (0,0) circle "
    "(1cm);\\end{tikzpicture}, not just \\draw (0,0) circle (1cm);). "
    "On the rare chance you still end up sketching something in "
    "plain-text/ASCII characters despite all of the above, it MUST go "
    "inside a fenced code block (```) - never as bare paragraph text. "
    "Outside a fenced block, whitespace gets collapsed and every line's "
    "alignment is destroyed, so unfenced ASCII art always renders as "
    "garbage; inside one, spacing is preserved exactly as written. This "
    "is a last-resort fallback, not a substitute for using TikZ. "
    "Code or pseudocode: a fenced code block with a language tag "
    "(```python, ```text, ...). "
    "Images: never include an image (markdown image syntax, an <img> tag, "
    "or a link to an image file) - nothing generates or hosts a real image "
    "here, so it can only point at something that doesn't exist. Use a "
    "TikZ or SVG diagram instead wherever a picture would otherwise help."
)
