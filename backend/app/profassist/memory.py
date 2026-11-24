"""Per-professor memory.

Postgres is the source of truth: a scrubbed copy is stored there, scoped to one
professor inside one university. Qdrant holds a 64-dim mirror used for
similarity work.

Mem0 is an optional mirror and is off by default. When it is enabled its hits are
merged into recall, and Postgres is the fallback: a missing library, a bad
configuration, or a failed call never removes the Postgres answer. Student names
never enter memory.
"""

import asyncio
import logging
import os
import tempfile
import threading
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.profassist.config import llm_api_key, llm_base_url, llm_model
from app.profassist.lessons import same_lesson
from app.profassist.models import ProfessorMemory
from app.profassist.pii import scrub
from app.profassist.similarity import hash_embed

logger = logging.getLogger(__name__)
COLLECTION = "profassist_memory"
MEM0_COLLECTION = "mem0_profassist"

# Mem0 embedders that run the model on this machine, so no memory text leaves the host.
LOCAL_EMBEDDERS = frozenset({"fastembed", "huggingface", "ollama"})
# A cloud embedder is used only when MEM0_EMBEDDER_PROVIDER names one on purpose.
CLOUD_EMBEDDERS = frozenset({"openai", "azure_openai"})
# Vector size per embedder, used only when mem0 creates the collection for the first time.
EMBEDDER_DIMS = {"fastembed": 1024, "openai": 1536}
DEFAULT_EMBEDDER = "fastembed"

_MEM0_LOCK = threading.Lock()
_MEM0_STORE: Any = None


def _is_interrupt(exc: BaseException) -> bool:
    """Signals that must stop the caller rather than be treated as a Mem0 failure."""
    return isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))


def _disable_mem0_telemetry() -> None:
    """Keep mem0's PostHog telemetry off unless an operator opts in.

    mem0 reads MEM0_TELEMETRY when its package is imported, so this runs at import
    time here and again right before the library is loaded.
    """
    os.environ.setdefault("MEM0_TELEMETRY", "False")


_disable_mem0_telemetry()


def mem0_enabled() -> bool:
    """Mem0 is an opt-in mirror. Off unless MEM0_ENABLED is set."""
    return os.getenv("MEM0_ENABLED", "").strip().lower() in {"1", "true"}


def scope_id(organization_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"{organization_id}:{user_id}"


def mem0_embedder_provider() -> str:
    """Embedder mem0 uses. It runs locally (fastembed) unless told otherwise."""
    return (os.getenv("MEM0_EMBEDDER_PROVIDER") or DEFAULT_EMBEDDER).strip().lower()


def _embedder_dims(provider: str, model: str) -> int | None:
    """Vector size for the embedder, or None when it cannot be known safely."""
    raw = os.getenv("MEM0_EMBEDDER_DIMS", "").strip()
    if raw:
        try:
            dims = int(raw)
        except ValueError:
            return None
        return dims if dims > 0 else None
    if model:
        return None
    return EMBEDDER_DIMS.get(provider)


def _mem0_embedder() -> dict[str, Any] | None:
    """The embedder block, or None when no safe embedder is configured.

    Returning None is what keeps memory text off OpenAI: mem0 defaults to its own
    ``openai`` embedder, so an omitted block would send every memory to
    api.openai.com even when this deployment runs its model somewhere else.
    """
    provider = mem0_embedder_provider()
    if provider not in LOCAL_EMBEDDERS and provider not in CLOUD_EMBEDDERS:
        logger.info("Mem0 skipped: unsupported MEM0_EMBEDDER_PROVIDER %r", provider)
        return None
    model = os.getenv("MEM0_EMBEDDER_MODEL", "").strip()
    dims = _embedder_dims(provider, model)
    if dims is None:
        logger.info(
            "Mem0 skipped: set MEM0_EMBEDDER_DIMS to the vector size of %r", model or provider
        )
        return None
    config: dict[str, Any] = {"embedding_dims": dims}
    if model:
        config["model"] = model
    if provider in CLOUD_EMBEDDERS:
        key = llm_api_key()
        if not key:
            logger.info("Mem0 skipped: the %s embedder needs LLM_API_KEY", provider)
            return None
        config["api_key"] = key
        base = llm_base_url()
        if base:
            config["openai_base_url"] = base
    return {"provider": provider, "config": config}


def _mem0_history_path() -> str:
    """Mem0's sqlite history file, under the platform temp dir rather than a hardcoded /tmp."""
    configured = os.getenv("MEM0_HISTORY_PATH", "").strip()
    path = configured or os.path.join(tempfile.gettempdir(), "profassist-mem0.db")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return path


def _mem0_config() -> dict[str, Any] | None:
    """The opt-in Mem0 store, or None when no safe embedder is configured."""
    embedder = _mem0_embedder()
    if embedder is None:
        return None
    llm: dict[str, Any] = {"provider": "litellm", "config": {"model": llm_model()}}
    key = llm_api_key()
    if key:
        llm["config"]["api_key"] = key
    # Point LiteLLM at the configured gateway. Without this Mem0's default
    # provider silently calls api.openai.com even on a local deployment.
    base = llm_base_url()
    if base:
        llm["config"]["api_base"] = base
    return {
        "embedder": embedder,
        "llm": llm,
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": os.getenv("QDRANT_HOST", "localhost"),
                "port": int(os.getenv("QDRANT_PORT", "6333")),
                "collection_name": MEM0_COLLECTION,
                "embedding_model_dims": embedder["config"]["embedding_dims"],
            },
        },
        "history_db_path": _mem0_history_path(),
    }


