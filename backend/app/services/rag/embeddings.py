"""Embedding providers: local fastembed by default, OpenAI for remote.

Vectors are real. When the local model cannot be loaded (missing package, a
failed download, no disk space) we raise ``EmbeddingError`` instead of
returning placeholder vectors that would poison the vector store.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import settings as app_settings
from app.services.rag.config import (
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    EmbeddingsConfig,
    RAGSettings,
)
from app.services.rag.models import Document

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """The embedding backend is unavailable or could not produce vectors."""


class EmbeddingDimensionError(EmbeddingError, ValueError):
    """A provider returned vectors whose size does not match the collection."""


def _chunk_texts(document: Document) -> list[str]:
    return [
        doc.chunk_content if doc.chunk_content else "" for doc in (document.chunked_pages or [])
    ]


# One loaded fastembed model per (model, cache dir, threads) for the whole
# process. Loading is expensive and must not repeat on every request.
_MODEL_CACHE: dict[str, Any] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def clear_model_cache() -> None:
    """Drop loaded local models (tests, or after switching ``EMBEDDING_MODEL``)."""
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()


class BaseEmbeddingProvider(ABC):
    model: str = ""
    name: str = "base"

    @abstractmethod
    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        pass

    @abstractmethod
    def embed_document(self, document: Document) -> list[list[float]]:
        pass

    @abstractmethod
    def warmup(self) -> None:
        """Ensures the model is loaded and ready for inference."""
        pass


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    """CPU embeddings through ``fastembed.TextEmbedding`` (ONNX).

    The model is downloaded from Hugging Face on first use and then kept in
    ``cache_dir`` (``MODELS_CACHE_DIR`` by default). The loaded model is cached
    for the process; ``warmup()`` forces the load.
    """

    name = "local"

    def __init__(
        self,
        model: str = DEFAULT_LOCAL_EMBEDDING_MODEL,
        cache_dir: str | None = None,
        threads: int | None = None,
    ) -> None:
        self.model = model
        self.cache_dir = str(cache_dir) if cache_dir else None
        self.threads = threads

    @property
    def _cache_key(self) -> str:
        return f"{self.model}|{self.cache_dir or ''}|{self.threads or ''}"

    def _load_model(self) -> Any:
        with _MODEL_CACHE_LOCK:
            cached = _MODEL_CACHE.get(self._cache_key)
            if cached is not None:
                return cached
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:
                raise EmbeddingError(
                    "fastembed is not installed, so local embeddings cannot run. "
                    "Install it with `uv add fastembed`, or set EMBEDDING_PROVIDER=openai "
                    "with an API key."
                ) from exc
            kwargs: dict[str, Any] = {}
            if self.cache_dir:
                kwargs["cache_dir"] = self.cache_dir
            if self.threads:
                kwargs["threads"] = self.threads
            try:
                model = TextEmbedding(model_name=self.model, **kwargs)
            except Exception as exc:
                raise EmbeddingError(
                    f"Could not load the local embedding model '{self.model}'. The first run "
                    f"downloads it from Hugging Face into "
                    f"{self.cache_dir or 'the default fastembed cache'}; check the network, "
                    f"the model name, and free disk space. Cause: {exc}"
                ) from exc
            _MODEL_CACHE[self._cache_key] = model
            logger.info("Loaded local embedding model %s", self.model)
            return model

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        try:
            return [[float(value) for value in vector] for vector in model.embed(list(texts))]
        except Exception as exc:
            raise EmbeddingError(
                f"Local embedding model '{self.model}' failed to embed text: {exc}"
            ) from exc

    def embed_document(self, document: Document) -> list[list[float]]:
        return self.embed_queries(_chunk_texts(document))

    def warmup(self) -> None:
        self._load_model()


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI (or OpenAI-compatible) embedding provider."""

    name = "openai"

    def __init__(self, model: str, api_key: str = "", base_url: str | None = None) -> None:
        """Initialize the OpenAI embedding provider.

        Args:
            model: The OpenAI embedding model name (e.g., 'text-embedding-3-small').
            api_key: API key; falls back to OPENAI_API_KEY env var when empty.
            base_url: Override base URL (e.g. OpenRouter-compatible endpoint).
        """
        from openai import OpenAI

        self.model = model
        try:
            self.client = OpenAI(api_key=api_key or None, base_url=base_url)
        except Exception as exc:
            raise EmbeddingError(
                "Remote embeddings need an API key. Set EMBEDDING_API_KEY (or "
                f"OPENAI_API_KEY) when EMBEDDING_PROVIDER=openai. Cause: {exc}"
            ) from exc

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.client.embeddings.create(model=self.model, input=list(texts))
        except Exception as exc:
            raise EmbeddingError(
                f"Remote embedding model '{self.model}' failed to embed text: {exc}"
            ) from exc
        return [data.embedding for data in response.data]

    def embed_document(self, document: Document) -> list[list[float]]:
        return self.embed_queries(_chunk_texts(document))

    def warmup(self) -> None:
        # Nothing to load locally. The first request does the network call.
        pass


class EmbeddingService:
    """Real embeddings with a dimension contract for the vector store."""

    def __init__(self, settings: RAGSettings):
        config = settings.embeddings_config
        self.expected_dim = config.dim
        self.model = config.model
        self.provider_name = config.provider
        self.provider = self._build_provider(config)
        logger.info(
            "Embeddings: provider=%s model=%s dim=%s",
            self.provider_name,
            self.model,
            self.expected_dim,
        )

    @staticmethod
    def _build_provider(config: EmbeddingsConfig) -> BaseEmbeddingProvider:
        if config.provider == "local":
            return LocalEmbeddingProvider(
                model=config.model,
                cache_dir=str(app_settings.MODELS_CACHE_DIR),
            )
        api_key = config.api_key or app_settings.EMBEDDING_API_KEY or app_settings.OPENAI_API_KEY
        if not api_key:
            raise EmbeddingError(
                f"Remote embeddings (EMBEDDING_PROVIDER={config.provider}) need an API "
                "key: set EMBEDDING_API_KEY (or OPENAI_API_KEY)."
            )
        base_url = config.base_url or app_settings.EMBEDDING_BASE_URL
        return OpenAIEmbeddingProvider(
            model=config.model,
            api_key=api_key,
            base_url=base_url,
        )

    def _validate(self, vectors: list[list[float]]) -> list[list[float]]:
        for vector in vectors:
            if len(vector) != self.expected_dim:
                raise EmbeddingDimensionError(
                    f"Embedding dimension mismatch: provider '{self.provider_name}' model "
                    f"'{self.model}' returned {len(vector)} dims, expected {self.expected_dim}. "
                    "Check EMBEDDING_MODEL/EMBEDDING_DIM or recreate the collection."
                )
        return vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch, rejecting anything that does not match the contract."""
        if not texts:
            return []
        vectors = self.provider.embed_queries(list(texts))
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"Embedding provider '{self.provider_name}' returned {len(vectors)} vectors "
                f"for {len(texts)} inputs."
            )
        return self._validate(vectors)

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]

    def embed_document(self, document: Document) -> list[list[float]]:
        return self.embed_texts(_chunk_texts(document))

    def warmup(self) -> None:
        self.provider.warmup()
