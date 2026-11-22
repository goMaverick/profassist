"""Subject outline wizard. Drafts stay on the professor until she finishes the document."""

import json
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.errors import ProfassistError
from app.profassist.models import (
    Assessment,
    Course,
    CourseOutcome,
    OutcomeMap,
    OutlinePolicy,
    OutlineReading,
    OutlineTask,
    OutlineWeek,
    ProgramOutcome,
    RubricCriterion,
    SubjectOutline,
)
from app.profassist.outline_data import demo_outline, empty_outline
from app.profassist.outline_doc import render_docx, render_pdf
from app.profassist.pii import scrub
from app.profassist.settings_admin import load_runtime
from app.profassist.storage import save_bytes

STEPS = (
    "basics",
    "attachments",
    "lecture",
    "description",
    "outcomes",
    "schedule",
    "readings",
    "assessments",
    "policies",
    "review",
)


def _public(row: SubjectOutline) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "status": row.status,
        "course_id": str(row.course_id) if row.course_id else "",
        "body": row.body or empty_outline(),
        "pdf_ready": bool(row.pdf_key),
        "docx_ready": bool(row.docx_key),
        "instructions": row.instructions or "",
    }


async def list_outlines(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(SubjectOutline).where(
            SubjectOutline.organization_id == org_id,
            SubjectOutline.owner_user_id == user_id,
        )
    )
    return [_public(row) for row in result.scalars().all()]


async def start_outline(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, *, demo: bool = False
) -> dict[str, Any]:
    body = demo_outline() if demo else empty_outline()
    basics = body["basics"]
    # Each blank outline needs its own code. The professor replaces it on Basics.
    code = str(basics.get("code") or "").strip() or f"NEW-{uuid.uuid4().hex[:6].upper()}"
    row = SubjectOutline(
        organization_id=org_id,
        owner_user_id=user_id,
        code=code,
        name=basics.get("name") or "New subject",
        body=body,
        status="draft",
    )
    db.add(row)
    await db.flush()
    return _public(row)


async def get_outline(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, outline_id: uuid.UUID
) -> SubjectOutline:
    row = await db.get(SubjectOutline, outline_id)
    if row is None or row.organization_id != org_id or row.owner_user_id != user_id:
        raise ProfassistError(404, "That subject outline is not in your workspace.")
    return row


async def save_step(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    step: str,
    payload: dict[str, Any],
    *,
    trust_course_text: bool = False,
) -> dict[str, Any]:
    if step not in STEPS:
        raise ProfassistError(400, "That is not a step in the subject outline.")
    row = await get_outline(db, org_id, user_id, outline_id)
    if trust_course_text:
        from app.profassist.pii import strip_contacts

        payload = json.loads(strip_contacts(json.dumps(payload)))
    else:
        cleaned = scrub(str(payload))
        if cleaned.quarantined:
            raise ProfassistError(
                400, "That step still looks like it names a student. Remove the name."
            )
    body = dict(row.body or empty_outline())
    body[step if step != "schedule" else "weeks"] = payload.get("value", payload)
    if step == "basics":
        row.code = str(payload.get("code") or row.code)
        row.name = str(payload.get("name") or row.name)
        body["basics"] = payload
    elif step == "lecture":
        body["lecture"] = payload
    elif step == "description":
        body["description"] = payload.get("description") or payload.get("value") or ""
    elif step == "outcomes":
        body["program"] = payload.get("program") or body.get("program") or ""
        body["plos"] = payload.get("plos") or []
        body["clos"] = payload.get("clos") or []
    elif step == "schedule":
        body["weeks"] = payload.get("weeks") or []
    elif step == "readings":
        body["readings"] = payload.get("readings") or []
    elif step == "assessments":
        body["tasks"] = payload.get("tasks") or []
    elif step == "policies":
        body["policies"] = payload.get("policies") or []
    elif step == "attachments":
        note = str(payload.get("instructions") or payload.get("message") or "").strip()
        if note:
            row.instructions = scrub(note).text.strip()
        body.pop("attachments", None)
    elif step == "review":
        body.pop("review", None)
    row.body = body
    row.status = "draft"
    await db.flush()
    return _public(row)


