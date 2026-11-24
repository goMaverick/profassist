"""Subject outline wizard. Drafts stay on the professor until she finishes the document."""

import json
import re
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.council_config import load_council_roles, role_of
from app.profassist.course_memory.service import dossier_ai_context
from app.profassist.errors import ProfassistError
from app.profassist.models import (
    Assessment,
    Course,
    CourseOutcome,
    GroupAssignment,
    OutcomeMap,
    OutlinePolicy,
    OutlineReading,
    OutlineTask,
    OutlineWeek,
    ProgramOutcome,
    RubricCriterion,
    SubjectOutline,
)
from app.profassist.observe import step_trace_url
from app.profassist.outline_data import BASICS_FIELDS, LECTURE_FIELDS, empty_outline
from app.profassist.outline_doc import render_docx, render_pdf
from app.profassist.pii import scrub
from app.profassist.service import capture_movement, reflect_on_change
from app.profassist.settings_admin import load_runtime
from app.profassist.slide_memory import artifact_preferences
from app.profassist.storage import save_bytes


def _body_text(body: dict[str, Any] | None) -> str:
    """Stable text for the content sections, so a movement can be compared."""
    payload = body or {}
    return json.dumps(
        {key: payload.get(key) for key in CONTENT_SECTIONS},
        sort_keys=True,
        ensure_ascii=False,
    )


def _step_text(body: dict[str, Any] | None, step: str) -> str:
    payload = body or {}
    keys = {
        "outcomes": ("plos", "clos"),
        "schedule": ("weeks",),
        "assessment_map": ("outcome_measures",),
    }.get(step, (step,))
    return "\n".join(
        json.dumps(payload.get(key) or "", sort_keys=True, ensure_ascii=False) for key in keys
    )


STEPS = (
    "basics",
    "lecture",
    "description",
    "outcomes",
    "schedule",
    "readings",
    "assessment_map",
    "genai",
    "grades",
    "satisfactory",
    "policy_documents",
    "policies",
    "ssp",
    "academic_integrity",
    "attendance",
    "supplementary",
    "lecture_capture",
    "sustainability",
    "late_submission",
)


def _public(row: SubjectOutline) -> dict[str, Any]:
    source_materials = (row.body or {}).get("source_materials") or []
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "status": row.status,
        "course_id": str(row.course_id) if row.course_id else "",
        "body": row.body or empty_outline(),
        "source_materials": source_materials,
        "sources": [item.get("filename") or "" for item in source_materials],
        "pdf_ready": bool(row.pdf_key),
        "docx_ready": bool(row.docx_key),
        "instructions": row.instructions or "",
    }


async def _refresh_source_materials(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, row: SubjectOutline
) -> None:
    """Keep the display snapshot current. A missing course simply leaves it empty."""
    if row.course_id is None:
        return
    try:
        from app.profassist.service import list_materials

        materials = await list_materials(db, org_id, row.course_id, user_id)
        body = dict(row.body or empty_outline())
        body["source_materials"] = [_material_source(item) for item in materials]
        row.body = body
    except Exception:
        import logging

        logging.getLogger(__name__).info("Outline source materials were not refreshed")


async def list_outlines(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(SubjectOutline).where(
            SubjectOutline.organization_id == org_id,
            SubjectOutline.owner_user_id == user_id,
        )
    )
    rows = result.scalars().all()
    for row in rows:
        await _refresh_source_materials(db, org_id, user_id, row)
    return [_public(row) for row in rows]


async def start_outline(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    body = empty_outline()
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
    await _refresh_source_materials(db, org_id, user_id, row)
    return row


async def save_step(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    step: str,
    payload: dict[str, Any],
    *,
    trust_course_text: bool = True,
) -> dict[str, Any]:
    if step not in STEPS:
        raise ProfassistError(400, "That is not a step in the subject outline.")
    row = await get_outline(db, org_id, user_id, outline_id)
    if trust_course_text:
        # Outline steps hold course content, not student submissions. The lecture
        # section is public staff information: keep the educator's name, email,
        # office, and consultation as the professor entered them. Other steps may
        # still include student-like contacts, so drop those.
        if step != "lecture":
            from app.profassist.pii import strip_contacts_in_payload

            # Scrub the string values, never the serialised JSON: the digits in a
            # ``\u2013`` escape look like a phone number and would corrupt it.
            payload = strip_contacts_in_payload(payload)
    else:
        cleaned = scrub(str(payload))
        if cleaned.quarantined:
            raise ProfassistError(
                400, "That step still looks like it names a student. Remove the name."
            )
    before_body = dict(row.body or empty_outline())
    body = dict(row.body or empty_outline())
    code_changed = False
    if step == "basics":
        code = str(payload.get("code") or row.code)
        code_changed = code != row.code
        row.code = code
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
        body["weeks"] = payload.get("weeks") or payload.get("value") or []
    elif step == "readings":
        body["readings"] = payload.get("readings") or payload.get("value") or []
    elif step == "assessment_map":
        body["outcome_measures"] = payload.get("outcome_measures") or payload.get("value") or []
    elif step == "genai":
        body["genai_intro"] = payload.get("genai_intro") or body.get("genai_intro") or ""
        body["genai"] = payload.get("genai") or payload.get("value") or []
    elif step == "grades":
        body["grades"] = payload.get("grades") or payload.get("value") or []
    elif step == "satisfactory":
        body["satisfactory"] = payload.get("satisfactory") or payload.get("value") or []
        body["satisfactory_note"] = (
            payload.get("satisfactory_note") or body.get("satisfactory_note") or ""
        )
    elif step == "policy_documents":
        body["policy_documents"] = payload.get("policy_documents") or payload.get("value") or []
    elif step == "policies":
        body["policies"] = payload.get("policies") or payload.get("value") or []
    elif step == "ssp":
        body["ssp"] = str(payload.get("ssp") or payload.get("value") or "")
    elif step == "academic_integrity":
        body["academic_integrity"] = payload.get("academic_integrity") or payload.get("value") or {}
    elif step == "attendance":
        body["attendance"] = str(payload.get("attendance") or payload.get("value") or "")
    elif step == "supplementary":
        body["supplementary"] = str(payload.get("supplementary") or payload.get("value") or "")
    elif step == "lecture_capture":
        body["lecture_capture"] = str(payload.get("lecture_capture") or payload.get("value") or "")
    elif step == "sustainability":
        body["sustainability"] = str(payload.get("sustainability") or payload.get("value") or "")
    elif step == "late_submission":
        body["late_submission"] = str(payload.get("late_submission") or payload.get("value") or "")
    row.body = body
    row.status = "draft"
    try:
        await db.flush()
    except IntegrityError as exc:
        if code_changed:
            await db.rollback()
            raise ProfassistError(
                409, "An outline with that code already exists. Open it instead."
            ) from exc
        raise
    before_text = _step_text(before_body, step)
    after_text = _step_text(body, step)
    if before_text != after_text:
        await capture_movement(
            db, org_id, user_id, "objective", before_text, after_text, "outline-edit"
        )
    return _public(row)


def asked_count(text: str) -> int | None:
    """How many items the professor asked for, when they named a count."""
    import re

    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
    }
    lowered = (text or "").lower()
    match = re.search(
        r"\b(\d+|one|two|three|four|five|six|seven|eight)\s+(?:draft\s+)?(?:learning\s+)?outcomes?\b",
        lowered,
    )
    if not match:
        match = re.search(
            r"\b(?:draft|write|suggest|give|list)\s+(\d+|one|two|three|four|five|six|seven|eight)\b",
            lowered,
        )
    if not match:
        return None
    token = match.group(1)
    count = words.get(token, int(token) if token.isdigit() else 0)
    return count or None


