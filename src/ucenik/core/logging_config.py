"""Structured JSON logging - one JSON object per line, so Promtail/Loki can
parse fields (level, event, tokens_total, ...) as queryable LogQL labels
instead of treating logs as opaque text. See observability/promtail-config.yaml
for the parsing side, docs/observability.md for how to query it in Grafana.

Usage: call configure_logging() once at startup (main.py). Elsewhere, log
structured events via the `extra` kwarg:

    logger.info("ingest.completed", extra={"event": "ingest.completed",
                                            "document_id": str(doc.id),
                                            "chunk_count": len(chunks)})
"""

import json
import logging
import sys
from datetime import UTC, datetime

# Computed from a blank LogRecord rather than hand-listed, so it stays
# correct across Python versions instead of silently drifting.
_BASE_LOG_RECORD_ATTRS = set(logging.makeLogRecord({}).__dict__.keys())


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _BASE_LOG_RECORD_ATTRS or key in payload:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except TypeError:
                payload[key] = str(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Noisy at INFO by default; not useful for our dashboards.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
