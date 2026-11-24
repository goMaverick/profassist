"""Course outline, outcomes, and the assessment plan. Drafts stay drafts until she approves."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist import agents
from app.profassist.errors import ProfassistError
from app.profassist.models import Assessment, CourseDesign, Objective
from app.profassist.pii import scrub
from app.profassist.service import (
    _chunks,
    _course,
    _soul,
    list_materials,
    recall,
    reflect_on_change,
)
from app.profassist.settings_admin import load_runtime


def _empty_body() -> dict[str, Any]:
    return {"reply": "", "weeks": [], "clos": [], "plan": []}


def _public(row: CourseDesign) -> dict[str, Any]:
    body = row.body or _empty_body()
    return {
        "id": str(row.id),
        "status": row.status,
        "version": row.version,
        "reply": body.get("reply") or "",
        "weeks": body.get("weeks") or [],
        "clos": body.get("clos") or [],
        "plan": body.get("plan") or [],
        "history": [
            {"version": item.get("version"), "status": item.get("status")}
            for item in (row.history or [])
        ],
    }


async def _row(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID, *, create: bool
) -> CourseDesign | None:
    result = await db.execute(
        select(CourseDesign).where(
            CourseDesign.organization_id == org_id,
            CourseDesign.course_id == course_id,
            CourseDesign.owner_user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None and create:
        row = CourseDesign(
            organization_id=org_id,
            course_id=course_id,
            owner_user_id=user_id,
            body=_empty_body(),
            status="draft",
        )
        db.add(row)
        await db.flush()
    return row


async def get_design(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, Any]:
    await _course(db, org_id, course_id)
    row = await _row(db, org_id, course_id, user_id, create=False)
    if row is None:
        return {
            "status": "empty",
            "version": 0,
            "reply": "",
            "weeks": [],
            "clos": [],
            "plan": [],
            "history": [],
        }
    return _public(row)


async def draft_design(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    message: str,
) -> dict[str, Any]:
    await load_runtime(db, org_id, user_id)
    course = await _course(db, org_id, course_id)
    materials = await list_materials(db, org_id, course.id, user_id)
    if not materials:
        raise ProfassistError(400, "Upload a course note before asking for a course design.")
    chunks = [
        {"id": str(row.id), "text": row.text}
        for row in await _chunks(db, org_id, course.id, user_id)
    ]
    cleaned = scrub(message or "Draft the course from my notes.")
    if cleaned.quarantined:
        raise ProfassistError(400, "That message still looks like it names a person.")
    memories = await recall(db, org_id, user_id)
    soul = (await _soul(db, org_id, user_id)) + "\n" + "\n".join(memories)
    drafted = agents.run_course(
        "course_design",
        title=course.title,
        query=cleaned.text or "course outline",
        message=cleaned.text,
        chunks=chunks[:4],
        clos=course.clos or [],
        soul=soul,
    )
    row = await _row(db, org_id, course_id, user_id, create=True)
    assert row is not None
    if row.body and row.body.get("weeks"):
        history = list(row.history or [])
        history.append({"version": row.version, "status": row.status, "body": row.body})
        row.history = history[-12:]
        row.version += 1
    row.body = {
        "reply": drafted.get("reply") or "Draft ready for you to edit.",
        "weeks": drafted.get("weeks") or [],
        "clos": drafted.get("clos") or [],
        "plan": drafted.get("plan") or [],
    }
    row.status = "draft"
    await db.flush()
    return _public(row)


async def save_design(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    body: dict[str, Any],
) -> dict[str, Any]:
    course = await _course(db, org_id, course_id)
    row = await _row(db, org_id, course.id, user_id, create=True)
    assert row is not None
    text = " ".join(
        str(item.get("text") or item.get("topic") or item.get("title") or "")
        for item in (body.get("clos") or []) + (body.get("weeks") or []) + (body.get("plan") or [])
    )
    cleaned = scrub(text)
    if cleaned.quarantined:
        raise ProfassistError(
            400, "The outline still looks like it names a person. Remove the name."
        )
    if row.body and row.body.get("weeks"):
        history = list(row.history or [])
        history.append({"version": row.version, "status": row.status, "body": row.body})
        row.history = history[-12:]
        row.version += 1
    row.body = {
        "reply": body.get("reply") or (row.body or {}).get("reply") or "",
        "weeks": body.get("weeks") or [],
        "clos": body.get("clos") or [],
        "plan": body.get("plan") or [],
    }
    row.status = "draft"
    await db.flush()
    return _public(row)


async def approve_design(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, Any]:
    course = await _course(db, org_id, course_id)
    row = await _row(db, org_id, course.id, user_id, create=False)
    if row is None or not (row.body or {}).get("clos"):
        raise ProfassistError(400, "Draft a course outline before you approve it.")
    before = " ".join(course.clos or [])
    clos = [item.get("text") or "" for item in row.body.get("clos") or [] if item.get("text")]
    course.clos = clos
    existing = await db.execute(
        select(Objective).where(
            Objective.organization_id == org_id,
            Objective.course_id == course.id,
            Objective.owner_user_id == user_id,
        )
    )
    have = {item.text for item in existing.scalars().all()}
    for ordinal, text in enumerate(clos, start=1):
        if text in have:
            continue
        db.add(
            Objective(
                organization_id=org_id,
                course_id=course.id,
                owner_user_id=user_id,
                ordinal=ordinal,
                text=text,
                status="approved",
                source_chunk_ids=[],
            )
        )
    for item in row.body.get("plan") or []:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        found = await db.execute(
            select(Assessment).where(
                Assessment.organization_id == org_id,
                Assessment.course_id == course.id,
                Assessment.owner_user_id == user_id,
                Assessment.title == title,
            )
        )
        assessment = found.scalar_one_or_none()
        if assessment is None:
            assessment = Assessment(
                organization_id=org_id,
                course_id=course.id,
                owner_user_id=user_id,
                title=title,
                brief=item.get("brief") or "",
                clos=item.get("clos") or clos,
                status="draft",
                external_id="",
                weight=int(item.get("weight") or 0),
                kind=item.get("kind") or "assignment",
            )
            db.add(assessment)
        elif assessment.status != "approved":
            assessment.brief = item.get("brief") or assessment.brief
            assessment.clos = item.get("clos") or assessment.clos
            assessment.weight = int(item.get("weight") or assessment.weight or 0)
            assessment.kind = item.get("kind") or assessment.kind
    row.status = "approved"
    await db.flush()
    await reflect_on_change(
        db, org_id, user_id, "objective", before, " ".join(clos), "design-approve"
    )
    return _public(row)
