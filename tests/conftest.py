import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ucenik.core.config import settings

# Point at a dedicated test database on the same Mongo instance dev already
# has running via docker-compose - never touch the real "ucenik" db.
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
    await db_module.init_db(document_models=ALL_MODELS)
    await init_storage()
    await init_redis()
    yield
    await db_module.mongodb_client.drop_database(settings.mongodb_db_name)
    await db_module.mongodb_client.close()
    await close_redis()


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
