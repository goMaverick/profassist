"""Per-professor memory.

The open-source Mem0 library is used when it is installed and an LLM key is set.
Either way, a scrubbed copy is stored in Postgres and Qdrant, scoped to one
professor inside one university. Student names never enter memory.
"""

import logging
import os
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.llm import llm_api_key
from app.profassist.models import ProfessorMemory
from app.profassist.pii import scrub
from app.profassist.similarity import hash_embed

logger = logging.getLogger(__name__)
COLLECTION = "profassist_memory"


def scope_id(organization_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"{organization_id}:{user_id}"


def _qdrant_upsert(organization_id: str, user_id: str, memory_id: str, text: str) -> None:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        client = QdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
            timeout=3.0,
        )
        if not client.collection_exists(COLLECTION):
            client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=64, distance=Distance.COSINE),
            )
        client.upsert(
            collection_name=COLLECTION,
            points=[
                PointStruct(
                    id=memory_id,
                    vector=hash_embed(text, 64),
                    payload={
                        "organization_id": organization_id,
                        "owner_user_id": user_id,
                        "text": text[:500],
                    },
                )
            ],
        )
    except Exception:
        logger.info("Memory vector was not written; the Postgres copy remains")


def _mem0_add(organization_id: str, user_id: str, text: str) -> None:
    """Best-effort Mem0 write. Skipped in demo mode (no key) and if Mem0 is absent."""
    if not llm_api_key():
        return
    try:
        from mem0 import Memory

        store = Memory.from_config(
            {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "host": os.getenv("QDRANT_HOST", "localhost"),
                        "port": int(os.getenv("QDRANT_PORT", "6333")),
                        "collection_name": "mem0_profassist",
                    },
                },
                "llm": {
                    "provider": "litellm",
                    "config": {
                        "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
                        "api_key": llm_api_key(),
                    },
                },
                "history_db_path": os.getenv("MEM0_HISTORY_PATH", "/tmp/profassist-mem0.db"),
            }
        )
        store.add(
            text,
            user_id=scope_id(uuid.UUID(organization_id), uuid.UUID(user_id)),
            metadata={"organization_id": organization_id, "owner_user_id": user_id},
        )
    except Exception:
        logger.info("Mem0 library write skipped")


async def remember(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    text: str,
    kind: str = "preference",
    source: str = "",
    known_names: list[str] | None = None,
) -> dict[str, Any] | None:
    cleaned = scrub(text or "", known_names)
    if cleaned.quarantined or not cleaned.text.strip():
        return None
    row = ProfessorMemory(
        organization_id=organization_id,
        owner_user_id=user_id,
        kind=kind,
        text=cleaned.text,
        source=source,
    )
    db.add(row)
    await db.flush()
    _qdrant_upsert(str(organization_id), str(user_id), str(row.id), cleaned.text)
    _mem0_add(str(organization_id), str(user_id), cleaned.text)
    return {"id": str(row.id), "kind": row.kind, "text": row.text, "source": row.source}


async def list_memories(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(ProfessorMemory)
        .where(
            ProfessorMemory.organization_id == organization_id,
            ProfessorMemory.owner_user_id == user_id,
        )
        .order_by(ProfessorMemory.created_at.desc())
    )
    return [
        {"id": str(row.id), "kind": row.kind, "text": row.text, "source": row.source}
        for row in result.scalars().all()
    ]


async def delete_memory(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, memory_id: uuid.UUID
) -> bool:
    row = await db.get(ProfessorMemory, memory_id)
    if row is None or row.organization_id != organization_id or row.owner_user_id != user_id:
        return False
    await db.delete(row)
    return True


async def recall(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, limit: int = 6
) -> list[str]:
    rows = await list_memories(db, organization_id, user_id)
    return [row["text"] for row in rows[:limit]]
