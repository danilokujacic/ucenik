"""Layer 2: business-rule errors, independent of transport and independent of the DB driver.

These are the only exceptions that should ever cross from api/ handlers into the
global exception handlers (see errors/handlers.py) - never a raw driver/pymongo
exception, and never a bare HTTPException raised ad hoc from a route.
"""

from beanie import PydanticObjectId


class ServiceError(Exception):
    """Base class for all service-layer errors."""


class InvalidCredentialsError(ServiceError):
    pass


class InvalidTokenError(ServiceError):
    pass


class TokenExpiredError(ServiceError):
    pass


class NotFoundError(ServiceError):
    def __init__(self, resource: str, identifier: str):
        self.resource = resource
        self.identifier = identifier
        super().__init__(f"{resource} not found: {identifier}")


class DuplicateResourceError(ServiceError):
    def __init__(self, resource: str, detail: str = ""):
        self.resource = resource
        message = f"{resource} already exists"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class PermissionDeniedError(ServiceError):
    pass


class UnsupportedMediaTypeError(ServiceError):
    pass


class PayloadTooLargeError(ServiceError):
    pass


class QuotaExceededError(ServiceError):
    def __init__(self, user_id: str, used: int, limit: int, retry_after_seconds: int | None = None):
        self.user_id = user_id
        self.used = used
        self.limit = limit
        # Read by errors/handlers.py to set a Retry-After header - see
        # core/quota.py's caller for how this is computed (seconds until
        # the daily counter resets at UTC midnight).
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"quota exceeded: {used}/{limit} tokens used today")


class RateLimitExceededError(ServiceError):
    def __init__(self, message: str, retry_after_seconds: int | None = None):
        # Read by errors/handlers.py (and core/rate_limit.py's middleware,
        # which constructs its own response rather than going through the
        # handler - see that file) to set a Retry-After header.
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class InvalidStateError(ServiceError):
    """Raised when an action isn't valid for a resource's current state -
    e.g. refining a Planner lecture that hasn't finished its first
    generation yet, or is already mid-generation. Distinct from
    DuplicateResourceError (a uniqueness violation, not a state problem).
    """


class ExternalServiceUnavailableError(ServiceError):
    """Raised when a downstream dependency (currently: the LLM proxy) fails
    for a live request/response endpoint that has no better way to degrade.
    Distinct from the two other places an LLM failure is already handled:
    the chat SSE flow (services/chat.py reports it as an "error" stream
    event, since headers are already sent) and background jobs
    (errors/user_messages.py sanitizes it into a job's `error` field). This
    is for everything else - a plain endpoint that can still return a
    normal HTTP error.
    """


def parse_object_id(resource: str, identifier: str) -> PydanticObjectId:
    """Parse a path/body id into a PydanticObjectId, raising the same clean
    NotFoundError a real "doesn't exist" case would. A malformed id and a
    missing one should look identical to the caller - and without this, a
    malformed id crashes with a raw pydantic ValidationError (500) instead
    of a 404, straight through Document.get().
    """
    if not PydanticObjectId.is_valid(identifier):
        raise NotFoundError(resource, identifier)
    return PydanticObjectId(identifier)
