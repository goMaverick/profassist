"""Security hotfix tests: RAG search/SSE tenant scoping and upload caps.

Covers the confirmed cross-tenant read paths:
  * ``POST /rag/search`` must resolve every collection through the caller's
    Knowledge Bases instead of searching an arbitrary name.
  * ``GET /rag/status/stream`` must require authentication and drop events
    published for another organization.
  * Both upload routes must refuse an oversized body before buffering it.
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.deps import (
    get_active_organization,
    get_current_user,
    get_file_upload_service,
    get_knowledge_base_service,
    get_rag_document_service,
    get_retrieval_service,
    get_vectorstore,
)
from app.core.config import settings
from app.main import app


def _user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.has_role.return_value = True
    return user


def _org() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _authenticate(user: MagicMock, org: SimpleNamespace) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_organization] = lambda: org


@pytest.mark.anyio
async def test_search_rejects_collection_outside_accessible_set(client):
    user = _user()
    org = _org()
    kb = MagicMock()
    kb.list_accessible_collection_names = AsyncMock(return_value=["course-a"])
    retrieval = MagicMock()
    retrieval.retrieve = AsyncMock(return_value=[])
    retrieval.retrieve_multi = AsyncMock(return_value=[])
    _authenticate(user, org)
    app.dependency_overrides[get_knowledge_base_service] = lambda: kb
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval

    response = await client.post(
        f"{settings.API_V1_STR}/rag/search",
        json={"query": "baseline load", "collection_name": "course-b"},
    )

    assert response.status_code == 404
    assert "course-b" in response.json()["error"]["message"]
    retrieval.retrieve.assert_not_called()
    retrieval.retrieve_multi.assert_not_called()


@pytest.mark.anyio
async def test_search_rejects_one_bad_name_in_a_multi_search(client):
    user = _user()
    org = _org()
    kb = MagicMock()
    kb.list_accessible_collection_names = AsyncMock(return_value=["course-a"])
    retrieval = MagicMock()
    retrieval.retrieve_multi = AsyncMock(return_value=[])
    _authenticate(user, org)
    app.dependency_overrides[get_knowledge_base_service] = lambda: kb
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval

    response = await client.post(
        f"{settings.API_V1_STR}/rag/search",
        json={"query": "x", "collection_names": ["course-a", "course-z"]},
    )

    assert response.status_code == 404
    assert "course-z" in response.json()["error"]["message"]
    retrieval.retrieve_multi.assert_not_called()


@pytest.mark.anyio
async def test_search_still_works_for_an_accessible_collection(client):
    user = _user()
    org = _org()
    kb = MagicMock()
    kb.list_accessible_collection_names = AsyncMock(return_value=["course-a"])
    retrieval = MagicMock()
    retrieval.retrieve = AsyncMock(return_value=[])
    _authenticate(user, org)
    app.dependency_overrides[get_knowledge_base_service] = lambda: kb
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval

    response = await client.post(
        f"{settings.API_V1_STR}/rag/search",
        json={"query": "x", "collection_name": "course-a"},
    )

    assert response.status_code == 200
    kb.list_accessible_collection_names.assert_awaited_once_with(
        user_id=user.id, organization_id=org.id
    )
    retrieval.retrieve.assert_awaited_once()


@pytest.mark.anyio
async def test_status_stream_requires_authentication(client):
    response = await client.get(f"{settings.API_V1_STR}/rag/status/stream")

    assert response.status_code == 401, response.text


class _FakePubSub:
    def __init__(self, messages):
        self._messages = messages

    async def subscribe(self, channel):
        return None

    async def unsubscribe(self, channel):
        return None

    async def listen(self):
        for message in self._messages:
            yield message


class _FakeRedis:
    def __init__(self, messages):
        self._messages = messages

    def pubsub(self):
        return _FakePubSub(self._messages)


def _message(payload: dict) -> dict:
    return {"type": "message", "data": json.dumps(payload).encode()}


@pytest.mark.anyio
async def test_status_stream_drops_other_organizations():
    from app.services.rag_status import RAGStatusService

    mine = uuid.uuid4()
    theirs = uuid.uuid4()
    service = RAGStatusService(
        _FakeRedis(
            [
                _message({"document_id": "d1", "status": "done", "organization_id": str(theirs)}),
                _message({"document_id": "d2", "status": "done"}),
                _message({"document_id": "d3", "status": "done", "organization_id": str(mine)}),
            ]
        )
    )

    events = [event async for event in service.stream_events(organization_id=mine)]

    assert len(events) == 1
    payload = json.loads(events[0].raw_data)
    assert payload["document_id"] == "d3"


@pytest.mark.anyio
async def test_status_stream_skips_non_json_payloads():
    from app.services.rag_status import RAGStatusService

    service = RAGStatusService(_FakeRedis([{"type": "message", "data": b"not json"}]))

    events = [event async for event in service.stream_events(organization_id=uuid.uuid4())]

    assert events == []


@pytest.mark.anyio
async def test_worker_publishes_organization_id():
    from app.worker.tasks.rag_tasks import _notify_ws

    org_id = uuid.uuid4()
    fake_redis = MagicMock()
    fake_redis.publish = AsyncMock()
    fake_redis.aclose = AsyncMock()

    with (
        patch(
            "app.worker.tasks.rag_tasks._document_organization_id",
            new=AsyncMock(return_value=str(org_id)),
        ),
        patch("app.worker.tasks.rag_tasks.aioredis.from_url", return_value=fake_redis),
    ):
        await _notify_ws("doc-1", "done", "brief.pdf")

    channel, raw = fake_redis.publish.call_args[0]
    assert channel == "rag_status"
    payload = json.loads(raw)
    assert payload["organization_id"] == str(org_id)
    assert payload["document_id"] == "doc-1"


@pytest.mark.anyio
async def test_worker_does_not_publish_without_an_organization():
    from app.worker.tasks.rag_tasks import _notify_ws

    fake_redis = MagicMock()
    fake_redis.publish = AsyncMock()

    with (
        patch(
            "app.worker.tasks.rag_tasks._document_organization_id",
            new=AsyncMock(return_value=None),
        ),
        patch("app.worker.tasks.rag_tasks.aioredis.from_url", return_value=fake_redis),
    ):
        await _notify_ws("doc-1", "done", "brief.pdf")

    fake_redis.publish.assert_not_called()


@pytest.mark.anyio
async def test_rag_ingest_refuses_an_oversized_upload(client, monkeypatch):
    user = _user()
    org = _org()
    rag_docs = MagicMock()
    rag_docs.dispatch_upload = AsyncMock()
    _authenticate(user, org)
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    app.dependency_overrides[get_rag_document_service] = lambda: rag_docs
    app.dependency_overrides[get_vectorstore] = lambda: MagicMock()

    response = await client.post(
        f"{settings.API_V1_STR}/rag/collections/course-a/ingest",
        files={"file": ("big.pdf", b"a" * (1024 * 1024 + 10), "application/pdf")},
    )

    assert response.status_code == 400
    assert "too large" in response.json()["error"]["message"].lower()
    rag_docs.dispatch_upload.assert_not_called()


@pytest.mark.anyio
async def test_file_upload_refuses_an_oversized_upload(client, monkeypatch):
    from app.api.routes.v1 import files as files_route

    user = _user()
    file_svc = MagicMock()
    file_svc.upload = AsyncMock()
    _authenticate(user, _org())
    monkeypatch.setattr(files_route, "MAX_UPLOAD_SIZE", 10)
    app.dependency_overrides[get_file_upload_service] = lambda: file_svc

    response = await client.post(
        f"{settings.API_V1_STR}/files/upload",
        files={"file": ("big.txt", b"a" * 11, "text/plain")},
    )

    assert response.status_code == 413
    file_svc.upload.assert_not_called()
