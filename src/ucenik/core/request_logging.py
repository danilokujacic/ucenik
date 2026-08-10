"""HTTP access logging - one structured event per request, feeding the
requests/errors/latency Grafana panels (see docs/observability.md).
"""

import logging
import time

from fastapi import FastAPI, Request

logger = logging.getLogger("ucenik.access")


def register_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "http.request",
            extra={
                "event": "http.request",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response
