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
    "with _ ($a_{n+1}$), roots with \\sqrt{...} or \\sqrt[n]{...} "
    "($\\sqrt{x}$, $\\sqrt[3]{8}$) - braces {} group anything more than a "
    "single character in an exponent or subscript. "
    "Fractions: ALWAYS \\frac{numerator}{denominator} inside math "
    "delimiters (e.g. $\\frac{2}{3}$, $\\frac{x+1}{2}$), with no "
    "exception, so it renders as a real stacked/vertical fraction - NEVER "
    "a flat slash like 2/3 or x/2, whether inside $...$ or written as bare "
    "prose. A slash-written fraction is wrong even as a quick aside or "
    "inside a sentence - every fraction, no matter how simple (even "
    "1/2), goes through \\frac{}{}. "
    "Logarithms: ALWAYS \\log, \\ln, or \\log_b with the base as a proper "
    "LaTeX subscript, inside math delimiters ($\\log_2(x)$, "
    "$\\log_{10}(x)$, $\\ln(x)$) - never written as plain prose like "
    "\"log2(x)\" or \"log base 2 of x\", and never with the base typed as "
    "a flattened suffix instead of a real \\log_{...} subscript. "
    "Concrete example - WRONG: \"2/3 + 1/4 = 11/12\" and \"log_2(8) = 3\". "
    "RIGHT: \"$\\frac{2}{3} + \\frac{1}{4} = \\frac{11}{12}$\" and "
    "\"$\\log_2(8) = 3$\". This applies even when converting a calculation "
    "you're walking through step by step, and even if the source material "
    "you're drawing on writes it the plain way - your own answer always "
    "goes through the proper notation regardless of how the source is "
    "written. "
    "A multi-line $$...$$ block (a matrix, a system of equations, "
    "\\begin{cases}...\\end{cases}, aligned equations, anything spanning "
    "more than one line) MUST have both the opening $$ and the closing $$ "
    "on their own line, separate from the content - never place the "
    "closing $$ directly after the last line of content on the same line "
    "(e.g. never \\end{cases}$$ - write \\end{cases} then a newline then "
    "$$). The renderer's math parser only recognizes a closing $$ that's "
    "on its own line; get this wrong and it doesn't just break that one "
    "equation, it silently swallows everything after it in the response "
    "as part of the same broken block, unrendered, for the rest of the "
    "message. A single-line $$...$$ with no line breaks inside it "
    "doesn't have this requirement. "
    "Never narrate, mention, or comment on the notation or tooling you're "
    "using to produce part of the answer - no \"here is a diagram drawn "
    "in TikZ\", \"I'll use LaTeX for this\", \"as SVG code below\", \"using "
    "a table to show this\", or similar. Present the math, diagram, or "
    "content directly, the way a textbook does - the notation is an "
    "implementation detail invisible to the student once rendered, not "
    "something to describe or draw attention to. "
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

# A short, separate reminder meant to be placed AFTER the retrieved-context
# block, not just once earlier in the system prompt alongside
# CONTENT_FORMATTING_INSTRUCTIONS. Verified live against a real model
# (Groq) that this genuinely matters, not just theory: with the formatting
# rules only stated once, before the context, a real chat answer came back
# with zero $ signs anywhere - flat "2/3", "log_2(8)" - despite the system
# prompt provably containing the \frac instruction. The context block
# itself is real course material, almost always plain text/no LaTeX, and
# it sits closer to where generation actually starts than the earlier
# instructions do - the model was evidently mirroring the source material's
# plain notation rather than the formatting rule stated earlier. Repeating
# the rule once more, positioned after the context (so it's the last thing
# read before the model starts writing its own answer), is what actually
# fixed it in testing.
CONTENT_FORMATTING_REMINDER = (
    "Reminder, regardless of how the material above is written: your OWN "
    "answer must still use $\\frac{a}{b}$ for every fraction and "
    "$\\log_b(x)$ for every logarithm - never a flat a/b or log_b(x) as "
    "plain text, even if the source material itself writes it that way. "
    "Converting plain notation into proper LaTeX in your answer is your "
    "job, not something to copy verbatim from the source."
)