async def assist_step(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    step: str,
    message: str,
) -> dict[str, Any]:
    from app.profassist.llm import complete

    row = await get_outline(db, org_id, user_id, outline_id)
    await load_runtime(db, org_id, user_id)
    cleaned = scrub(message or step)
    if cleaned.quarantined:
        raise ProfassistError(400, "That request still looks like it names a student.")
    course = await _course_for(db, org_id, row.body or {})
    row.course_id = course.id
    if row.instructions and not course.ai_instructions:
        course.ai_instructions = row.instructions
    drafted = complete(
        "outline_assist",
        {
            "step": step,
            "message": cleaned.text,
            "body": row.body or {},
            "instructions": row.instructions or course.ai_instructions or "",
            "chunks": await _ready_chunks(db, org_id, user_id, course.id),
        },
    )
    suggestion = drafted.get("suggestion") or {}
    if suggestion:
        await save_step(db, org_id, user_id, outline_id, step, suggestion, trust_course_text=True)
        row = await get_outline(db, org_id, user_id, outline_id)
    return {"reply": drafted.get("reply") or "Draft ready.", "outline": _public(row)}


async def finish_outline(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, outline_id: uuid.UUID
) -> dict[str, Any]:
    row = await get_outline(db, org_id, user_id, outline_id)
    body = row.body or {}
    if not (body.get("basics") or {}).get("name"):
        raise ProfassistError(400, "Name the subject before you finish the outline.")
    course = await _course_for(db, org_id, body)
    row.course_id = course.id
    await _replace_children(db, org_id, user_id, row, course, body)
    pdf = render_pdf(body)
    docx = render_docx(body)
    row.pdf_key = save_bytes(f"{org_id}/{user_id}/outline-{row.id}.pdf", pdf, "application/pdf")
    row.docx_key = save_bytes(
        f"{org_id}/{user_id}/outline-{row.id}.docx",
        docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    row.status = "published"
    await db.flush()
    index_outline(str(org_id), str(user_id), str(course.id), str(row.id), body)
    published = _public(row)
    published["course_id"] = str(course.id)
    return published


async def document_bytes(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, outline_id: uuid.UUID, kind: str
) -> tuple[str, bytes, str]:
    from app.profassist.storage import read_bytes

    row = await get_outline(db, org_id, user_id, outline_id)
    key = row.pdf_key if kind == "pdf" else row.docx_key
    if not key:
        raise ProfassistError(404, "Finish the outline before you download it.")
    media = (
        "application/pdf"
        if kind == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    filename = f"{row.code or 'subject'}-outline.{kind}"
    return filename, read_bytes(key), media


async def suggest_assessments(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    lo_codes: list[str],
) -> dict[str, Any]:
    from app.profassist.llm import complete

    row = await get_outline(db, org_id, user_id, outline_id)
    await load_runtime(db, org_id, user_id)
    clos = [
        item
        for item in (row.body or {}).get("clos") or []
        if not lo_codes or item.get("code") in lo_codes
    ]
    if not clos:
        raise ProfassistError(400, "Choose at least one course learning outcome.")
    drafted = complete(
        "assessment_suggest",
        {"clos": clos, "existing": (row.body or {}).get("tasks") or []},
    )
    return {"suggestions": drafted.get("suggestions") or [], "clos": clos}


async def accept_assessments(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    row = await get_outline(db, org_id, user_id, outline_id)
    body = dict(row.body or empty_outline())
    current = list(body.get("tasks") or [])
    numbers = {item.get("number") for item in current}
    for task in tasks:
        number = task.get("number") or _next_number(numbers)
        numbers.add(number)
        task = {**task, "number": number}
        current = [item for item in current if item.get("number") != number]
        current.append(task)
    body["tasks"] = current
    row.body = body
    await db.flush()
    if row.course_id:
        course = await db.get(Course, row.course_id)
        if course is not None:
            await _tasks_to_assessments(db, org_id, user_id, row, course, current)
    return _public(row)


async def save_instructions(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    text: str,
) -> dict[str, Any]:
    row = await get_outline(db, org_id, user_id, outline_id)
    cleaned = scrub(text or "")
    if cleaned.quarantined:
        raise ProfassistError(400, "Those instructions still look like they name a student.")
    row.instructions = cleaned.text.strip()
    course = await _course_for(db, org_id, row.body or {})
    row.course_id = course.id
    course.ai_instructions = row.instructions
    await db.flush()
    return _public(row)


async def attach_file(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    filename: str,
    data: bytes,
) -> dict[str, Any]:
    from app.profassist.service import add_material, list_materials

    row = await get_outline(db, org_id, user_id, outline_id)
    course = await _course_for(db, org_id, row.body or {})
    row.course_id = course.id
    await db.flush()
    material = await add_material(db, org_id, course.id, user_id, filename, data)
    materials = await list_materials(db, org_id, course.id, user_id)
    return {"material": material, "materials": materials, "outline": _public(row)}


async def outline_materials(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, outline_id: uuid.UUID
) -> list[dict[str, Any]]:
    from app.profassist.service import list_materials

    row = await get_outline(db, org_id, user_id, outline_id)
    if row.course_id is None:
        return []
    return await list_materials(db, org_id, row.course_id, user_id)


async def _ready_chunks(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> list[dict[str, str]]:
    from app.profassist.models import Chunk, Material

    materials = {
        row.id: row.filename
        for row in (
            await db.execute(
                select(Material).where(
                    Material.organization_id == org_id,
                    Material.course_id == course_id,
                    Material.owner_user_id == user_id,
                    Material.status == "ready",
                )
            )
        ).scalars()
    }
    chunks = []
    for row in (
        await db.execute(
            select(Chunk).where(
                Chunk.organization_id == org_id,
                Chunk.course_id == course_id,
                Chunk.owner_user_id == user_id,
            )
        )
    ).scalars():
        chunks.append(
            {
                "id": str(row.id),
                "text": row.text,
                "filename": materials.get(row.material_id, "note"),
            }
        )
    return chunks[:8]


def course_brief(body: dict[str, Any]) -> str:
    """Short context the council, slide studio, and chat can quote by id."""
    basics = body.get("basics") or {}
    lines = [
        f"Course {basics.get('code')} {basics.get('name')}.",
        "Course learning outcomes:",
    ]
    for item in body.get("clos") or []:
        lines.append(f"- {item.get('code')}: {item.get('text')}")
    lines.append("Assessments:")
    for item in body.get("tasks") or []:
        lines.append(
            f"- {item.get('number')} {item.get('name')} weight {item.get('weight')} due {item.get('due')} "
            f"outcomes {', '.join(item.get('lo_codes') or [])}"
        )
    return "\n".join(lines)


def index_outline(
    organization_id: str, user_id: str, course_id: str, outline_id: str, body: dict[str, Any]
) -> None:
    """Best-effort Qdrant index. Postgres remains the source of the outline."""
    import logging

    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from app.core.config import settings
    from app.profassist.similarity import hash_embed

    text = course_brief(body)
    if not settings.QDRANT_HOST:
        return
    try:
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT or 6333)
        name = "profassist_outline"
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=64, distance=Distance.COSINE),
            )
        client.upsert(
            collection_name=name,
            points=[
                PointStruct(
                    id=outline_id,
                    vector=hash_embed(text, 64),
                    payload={
                        "organization_id": organization_id,
                        "owner_user_id": user_id,
                        "course_id": course_id,
                        "text": text[:2000],
                        "clo_codes": [item.get("code") for item in body.get("clos") or []],
                        "assessment_numbers": [
                            item.get("number") for item in body.get("tasks") or []
                        ],
                    },
                )
            ],
        )
    except Exception:
        logging.getLogger(__name__).info("Outline vector was not written")


async def _course_for(db: AsyncSession, org_id: uuid.UUID, body: dict[str, Any]) -> Course:
    basics = body.get("basics") or {}
    code = str(basics.get("code") or "SUBJECT")
    compact = code.replace(" ", "").upper()
    result = await db.execute(select(Course).where(Course.organization_id == org_id))
    for course in result.scalars().all():
        if course.code.replace(" ", "").upper() == compact:
            return course
    course = Course(
        organization_id=org_id,
        code=compact,
        title=basics.get("name") or code,
        term=str(basics.get("year") or ""),
        clos=[item.get("text") for item in body.get("clos") or []],
    )
    db.add(course)
    await db.flush()
    return course


async def _clear_outline(db: AsyncSession, outline_id: uuid.UUID) -> None:
    clo_ids = [
        item.id
        for item in (
            await db.execute(select(CourseOutcome).where(CourseOutcome.outline_id == outline_id))
        ).scalars()
    ]
    if clo_ids:
        await db.execute(delete(OutcomeMap).where(OutcomeMap.clo_id.in_(clo_ids)))
    for model in (
        OutlinePolicy,
        OutlineTask,
        OutlineReading,
        OutlineWeek,
        CourseOutcome,
        ProgramOutcome,
    ):
        await db.execute(delete(model).where(model.outline_id == outline_id))


async def _replace_children(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    row: SubjectOutline,
    course: Course,
    body: dict[str, Any],
) -> None:
    await _clear_outline(db, row.id)
    plo_ids: dict[str, uuid.UUID] = {}
    for item in body.get("plos") or []:
        plo = ProgramOutcome(
            organization_id=org_id,
            owner_user_id=user_id,
            outline_id=row.id,
            code=item.get("code") or "",
            text=item.get("text") or "",
        )
        db.add(plo)
        await db.flush()
        plo_ids[plo.code] = plo.id
    for item in body.get("clos") or []:
        clo = CourseOutcome(
            organization_id=org_id,
            owner_user_id=user_id,
            outline_id=row.id,
            code=item.get("code") or "",
            text=item.get("text") or "",
        )
        db.add(clo)
        await db.flush()
        for code in item.get("plos") or []:
            if code in plo_ids:
                db.add(
                    OutcomeMap(
                        organization_id=org_id,
                        owner_user_id=user_id,
                        clo_id=clo.id,
                        plo_id=plo_ids[code],
                    )
                )
    for item in body.get("weeks") or []:
        db.add(
            OutlineWeek(
                organization_id=org_id,
                owner_user_id=user_id,
                outline_id=row.id,
                week=int(item.get("week") or 1),
                topic=item.get("topic") or "",
                lo_codes=item.get("lo_codes") or [],
                session_type=item.get("session_type") or "",
                delivery=item.get("delivery") or "",
                assessment_note=item.get("assessment_note") or "",
            )
        )
    for index, citation in enumerate(body.get("readings") or [], start=1):
        db.add(
            OutlineReading(
                organization_id=org_id,
                owner_user_id=user_id,
                outline_id=row.id,
                ordinal=index,
                citation=citation,
            )
        )
    for item in body.get("policies") or []:
        db.add(
            OutlinePolicy(
                organization_id=org_id,
                owner_user_id=user_id,
                outline_id=row.id,
                key=item.get("key") or "policy",
                title=item.get("title") or "Policy",
                body=item.get("body") or "",
            )
        )
    course.clos = [item.get("text") or "" for item in body.get("clos") or []]
    await _tasks_to_assessments(db, org_id, user_id, row, course, body.get("tasks") or [])
    await db.flush()


async def _tasks_to_assessments(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    row: SubjectOutline,
    course: Course,
    tasks: list[dict[str, Any]],
) -> None:
    for task in tasks:
        number = task.get("number") or "A1"
        external = f"outline:{number}"
        found = await db.execute(
            select(Assessment).where(
                Assessment.organization_id == org_id,
                Assessment.owner_user_id == user_id,
                Assessment.external_id == external,
            )
        )
        assessment = found.scalar_one_or_none()
        if assessment is None:
            assessment = Assessment(
                organization_id=org_id,
                course_id=course.id,
                owner_user_id=user_id,
                title=task.get("name") or number,
                brief=task.get("brief") or "",
                clos=task.get("lo_codes") or [],
                status="draft",
                external_id=external,
                weight=int(task.get("weight") or 0),
                kind="assignment",
            )
            db.add(assessment)
            await db.flush()
        else:
            assessment.title = task.get("name") or assessment.title
            assessment.brief = task.get("brief") or assessment.brief
            assessment.clos = task.get("lo_codes") or []
            assessment.weight = int(task.get("weight") or 0)
            assessment.course_id = course.id
        await db.execute(
            delete(RubricCriterion).where(RubricCriterion.assessment_id == assessment.id)
        )
        for ordinal, criterion in enumerate(task.get("criteria") or [], start=1):
            db.add(
                RubricCriterion(
                    organization_id=org_id,
                    assessment_id=assessment.id,
                    ordinal=ordinal,
                    name=criterion.get("name") or f"Criterion {ordinal}",
                    weight=int(criterion.get("weight") or 1),
                    levels=criterion.get("levels") or {},
                )
            )
        existing = await db.execute(
            select(OutlineTask).where(
                OutlineTask.outline_id == row.id, OutlineTask.number == number
            )
        )
        stored = existing.scalar_one_or_none()
        if stored is None:
            db.add(
                OutlineTask(
                    organization_id=org_id,
                    owner_user_id=user_id,
                    outline_id=row.id,
                    course_id=course.id,
                    assessment_id=assessment.id,
                    number=number,
                    name=task.get("name") or "",
                    task_type=task.get("task_type") or "",
                    weight=int(task.get("weight") or 0),
                    due=str(task.get("due") or ""),
                    lo_codes=task.get("lo_codes") or [],
                    brief=task.get("brief") or "",
                    criteria=task.get("criteria") or [],
                )
            )
        else:
            stored.assessment_id = assessment.id
            stored.name = task.get("name") or stored.name
            stored.weight = int(task.get("weight") or 0)
            stored.due = str(task.get("due") or "")
            stored.lo_codes = task.get("lo_codes") or []
            stored.brief = task.get("brief") or ""
            stored.criteria = task.get("criteria") or []


def _next_number(existing: set[str]) -> str:
    index = 1
    while f"A{index}" in existing:
        index += 1
    return f"A{index}"
