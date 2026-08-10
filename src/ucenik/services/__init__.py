"""Business logic, one module per domain - DB queries, validation rules,
storage/task dispatch, everything that isn't shaping an HTTP request/response.

`api/*.py` stays a thin presentation/controller layer: FastAPI routing,
request/response Pydantic models, and mapping a domain model returned from
here into the wire-format `*Public` model. `core/permissions.py`'s
`Depends()` functions (role/ownership checks) are the one exception left
outside this package - they're framework-shaped authorization plumbing
reused as FastAPI dependencies across multiple routers, not a single
domain's business logic.
"""
