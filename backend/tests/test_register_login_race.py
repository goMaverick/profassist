"""Regression tests: a registered user must be visible to an immediate login.

``get_db_session`` commits only after the response is sent. Registration used
to rely on that teardown commit, so a login arriving in the window between the
201 and the commit saw no user and returned 401.

These tests use a small in-memory session double with real transaction
visibility rules: flushed rows are visible only inside their own session until
``commit()`` publishes them to a shared store. That reproduces the race without
requiring Postgres.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session, get_redis
from app.core.config import settings
from app.db.models.user import User
from app.main import app
from app.repositories import user_repo
from app.schemas.user import UserCreate
from app.services.organization import OrganizationService
from app.services.user import UserService


class FakeSession:
    """Minimal ``AsyncSession`` stand-in with transaction visibility rules.

    ``flush`` makes a row visible inside this session only; ``commit`` moves it
    to the shared ``store`` so other sessions can see it. This is exactly the
    distinction the register -> login race hinges on.
    """

    def __init__(self, store: dict[str, User]) -> None:
        self._store = store
        self._new: list[object] = []
        self._uncommitted: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self._new.append(obj)

    async def flush(self) -> None:
        for obj in self._new:
            if getattr(obj, "id", "missing") is None:
                obj.id = uuid4()  # type: ignore[attr-defined]
            if getattr(obj, "created_at", "missing") is None:
                obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            if getattr(obj, "last_used_at", "missing") is None:
                obj.last_used_at = datetime.now(UTC)  # type: ignore[attr-defined]
        self._uncommitted.extend(self._new)
        self._new.clear()

    async def refresh(self, obj: object) -> None:
        if getattr(obj, "created_at", "missing") is None:
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]

    async def commit(self) -> None:
        self.commits += 1
        for obj in self._uncommitted:
            if isinstance(obj, User):
                self._store[obj.email] = obj
        self._uncommitted.clear()

    async def rollback(self) -> None:
        self._new.clear()
        self._uncommitted.clear()

    async def close(self) -> None:
        return None

    async def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("unexpected execute() in FakeSession")


@pytest.fixture
def user_store() -> dict[str, User]:
    return {}


@pytest.fixture
def fake_user_persistence(
    monkeypatch: pytest.MonkeyPatch, user_store: dict[str, User]
) -> dict[str, User]:
    """Wire the user layer to the in-memory store.

    Only the pieces unrelated to the race are stubbed: duplicate-email lookup,
    first-user detection, and personal-org creation. The create/flush/commit
    path stays real.
    """

    async def fake_get_by_email(db: object, email: str) -> User | None:
        return user_store.get(email)

    monkeypatch.setattr(user_repo, "get_by_email", fake_get_by_email)
    monkeypatch.setattr(UserService, "_is_first_user", AsyncMock(return_value=False))
    monkeypatch.setattr(OrganizationService, "create_personal_org", AsyncMock(return_value=None))
    return user_store


@pytest.mark.anyio
async def test_register_commits_before_returning(
    fake_user_persistence: dict[str, User],
) -> None:
    """A fresh session must see the user as soon as ``register`` returns."""
    register_session = FakeSession(fake_user_persistence)
    service = UserService(register_session)  # type: ignore[arg-type]

    user = await service.register(
        UserCreate(email="race@example.com", password="password123", full_name="Race")
    )

    assert register_session.commits == 1, (
        "register() must commit the new user before returning; otherwise a "
        "login that arrives before the request-scoped teardown commit gets 401"
    )

    # A brand-new session is what the immediate login request uses. It sees
    # only committed rows, so this fails unless register committed.
    login_session = FakeSession(fake_user_persistence)
    authenticated = await UserService(login_session).authenticate(  # type: ignore[arg-type]
        "race@example.com", "password123"
    )
    assert authenticated.id == user.id


@pytest.fixture
async def racing_client(
    fake_user_persistence: dict[str, User],
    mock_redis: object,
) -> AsyncClient:
    """HTTP client whose request session does not commit at teardown.

    The production teardown commit happens *after* the response is sent. To
    make the race deterministic we model the moment just before it: each
    request gets a fresh session, and only ``register``'s own commit can make
    the row visible to the subsequent login.
    """

    async def override_get_db_session():
        yield FakeSession(fake_user_persistence)

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_register_then_immediate_login_returns_200(
    racing_client: AsyncClient,
) -> None:
    """Register, then log in at once over HTTP - the login must succeed."""
    register = await racing_client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={
            "email": "race@example.com",
            "password": "password123",
            "full_name": "Race",
        },
    )
    assert register.status_code == 201, register.text

    login = await racing_client.post(
        f"{settings.API_V1_STR}/auth/login",
        data={"username": "race@example.com", "password": "password123"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["token_type"] == "bearer"
