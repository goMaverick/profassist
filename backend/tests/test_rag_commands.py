"""Guards for the RAG CLI boundary.

`rag-reindex` must call `reindex_materials` with the keyword names that the
service actually declares, and an empty `QDRANT_API_KEY` must reach
qdrant-client as `None` (any non-None key turns TLS on, which fails against a
plain-HTTP Qdrant with ``[SSL: WRONG_VERSION_NUMBER]``).
"""

import inspect
import uuid
from contextlib import asynccontextmanager

from click.testing import CliRunner

from app.commands import rag as rag_commands
from app.profassist import service as profassist_service
from app.services.rag import vectorstore


@asynccontextmanager
async def _fake_db_context():
    yield None


def test_rag_reindex_calls_service_with_declared_keywords(monkeypatch):
    """The CLI must bind to the real service signature, not a guessed one."""
    captured: dict[str, object] = {}
    signature = inspect.signature(profassist_service.reindex_materials)

    async def fake_reindex(db, *args, **kwargs):
        # Binding against the real signature turns a stale keyword name into a
        # TypeError here instead of a crash in a live `rag-reindex` run.
        signature.bind(db, *args, **kwargs)
        captured.update(kwargs)
        return {"materials": 0, "reindexed": 0, "skipped": 0, "failed": []}

    monkeypatch.setattr(profassist_service, "reindex_materials", fake_reindex)
    monkeypatch.setattr(rag_commands, "get_db_context", _fake_db_context)

    org_id = uuid.uuid4()
    result = CliRunner().invoke(rag_commands.rag_reindex, ["--organization", str(org_id)])

    assert result.exit_code == 0, result.output
    assert captured["org_id"] == org_id
    assert captured["course_id"] is None
    assert captured["user_id"] is None


def test_rag_reindex_all_passes_no_filters(monkeypatch):
    captured: dict[str, object] = {}
    signature = inspect.signature(profassist_service.reindex_materials)

    async def fake_reindex(db, *args, **kwargs):
        signature.bind(db, *args, **kwargs)
        captured.update(kwargs)
        return {"materials": 0, "reindexed": 0, "skipped": 0, "failed": []}

    monkeypatch.setattr(profassist_service, "reindex_materials", fake_reindex)
    monkeypatch.setattr(rag_commands, "get_db_context", _fake_db_context)

    result = CliRunner().invoke(rag_commands.rag_reindex, ["--all"])

    assert result.exit_code == 0, result.output
    assert captured == {"org_id": None, "course_id": None, "user_id": None}


def _capture_client_kwargs(monkeypatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    class _StubClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(vectorstore, "AsyncQdrantClient", _StubClient)
    return captured


def test_build_client_empty_api_key_is_none(monkeypatch):
    captured = _capture_client_kwargs(monkeypatch)
    monkeypatch.setattr(vectorstore.app_settings, "QDRANT_API_KEY", "")

    vectorstore._build_client()

    assert captured["api_key"] is None


def test_build_client_keeps_cloud_api_key(monkeypatch):
    captured = _capture_client_kwargs(monkeypatch)
    monkeypatch.setattr(vectorstore.app_settings, "QDRANT_API_KEY", "test-key")

    vectorstore._build_client()

    assert captured["api_key"] == "test-key"
