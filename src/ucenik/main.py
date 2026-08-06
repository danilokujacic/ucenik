from contextlib import asynccontextmanager

from fastapi import FastAPI

from ucenik.api.auth import router as auth_router
from ucenik.api.documents import router as documents_router
from ucenik.api.subjects import router as subjects_router
from ucenik.api.users import router as users_router
from ucenik.core.db import close_db, init_db
from ucenik.core.redis import close_redis, init_redis
from ucenik.core.storage import init_storage
from ucenik.errors.handlers import register_exception_handlers
from ucenik.models.auth_sessions import AuthSession
from ucenik.models.documents import Document
from ucenik.models.enrollments import Enrollment
from ucenik.models.item import Item
from ucenik.models.subjects import Subject
from ucenik.models.users import User


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db(document_models=[Item, User, AuthSession, Subject, Enrollment, Document])
    await init_redis()
    await init_storage()
    yield

    await close_db()
    await close_redis()


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(subjects_router)
app.include_router(documents_router)


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "q": q}
