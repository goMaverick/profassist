"""Local-first embeddings: selection, lazy loading, and ready-chunk gating."""

import sys
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.config import EmbeddingsConfig, RAGSettings
from app.services.rag.embeddings import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingService,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    clear_model_cache,
)
from app.services.rag.vectorstore import CollectionDimensionMismatch, QdrantVectorStore


class _FakeTextEmbedding:
    """Stands in for ``fastembed.TextEmbedding`` without downloading anything."""

    instances = 0
    calls = 0
    dim = 384

    def __init__(self, model_name: str = "", **kwargs: Any) -> None:
        type(self).instances += 1
        self.model_name = model_name
        self.kwargs = kwargs

    def embed(self, documents: Any, **kwargs: Any) -> list[list[float]]:
        type(self).calls += 1
        return [[0.01] * type(self).dim for _ in documents]


class _FailingTextEmbedding:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise OSError("model download failed")


@pytest.fixture(autouse=True)
def _reset_local_model() -> Any:
    clear_model_cache()
    _FakeTextEmbedding.instances = 0
    _FakeTextEmbedding.calls = 0
    _FakeTextEmbedding.dim = 384
    yield
    clear_model_cache()


def _use_fake_fastembed(monkeypatch: pytest.MonkeyPatch, cls: type = _FakeTextEmbedding) -> None:
    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=cls))


def test_default_provider_is_local_bge_small_384() -> None:
    service = EmbeddingService(RAGSettings())

    assert isinstance(service.provider, LocalEmbeddingProvider)
    assert service.provider_name == "local"
    assert service.model == "BAAI/bge-small-en-v1.5"
    assert service.expected_dim == 384


