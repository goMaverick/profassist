"""RAG status streaming — Redis pub/sub fan-out for SSE clients."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import redis.asyncio as aioredis
import redis.exceptions
from fastapi.sse import ServerSentEvent

logger = logging.getLogger(__name__)


class RAGStatusService:
    """Streams RAG ingestion status events from Redis pub/sub.

    A shared ``aioredis.Redis`` client must be injected at construction time
    (created once during application lifespan and stored in ``app.state``).
    This avoids opening a new Redis connection for every SSE subscriber.
    """

    CHANNEL = "rag_status"

    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client

    async def stream_events(self, *, organization_id: UUID) -> AsyncIterator[ServerSentEvent]:
        """Yield ``ServerSentEvent`` items scoped to ``organization_id``.

        The channel is shared by every tenant, so each payload is parsed and
        events for another workspace (or events with no workspace at all) are
        dropped. Cleanup is guaranteed via ``finally`` even if the consumer
        disconnects mid-stream.
        """
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self.CHANNEL)
        event_id = 0

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                payload = message["data"]
                data = payload.decode() if isinstance(payload, bytes) else payload
                if not self._belongs_to(data, organization_id):
                    continue
                event_id += 1
                yield ServerSentEvent(raw_data=data, event="status", id=str(event_id))
        except asyncio.CancelledError:
            # Client disconnected — propagate cancellation cleanly
            raise
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as exc:
            logger.warning("RAG SSE stream lost Redis connection: %s", exc)
            yield ServerSentEvent(data="stream_error", event="error", id=str(event_id + 1))
        except Exception:
            logger.exception("RAG SSE stream encountered an unexpected error")
            yield ServerSentEvent(data="stream_error", event="error", id=str(event_id + 1))
            raise
        finally:
            try:
                await pubsub.unsubscribe(self.CHANNEL)
            except Exception as exc:
                logger.debug("RAG SSE cleanup error: %s", exc)

    @staticmethod
    def _belongs_to(data: str, organization_id: UUID) -> bool:
        """True only when the payload names this exact organization."""
        try:
            parsed = json.loads(data)
        except (TypeError, ValueError):
            logger.debug("RAG SSE event is not JSON; dropping it")
            return False
        if not isinstance(parsed, dict):
            return False
        event_org = parsed.get("organization_id")
        if event_org is None:
            logger.debug("RAG SSE event has no organization_id; dropping it")
            return False
        return str(event_org) == str(organization_id)
