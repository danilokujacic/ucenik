"""Shared prompt-injection hardening for every RAG prompt that embeds
untrusted content (uploaded documents, retrieved chunks) inside an LLM
prompt - rag/generator.py's <context>, rag/contextualizer.py's <document>/
<chunk>, rag/refiner.py's <context>. See docs/security-hardening.md for
the full writeup, including what this does and doesn't defend against -
short version: both layers below are risk *reduction*, not elimination.
Prompt-based defenses can still be argued with by a sufficiently
adversarial document; there's no technical control here that makes that
structurally impossible.

Two independent layers:

1. Randomized delimiter tags, not the same static "<context>" string on
   every single request. This app's source is public - the exact tag name
   an attacker would need to "close" early (so whatever text follows reads
   to the model as a new, trusted instruction rather than more untrusted
   data) is otherwise sitting in the repo for anyone to read, for free, no
   guessing required. A random tag per request means a payload crafted in
   advance (e.g. baked into an uploaded document ahead of time, before the
   tag name for THIS request even exists) can't reliably target the real
   tag.

2. A lightweight, logging-only detector for common injection phrasing.
   Deliberately never blocks - a course document *about* prompt injection
   as a security topic would otherwise trip a false positive on completely
   legitimate content - but gives ops visibility into how often this is
   actually being attempted, which nothing currently surfaces at all.
   Being logging-only (not a filter) is also why this list can afford to
   be broad rather than narrowly tuned - a false positive just costs one
   extra log line, not a rejected legitimate document.
"""

import logging
import re
import secrets

logger = logging.getLogger(__name__)

# Deliberately broad (see module docstring on why a false positive is
# cheap here) - grouped by the technique each line is aimed at, not just
# a flat word list, so this stays legible as it grows rather than turning
# into an unreadable wall of alternation.
_SUSPICIOUS_PATTERNS = re.compile(
    "|".join(
        [
            # Direct instruction override
            r"ignore (all |any )?(the )?(above|previous|prior|preceding) instructions?",
            r"disregard (all |any )?(the )?(above|previous|prior|preceding)",
            r"forget (all |everything|what)(\s\w+){0,3}\s(instructions?|told|programmed)",
            r"new instructions?\s*:",
            r"do not follow (your |the )?(system )?instructions?",
            r"override (your |the )?(instructions?|programming|restrictions?|guidelines?|rules?)",
            # Role hijacking
            r"you are now\b",
            r"from now on,?\s*you\s",
            r"pretend (you are|to be)\b",
            r"act as (if|though)\b",
            r"roleplay as\b",
            r"simulate a (mode|version|persona)\b",
            # Prompt/system-prompt extraction
            r"reveal (your |the )?(system )?(prompt|instructions?)",
            r"(print|show|output|repeat) (your |the )?(system )?(prompt|instructions?)",
            r"(repeat|output) the (words?|text) above",
            r"what (is|are) your (system )?(prompt|instructions?)",
            r"end (of )?(system )?(prompt|instructions?)",
            # Jailbreak / restriction-bypass framing
            r"\bjailbreak\b",
            r"\bdan\b.{0,20}\bdo anything now\b",
            r"(developer|admin|god|unrestricted)\s+mode\b",
            r"bypass (your |the )?(safety|restrictions?|guidelines?|rules?|filters?)",
            r"without (any )?(restrictions?|limitations?|filters?)\b",
            r"no (restrictions?|limitations?|filters?|rules?) (apply|anymore)",
        ]
    ),
    re.IGNORECASE,
)


def random_tag(label: str) -> str:
    """A per-call delimiter tag name, e.g. random_tag("context") ->
    "context_3f9a1c2b8e7d4a10" - unpredictable ahead of time, unlike a
    fixed "<context>" string that's identical on every request and visible
    in this (public) repo's source to begin with.
    """
    return f"{label}_{secrets.token_hex(8)}"


def flag_if_suspicious(text: str, *, source: str) -> None:
    """Logs (never raises/blocks) if `text` contains common prompt-
    injection phrasing. `source` identifies where this text came from
    (e.g. "chat_context", "document_chunk") for the log event - see
    docs/observability.md for querying these in Grafana.
    """
    if _SUSPICIOUS_PATTERNS.search(text):
        logger.warning(
            "prompt_safety.suspicious_content",
            extra={"event": "prompt_safety.suspicious_content", "source": source, "char_count": len(text)},
        )
