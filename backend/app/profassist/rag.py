"""Chunk course files and retrieve them for a draft.

Vectors go to Qdrant when it is reachable. Keyword overlap always runs, so a
missing embedding key does not stop the studio. Uploads are parsed with
PyMuPDF and python-docx (the template's parsers). Docling is not bundled.
"""

import logging
from typing import Any

from app.profassist.similarity import hash_embed, tokens

logger = logging.getLogger(__name__)

DIM = 64
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


def index_chunks(
    organization_id: str, course_id: str, rows: list[dict[str, str]], owner_user_id: str = ""
) -> bool:
    """Best-effort Qdrant upsert. Returns False when the store is unreachable."""
    try:
        from qdrant_client.models import Distance, PointStruct, VectorParams

        client = _qdrant()
        if not client.collection_exists(COLLECTION):
            client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
            )
        points = [
            PointStruct(
                id=str(row["id"]),
                vector=hash_embed(row["text"], DIM),
                payload={
                    "organization_id": organization_id,
                    "course_id": course_id,
                    "owner_user_id": owner_user_id,
                    "text": row["text"][:500],
                },
            )
            for row in rows
        ]
        if points:
            client.upsert(collection_name=COLLECTION, points=points)
        return True
    except Exception:
        logger.info("Qdrant index skipped; keyword retrieval still works")
        return False


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
            query=hash_embed(query, DIM),
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