def shape_outcomes(suggestion: dict[str, Any], message: str) -> tuple[dict[str, Any], str | None]:
    """Keep only the number of outcomes the professor asked for, as a numbered list."""
    count = asked_count(message)
    clos = list((suggestion or {}).get("clos") or [])
    if not count or not clos:
        return suggestion or {}, None
    trimmed = clos[:count]
    shaped = {**(suggestion or {}), "clos": trimmed}
    lines = []
    for index, item in enumerate(trimmed, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("code") or "").strip()
        else:
            text = str(item).strip()
        lines.append(f"{index}. {text}")
    reply = "Here are the learning outcomes:\n\n" + "\n".join(lines)
    return shaped, reply


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
    chunks = await _ready_chunks(db, org_id, user_id, course.id)
    sources = await _source_materials(db, org_id, user_id, course.id)
    note = _sources_note(sources, chunks)
    body = dict(row.body or empty_outline())
    body["source_materials"] = sources
    row.body = body
    dossier = await dossier_ai_context(db, org_id, user_id, course.id, budget=6000)
    instructions = row.instructions or course.ai_instructions or cleaned.text
    preferences = await artifact_preferences(
        db, org_id, user_id, _preference_query(course.code, step, instructions)
    )
    drafted = complete(
        "outline_assist",
        {
            "step": step,
            "message": cleaned.text,
            "body": body,
            "instructions": row.instructions or course.ai_instructions or "",
            "chunks": chunks,
            "sources": sources,
            "sources_note": note,
            "dossier": dossier,
            "preferences": preferences,
        },
    )
    suggestion = drafted.get("suggestion") or {}
    if step == "outcomes":
        suggestion, numbered = shape_outcomes(suggestion, cleaned.text)
        if numbered:
            drafted["reply"] = numbered
    if suggestion:
        await save_step(db, org_id, user_id, outline_id, step, suggestion, trust_course_text=True)
        row = await get_outline(db, org_id, user_id, outline_id)
    return {
        "reply": drafted.get("reply") or "Draft ready.",
        "outline": _public(row),
        "trace_url": step_trace_url() or "",
    }


async def finish_outline(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, outline_id: uuid.UUID
) -> dict[str, Any]:
    row = await get_outline(db, org_id, user_id, outline_id)
    body = row.body or {}
    before_text = _body_text(body)
    if not (body.get("basics") or {}).get("name"):
        raise ProfassistError(400, "Name the subject before you finish the outline.")
    course = await _course_for(db, org_id, body)
    row.course_id = course.id
    body = await _with_assessment_tasks(db, org_id, user_id, course, body)
    row.body = body
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
    await reflect_on_change(
        db,
        org_id,
        user_id,
        "objective",
        before_text,
        _body_text(body),
        "outline-publish",
        propose=True,
    )
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
    before_tasks = json.dumps(current, sort_keys=True, ensure_ascii=False)
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
    after_tasks = json.dumps(current, sort_keys=True, ensure_ascii=False)
    if before_tasks != after_tasks:
        await capture_movement(
            db,
            org_id,
            user_id,
            "objective",
            before_tasks,
            after_tasks,
            "outline-assessments",
        )
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
    before_text = row.instructions or ""
    cleaned = scrub(text or "")
    if cleaned.quarantined:
        raise ProfassistError(400, "Those instructions still look like they name a student.")
    row.instructions = cleaned.text.strip()
    course = await _course_for(db, org_id, row.body or {})
    row.course_id = course.id
    course.ai_instructions = row.instructions
    await db.flush()
    if (row.instructions or "") != before_text:
        await capture_movement(
            db,
            org_id,
            user_id,
            "objective",
            before_text,
            row.instructions or "",
            "outline-instructions",
        )
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
    sources = [_material_source(item) for item in materials]
    body = dict(row.body or empty_outline())
    body["source_materials"] = sources
    row.body = body
    await db.flush()
    return {
        "material": material,
        "materials": materials,
        "source_materials": sources,
        "outline": _public(row),
    }


async def outline_materials(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, outline_id: uuid.UUID
) -> list[dict[str, Any]]:
    from app.profassist.service import list_materials

    row = await get_outline(db, org_id, user_id, outline_id)
    if row.course_id is None:
        return []
    materials = await list_materials(db, org_id, row.course_id, user_id)
    body = dict(row.body or empty_outline())
    body["source_materials"] = [_material_source(item) for item in materials]
    row.body = body
    await db.flush()
    return materials


async def outline_context(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, outline_id: uuid.UUID
) -> dict[str, Any]:
    """Materials plus their current status. The existing `items` shape is kept."""
    row = await get_outline(db, org_id, user_id, outline_id)
    items = await outline_materials(db, org_id, user_id, outline_id)
    return {
        "items": items,
        "source_materials": [_material_source(item) for item in items],
        "instructions": row.instructions or "",
    }


async def remove_outline_material(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    material_id: uuid.UUID,
) -> dict[str, Any]:
    from app.profassist.service import delete_material, list_materials

    row = await get_outline(db, org_id, user_id, outline_id)
    if row.course_id is None:
        raise ProfassistError(404, "That material is not on this outline.")
    await delete_material(db, org_id, row.course_id, user_id, material_id)
    materials = await list_materials(db, org_id, row.course_id, user_id)
    sources = [_material_source(item) for item in materials]
    body = dict(row.body or empty_outline())
    body["source_materials"] = sources
    row.body = body
    await db.flush()
    return {"materials": materials, "source_materials": sources, "outline": _public(row)}


