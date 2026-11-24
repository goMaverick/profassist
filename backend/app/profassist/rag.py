"""Chunk course files and retrieve them for a draft.

Embeddings are the same ones the RAG service uses (local fastembed by default,
OpenAI when configured). Vectors go to Qdrant when it is reachable. Keyword
overlap always runs, so a stopped vector store does not block the studio.
Uploads are parsed with PyMuPDF and python-docx (the template's parsers).
Docling is not bundled.
"""

import logging
from typing import Any

from app.profassist.similarity import tokens

logger = logging.getLogger(__name__)

COLLECTION = "profassist"


def chunk_text(text: str, size: int = 700, overlap: int = 80) -> list[str]:
    paragraphs = [part.strip() for part in (text or "").split("\n") if part.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 1 <= size:
            current = f"{current}\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        current = paragraph
    if current:
        chunks.append(current)
    if overlap <= 0 or len(chunks) < 2:
        return chunks
    overlapped = [chunks[0]]
    for chunk in chunks[1:]:
        tail = chunks[0] if not overlapped else overlapped[-1]
        prefix = tail[-overlap:]
        overlapped.append(f"{prefix} {chunk}".strip())
    return overlapped


def keyword_score(query: str, text: str) -> float:
    query_tokens = set(tokens(query))
    text_tokens = set(tokens(text))
    if not query_tokens or not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens)


def _qdrant():
    import os

    from qdrant_client import QdrantClient

    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))
    return QdrantClient(host=host, port=port, timeout=3.0)


def _embedder():
    """Real embeddings through the RAG service (local fastembed by default)."""
    from app.core.config import settings
    from app.services.rag.embeddings import EmbeddingService

    return EmbeddingService(settings.rag)


def _ensure_collection(client: Any, name: str, dim: int) -> None:
    """Create the notes collection or refuse a size the model cannot fill."""
    from qdrant_client.models import Distance, VectorParams

    from app.services.rag.vectorstore import CollectionDimensionMismatch, _collection_vector_size

    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        return
    info = client.get_collection(name)
    actual = _collection_vector_size(info)
    if actual is None or actual == dim:
        return
    points = info.points_count or 0
    if points == 0:
        logger.warning(
            "Collection '%s' was created for %d-dim vectors but needs %d. It is empty, "
            "so it will be recreated.",
            name,
            actual,
            dim,
        )
        client.delete_collection(name)
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        return
    raise CollectionDimensionMismatch(
        f"Collection '{name}' stores {actual}-dim vectors, but the configured embedding "
        f"model produces {dim}-dim vectors. Rebuild it with "
        f"`uv run profassist cmd rag-reset-collection --collection {name} --force`, "
        "then run `uv run profassist cmd rag-reindex --all`."
    )


def index_chunks(
    organization_id: str, course_id: str, rows: list[dict[str, str]], owner_user_id: str = ""
) -> bool:
    """Embed and upsert chunks.

    Raises ``EmbeddingError`` (missing model, failed download, size mismatch)
    so the caller never marks a material ready without real vectors. Returns
    False only when Qdrant is unreachable.
    """
    if not rows:
        return True
    from qdrant_client.models import PointStruct

    embedder = _embedder()
    vectors = embedder.embed_texts([row["text"] for row in rows])
    try:
        client = _qdrant()
        _ensure_collection(client, COLLECTION, embedder.expected_dim)
        points = [
            PointStruct(
                id=str(row["id"]),
                vector=vectors[index],
                payload={
                    "organization_id": organization_id,
                    "course_id": course_id,
                    "owner_user_id": owner_user_id,
                    "text": row["text"][:500],
                },
            )
            for index, row in enumerate(rows)
        ]
        client.upsert(collection_name=COLLECTION, points=points)
        return True
    except Exception as exc:
        from app.services.rag.vectorstore import CollectionDimensionMismatch

        if isinstance(exc, CollectionDimensionMismatch):
            raise
        logger.warning("Qdrant index skipped; keyword retrieval still works: %s", exc)
        return False


def delete_chunks(chunk_ids: list[str]) -> None:
    """Best-effort removal of stale vectors when chunks are rebuilt."""
    if not chunk_ids:
        return
    try:
        from qdrant_client.models import PointIdsList

        client = _qdrant()
        if client.collection_exists(COLLECTION):
            client.delete(
                collection_name=COLLECTION,
                points_selector=PointIdsList(points=list(chunk_ids)),
            )
    except Exception as exc:
        logger.info("Qdrant delete skipped: %s", exc)


def search_qdrant(
    organization_id: str,
    course_id: str,
    query: str,
    limit: int = 4,
    owner_user_id: str = "",
) -> list[str]:
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = _qdrant()
        points = client.query_points(
            collection_name=COLLECTION,
            query=_embedder().embed_query(query),
            query_filter=Filter(
                must=[
                    FieldCondition(key="organization_id", match=MatchValue(value=organization_id)),
                    FieldCondition(key="course_id", match=MatchValue(value=course_id)),
                    FieldCondition(key="owner_user_id", match=MatchValue(value=owner_user_id)),
                ]
            ),
            limit=limit,
        )
        found = []
        for point in points.points:
            text = (point.payload or {}).get("text")
            if text:
                found.append(str(text))
        return found
    except Exception:
        logger.info("Qdrant search skipped")
        return []


def rank_chunks(query: str, chunks: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    scored = []
    for chunk in chunks:
        scored.append((keyword_score(query, chunk.get("text") or ""), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked = [chunk for score, chunk in scored if score > 0][:limit]
    return picked or [chunk for _, chunk in scored[:limit]]
