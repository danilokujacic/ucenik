"""Contextual retrieval - an LLM generates a short blurb situating each chunk
within its source document, prepended before embedding.

Anthropic's "Contextual Retrieval" technique: a chunk like "it grew 3% that
quarter" is meaningless alone; prepending something like "This chunk is from
Q2 2024 earnings, discussing regional revenue" gives the embedding an actual
anchor for what the chunk is about.

Caveat worth remembering: the reference implementation relies on prompt
caching (send the whole document once, cheaply reuse it across every chunk's
call) to keep this affordable. llm/proxy_client.py is a plain request/response
wrapper with no caching support yet, so this sends the (truncated) document
text on every single chunk call - real latency/cost per document, and the
reason ingest has to run as a background job (see docs/rag-notes.md). Revisit
once the proxy contract supports caching.
"""

from ucenik.llm.proxy_client import complete

_MAX_DOCUMENT_CHARS = 8000  # crude cap until the proxy supports prompt caching

_SYSTEM_PROMPT = (
    "You situate a short excerpt within its source document, for the sole "
    "purpose of improving search retrieval of that excerpt. Answer with "
    "ONLY the succinct context - one or two sentences, no preamble, no "
    "restating the excerpt itself."
)


def _build_prompt(document_text: str, chunk_text: str) -> list[dict[str, str]]:
    truncated_doc = document_text[:_MAX_DOCUMENT_CHARS]
    user_prompt = (
        f"<document>\n{truncated_doc}\n</document>\n\n"
        "Here is the chunk to situate within the document:\n"
        f"<chunk>\n{chunk_text}\n</chunk>\n\n"
        "Give a short, succinct context (1-2 sentences) situating this chunk "
        "within the overall document, to improve search retrieval of the chunk."
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


async def generate_context(document_text: str, chunk_text: str) -> str:
    """Returns a short blurb to prepend to `chunk_text` before embedding."""
    messages = _build_prompt(document_text, chunk_text)
    return await complete(messages, temperature=0.0, max_tokens=100)


def apply_context(context: str, chunk_text: str) -> str:
    """Combine the generated context with the original chunk text - this is
    what actually gets embedded, not the raw chunk alone.
    """
    context = context.strip()
    if not context:
        return chunk_text
    return f"{context}\n\n{chunk_text}"