async def _ready_chunks(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every chunk from every ready material, with no truncation."""
    from app.profassist.models import Chunk, Material

    material_rows = (
        (
            await db.execute(
                select(Material).where(
                    Material.organization_id == org_id,
                    Material.course_id == course_id,
                    Material.owner_user_id == user_id,
                    Material.status == "ready",
                )
            )
        )
        .scalars()
        .all()
    )
    materials = {
        row.id: row.filename for row in material_rows if getattr(row, "status", "") == "ready"
    }
    if not materials:
        return []
    chunks = []
    for row in (
        await db.execute(
            select(Chunk)
            .where(
                Chunk.organization_id == org_id,
                Chunk.course_id == course_id,
                Chunk.owner_user_id == user_id,
                Chunk.material_id.in_(list(materials)),
            )
            .order_by(Chunk.material_id, Chunk.ordinal)
        )
    ).scalars():
        if row.material_id not in materials:
            continue
        chunks.append(
            {
                "id": str(row.id),
                "material_id": str(row.material_id),
                "text": row.text,
                "filename": materials.get(row.material_id, "note"),
                "ordinal": row.ordinal,
            }
        )
    return chunks


def _material_source(item: dict[str, Any]) -> dict[str, Any]:
    report = item.get("pii_report") or {}
    status = item.get("status") or "unknown"
    return {
        "id": item.get("id") or "",
        "filename": item.get("filename") or "",
        "status": status,
        "pii_quarantined": bool(status == "quarantined" or report.get("quarantined")),
    }


async def _source_materials(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> list[dict[str, Any]]:
    from app.profassist.service import list_materials

    return [_material_source(item) for item in await list_materials(db, org_id, course_id, user_id)]


def _sources_note(sources: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> str:
    if not sources:
        return "No files are attached to this outline."
    parts = []
    ready = [
        item
        for item in sources
        if item.get("status") == "ready" and not item.get("pii_quarantined")
    ]
    blocked = [item for item in sources if item not in ready]
    if not chunks:
        parts.append("No ready notes are available; do not invent content from notes.")
    elif ready:
        parts.append("Ready notes used: " + ", ".join(item["filename"] for item in ready) + ".")
    if chunks:
        parts.append(f"{len(chunks)} ready chunk(s) supplied.")
    if blocked:
        parts.append(
            "Not usable yet: "
            + ", ".join(
                f"{item['filename']} "
                f"({'quarantined' if item.get('pii_quarantined') else item.get('status')})"
                for item in blocked
            )
            + "."
        )
    return " ".join(parts)


def course_brief(body: dict[str, Any]) -> str:
    """Short context the council, slide studio, and chat can quote by id."""
    basics = body.get("basics") or {}
    lecture = body.get("lecture") or {}
    lines = [
        f"Course {basics.get('code')} {basics.get('name')}.",
        (
            f"Section {basics.get('section')}; credit points {basics.get('credit_points')}; "
            f"{basics.get('session')} {basics.get('year')}; {basics.get('duration')}; "
            f"delivery {basics.get('delivery_mode')}."
        ),
        f"Prerequisites: {basics.get('prerequisites') or 'None'}.",
        (
            f"Equivalent subject(s): "
            f"{basics.get('equivalent_subjects') or basics.get('equivalent') or 'None'}."
        ),
        (
            f"Lecture: {lecture.get('day')} {lecture.get('time')} "
            f"{lecture.get('location')}; educator {lecture.get('educator_name')}; "
            f"office {lecture.get('office')}; email {lecture.get('email')}; "
            f"consultation {lecture.get('consultation')}."
        ),
        f"Description: {body.get('description') or ''}",
        f"Program: {body.get('program') or ''}",
        "Course learning outcomes:",
    ]
    for item in body.get("clos") or []:
        lines.append(f"- {item.get('code')}: {item.get('text')}")
    lines.append("Program learning outcomes:")
    for item in body.get("plos") or []:
        lines.append(f"- {item.get('code')}: {item.get('text')}")
    lines.append("Schedule:")
    for week in body.get("weeks") or []:
        lines.append(
            f"- Week {week.get('week')}: {week.get('topic')} "
            f"[{', '.join(week.get('lo_codes') or [])}] {week.get('session_type')} "
            f"{week.get('delivery')} {week.get('assessment_note')}"
        )
    lines.append("Supporting materials:")
    for index, reading in enumerate(body.get("readings") or [], start=1):
        lines.append(f"- {index}. {reading}")
    lines.append("Assessment of learning outcomes:")
    for row in body.get("outcome_measures") or []:
        lines.append(f"- {row.get('lo_code')}: {row.get('measures')}")
    lines.append("Assessment tasks:")
    for task in body.get("assessment_tasks") or []:
        lines.append(
            f"- {task.get('number')} {task.get('title')} weight {task.get('weight')}% "
            f"{task.get('type')} due {task.get('due')} LOs "
            f"{', '.join(task.get('lo_codes') or [])}"
        )
        for criterion in task.get("rubric") or []:
            lines.append(f"  criterion {criterion.get('name')} {criterion.get('weight')}%")
    if body.get("late_submission"):
        lines.append(f"Late submission: {body.get('late_submission')}")
    lines.append("GenAI guidance:")
    for point in body.get("genai") or []:
        lines.append(f"- {point}")
    lines.append("Grades awarded:")
    for grade in body.get("grades") or []:
        lines.append(
            f"- {grade.get('band') or grade.get('grade')}: {grade.get('range')} "
            f"{grade.get('description') or ''}"
        )
    for paragraph in body.get("satisfactory") or []:
        lines.append(f"Satisfactory completion: {paragraph}")
    if body.get("satisfactory_note"):
        lines.append(f"Template note: {body.get('satisfactory_note')}")
    lines.append("Policies:")
    for item in body.get("policy_documents") or body.get("policies") or []:
        title = item if isinstance(item, str) else item.get("title") or ""
        lines.append(f"- {title}")
    for key in (
        "ssp",
        "attendance",
        "supplementary",
        "lecture_capture",
        "sustainability",
    ):
        if body.get(key):
            lines.append(f"{key}: {body.get(key)}")
    integrity = body.get("academic_integrity") or {}
    if isinstance(integrity, dict):
        for key in ("intro", "turnitin", "referencing", "rules"):
            if integrity.get(key):
                lines.append(f"Academic integrity {key}: {integrity.get(key)}")
    elif integrity:
        lines.append(f"Academic integrity: {integrity}")
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
    base_payload = {
        "organization_id": organization_id,
        "owner_user_id": user_id,
        "course_id": course_id,
        "outline_id": outline_id,
        "clo_codes": [item.get("code") for item in body.get("clos") or []],
        "outcome_measures": [item.get("lo_code") for item in body.get("outcome_measures") or []],
    }
    points = [
        PointStruct(
            id=outline_id,
            vector=hash_embed(text, 64),
            payload={**base_payload, "kind": "outline", "text": text[:2000]},
        )
    ]
    extras: list[tuple[str, str, dict[str, Any]]] = []
    for index, week in enumerate(body.get("weeks") or [], start=1):
        extras.append(
            (
                "week",
                f"Week {week.get('week') or index}: {week.get('topic') or ''} "
                f"[{', '.join(week.get('lo_codes') or [])}] "
                f"{week.get('session_type') or ''} {week.get('delivery') or ''} "
                f"{week.get('assessment_note') or ''}",
                {"week": week.get("week") or index, "lo_codes": week.get("lo_codes") or []},
            )
        )
    for index, reading in enumerate(body.get("readings") or [], start=1):
        extras.append(("reading", f"Reading {index}: {reading}", {"ordinal": index}))
    for index, policy in enumerate(
        body.get("policy_documents") or body.get("policies") or [], start=1
    ):
        if isinstance(policy, str):
            title, key = policy, f"document_{index}"
        else:
            title = policy.get("title") or ""
            key = policy.get("key") or f"document_{index}"
        extras.append(("policy", f"Policy: {title}", {"policy_key": key}))
    for row in body.get("outcome_measures") or []:
        extras.append(
            (
                "assessment_map",
                f"{row.get('lo_code') or ''} measures: {row.get('measures') or ''}",
                {"lo_code": row.get("lo_code") or ""},
            )
        )
    for task in body.get("assessment_tasks") or []:
        entity_id = str(task.get("entity_id") or task.get("number") or "")
        rubric = "; ".join(
            f"{criterion.get('name')} {criterion.get('weight')}%"
            for criterion in task.get("rubric") or []
        )
        extras.append(
            (
                "assessment_task",
                f"{task.get('number')} {task.get('title')} weight {task.get('weight')}% "
                f"{task.get('type')} due {task.get('due')} "
                f"LOs {', '.join(task.get('lo_codes') or [])} {rubric}",
                {
                    "number": task.get("number") or "",
                    "lo_codes": task.get("lo_codes") or [],
                    "entity_id": entity_id,
                },
            )
        )
        for criterion_index, criterion in enumerate(task.get("rubric") or [], start=1):
            levels = criterion.get("levels") or {}
            extras.append(
                (
                    "rubric_criterion",
                    f"{task.get('number')} {task.get('title')} criterion "
                    f"{criterion.get('name')} {criterion.get('weight')}% "
                    f"excellent: {levels.get('advanced') or ''}",
                    {
                        "number": task.get("number") or "",
                        "criterion": criterion.get("name") or "",
                        "weight": criterion.get("weight") or 0,
                        "entity_id": f"{entity_id}:criterion:{criterion_index}",
                    },
                )
            )
    for point in body.get("genai") or []:
        extras.append(("genai", str(point), {}))
    for grade in body.get("grades") or []:
        band = grade.get("band") or grade.get("grade")
        extras.append(
            (
                "grade",
                f"{band} {grade.get('range')} {grade.get('description') or ''}",
                {"grade": band},
            )
        )
    for paragraph in body.get("satisfactory") or []:
        extras.append(("satisfactory", str(paragraph), {}))
    for key in (
        "late_submission",
        "ssp",
        "attendance",
        "supplementary",
        "lecture_capture",
        "sustainability",
    ):
        if body.get(key):
            extras.append(("section", f"{key}: {body.get(key)}", {"section": key}))
    integrity = body.get("academic_integrity") or {}
    if isinstance(integrity, dict):
        for key in ("intro", "turnitin", "referencing", "rules"):
            if integrity.get(key):
                extras.append(
                    (
                        "section",
                        f"academic_integrity {key}: {integrity.get(key)}",
                        {"section": "academic_integrity"},
                    )
                )
    elif integrity:
        extras.append(
            ("section", f"academic_integrity: {integrity}", {"section": "academic_integrity"})
        )
    for position, (kind, extra_text, extra_payload) in enumerate(extras, start=1):
        extras_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{outline_id}:{kind}:{position}")
        points.append(
            PointStruct(
                id=str(extras_id),
                vector=hash_embed(extra_text, 64),
                payload={
                    **base_payload,
                    "kind": kind,
                    "text": extra_text[:2000],
                    **extra_payload,
                },
            )
        )
    try:
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT or 6333)
        name = "profassist_outline"
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=64, distance=Distance.COSINE),
            )
        client.upsert(collection_name=name, points=points)
    except Exception:
        logging.getLogger(__name__).info("Outline vector was not written")


async def _rubric_for(db: AsyncSession, assessment_id: Any) -> list[dict[str, Any]]:
    if not assessment_id:
        return []
    result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.assessment_id == assessment_id)
        .order_by(RubricCriterion.ordinal)
    )
    return [
        {
            "name": criterion.name,
            "weight": int(criterion.weight or 0),
            "levels": criterion.levels or {},
        }
        for criterion in result.scalars().all()
    ]


async def _with_assessment_tasks(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course: Course,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Prefer the course's assignment rows; keep the snapshot when none exist.

    GroupAssignment is the group-task link. Assessment rows that are not linked
    to a GroupAssignment cover individual tasks. The rubric always comes from the
    linked RubricCriterion rows; an empty rubric stays empty. This never creates
    Assessment rows.
    """
    group_result = await db.execute(
        select(GroupAssignment).where(
            GroupAssignment.organization_id == org_id,
            GroupAssignment.owner_user_id == user_id,
            GroupAssignment.course_id == course.id,
        )
    )
    groups = list(group_result.scalars().all())
    tasks: list[dict[str, Any]] = []
    linked_assessments: set[Any] = set()
    for index, group in enumerate(groups, start=1):
        assessment_id = group.assessment_id
        if assessment_id is None and group.outline_task_id:
            stored = await db.get(OutlineTask, group.outline_task_id)
            if stored is not None:
                assessment_id = stored.assessment_id
        assessment = None
        if assessment_id is not None:
            linked_assessments.add(assessment_id)
            assessment = await db.get(Assessment, assessment_id)
        rubric = await _rubric_for(db, assessment_id)
        title = (
            group.title
            or (assessment.title if assessment is not None else "")
            or f"Assessment {index}"
        )
        tasks.append(
            {
                "number": group.number or f"A{index}",
                "title": title,
                "type": "Group",
                "weight": int(group.weight or (assessment.weight if assessment else 0) or 0),
                "total_marks": 100,
                "due": group.due or "",
                "lo_codes": list(group.lo_codes or (assessment.clos if assessment else []) or []),
                "overview": [
                    item
                    for item in (
                        group.body or (assessment.brief if assessment else "") or ""
                    ).split("\n\n")
                    if item.strip()
                ],
                "deliverables": [],
                "format": [],
                "rubric": rubric,
                "entity_id": str(group.id),
            }
        )
    assessment_result = await db.execute(
        select(Assessment).where(
            Assessment.organization_id == org_id,
            Assessment.owner_user_id == user_id,
            Assessment.course_id == course.id,
        )
    )
    for index, item in enumerate(assessment_result.scalars().all(), start=1):
        if item.id in linked_assessments:
            continue
        rubric = await _rubric_for(db, item.id)
        external = str(item.external_id or "")
        number = external.split(":", 1)[1] if ":" in external else f"A{len(tasks) + index}"
        tasks.append(
            {
                "number": number,
                "title": item.title or number,
                "type": "Group" if item.kind == "group" else "Individual",
                "weight": int(item.weight or 0),
                "total_marks": 100,
                "due": "",
                "lo_codes": list(item.clos or []),
                "overview": [item.brief] if item.brief else [],
                "deliverables": [],
                "format": [],
                "rubric": rubric,
                "entity_id": str(item.id),
            }
        )
    return {**body, "assessment_tasks": tasks} if tasks else body


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
    for index, item in enumerate(body.get("policies") or [], start=1):
        if isinstance(item, str):
            key, title, text = f"document_{index}", item, ""
        else:
            key = item.get("key") or f"document_{index}"
            title = item.get("title") or "Policy"
            text = item.get("body") or ""
        db.add(
            OutlinePolicy(
                organization_id=org_id,
                owner_user_id=user_id,
                outline_id=row.id,
                key=key,
                title=title,
                body=text,
            )
        )
    course.clos = [item.get("text") or "" for item in body.get("clos") or []]
    # outcome_measures has no normalized table yet; it stays in body and is indexed.
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
        raw_title = task.get("title") or task.get("name")
        title = raw_title or number
        overview = [str(item) for item in task.get("overview") or [] if str(item).strip()]
        brief = task.get("brief") or "\n\n".join(overview)
        criteria = task.get("rubric") or task.get("criteria") or []
        task_type = task.get("type") or task.get("task_type") or ""
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
                title=title,
                brief=brief,
                clos=task.get("lo_codes") or [],
                status="draft",
                external_id=external,
                weight=int(task.get("weight") or 0),
                kind="assignment",
            )
            db.add(assessment)
            await db.flush()
        else:
            assessment.title = raw_title or assessment.title
            assessment.brief = brief or assessment.brief
            assessment.clos = task.get("lo_codes") or []
            assessment.weight = int(task.get("weight") or 0)
            assessment.course_id = course.id
        await db.execute(
            delete(RubricCriterion).where(RubricCriterion.assessment_id == assessment.id)
        )
        for ordinal, criterion in enumerate(criteria, start=1):
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
                    name=title,
                    task_type=task_type,
                    weight=int(task.get("weight") or 0),
                    due=str(task.get("due") or ""),
                    lo_codes=task.get("lo_codes") or [],
                    brief=brief,
                    criteria=criteria,
                )
            )
        else:
            stored.assessment_id = assessment.id
            stored.name = raw_title or stored.name
            stored.weight = int(task.get("weight") or 0)
            stored.due = str(task.get("due") or "")
            stored.lo_codes = task.get("lo_codes") or []
            stored.brief = brief
            stored.criteria = criteria


