"""Sanitizes exceptions caught in background jobs (document ingest -
rag/ingest.py; Planner generate/refine - workers/planner_tasks.py) before
they're written to a `*.error` field and read straight back through a plain
GET response (DocumentPublic.error / LecturePublic.error).

Unlike an HTTP-request failure (errors/handlers.py), there's no active
request/response cycle here to redact anything at - by the time a caller
GETs the resource and sees `error`, the job that failed is long gone. So the
job itself has to decide up front what's safe to hand an end user: an LLM
proxy outage or "OCR isn't implemented yet" are implementation/infra details
for whoever operates this thing to go fix, not something a teacher uploading
a document needs explained to them. `logger.exception`/`logger.warning` at
every call site already captures the real `str(exc)` in full - this
function only controls the copy a user actually sees.
"""

from ucenik.errors.service import QuotaExceededError
from ucenik.llm.proxy_client import LLMProxyError
from ucenik.rag.extractor import UnsupportedDocumentError

_LLM_PROXY_UNAVAILABLE = "Processing is temporarily unavailable. Please try again shortly."
_NO_EXTRACTABLE_TEXT = "No readable text could be found in this document."
_GENERIC = "An unexpected error occurred. Please try again."


def safe_job_error_message(exc: Exception) -> str:
    if isinstance(exc, LLMProxyError):
        return _LLM_PROXY_UNAVAILABLE
    if isinstance(exc, UnsupportedDocumentError):
        return _NO_EXTRACTABLE_TEXT
    if isinstance(exc, QuotaExceededError):
        # About the user's own usage, not an internal/infra detail - unlike
        # the cases above, this one *is* theirs to know about verbatim.
        return str(exc)
    return _GENERIC