def test_local_provider_falls_back_from_a_remote_model_to_bge_small(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stale remote model name must not take RAG warmup down."""
    with caplog.at_level("WARNING", logger="app.services.rag.config"):
        service = EmbeddingService(
            RAGSettings(
                embeddings_config=EmbeddingsConfig(
                    provider="local",
                    model="gemini-embedding-001",
                )
            )
        )

    assert service.provider_name == "local"
    assert isinstance(service.provider, LocalEmbeddingProvider)
    assert service.model == "BAAI/bge-small-en-v1.5"
    assert service.expected_dim == 384
    assert "gemini-embedding-001" in caplog.text
    assert "BAAI/bge-small-en-v1.5" in caplog.text


def test_local_provider_keeps_a_known_local_model() -> None:
    service = EmbeddingService(
        RAGSettings(
            embeddings_config=EmbeddingsConfig(
                provider="local",
                model="BAAI/bge-base-en-v1.5",
            )
        )
    )

    assert service.provider_name == "local"
    assert isinstance(service.provider, LocalEmbeddingProvider)
    assert service.model == "BAAI/bge-base-en-v1.5"
    assert service.expected_dim == 768


def test_local_fallback_ignores_a_remote_dimension(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="app.services.rag.config"):
        service = EmbeddingService(
            RAGSettings(
                embeddings_config=EmbeddingsConfig(
                    provider="local",
                    model="gemini-embedding-001",
                    dim=3072,
                )
            )
        )

    assert service.model == "BAAI/bge-small-en-v1.5"
    assert service.expected_dim == 384
    assert "Ignoring EMBEDDING_DIM=3072" in caplog.text


def test_remote_provider_keeps_the_configured_model() -> None:
    service = EmbeddingService(
        RAGSettings(
            embeddings_config=EmbeddingsConfig(
                provider="remote",
                model="text-embedding-3-small",
                api_key="sk-test",
            )
        )
    )

    assert service.provider_name == "openai"
    assert isinstance(service.provider, OpenAIEmbeddingProvider)
    assert service.model == "text-embedding-3-small"
    assert service.expected_dim == 1536


def test_remote_provider_requires_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "EMBEDDING_API_KEY", "")
    monkeypatch.setattr(app_settings, "OPENAI_API_KEY", "")
    settings = RAGSettings(
        embeddings_config=EmbeddingsConfig(provider="openai", model="text-embedding-3-small")
    )

    with pytest.raises(EmbeddingError, match="need an API key"):
        EmbeddingService(settings)


@pytest.mark.parametrize("provider", ["openai", "remote"])
def test_remote_provider_uses_configured_model_and_dim(provider: str) -> None:
    settings = RAGSettings(
        embeddings_config=EmbeddingsConfig(
            provider=provider,
            model="text-embedding-3-small",
            api_key="sk-test",
        )
    )

    service = EmbeddingService(settings)

    assert isinstance(service.provider, OpenAIEmbeddingProvider)
    assert service.provider_name == "openai"
    assert service.expected_dim == 1536


def test_local_provider_embeds_and_caches_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_fake_fastembed(monkeypatch)
    service = EmbeddingService(RAGSettings())

    vectors = service.embed_texts(["alpha", "beta"])
    service.embed_query("a third call")
    service.warmup()

    assert len(vectors) == 2
    assert len(vectors[0]) == 384
    assert _FakeTextEmbedding.instances == 1
    assert _FakeTextEmbedding.calls == 2


def test_model_cache_is_shared_between_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_fake_fastembed(monkeypatch)
    first = LocalEmbeddingProvider(model="BAAI/bge-small-en-v1.5")
    first.warmup()
    second = LocalEmbeddingProvider(model="BAAI/bge-small-en-v1.5")

    second.embed_queries(["hello"])

    assert _FakeTextEmbedding.instances == 1


def test_missing_fastembed_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "fastembed", None)
    provider = LocalEmbeddingProvider()

    with pytest.raises(EmbeddingError, match="fastembed is not installed"):
        provider.warmup()


def test_model_download_failure_raises_and_returns_no_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_fake_fastembed(monkeypatch, _FailingTextEmbedding)
    service = EmbeddingService(RAGSettings())

    with pytest.raises(EmbeddingError, match="Could not load the local embedding model"):
        service.embed_texts(["hello"])


def test_dimension_mismatch_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeTextEmbedding.dim = 3
    _use_fake_fastembed(monkeypatch)
    service = EmbeddingService(RAGSettings())

    with pytest.raises(EmbeddingDimensionError, match="dimension mismatch"):
        service.embed_query("hello")


@pytest.mark.anyio
async def test_index_failure_does_not_mark_the_material_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.profassist import service as prof_service

    material = SimpleNamespace(
        id=uuid.uuid4(),
        filename="notes.txt",
        status="processing",
        pii_report={"bytes": 12},
    )
    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    def _raise(*args: Any, **kwargs: Any) -> bool:
        raise EmbeddingError("model still loading")

    monkeypatch.setattr(prof_service, "index_chunks", _raise)

    await prof_service._index_material(
        db,
        uuid.uuid4(),
        uuid.uuid4(),
        material,
        "Campus energy notes.",
        None,
    )

    assert material.status == "error"
    assert "model still loading" in material.pii_report["index_error"]


@pytest.mark.anyio
async def test_index_success_marks_the_material_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist import service as prof_service

    material = SimpleNamespace(
        id=uuid.uuid4(),
        filename="notes.txt",
        status="processing",
        pii_report={"bytes": 12},
    )
    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    monkeypatch.setattr(prof_service, "index_chunks", lambda *args, **kwargs: True)

    await prof_service._index_material(
        db,
        uuid.uuid4(),
        uuid.uuid4(),
        material,
        "Campus energy notes.",
        None,
    )

    assert material.status == "ready"
    assert "index_error" not in material.pii_report


@pytest.mark.anyio
async def test_add_material_is_not_ready_when_embedding_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.profassist import service as prof_service

    org_id = uuid.uuid4()
    course_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async def _course(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(id=course_id, organization_id=org_id)

    async def _names(*args: Any, **kwargs: Any) -> list[str]:
        return []

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    def _raise(*args: Any, **kwargs: Any) -> bool:
        raise EmbeddingError("fastembed is not installed")

    monkeypatch.setattr(prof_service, "_course", _course)
    monkeypatch.setattr(prof_service, "_names", _names)
    monkeypatch.setattr(prof_service, "_remember_pii", _noop)
    monkeypatch.setattr(
        prof_service, "extract_text", lambda filename, data: "Lecture notes on energy."
    )
    monkeypatch.setattr(prof_service, "save_bytes", lambda *args, **kwargs: "key")
    monkeypatch.setattr(prof_service, "index_chunks", _raise)
    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    result = await prof_service.add_material(
        db, org_id, course_id, user_id, "notes.txt", b"lecture notes"
    )

    assert result["status"] == "error"
    assert "fastembed is not installed" in result["index_error"]


class _FakeQdrant:
    def __init__(self, size: int, points: int) -> None:
        self.info = SimpleNamespace(
            points_count=points,
            config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=size))),
        )
        self.deleted: list[str] = []
        self.created: list[int] = []

    async def get_collections(self) -> Any:
        return SimpleNamespace(collections=[SimpleNamespace(name="documents")])

    async def get_collection(self, name: str) -> Any:
        return self.info

    async def delete_collection(self, name: str) -> None:
        self.deleted.append(name)

    async def create_collection(self, collection_name: str, vectors_config: Any) -> None:
        self.created.append(vectors_config.size)


def _store_with(fake: _FakeQdrant) -> QdrantVectorStore:
    store = object.__new__(QdrantVectorStore)
    store.settings = RAGSettings()
    store.embedder = None  # type: ignore[assignment]
    store.client = fake  # type: ignore[assignment]
    return store


@pytest.mark.anyio
async def test_existing_collection_with_data_and_wrong_dim_is_rejected() -> None:
    fake = _FakeQdrant(size=64, points=7)
    store = _store_with(fake)

    with pytest.raises(CollectionDimensionMismatch, match="rag-reset-collection"):
        await store._ensure_collection("documents")

    assert fake.deleted == []
    assert fake.created == []


@pytest.mark.anyio
async def test_empty_collection_with_wrong_dim_is_recreated() -> None:
    fake = _FakeQdrant(size=64, points=0)
    store = _store_with(fake)

    await store._ensure_collection("documents")

    assert fake.deleted == ["documents"]
    assert fake.created == [384]


@pytest.mark.anyio
async def test_matching_collection_is_left_alone() -> None:
    fake = _FakeQdrant(size=384, points=4)
    store = _store_with(fake)

    await store._ensure_collection("documents")

    assert fake.deleted == []
    assert fake.created == []
