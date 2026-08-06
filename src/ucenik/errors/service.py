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
