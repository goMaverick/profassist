"""Council settings: which reviewers run, in what order, and in whose voice.

Only an app admin may read or change a council. A university's saved list
replaces the code default, and the chair always speaks last.
"""

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentAppAdmin, DBSession
from app.profassist.council_config import (
    COUNCIL_KEYS,
    council_view,
    reset_council,
    save_council_roles,
)
from app.profassist.deps import ProfOrg

router = APIRouter()


class RoleBody(BaseModel):
    role_key: str
    label: str = ""
    kind: Literal["creator", "deterministic", "llm", "chair"] = "llm"
    persona_prompt: str = ""
    agent_key: str = ""
    model: str = ""
    position: int | None = None
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class CouncilBody(BaseModel):
    roles: list[RoleBody]


@router.get("/councils")
async def list_councils(user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    del user
    return {"councils": [await council_view(db, org.id, key) for key in COUNCIL_KEYS]}


@router.put("/councils/{key}")
async def save_council(
    key: str, body: CouncilBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict:
    del user
    roles = [role.model_dump() for role in body.roles]
    return await save_council_roles(db, org.id, key, roles)


@router.post("/councils/{key}/reset")
async def reset_council_route(key: str, user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    del user
    return await reset_council(db, org.id, key)
