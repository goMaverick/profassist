"""Per-university Moodle connection.

Creating, changing, testing, syncing, and deleting a connection require an app
admin. The read-only status stays available to a workspace member so the grading
and outline pages can show the redacted sync state. Every read path masks the
token, and test/sync redact it out of Moodle errors before storage or a response.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentAppAdmin, CurrentUser, DBSession
from app.integrations.moodle.gateway import audit_for, status_for, test_connection
from app.integrations.moodle.gateway import sync as gateway_sync
from app.profassist.deps import ProfOrg
from app.profassist.moodle_connection import (
    disable_connection,
    get_view,
    save_connection,
)

router = APIRouter()


class ConnectionBody(BaseModel):
    label: str = ""
    base_url: str = ""
    ws_token: str = ""
    course_scope: dict[str, Any] = Field(default_factory=dict)
    push_enabled: bool = False


@router.get("/moodle/connection")
async def moodle_connection_view(user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await get_view(db, org.id)


@router.put("/moodle/connection")
async def moodle_connection_save(
    body: ConnectionBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict:
    return await save_connection(
        db,
        org.id,
        user.id,
        label=body.label,
        base_url=body.base_url,
        ws_token=body.ws_token,
        course_scope=body.course_scope,
        push_enabled=body.push_enabled,
    )


@router.post("/moodle/connection/test")
async def moodle_connection_test(user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await test_connection(db, org.id)


@router.delete("/moodle/connection")
async def moodle_connection_delete(user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await disable_connection(db, org.id)


@router.post("/moodle/sync")
async def moodle_sync_route(user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    return await gateway_sync(db, org.id, user.id, trigger="manual")


@router.post("/moodle/test")
async def moodle_test_route(user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    """Legacy admin-only probe. The connection screen uses /connection/test."""
    del user
    return await test_connection(db, org.id)


@router.get("/moodle/status")
async def moodle_status_route(user: CurrentUser, org: ProfOrg, db: DBSession) -> dict:
    # Read-only and redacted, so the grading and outline pages can show the
    # sync state. The token never appears in this payload.
    del user
    return await status_for(db, org.id)


@router.get("/moodle/audit")
async def moodle_audit_route(user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await audit_for(db, org.id, limit=10)
