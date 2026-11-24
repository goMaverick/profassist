"""Test configuration and fixtures.

Uses anyio for async testing instead of pytest-asyncio.
This allows using the same async primitives that Starlette uses internally.
See: https://anyio.readthedocs.io/en/stable/testing.html
"""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.config import settings
from app.api.deps import get_redis
from app.clients.redis import RedisClient
from app.api.deps import get_db_session
from app.services.rate_limit import service as rate_limit_service
from app.services.rate_limit.storage import InMemoryStorage


@pytest.fixture
def anyio_backend() -> str:
    """Specify the async backend for anyio tests.

    Options: "asyncio" or "trio". We use asyncio since that's what uvicorn uses.
    """
    return "asyncio"


@pytest.fixture(autouse=True)
def restore_profassist_runtime() -> Iterator[None]:
    """Give every test the same AI runtime it started with.

    ``bind_runtime`` writes module-level ContextVars that outlive a test, so one
    test that sends traffic to Gemini leaks that route into the next test file.
    Snapshot before the test and restore after, even when the test fails.
    """
    from app.profassist import runtime

    variables = (runtime._prompts, runtime._tools, runtime._model)
    saved = tuple(variable.get() for variable in variables)
    yield
    for variable, value in zip(variables, saved):
        variable.set(value)


@pytest.fixture(autouse=True)
def reset_rate_limit_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test its own rate-limit counters.

    The limiter's storage is a module-level singleton keyed by client IP, and in
    tests every request arrives from the same IP. Without this, the sixth test
    that posts to an ``/auth/*`` route gets a 429 from the previous five.
    """
    monkeypatch.setattr(rate_limit_service, "_storage", InMemoryStorage())


@pytest.fixture
def fake_langfuse(monkeypatch: pytest.MonkeyPatch) -> str:
    """A Langfuse client with a stable trace id, so trace URLs can be asserted."""
    from app.profassist import observe

    class _Span:
        def __enter__(self) -> "_Span":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    class _Client:
        def start_as_current_generation(self, **kwargs: object) -> _Span:
            return _Span()

        def start_as_current_span(self, **kwargs: object) -> _Span:
            return _Span()

        def update_current_trace(self, **kwargs: object) -> None:
            return None

        def get_current_trace_id(self) -> str:
            return "trace-123"

        def flush(self) -> None:
            return None

    monkeypatch.setattr(observe, "_client", lambda: _Client())
    monkeypatch.setenv("LANGFUSE_PUBLIC_BASE_URL", "http://langfuse.test")
    monkeypatch.setenv("LANGFUSE_PROJECT_ID", "proj-test")
    observe.reset_step_trace()
    return "http://langfuse.test/project/proj-test/traces/trace-123"


@pytest.fixture
def mock_redis() -> MagicMock:
    """Create a mock Redis client for testing."""
    mock = MagicMock(spec=RedisClient)
    mock.ping = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    mock.exists = AsyncMock(return_value=0)
    mock.incr = AsyncMock(return_value=1)
    mock.expire = AsyncMock(return_value=True)
    return mock


@pytest.fixture
async def mock_db_session() -> AsyncGenerator[AsyncMock, None]:
    """Create a mock database session for testing."""
    mock = AsyncMock()
    mock.execute = AsyncMock()
    mock.commit = AsyncMock()
    mock.rollback = AsyncMock()
    mock.close = AsyncMock()
    yield mock


@pytest.fixture
async def client(
    mock_redis: MagicMock,
    mock_db_session,
) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing.

    Uses HTTPX AsyncClient with ASGITransport instead of Starlette's TestClient.
    This allows proper async testing without thread pool overhead.
    """
    # Override dependencies for testing
    app.dependency_overrides[get_redis] = lambda: mock_redis
    app.dependency_overrides[get_db_session] = lambda: mock_db_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    # Clear overrides after test
    app.dependency_overrides.clear()


@pytest.fixture
def api_key_headers() -> dict[str, str]:
    """Headers with valid API key."""
    return {settings.API_KEY_HEADER: settings.API_KEY}


# Note: For integration tests requiring authenticated users,
# use dependency overrides with mock users instead of test_user fixture.
# See tests/api/test_auth.py and tests/api/test_users.py for examples.
