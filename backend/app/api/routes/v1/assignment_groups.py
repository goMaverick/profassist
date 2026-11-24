"""Assignment-scoped student groups.

Course-level groups live on the course. The moment a group belongs to one
assignment, saving it must not replace the course-level groups or another
assignment's groups.
"""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.profassist.deps import ProfOrg
from app.profassist.errors import ProfassistError
from app.profassist.groupwork import assignment_groups, assignment_view, roster, save_groups

router = APIRouter()


class GroupItem(BaseModel):
    name: str = "Group"
    member_ids: list[str] = Field(default_factory=list)


class GroupsBody(BaseModel):
    groups: list[GroupItem] = Field(default_factory=list)


@router.get("/assignments/{assignment_id}/groups")
async def assignment_groups_list(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return {"items": await assignment_groups(db, org.id, user.id, assignment_id)}


@router.post("/assignments/{assignment_id}/groups")
async def assignment_groups_save(
    assignment_id: uuid.UUID, body: GroupsBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    """Save groups for exactly one assignment.

    ``assignment_view`` hides another tenant's assignment as a 404. Every member
    id must already be on that assignment's course roster.
    """
    current = await assignment_view(db, org.id, user.id, assignment_id)
    course_id = uuid.UUID(current["course_id"])
    roster_ids = {item["id"] for item in await roster(db, org.id, course_id)}
    for group in body.groups:
        if any(member not in roster_ids for member in group.member_ids):
            raise ProfassistError(400, "Every member must be on the course roster.")
    items = await save_groups(
        db,
        org.id,
        user.id,
        course_id,
        [group.model_dump() for group in body.groups],
        assignment_id=assignment_id,
    )
    return {"items": items}
