"""Idempotent demo professor, university workspace, course and Moodle submissions."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.config import demo_email, demo_password
from app.profassist.moodle import LECTURE_NOTE
from app.profassist.service import DEFAULT_SOUL, add_material, save_style, sync_moodle
from app.repositories import organization_repo, user_repo
from app.schemas.organization import OrganizationCreate
from app.schemas.user import UserCreate
from app.services.organization import OrganizationService
from app.services.user import UserService

logger = logging.getLogger(__name__)


async def seed_demo(db: AsyncSession) -> None:
    email = demo_email()
    user = await user_repo.get_by_email(db, email)
    if user is None:
        user = await UserService(db).register(
            UserCreate(
                email=email,
                password=demo_password(),
                full_name="Layla Hassan",
            )
        )
        logger.info("Created demo professor %s", email)
    user.onboarding_completed_at = datetime.now(UTC)
    user.is_app_admin = True
    user.full_name = user.full_name or "Layla Hassan"

    org = await organization_repo.get_by_slug(db, "uowd")
    if org is None:
        org = await OrganizationService(db).create(
            OrganizationCreate(name="University of Wollongong in Dubai", slug="uowd"),
            user.id,
        )
        logger.info("Created university workspace uowd")

    from app.profassist.models import Course, Material, StyleProfile

    existing_style = await db.execute(
        select(StyleProfile).where(
            StyleProfile.organization_id == org.id, StyleProfile.user_id == user.id
        )
    )
    if existing_style.scalar_one_or_none() is None:
        await save_style(db, org.id, user.id, DEFAULT_SOUL)
    summary = await sync_moodle(db, org.id, user.id)

    result = await db.execute(
        select(Course).where(Course.organization_id == org.id, Course.code == "MAAI903")
    )
    course = result.scalar_one_or_none()
    if course is None:
        return
    materials = await db.execute(select(Material).where(Material.course_id == course.id))
    if materials.first() is None:
        await add_material(
            db,
            org.id,
            course.id,
            user.id,
            "lecture-note.txt",
            LECTURE_NOTE.encode(),
        )
    from app.profassist.models import Assessment, Chunk, Material, Objective, SlideDeck

    for model in (Material, Chunk, Objective, SlideDeck, Assessment):
        rows = await db.execute(
            select(model).where(model.organization_id == org.id, model.owner_user_id.is_(None))
        )
        for row in rows.scalars().all():
            row.owner_user_id = user.id
    logger.info("Demo seed sync %s", summary)
