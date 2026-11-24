"""Admin prompt saves publish to Langfuse and always keep the local fallback."""

import uuid
from typing import Any

import pytest

import app.profassist.observe as observe
from app.profassist import settings_admin
from app.profassist.models import PromptVersion
from tests.test_profassist_rubric import FakeSession


class _Prompt:
    def __init__(self, version: int) -> None:
        self.version = version


class _PublishingClient:
    def __init__(self, *, version: int = 7, fail: bool = False) -> None:
        self.version = version
        self.fail = fail
        self.created: list[dict[str, Any]] = []
        self.flushed = 0

    def create_prompt(self, **kwargs: Any) -> _Prompt:
        if self.fail:
            raise RuntimeError("langfuse is down")
        self.created.append(kwargs)
        return _Prompt(self.version)

    def flush(self) -> None:
        self.flushed += 1


def test_publish_prompt_creates_a_production_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _PublishingClient(version=4)
    monkeypatch.setattr(observe, "_client", lambda: client)
    observe._prompt_cache["chat"] = ("old", 1)

    version = observe.publish_prompt("chat", "New global text.")

    assert version == 4
    assert client.created == [
        {
            "name": "chat",
            "type": "text",
            "prompt": "New global text.",
            "labels": ["production"],
            "commit_message": "Published from ProfAssist admin",
        }
    ]
    assert "chat" not in observe._prompt_cache
    assert client.flushed == 1


def test_publish_prompt_returns_none_when_langfuse_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(observe, "_client", lambda: None)

    assert observe.publish_prompt("chat", "New global text.") is None


def test_publish_prompt_swallows_a_publish_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _PublishingClient(fail=True)
    monkeypatch.setattr(observe, "_client", lambda: client)

    assert observe.publish_prompt("chat", "New global text.") is None


async def _save(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> tuple[dict[str, Any], FakeSession, list[tuple[str, str]]]:
    db = FakeSession()
    org_id, actor = uuid.uuid4(), uuid.uuid4()
    calls: list[tuple[str, str]] = []

    async def fake_admin_view(_db: Any, _org: uuid.UUID) -> dict[str, Any]:
        return {"prompts": []}

    def fake_publish(name: str, body: str) -> int | None:
        calls.append((name, body))
        return 3

    monkeypatch.setattr(settings_admin, "admin_view", fake_admin_view)
    monkeypatch.setattr(settings_admin, "langfuse_enabled", lambda: enabled)
    monkeypatch.setattr(settings_admin, "publish_prompt", fake_publish)

    view = await settings_admin.save_prompt(db, org_id, actor, "chat", "New body")
    return view, db, calls


@pytest.mark.anyio
async def test_save_prompt_publishes_when_langfuse_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, db, calls = await _save(monkeypatch, enabled=True)

    assert calls == [("chat", "New body")]
    assert view["published_to_langfuse"] is True
    assert any(isinstance(row, PromptVersion) and row.body == "New body" for row in db.rows)


@pytest.mark.anyio
async def test_save_prompt_does_not_publish_when_langfuse_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, db, calls = await _save(monkeypatch, enabled=False)

    assert calls == []
    assert view["published_to_langfuse"] is False
    assert any(isinstance(row, PromptVersion) and row.body == "New body" for row in db.rows)


@pytest.mark.anyio
async def test_save_prompt_keeps_the_database_copy_when_publish_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, actor = uuid.uuid4(), uuid.uuid4()

    async def fake_admin_view(_db: Any, _org: uuid.UUID) -> dict[str, Any]:
        return {"prompts": []}

    def boom(_name: str, _body: str) -> int | None:
        raise RuntimeError("langfuse is down")

    monkeypatch.setattr(settings_admin, "admin_view", fake_admin_view)
    monkeypatch.setattr(settings_admin, "langfuse_enabled", lambda: True)
    monkeypatch.setattr(settings_admin, "publish_prompt", boom)

    view = await settings_admin.save_prompt(db, org_id, actor, "chat", "New body")

    assert view["published_to_langfuse"] is False
    assert any(isinstance(row, PromptVersion) and row.body == "New body" for row in db.rows)
