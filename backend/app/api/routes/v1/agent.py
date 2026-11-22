# Route is lifecycle plumbing only — auth, accept, dispatch loop, disconnect.
# Per-turn orchestration lives in app.services.agent_session.AgentSession.
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import CurrentUserWS
from app.core.config import settings
from app.schemas.base import AgentModelsResponse
from app.services.agent import AgentConnectionManager
from app.services.agent_session import AgentSession

logger = logging.getLogger(__name__)

router = APIRouter()

manager = AgentConnectionManager()


@router.get("/agent/models", response_model=AgentModelsResponse)
async def list_models() -> dict[str, Any]:
    """Return available LLM models and the current default."""
    return {
        "default": settings.AI_MODEL,
        "models": settings.AI_AVAILABLE_MODELS,
    }


@router.websocket("/ws/agent")
async def agent_websocket(
    websocket: WebSocket,
    user: CurrentUserWS,
) -> None:
    if user is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    from sqlalchemy import select

    from app.db.models.organization import Organization, OrganizationMember
    from app.db.session import get_db_context
    from app.profassist.models import AiSettings

    async with get_db_context() as db:
        result = await db.execute(
            select(AiSettings.chat_enabled)
            .join(Organization, Organization.id == AiSettings.organization_id)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user.id, Organization.is_personal.is_(False))
        )
        flags = list(result.scalars().all())
    if flags and not any(flags):
        await websocket.close(code=4003, reason="AI chat is disabled")
        return

    await manager.connect(websocket)
    session = AgentSession(
        websocket,
        user,
    )

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            await session.handle_frame(data)
    finally:
        await session.shutdown()
        manager.disconnect(websocket)
