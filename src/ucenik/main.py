from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ucenik.api.auth import router as auth_router
from ucenik.api.chat import router as chat_router
from ucenik.api.documents import router as documents_router
from ucenik.api.lectures import router as lectures_router
from ucenik.api.plans import router as plans_router
from ucenik.api.subjects import router as subjects_router
from ucenik.api.users import router as users_router
from ucenik.api.users import students_router
from ucenik.api.ws import router as ws_router
from ucenik.core.config import settings
from ucenik.core.db import close_db, init_db
from ucenik.core.logging_config import configure_logging
from ucenik.core.rate_limit import register_rate_limiting
from ucenik.core.redis import close_redis, init_redis
from ucenik.core.request_logging import register_request_logging
from ucenik.core.storage import init_storage
from ucenik.errors.handlers import register_exception_handlers
from ucenik.models import ALL_DOCUMENT_MODELS


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    await init_db(document_models=ALL_DOCUMENT_MODELS)
    await init_redis()
    await init_storage()
    yield

    await close_db()
    await close_redis()


app = FastAPI(
    lifespan=lifespan,
    # Swagger/ReDoc/raw schema off in production - roadmap §17. Not just
    # security-through-obscurity: /docs' "Try it out" is a live authenticated
    # client against real data, and the raw schema hands an attacker the
    # full endpoint/field map for free. On in dev (ENVIRONMENT unset or
    # anything other than "production") for normal API-building convenience.
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
register_exception_handlers(app)
# Order matters: Starlette middleware wraps in reverse-registration-order, so
# registering rate-limiting first makes request-logging the outer layer -
# it still sees (and logs) a 429 rejection, rather than short-circuiting
# before the access log ever records the request happened.
register_rate_limiting(app)
register_request_logging(app)
# CORS registered last so it's the outermost layer - browser needs the
# Access-Control-Allow-Origin header on every response, including 429s from
# rate limiting and errors from request logging's inner layers, not just
# successful ones. FRONTEND_URL(S) - see core/config.py.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(students_router)
app.include_router(subjects_router)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(plans_router)
app.include_router(lectures_router)
app.include_router(ws_router)


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}