def _next_number(existing: set[str]) -> str:
    index = 1
    while f"A{index}" in existing:
        index += 1
    return f"A{index}"


# --- Artifact-first generation and refinement --------------------------------

CONTENT_SECTIONS: tuple[str, ...] = (
    "basics",
    "lecture",
    "description",
    "plos",
    "clos",
    "weeks",
    "readings",
    "outcome_measures",
    "assessment_tasks",
)

FIXED_SECTIONS: tuple[str, ...] = (
    "genai",
    "grades",
    "satisfactory",
    "policy_documents",
    "ssp",
    "academic_integrity",
    "attendance",
    "supplementary",
    "lecture_capture",
    "sustainability",
    "late_submission",
)

REFINE_SECTIONS: tuple[str, ...] = (
    "basics",
    "lecture",
    "description",
    "outcomes",
    "schedule",
    "readings",
    "assessment_map",
    "assessment_tasks",
    *FIXED_SECTIONS,
)

REFINE_ALIASES = {
    "weeks": "schedule",
    "plos": "outcomes",
    "clos": "outcomes",
    "program": "outcomes",
}


def _fixed_template() -> dict[str, Any]:
    """The fixed sections always come from the outline template, never the model."""
    from app.profassist import outline_data as template

    return {
        "genai": [str(item) for item in template.GENAI_POINTS],
        "grades": [dict(item) for item in template.GRADES],
        "satisfactory": [str(item) for item in template.SATISFACTORY],
        "policy_documents": [
            {"title": title, "url": "", "text": ""} for title in template.POLICY_DOCUMENTS
        ],
        "ssp": template.SSP,
        "academic_integrity": json.loads(json.dumps(template.ACADEMIC_INTEGRITY)),
        "attendance": template.ATTENDANCE,
        "supplementary": template.SUPPLEMENTARY,
        "lecture_capture": template.LECTURE_CAPTURE,
        "sustainability": template.SUSTAINABILITY,
        "late_submission": template.LATE_SUBMISSION,
    }


