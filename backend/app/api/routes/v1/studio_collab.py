"""Material Studio collaboration routes: start, stream over SSE, and pause.

A collaboration job lives in process memory for the length of one draft. The
stream runs the Creator/Reviewer loop; pause is a separate POST so the UI can
stop the loop without dropping the connection.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.profassist import service
from app.profassist.deps import ProfOrg
from app.profassist.errors import ProfassistError
from app.profassist.slide_collab import (
    collaboration_events,
    create_job,
    get_job,
    pause_job,
)

router = APIRouter()


class CollaborateBody(BaseModel):
    week: int = 0
    instructions: str = ""


@router.post("/courses/{course_id}/slides/collaborate")
async def slides_collaborate(
    course_id: uuid.UUID,
    body: CollaborateBody,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
) -> dict[str, str]:
    """Start a Creator/Reviewer job for one of this workspace's courses."""
    await service._course(db, org.id, course_id)
    if not 0 <= body.week <= 52:
        raise ProfassistError(400, "Week must be between 0 and 52.")
    job_id = create_job(org.id, user.id, course_id, body.week, body.instructions)
    return {"job_id": job_id}


@router.get("/slides/collaborate/{job_id}/stream")
async def slides_collaborate_stream(
    job_id: str, user: CurrentUser, org: ProfOrg, db: DBSession
) -> StreamingResponse:
    job = get_job(job_id, org.id, user.id)

    async def events():
        async for event in collaboration_events(job, db):
            yield f"data: {json.dumps(event)}\n\n".encode()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/slides/collaborate/{job_id}/pause")
async def slides_collaborate_pause(job_id: str, user: CurrentUser, org: ProfOrg) -> dict[str, bool]:
    """Ask the running loop to keep the draft as it is. Idempotent."""
    pause_job(job_id, org.id, user.id)
    return {"paused": True}


@router.get("/slides/collaborate/{job_id}")
async def slides_collaborate_status(job_id: str, user: CurrentUser, org: ProfOrg) -> dict[str, Any]:
    job = get_job(job_id, org.id, user.id)
    return {
        "job_id": job["id"],
        "done": bool(job["done"]),
        "paused": bool(job["stop"]),
        "deck_id": job["deck_id"] or "",
    }
