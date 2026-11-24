import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.profassist.deps import ProfOrg
from app.profassist.outline import generate_outline, refine_outline

router = APIRouter()


class OutlineGenerateBody(BaseModel):
    message: str = ""


class OutlineRefineBody(BaseModel):
    message: str = ""
    section: str | None = None


@router.post("/outlines/{outline_id}/generate")
async def outlines_generate(
    outline_id: uuid.UUID, body: OutlineGenerateBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await generate_outline(db, org.id, user.id, outline_id, body.message)


@router.post("/outlines/{outline_id}/refine")
async def outlines_refine(
    outline_id: uuid.UUID, body: OutlineRefineBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    return await refine_outline(db, org.id, user.id, outline_id, body.message, body.section)