def _seed_fixed(body: dict[str, Any]) -> dict[str, Any]:
    """Keep a professor's edit, otherwise use the template default for that section."""
    template = _fixed_template()
    seeded = dict(body)
    for key in FIXED_SECTIONS:
        current = body.get(key)
        if current in (None, "", [], {}):
            seeded[key] = template[key]
    return seeded


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _plo_code(value: Any) -> str:
    match = re.fullmatch(r"PLO\s*0*(\d+)", _as_text(value).upper())
    if not match:
        return ""
    number = int(match.group(1))
    return f"PLO{number}" if 1 <= number <= 6 else ""


def _clo_code(value: Any) -> str:
    match = re.fullmatch(r"(?:CLO|LO)\s*0*(\d+)", _as_text(value).upper())
    if not match:
        return ""
    number = int(match.group(1))
    return f"LO{number}" if number >= 1 else ""


def _clean_plos(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        # Gemini returns {"PLO1": "text", ...} instead of a list of objects.
        items: list[Any] = [{"code": key, "text": text} for key, text in value.items()]
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError("plos must be a list or an object")
    result: list[dict[str, Any]] = []
    used: set[int] = set()
    for item in items:
        if isinstance(item, dict):
            text = _as_text(item.get("text") or item.get("description") or item.get("outcome"))
            wanted = _plo_code(item.get("code"))
        else:
            text, wanted = _as_text(item), ""
        if not text:
            continue
        number = int(wanted[3:]) if wanted and int(wanted[3:]) not in used else 0
        if not number:
            number = next((n for n in range(1, 7) if n not in used), 0)
        if not number:
            break
        used.add(number)
        result.append({"code": f"PLO{number}", "text": text})
    return result


def _clean_clos(value: Any, plo_codes: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("clos must be a list")
    result: list[dict[str, Any]] = []
    used: set[int] = set()
    next_free = 1
    for item in value:
        if isinstance(item, dict):
            text = _as_text(
                item.get("text")
                or item.get("description")
                or item.get("title")
                or item.get("outcome")
            )
            wanted = _clo_code(item.get("code") or item.get("id"))
            raw_plos = item.get("plos") or item.get("plo_codes") or item.get("supports") or []
        else:
            text, wanted, raw_plos = _as_text(item), "", []
        if not text:
            continue
        number = int(wanted[2:]) if wanted and int(wanted[2:]) not in used else 0
        if not number:
            while next_free in used:
                next_free += 1
            number = next_free
        used.add(number)
        if isinstance(raw_plos, str):
            raw_plos = [raw_plos]
        refs: list[str] = []
        for ref in raw_plos if isinstance(raw_plos, list) else []:
            if isinstance(ref, dict):
                ref = ref.get("code") or ref.get("id") or ""
            code = _plo_code(ref) or _as_text(ref).upper().replace(" ", "")
            if plo_codes and code not in plo_codes:
                continue
            if code and code not in refs:
                refs.append(code)
        result.append({"code": f"LO{number}", "text": text, "plos": refs})
    return result


def _clean_weeks(value: Any, lo_codes: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("weeks must be a list")
    result: list[dict[str, Any]] = []
    used: set[int] = set()
    for item in value:
        if isinstance(item, dict):
            topic = _as_text(item.get("topic") or item.get("title"))
            raw_week = item.get("week", item.get("number"))
            raw_los: Any = item.get("lo_codes") or item.get("clos") or []
        else:
            topic, raw_week, raw_los = _as_text(item), None, []
        if not topic:
            continue
        try:
            number = int(raw_week) if raw_week is not None else 0
        except (TypeError, ValueError):
            number = 0
        if number < 1 or number > 12 or number in used:
            number = next((n for n in range(1, 13) if n not in used), 0)
        if not number:
            break
        used.add(number)
        if isinstance(raw_los, str):
            raw_los = [raw_los]
        refs: list[str] = []
        for ref in raw_los if isinstance(raw_los, list) else []:
            code = _clo_code(ref)
            if lo_codes and code not in lo_codes:
                continue
            if code and code not in refs:
                refs.append(code)
        result.append(
            {
                "week": number,
                "topic": topic,
                "lo_codes": refs,
                "session_type": _as_text(item.get("session_type"))
                if isinstance(item, dict)
                else "",
                "delivery": _as_text(item.get("delivery")) if isinstance(item, dict) else "",
                "assessment_note": _as_text(item.get("assessment_note"))
                if isinstance(item, dict)
                else "",
            }
        )
    result.sort(key=lambda week: int(week["week"]))
    return result


def _clean_readings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("readings must be a list")
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = _as_text(item.get("citation") or item.get("title") or item.get("text"))
        else:
            text = _as_text(item)
        if text:
            result.append(text)
    return result


def _clean_outcome_measures(value: Any, lo_codes: list[str]) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if "lo_code" in value or "code" in value:
            value = [value]
        else:
            value = [{"lo_code": key, "measures": item} for key, item in value.items()]
    if not isinstance(value, list):
        raise ValueError("outcome_measures must be a list")
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            code = _clo_code(item.get("lo_code") or item.get("code"))
            measures = item.get("measures") or item.get("measure") or item.get("text")
        else:
            code, measures = _clo_code(item), ""
        if lo_codes and code not in lo_codes:
            continue
        if isinstance(measures, list):
            measures = ", ".join(text for text in (_as_text(part) for part in measures) if text)
        else:
            measures = _as_text(measures)
        if code and measures:
            result.append({"lo_code": code, "measures": measures})
    return result


def _round_weight(number: float) -> int:
    """Round a mark to the nearest whole number, with halves going up."""
    return int(number + 0.5) if number >= 0 else -int(-number + 0.5)


def _clean_weight(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _round_weight(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return _round_weight(float(match.group(0))) if match else 0


TASK_LEVELS: tuple[str, ...] = ("beginning", "developing", "proficient", "advanced")


def _task_like(value: dict[str, Any]) -> bool:
    keys = (
        "number",
        "id",
        "name",
        "title",
        "type",
        "weight",
        "percentage",
        "due",
        "due_date",
        "overview",
        "brief",
        "description",
        "deliverables",
        "rubric",
        "criteria",
    )
    return any(key in value for key in keys)


def _clean_text_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = _as_text(
                item.get("title") or item.get("text") or item.get("description") or item.get("item")
            )
        else:
            text = _as_text(item)
        if text:
            result.append(text)
    return result


def _task_overview(item: dict[str, Any]) -> list[str]:
    """An overview list from a list or from text split on blank lines."""
    raw = item.get("overview")
    if isinstance(raw, list):
        return _clean_text_items(raw)
    text = _as_text(raw) if raw else _as_text(item.get("brief") or item.get("description"))
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _clean_task_rubric(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("rubric") or value.get("criteria") or []
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            name = _as_text(item.get("name") or item.get("criterion") or item.get("title"))
            if not name:
                continue
            raw_levels = item.get("levels")
            levels: dict[str, str] = {}
            if isinstance(raw_levels, dict):
                levels = {
                    level: _as_text(raw_levels.get(level))
                    for level in TASK_LEVELS
                    if _as_text(raw_levels.get(level))
                }
            else:
                levels = {
                    level: _as_text(item.get(level))
                    for level in TASK_LEVELS
                    if _as_text(item.get(level))
                }
            result.append(
                {
                    "name": name,
                    "weight": _clean_weight(item.get("weight")),
                    "levels": levels,
                }
            )
        else:
            name = _as_text(item)
            if name:
                result.append({"name": name, "weight": 0, "levels": {}})
    return result


def _clean_assessment_tasks(value: Any, lo_codes: list[str]) -> list[dict[str, Any]]:
    """Canonical assessment tasks from a list, or a code-to-task object."""
    if isinstance(value, dict):
        if _task_like(value):
            items: list[Any] = [value]
        else:
            items = []
            for key, item in value.items():
                if isinstance(item, dict):
                    items.append({**item, "name": item.get("name") or item.get("title") or key})
                elif _as_text(item):
                    items.append({"name": key, "brief": item})
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError("assessment_tasks must be a list or an object")
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            title = _as_text(item.get("title") or item.get("name"))
            weight_raw: Any = item.get("weight")
            if weight_raw is None:
                weight_raw = item.get("percentage")
            due = _as_text(item.get("due") or item.get("due_date"))
            overview = _task_overview(item)
            raw_los: Any = item.get("lo_codes") or item.get("clos") or []
            raw_rubric: Any = item.get("rubric") or item.get("criteria")
            number = _as_text(item.get("number") or item.get("id"))
            task_type = _as_text(item.get("type"))
            deliverables = _clean_text_items(item.get("deliverables"))
            task_format = _clean_text_items(item.get("format"))
        else:
            title, weight_raw, due, overview = _as_text(item), None, "", []
            raw_los, raw_rubric = [], None
            number, task_type, deliverables, task_format = "", "", [], []
        if not title:
            continue
        if isinstance(raw_los, str):
            raw_los = [raw_los]
        codes: list[str] = []
        for ref in raw_los if isinstance(raw_los, list) else []:
            code = _clo_code(ref)
            if lo_codes and code not in lo_codes:
                continue
            if code and code not in codes:
                codes.append(code)
        result.append(
            {
                "number": number or f"A{len(result) + 1}",
                "title": title,
                "type": task_type or "Individual",
                "weight": _clean_weight(weight_raw),
                "total_marks": 100,
                "due": due,
                "lo_codes": codes,
                "overview": overview,
                "deliverables": deliverables,
                "format": task_format,
                "rubric": _clean_task_rubric(raw_rubric),
                "name": title,
                "brief": "\n\n".join(overview),
            }
        )
        if len(result) >= 20:
            break
    return result


def _clean_mapping(value: Any, fields: tuple[str, ...], existing: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("section must be an object")
    result = dict(existing) if isinstance(existing, dict) else {}
    for key in fields:
        if key in value:
            result[key] = value[key]
    return result


def _clean_fixed(name: str, value: Any) -> Any:
    text_sections = {
        "ssp",
        "attendance",
        "supplementary",
        "lecture_capture",
        "sustainability",
        "late_submission",
    }
    if name in text_sections:
        if isinstance(value, dict):
            value = value.get("value") or value.get("text") or ""
        if not isinstance(value, str):
            raise ValueError(f"{name} must be text")
        return value.strip()
    if name == "academic_integrity":
        if not isinstance(value, dict):
            raise ValueError("academic_integrity must be an object")
        return dict(value)
    if name in {"genai", "satisfactory"}:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
        return [text for text in (_as_text(item) for item in value) if text]
    if name == "grades":
        if not isinstance(value, list):
            raise ValueError("grades must be a list")
        rows: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                rows.append(dict(item))
            elif _as_text(item):
                rows.append({"band": _as_text(item), "range": "", "description": ""})
        return rows
    if name == "policy_documents":
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("policy_documents must be a list")
        rows = []
        for item in value:
            if isinstance(item, dict):
                rows.append(dict(item))
            elif _as_text(item):
                rows.append({"title": _as_text(item), "url": "", "text": ""})
        return rows
    raise ValueError(f"Unknown section {name}")


def _normalise_section_name(name: str) -> str:
    key = (name or "").strip().lower()
    return REFINE_ALIASES.get(key, key)


def _outcome_parts(value: Any) -> tuple[Any, Any]:
    """Split an `outcomes` value into (plos, clos), or (None, None) when unusable."""
    if isinstance(value, dict):
        return value.get("plos"), value.get("clos")
    if isinstance(value, list):
        plos = [
            item
            for item in value
            if _plo_code(item.get("code") if isinstance(item, dict) else item)
        ]
        clos = [item for item in value if item not in plos]
        if plos or clos:
            return plos or None, clos or None
    return None, None


def _apply_refine_sections(
    body: dict[str, Any], sections: dict[str, Any], section: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Apply only the sections the model supplied. Raises ValueError on a bad shape."""
    requested = _normalise_section_name(section) if section else ""
    if requested not in REFINE_SECTIONS:
        requested = ""
    provided: dict[str, Any] = {}
    for raw_name, value in sections.items():
        name = _normalise_section_name(str(raw_name))
        if name not in REFINE_SECTIONS:
            continue
        if requested and name != requested:
            continue
        provided[name] = value

    old = body
    updated = dict(body)
    applied: list[str] = []

    # Outcomes first so weeks and the assessment map can reference the new CLOs.
    if "outcomes" in provided:
        plos, clos = _outcome_parts(provided["outcomes"])
        if plos is None and clos is None:
            raise ValueError("outcomes must contain plos, clos, or both")
        if plos is not None:
            updated["plos"] = _clean_plos(plos)
        if clos is not None:
            updated["clos"] = _clean_clos(
                clos, [item["code"] for item in updated.get("plos") or []]
            )
        if updated.get("plos") != old.get("plos") or updated.get("clos") != old.get("clos"):
            applied.append("outcomes")

    lo_codes = [item.get("code") for item in updated.get("clos") or [] if item.get("code")]

    if "schedule" in provided:
        updated["weeks"] = _clean_weeks(provided["schedule"], lo_codes)
        if updated["weeks"] != old.get("weeks"):
            applied.append("schedule")

    if "assessment_map" in provided:
        updated["outcome_measures"] = _clean_outcome_measures(provided["assessment_map"], lo_codes)
        if updated["outcome_measures"] != old.get("outcome_measures"):
            applied.append("assessment_map")

    if "assessment_tasks" in provided:
        updated["assessment_tasks"] = _clean_assessment_tasks(
            provided["assessment_tasks"], lo_codes
        )
        if updated["assessment_tasks"] != old.get("assessment_tasks"):
            applied.append("assessment_tasks")

    if "basics" in provided:
        updated["basics"] = _clean_mapping(provided["basics"], BASICS_FIELDS, old.get("basics"))
        if updated["basics"] != old.get("basics"):
            applied.append("basics")
    if "lecture" in provided:
        updated["lecture"] = _clean_mapping(provided["lecture"], LECTURE_FIELDS, old.get("lecture"))
        if updated["lecture"] != old.get("lecture"):
            applied.append("lecture")
    if "description" in provided:
        raw = provided["description"]
        if isinstance(raw, dict):
            raw = raw.get("description") or raw.get("value")
        description = _as_text(raw)
        updated["description"] = description
        if description != old.get("description"):
            applied.append("description")
    if "readings" in provided:
        updated["readings"] = _clean_readings(provided["readings"])
        if updated["readings"] != old.get("readings"):
            applied.append("readings")

    for key in FIXED_SECTIONS:
        if key not in provided:
            continue
        updated[key] = _clean_fixed(key, provided[key])
        if updated[key] != old.get(key):
            applied.append(key)

    return updated, applied


def _generate_body(
    body: dict[str, Any], drafted: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Merge content sections. Fixed sections stay on the template defaults."""
    updated = _seed_fixed(dict(body))
    missing: list[str] = []
    data: dict[str, Any] = drafted
    for wrapper in ("outline", "body", "sections"):
        inner = drafted.get(wrapper)
        if isinstance(inner, dict) and any(key in inner for key in CONTENT_SECTIONS):
            data = inner
            break

    def apply(key: str, cleaner: Any) -> None:
        value = data.get(key)
        if value in (None, "", [], {}):
            missing.append(key)
            return
        try:
            updated[key] = cleaner(value)
        except (TypeError, ValueError):
            missing.append(key)

    apply("basics", lambda value: _clean_mapping(value, BASICS_FIELDS, body.get("basics")))
    apply("lecture", lambda value: _clean_mapping(value, LECTURE_FIELDS, body.get("lecture")))
    apply("description", _as_text)
    apply("plos", _clean_plos)
    apply(
        "clos",
        lambda value: _clean_clos(value, [item["code"] for item in updated.get("plos") or []]),
    )
    apply(
        "weeks",
        lambda value: _clean_weeks(value, [item["code"] for item in updated.get("clos") or []]),
    )
    apply("readings", _clean_readings)
    apply(
        "outcome_measures",
        lambda value: _clean_outcome_measures(
            value, [item["code"] for item in updated.get("clos") or []]
        ),
    )
    apply(
        "assessment_tasks",
        lambda value: _clean_assessment_tasks(
            value, [item["code"] for item in updated.get("clos") or []]
        ),
    )

    changed = [key for key in CONTENT_SECTIONS if updated.get(key) != body.get(key)]
    return updated, changed, missing


def _preference_query(course_code: str, step: str, instructions: str) -> str:
    """Rank this professor's artifact lessons against the work in hand."""
    return " ".join(
        part
        for part in (
            str(course_code or "").strip(),
            str(step or "").strip(),
            str(instructions or "").strip(),
        )
        if part
    )


async def generate_outline(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    message: str,
) -> dict[str, Any]:
    """Draft the whole outline body from the professor's notes and instructions."""
    from app.profassist.llm import complete

    row = await get_outline(db, org_id, user_id, outline_id)
    await load_runtime(db, org_id, user_id)
    roles = await load_council_roles(db, org_id, "outline")
    creator = role_of(roles, "creator")
    creator_request: dict[str, Any] = {}
    if creator is not None:
        creator_prompt = str(creator.get("persona_prompt") or "").strip()
        if creator_prompt:
            creator_request["prompt_override"] = creator_prompt
        creator_model = str(creator.get("model") or "").strip()
        if creator_model:
            creator_request["model"] = creator_model
    cleaned = scrub(message or "")
    if cleaned.quarantined:
        raise ProfassistError(400, "That request still looks like it names a student.")
    if cleaned.text.strip():
        row.instructions = cleaned.text.strip()
    course = await _course_for(db, org_id, row.body or empty_outline())
    row.course_id = course.id
    if row.instructions and not course.ai_instructions:
        course.ai_instructions = row.instructions
    chunks = await _ready_chunks(db, org_id, user_id, course.id)
    sources = await _source_materials(db, org_id, user_id, course.id)
    note = _sources_note(sources, chunks)
    body = dict(row.body or empty_outline())
    body["source_materials"] = sources
    row.body = body
    before_text = _body_text(body)
    dossier = await dossier_ai_context(db, org_id, user_id, course.id, budget=6000)
    instructions = row.instructions or course.ai_instructions or ""
    preferences = await artifact_preferences(
        db, org_id, user_id, _preference_query(course.code, "outline_generate", instructions)
    )
    drafted = complete(
        "outline_generate",
        {
            "message": cleaned.text,
            "body": body,
            "basics": body.get("basics") or {},
            "code": row.code,
            "title": row.name,
            "instructions": instructions,
            "chunks": chunks,
            "sources": sources,
            "sources_note": note,
            "existing": {key: body.get(key) for key in CONTENT_SECTIONS},
            "dossier": dossier,
            "preferences": preferences,
            **creator_request,
        },
    )
    updated, changed_sections, missing = _generate_body(body, drafted)
    basics = updated.get("basics") or {}
    if isinstance(basics, dict):
        if basics.get("code"):
            row.code = str(basics["code"])
        if basics.get("name"):
            row.name = str(basics["name"])
    row.body = updated
    row.status = "draft"
    await db.flush()
    if changed_sections:
        await capture_movement(
            db,
            org_id,
            user_id,
            "objective",
            before_text,
            _body_text(updated),
            "outline-generate",
        )
    row = await get_outline(db, org_id, user_id, outline_id)
    reply = str(drafted.get("reply") or "Draft ready.")
    if missing:
        reply = f"{reply} Not drafted yet: {', '.join(missing)}."
    if not chunks and "no ready notes" not in reply.lower():
        reply = f"{reply} No ready notes are available, so this draft uses only your instructions."
    review: dict[str, Any] | None = None
    try:
        from app.profassist.outline_review import run_review

        review = await run_review(
            db, org_id, user_id, outline_id, mode="council", reviewer="curriculum"
        )
    except Exception:
        import logging

        logging.getLogger(__name__).info("Outline review after generation did not complete")
    return {
        "outline": _public(row),
        "reply": reply,
        "sources": sources,
        "changed_sections": changed_sections,
        "review": review,
        "trace_url": step_trace_url() or "",
    }


async def refine_outline(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    message: str,
    section: str | None = None,
) -> dict[str, Any]:
    """Apply only the sections the model asks to change. Status is never touched."""
    from app.profassist.llm import complete

    row = await get_outline(db, org_id, user_id, outline_id)
    await load_runtime(db, org_id, user_id)
    cleaned = scrub(message or "")
    if cleaned.quarantined:
        raise ProfassistError(400, "That request still looks like it names a student.")
    course = await _course_for(db, org_id, row.body or empty_outline())
    row.course_id = course.id
    if row.instructions and not course.ai_instructions:
        course.ai_instructions = row.instructions
    chunks = await _ready_chunks(db, org_id, user_id, course.id)
    sources = await _source_materials(db, org_id, user_id, course.id)
    note = _sources_note(sources, chunks)
    body = dict(row.body or empty_outline())
    body["source_materials"] = sources
    row.body = body
    before_text = _body_text(body)
    dossier = await dossier_ai_context(db, org_id, user_id, course.id, budget=6000)
    instructions = row.instructions or course.ai_instructions or cleaned.text
    preferences = await artifact_preferences(
        db, org_id, user_id, _preference_query(course.code, section or "outline", instructions)
    )
    drafted = complete(
        "outline_refine",
        {
            "message": cleaned.text,
            "section": section or "",
            "body": body,
            "instructions": row.instructions or course.ai_instructions or "",
            "chunks": chunks,
            "sources": sources,
            "sources_note": note,
            "dossier": dossier,
            "preferences": preferences,
        },
    )
    raw_sections = drafted.get("sections")
    sections = raw_sections if isinstance(raw_sections, dict) else {}
    try:
        updated, changed_sections = _apply_refine_sections(body, sections, section)
    except (TypeError, ValueError) as exc:
        raise ProfassistError(400, f"That change is not valid for the outline: {exc}.") from exc
    basics = updated.get("basics") or {}
    current_basics = body.get("basics") or {}
    if isinstance(basics, dict) and basics.get("code") != current_basics.get("code"):
        row.code = str(basics.get("code") or row.code)
    if isinstance(basics, dict) and basics.get("name") != current_basics.get("name"):
        row.name = str(basics.get("name") or row.name)
    changed = bool(changed_sections)
    if changed:
        row.body = updated
        await db.flush()
        await capture_movement(
            db,
            org_id,
            user_id,
            "objective",
            before_text,
            _body_text(updated),
            "outline-refine",
        )
        row = await get_outline(db, org_id, user_id, outline_id)
    reply = str(drafted.get("reply") or ("Updated." if changed else "No change was needed."))
    if not chunks and "no ready notes" not in reply.lower() and changed:
        reply = f"{reply} No ready notes are available, so this change uses only your instructions."
    return {
        "outline": _public(row),
        "reply": reply,
        "changed_sections": changed_sections,
        "changed": changed,
        "trace_url": step_trace_url() or "",
    }
