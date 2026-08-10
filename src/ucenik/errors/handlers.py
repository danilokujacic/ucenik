"""Layer 3: map service-layer errors onto HTTP responses.

Registered once against the app in main.py. Anything that isn't a recognized
ServiceError is treated as a bug: logged with a full traceback and returned as
an opaque 500 - internals (stack traces, driver errors, ...) never leak to callers.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ucenik.errors.service import (
    DuplicateResourceError,
    ExternalServiceUnavailableError,
    InvalidCredentialsError,
    InvalidStateError,
    InvalidTokenError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitExceededError,
    ServiceError,
    TokenExpiredError,
    UnsupportedMediaTypeError,
)

logger = logging.getLogger(__name__)

_STATUS_BY_ERROR: dict[type[ServiceError], int] = {
    InvalidCredentialsError: 401,
    InvalidTokenError: 401,
    TokenExpiredError: 401,
    PermissionDeniedError: 403,
    NotFoundError: 404,
    DuplicateResourceError: 409,
    InvalidStateError: 409,
    PayloadTooLargeError: 413,
    UnsupportedMediaTypeError: 415,
    QuotaExceededError: 429,
    RateLimitExceededError: 429,
    ExternalServiceUnavailableError: 503,
}


def _status_for(exc: ServiceError) -> int:
    for exc_type, status_code in _STATUS_BY_ERROR.items():
        if isinstance(exc, exc_type):
            return status_code
    return 400


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError) -> JSONResponse:
        headers = {}
        # QuotaExceededError/RateLimitExceededError carry this; nothing
        # else does (getattr avoids an isinstance chain just to read one
        # optional field two error types happen to share).
        retry_after = getattr(exc, "retry_after_seconds", None)
        if retry_after is not None:
            headers["Retry-After"] = str(max(0, int(retry_after)))
        return JSONResponse(status_code=_status_for(exc), content={"detail": str(exc)}, headers=headers)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