def _reset_mem0_store() -> None:
    """Drop the cached Mem0 client. Tests call this between cases."""
    global _MEM0_STORE
    with _MEM0_LOCK:
        _MEM0_STORE = None


def _mem0_store() -> Any:
    """One Mem0 client per process, or None when Mem0 is off or unavailable."""
    global _MEM0_STORE
    if _MEM0_STORE is not None:
        return _MEM0_STORE
    with _MEM0_LOCK:
        if _MEM0_STORE is not None:
            return _MEM0_STORE
        _disable_mem0_telemetry()
        try:
            config = _mem0_config()
            if config is None:
                return None
            from mem0 import Memory

            _MEM0_STORE = Memory.from_config(config)
        except BaseException as exc:
            # mem0 can raise SystemExit (spacy.cli.download) instead of Exception.
            # Swallowing it keeps one bad mirror from taking the ASGI worker down.
            if _is_interrupt(exc):
                raise
            logger.info("Mem0 is unavailable (%s); the Postgres copy stands", type(exc).__name__)
            return None
        return _MEM0_STORE


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
    """Best-effort Mem0 write. Opt-in via MEM0_ENABLED and an LLM key; absent lib is skipped."""
    if not mem0_enabled() or not llm_api_key():
        return
    store = _mem0_store()
    if store is None:
        return
    try:
        store.add(
            text,
            user_id=scope_id(uuid.UUID(organization_id), uuid.UUID(user_id)),
            metadata={"organization_id": organization_id, "owner_user_id": user_id},
        )
    except BaseException as exc:
        if _is_interrupt(exc):
            raise
        logger.info("Mem0 write skipped (%s); the Postgres copy remains", type(exc).__name__)


def _mem0_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("memory", "text", "data", "value"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def mem0_search(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[str]:
    """Best-effort Mem0 read, scoped to this professor. Postgres answers if it fails."""
    if not mem0_enabled() or not llm_api_key() or limit <= 0:
        return []
    store = _mem0_store()
    if store is None:
        return []
    try:
        found = store.search(
            query,
            filters={"user_id": scope_id(organization_id, user_id)},
            top_k=limit,
        )
    except BaseException as exc:
        if _is_interrupt(exc):
            raise
        logger.info("Mem0 search skipped (%s); the Postgres copy stands", type(exc).__name__)
        return []
    if isinstance(found, dict):
        raw = found.get("results") or found.get("memories") or []
    else:
        raw = found or []
    texts: list[str] = []
    if not isinstance(raw, list):
        raw = [raw]
    for item in raw:
        text = _mem0_text(item)
        if text and text not in texts:
            texts.append(text)
        if len(texts) >= limit:
            break
    return texts


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
    existing = await db.execute(
        select(ProfessorMemory).where(
            ProfessorMemory.organization_id == organization_id,
            ProfessorMemory.owner_user_id == user_id,
            ProfessorMemory.kind == kind,
        )
    )
    for prior in existing.scalars().all():
        if same_lesson(prior.text, cleaned.text):
            prior.text = cleaned.text
            prior.source = source
            await db.flush()
            _qdrant_upsert(str(organization_id), str(user_id), str(prior.id), cleaned.text)
            _mem0_add(str(organization_id), str(user_id), cleaned.text)
            return {
                "id": str(prior.id),
                "kind": prior.kind,
                "text": prior.text,
                "source": prior.source,
                "updated": True,
            }
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
    return {
        "id": str(row.id),
        "kind": row.kind,
        "text": row.text,
        "source": row.source,
        "updated": False,
    }


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
    owner = await db.get(User, user_id)
    owner_name = owner.full_name if owner and owner.full_name else ""
    return [
        {
            "id": str(row.id),
            "kind": row.kind,
            "text": row.text,
            "source": row.source,
            "owner_name": owner_name,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
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
