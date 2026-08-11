import os
import socket
import subprocess
import sys
import time

# testcontainers normally starts its own "Reaper" (Ryuk) container as a
# safety net - it bind-mounts the Docker socket into itself so it can clean
# up containers if this process dies abnormally (a plain `with` block's
# __exit__, which we do rely on, only covers *normal* termination). Docker
# Desktop's file-sharing restrictions reject that exact bind mount on this
# setup (verified: "Mounts denied: .../docker.sock is not shared from the
# host"), so Ryuk can never actually start - disabling it is the documented
# workaround, not a hack. Must be set before testcontainers is imported
# below, since it's read at import/first-use time. Trade-off this accepts:
# a hard crash mid-suite could leak a container - `docker rm -f` it by hand
# if that ever happens; a normal pass/fail/Ctrl-C still cleans up fine via
# the `with` blocks in _test_db below.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import asyncio

import httpx
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from testcontainers.mongodb import MongoDbContainer
from testcontainers.redis import RedisContainer

from ucenik.core.config import settings

# Dedicated test database name - never touch a real "ucenik" db. Which
# *Mongo instance* settings.mongodb_url actually points at is decided in
# _test_db below (a throwaway testcontainers container, not whatever
# docker-compose happens to have running) - this only fixes the db name
# within whichever instance that ends up being.
settings.mongodb_db_name = "ucenik_test"

# A global per-IP rate limit would otherwise trip against the test suite's
# own rapid-fire requests, which all come from the same IP under
# ASGITransport. test_rate_limit.py re-enables it explicitly to verify the
# limiter itself.
settings.rate_limit_enabled = False

import ucenik.core.db as db_module  # noqa: E402  (import after the settings patch above)
from ucenik.core.redis import close_redis, init_redis  # noqa: E402
from ucenik.core.security import hash_password  # noqa: E402
from ucenik.core.storage import init_storage  # noqa: E402
from ucenik.enum.user_role import UserRole  # noqa: E402
from ucenik.llm.proxy_client import CompletionResult, StreamedCompletion, UsageInfo  # noqa: E402
from ucenik.models import ALL_DOCUMENT_MODELS as ALL_MODELS  # noqa: E402
from ucenik.models.users import User  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _test_db():
    """Spins up throwaway Mongo + Redis containers for this test session via
    testcontainers, rather than assuming docker-compose.yaml's dev infra is
    already running - the suite becomes self-contained (no manual
    `docker compose up` step first, no risk of colliding with dev data).
    Each container is destroyed at the end of the session; nothing persists
    between runs. Same images docker-compose.yaml uses, for consistency.

    Chroma/MinIO aren't containerized here (yet) - document-ingest/storage
    tests still rely on docker-compose.yaml's chromadb/minio being up
    separately, same as before this existed.
    """
    with MongoDbContainer("mongo:8") as mongo, RedisContainer("redis:8") as redis_container:
        settings.mongodb_url = mongo.get_connection_url()
        redis_host = redis_container.get_container_host_ip()
        redis_port = redis_container.get_exposed_port(redis_container.port)
        settings.redis_url = f"redis://{redis_host}:{redis_port}"

        await db_module.init_db(document_models=ALL_MODELS)
        await init_storage()
        await init_redis()
        yield
        await db_module.mongodb_client.drop_database(settings.mongodb_db_name)
        await db_module.mongodb_client.close()
        await close_redis()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _embedding_service():
    """Spins up a real embedding_service subprocess for this test session.
    Document-ingest/retrieval tests call embed_documents()/embed_query()
    for real (no mocking - same "test the real thing" philosophy already
    used everywhere else real embedding is exercised), and since
    rag/embedder.py became an HTTP client to this service rather than
    loading the model in-process, something has to actually be listening
    for those calls to succeed.

    A dynamically-picked free port (not .env.example's default 4001) so
    this never collides with a `make embedding-service` you might already
    have running in another terminal for manual testing at the same time -
    same reasoning as testcontainers auto-assigning host ports for the
    Mongo/Redis containers above, just done by hand since this is our own
    code, not a prebuilt image testcontainers can pull and manage.

    Uses the already-running interpreter (sys.executable - the same venv
    pytest itself is running under, via uvicorn directly) rather than
    shelling out through `uv run` again - one less process layer, and
    avoids depending on the `fastapi` CLI's own subprocess-invocation
    behavior when a plain module invocation does the same job.
    """
    port = _free_port()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "uvicorn",
        "ucenik.embedding_service.main:app",
        "--port",
        str(port),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    settings.embedding_service_url = f"http://127.0.0.1:{port}"

    deadline = time.monotonic() + 60  # first load pulls in the real ~2.3GB model - generous
    try:
        async with AsyncClient() as client:
            while time.monotonic() < deadline:
                if process.returncode is not None:
                    raise RuntimeError("embedding_service subprocess exited before becoming ready")
                try:
                    response = await client.get(f"{settings.embedding_service_url}/health", timeout=2)
                    if response.status_code == 200 and response.json().get("model_loaded"):
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
            else:
                raise RuntimeError("embedding_service did not become ready within the timeout")

        yield
    finally:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()


@pytest_asyncio.fixture(autouse=True)
async def _clean_collections():
    yield
    for model in ALL_MODELS:
        await model.find_all().delete()


@pytest_asyncio.fixture
async def client():
    from ucenik.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def make_user():
    """Factory fixture: create a User with a known plaintext password, return (user, password)."""

    async def _make(email: str, role: UserRole, password: str = "password123", full_name: str = "Test User") -> User:
        user = User(email=email, password_hash=hash_password(password), full_name=full_name, role=role)
        await user.insert()
        return user

    return _make


async def login(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def fake_completion(content: str, total_tokens: int = 42) -> CompletionResult:
    """Builds a CompletionResult for mocking ucenik.rag.contextualizer.complete -
    llm/proxy_client.complete() returns this, not a plain string.
    """
    return CompletionResult(
        content=content,
        prompt_tokens=total_tokens - 10,
        completion_tokens=10,
        total_tokens=total_tokens,
        model="test-model",
    )


def fake_stream_completion(tokens: list[str], total_tokens: int = 42) -> StreamedCompletion:
    """Builds a StreamedCompletion for mocking ucenik.rag.generator.stream_complete -
    llm/proxy_client.stream_complete() returns this: async-iterating yields
    `tokens` in order, then `.usage` is populated, same shape the real thing
    exposes once its stream is exhausted.
    """
    result = StreamedCompletion(model="test-model")

    async def _agen():
        for token in tokens:
            yield token
        result.usage = UsageInfo(prompt_tokens=total_tokens - 10, completion_tokens=10, total_tokens=total_tokens)

    result._agen = _agen()
    return result
