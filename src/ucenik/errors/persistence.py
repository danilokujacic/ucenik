"""Layer 1: translate raw driver/pymongo exceptions into our own vocabulary.

Nothing above the persistence layer should ever see a pymongo exception directly.
"""

from pymongo.errors import DuplicateKeyError as MongoDuplicateKeyError


class PersistenceError(Exception):
    """Base class for all persistence-layer errors."""


class NotFoundError(PersistenceError):
    def __init__(self, resource: str, identifier: str):
        self.resource = resource
        self.identifier = identifier
        super().__init__(f"{resource} not found: {identifier}")


class DuplicateKeyError(PersistenceError):
    def __init__(self, resource: str, detail: str = ""):
        self.resource = resource
        message = f"{resource} already exists"
        if detail:
            message += f": {detail}"
        super().__init__(message)


def translate_duplicate_key(resource: str, exc: MongoDuplicateKeyError) -> DuplicateKeyError:
    return DuplicateKeyError(resource, detail=str(exc))
