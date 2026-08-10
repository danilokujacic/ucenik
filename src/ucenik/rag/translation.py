"""Thin wrapper over the LLM proxy for translating lecture content (§Phase
8), wired into rag/refiner.py's "translate" transform. Kept as its own file
(mirroring docs/roadmap.md's Phase 8 layout) rather than folded straight
into refiner.py - translation has a genuinely different concern (preserving
structure/formatting across a language boundary) that could need its own
tuning independent of the shorten/extend/regenerate transforms.
"""

from ucenik.llm.proxy_client import CompletionResult, complete

_SYSTEM_PROMPT = (
    "Translate the lecture content below into {language}. Preserve all "
    "structure exactly: headings, lists, and especially LaTeX math ($...$ "
    "inline, $$...$$ display) and TikZ/SVG code blocks must be carried over "
    "completely unchanged, not translated or reformatted - translate only "
    "the natural-language prose around them. Respond with ONLY the "
    "translated content, no preamble or explanation."
)


async def translate_content(content: str, target_language: str) -> CompletionResult:
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT.format(language=target_language)},
        {"role": "user", "content": content},
    ]
    return await complete(messages, temperature=0.3)
