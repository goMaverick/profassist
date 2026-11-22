"""Workspace selection. A university org wins over the personal org."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy import select, text

from app.api.deps import CurrentUser, DBSession
from app.db.models.organization import Organization, OrganizationMember
from app.profassist.errors import ProfassistError
from app.repositories import member_repo, organization_repo


async def get_profassist_org(
    user: CurrentUser,
    db: DBSession,
    x_organization_id: Annotated[UUID | None, Header()] = None,
) -> Organization:
    if x_organization_id is not None:
        membership = await member_repo.get(db, organization_id=x_organization_id, user_id=user.id)
        if membership is None:
            raise ProfassistError(404, "Organization not found or access denied")
        org = await organization_repo.get_by_id(db, x_organization_id)
        if org is None:
            raise ProfassistError(404, "Organization not found")
    else:
        result = await db.execute(
            select(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user.id)
            .order_by(Organization.is_personal.asc(), Organization.created_at.asc())
        )
        org = result.scalars().first()
        if org is None:
            raise ProfassistError(404, "This account has no workspace yet")
    await db.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org.id)})
    return org


ProfOrg = Annotated[Organization, Depends(get_profassist_org)]
