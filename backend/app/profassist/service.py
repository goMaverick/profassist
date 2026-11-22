"""Professor workflows. Models draft. These functions refuse to push early."""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.profassist import agents, stubs
from app.profassist.errors import ProfassistError
from app.profassist.grading import assert_can_push, is_blind_sample, redact_blind
from app.profassist.lessons import condense_about, extract_lessons, same_lesson
from app.profassist.llm import complete as llm_complete
from app.profassist.llm import mode as llm_mode
from app.profassist.memory import list_memories, recall, remember
from app.profassist.models import (
    Approval,
    Assessment,
    Chunk,
    Course,
    GradeDraft,
    IntegrityFlag,
    Material,
    MoodlePush,
    Objective,
    PiiVault,
    Reflection,
    RubricCriterion,
    SlideDeck,
    Student,
    StyleProfile,
    Submission,
)
from app.profassist.moodle import CLOS, get_connector
from app.profassist.pii import scrub
from app.profassist.rag import chunk_text, index_chunks, rank_chunks
from app.profassist.runtime import set_about
from app.profassist.settings_admin import load_runtime
from app.profassist.similarity import compare_submissions
from app.profassist.slides import build_pptx, deck_plan, render_thumbnails
from app.profassist.storage import extract_text, read_bytes, save_bytes

DEFAULT_SOUL = """# My style

Short sentences. Address the student as "you".
Lead with the strongest evidence, then one improvement.
Never use exclamation marks.
Do not mention that an AI wrote the comment.
Flags are evidence for a conversation, never a verdict.
"""


async def _course(db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID) -> Course:
    row = await db.get(Course, course_id)
    if row is None or row.organization_id != org_id:
        raise ProfassistError(404, "Course not found in this workspace")
    return row


async def _owned(
    db: AsyncSession,
    model: type,
    org_id: uuid.UUID,
    row_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
):
    row = await db.get(model, row_id)
    if row is None or row.organization_id != org_id:
        raise ProfassistError(404, "Not found in this workspace")
    owner = getattr(row, "owner_user_id", None)
    if user_id is not None and owner is not None and owner != user_id:
        raise ProfassistError(404, "Not found in this workspace")
    return row


async def _names(db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID) -> list[str]:
    result = await db.execute(
        select(Student).where(Student.organization_id == org_id, Student.course_id == course_id)
    )
    return [row.display_name for row in result.scalars().all()]


async def _remember_pii(
    db: AsyncSession, org_id: uuid.UUID, replacements: list[dict[str, str]], source: str
) -> None:
    for item in replacements:
        db.add(
            PiiVault(
                organization_id=org_id,
                token=item["token"],
                value=item["value"],
                kind=item["kind"],
                source=source,
            )
        )


async def _soul(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> str:
    result = await db.execute(
        select(StyleProfile).where(
            StyleProfile.organization_id == org_id, StyleProfile.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    return row.soul_md if row else DEFAULT_SOUL


async def _chunks(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[Chunk]:
    result = await db.execute(
        select(Chunk)
        .where(
            Chunk.organization_id == org_id,
            Chunk.course_id == course_id,
            Chunk.owner_user_id == user_id,
        )
        .order_by(Chunk.ordinal)
    )
    return list(result.scalars().all())


def _course_dict(course: Course) -> dict[str, Any]:
    return {
        "id": str(course.id),
        "code": course.code,
        "title": course.title,
        "term": course.term,
        "external_id": course.external_id,
        "clos": course.clos,
    }


async def list_courses(db: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Course).where(Course.organization_id == org_id).order_by(Course.code)
    )
    return [_course_dict(row) for row in result.scalars().all()]


async def home(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    courses = await list_courses(db, org_id)
    course_ids = [uuid.UUID(row["id"]) for row in courses]
    drafts = []
    flags = 0
    if course_ids:
        sub_rows = await db.execute(select(Submission).where(Submission.organization_id == org_id))
        submissions = list(sub_rows.scalars().all())
        draft_rows = await db.execute(
            select(GradeDraft).where(
                GradeDraft.organization_id == org_id, GradeDraft.owner_user_id == user_id
            )
        )
        drafts = list(draft_rows.scalars().all())
        flag_rows = await db.execute(
            select(IntegrityFlag).where(
                IntegrityFlag.organization_id == org_id,
                IntegrityFlag.owner_user_id == user_id,
                IntegrityFlag.status == "open",
            )
        )
        flags = len(list(flag_rows.scalars().all()))
        waiting = len(submissions)
    else:
        waiting = 0
    connector = get_connector()
    return {
        "courses": courses,
        "submissions": waiting,
        "drafts": len(drafts),
        "approved": sum(1 for row in drafts if row.status == "approved"),
        "pushed": sum(1 for row in drafts if row.status == "pushed"),
        "open_flags": flags,
        "moodle_mode": connector.mode,
        "llm_mode": llm_mode(),
        "calibrator": stubs.grade_calibrator(),
        "early_warning": {"status": "not_trained", "trained": False},
        "principle": "AI drafts only. Nothing is pushed to Moodle until you approve it.",
    }


async def _index_material(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    material: Material,
    text: str,
    user_id: uuid.UUID,
) -> None:
    rows = []
    for ordinal, part in enumerate(chunk_text(text)):
        chunk = Chunk(
            organization_id=org_id,
            course_id=course_id,
            material_id=material.id,
            owner_user_id=user_id,
            ordinal=ordinal,
            text=part,
        )
        db.add(chunk)
        await db.flush()
        rows.append({"id": str(chunk.id), "text": part, "filename": material.filename})
    index_chunks(str(org_id), str(course_id), rows, owner_user_id=str(user_id))


async def add_material(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
) -> dict[str, Any]:
    course = await _course(db, org_id, course_id)
    if len(data) > 10 * 1024 * 1024:
        raise ProfassistError(413, "Keep uploads under 10 MB for this demo.")
    raw = extract_text(filename, data)
    if not raw.strip():
        raise ProfassistError(400, "That file had no text to read.")
    cleaned = scrub(raw, await _names(db, org_id, course_id))
    storage_key = save_bytes(f"{org_id}/{course.id}/{filename}", data, "application/octet-stream")
    material = Material(
        organization_id=org_id,
        course_id=course.id,
        owner_user_id=user_id,
        filename=filename,
        text_content=raw,
        scrubbed_text=cleaned.text,
        status="quarantined" if cleaned.quarantined else "ready",
        pii_report={
            "replacements": len(cleaned.replacements),
            "uncertain": cleaned.uncertain,
            "quarantined": cleaned.quarantined,
        },
        storage_key=storage_key,
    )
    db.add(material)
    await db.flush()
    await _remember_pii(db, org_id, cleaned.replacements, f"material:{material.id}")
    if not cleaned.quarantined:
        await _index_material(db, org_id, course.id, material, cleaned.text, user_id)
    return _material_dict(material)


def _material_dict(row: Material) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "filename": row.filename,
        "status": row.status,
        "pii_report": row.pii_report,
    }


async def list_materials(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict]:
    await _course(db, org_id, course_id)
    result = await db.execute(
        select(Material).where(
            Material.organization_id == org_id,
            Material.course_id == course_id,
            Material.owner_user_id == user_id,
        )
    )
    return [_material_dict(row) for row in result.scalars().all()]


async def draft_objectives(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    course = await _course(db, org_id, course_id)
    await load_runtime(db, org_id, user_id)
    memories = await recall(db, org_id, user_id)
    chunks = await _chunks(db, org_id, course.id, user_id)
    if not chunks:
        raise ProfassistError(400, "Upload a course note before drafting objectives.")
    payload_chunks = [{"id": str(row.id), "text": row.text} for row in chunks]
    result = agents.run_course(
        "objectives",
        title=course.title,
        query="course learning outcome",
        chunks=payload_chunks,
        clos=course.clos or CLOS,
        soul=(await _soul(db, org_id, user_id)) + "\n" + "\n".join(memories),
    )
    created = []
    for ordinal, objective in enumerate(result.get("objectives") or []):
        row = Objective(
            organization_id=org_id,
            course_id=course.id,
            owner_user_id=user_id,
            ordinal=ordinal + 1,
            text=objective.get("text") or "",
            status="proposed",
            source_chunk_ids=objective.get("source_chunk_ids") or [],
        )
        db.add(row)
        await db.flush()
        created.append(_objective_dict(row))
    if not created:
        raise ProfassistError(
            422,
            "The draft was not grounded in your notes, so it was discarded. Upload a clearer note.",
        )
    return created


def _objective_dict(row: Objective) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "ordinal": row.ordinal,
        "text": row.text,
        "status": row.status,
        "source_chunk_ids": row.source_chunk_ids,
    }


async def list_objectives(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict]:
    await _course(db, org_id, course_id)
    result = await db.execute(
        select(Objective)
        .where(
            Objective.organization_id == org_id,
            Objective.course_id == course_id,
            Objective.owner_user_id == user_id,
        )
        .order_by(Objective.ordinal)
    )
    return [_objective_dict(row) for row in result.scalars().all()]


async def approve_objective(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, objective_id: uuid.UUID
) -> dict[str, Any]:
    row = await _owned(db, Objective, org_id, objective_id, user_id)
    row.status = "approved"
    db.add(
        Approval(
            organization_id=org_id,
            user_id=user_id,
            target_type="objective",
            target_id=str(row.id),
            action="approved",
            note="",
        )
    )
    await reflect_on_change(
        db, org_id, user_id, "objective", row.text, row.text, "objective-approve"
    )
    return _objective_dict(row)


async def draft_slides(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, Any]:
    course = await _course(db, org_id, course_id)
    await load_runtime(db, org_id, user_id)
    objectives = await list_objectives(db, org_id, course.id, user_id)
    approved = [row for row in objectives if row["status"] == "approved"]
    if not approved:
        raise ProfassistError(400, "Approve at least one objective before drafting slides.")
    chunks = [
        {"id": str(row.id), "text": row.text}
        for row in await _chunks(db, org_id, course.id, user_id)
    ]
    query = " ".join(row["text"] for row in approved)
    ranked = rank_chunks(query, chunks, limit=4)
    result = agents.run_course(
        "slides",
        title=course.title,
        query=query,
        chunks=ranked,
        clos=course.clos or CLOS,
        soul=await _soul(db, org_id, user_id),
    )
    slides = result.get("slides") or []
    if not slides:
        raise ProfassistError(
            422,
            "No slide was kept, because each bullet has to appear in your notes.",
        )
    deck = SlideDeck(
        organization_id=org_id,
        course_id=course.id,
        owner_user_id=user_id,
        title=result.get("title") or course.title,
        slides=slides,
        status="draft",
    )
    db.add(deck)
    await db.flush()
    pptx = build_pptx(deck.title, slides)
    deck.storage_key = save_bytes(
        f"{org_id}/{course.id}/slides-{deck.id}.pptx",
        pptx,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    return _deck_dict(deck)


def _deck_dict(row: SlideDeck) -> dict[str, Any]:
    plan = deck_plan(row.title, row.slides or [])
    return {
        "id": str(row.id),
        "title": row.title,
        "status": row.status,
        "slides": row.slides,
        "previews": render_thumbnails(plan[:8]),
    }


async def list_decks(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict]:
    await _course(db, org_id, course_id)
    result = await db.execute(
        select(SlideDeck).where(
            SlideDeck.organization_id == org_id,
            SlideDeck.course_id == course_id,
            SlideDeck.owner_user_id == user_id,
        )
    )
    return [_deck_dict(row) for row in result.scalars().all()]


async def approve_deck(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, deck_id: uuid.UUID
) -> dict[str, Any]:
    row = await _owned(db, SlideDeck, org_id, deck_id)
    row.status = "approved"
    db.add(
        Approval(
            organization_id=org_id,
            user_id=user_id,
            target_type="slides",
            target_id=str(row.id),
            action="approved",
            note="",
        )
    )
    titles = " ".join(str(slide.get("title", "")) for slide in (row.slides or []))
    await reflect_on_change(db, org_id, user_id, "slides", titles, titles, "deck-approve")
    return _deck_dict(row)


async def deck_bytes(db: AsyncSession, org_id: uuid.UUID, deck_id: uuid.UUID) -> tuple[str, bytes]:
    row = await _owned(db, SlideDeck, org_id, deck_id)
    data = read_bytes(row.storage_key) if row.storage_key else build_pptx(row.title, row.slides)
    return f"{row.title}.pptx", data


async def draft_assessment(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, Any]:
    await load_runtime(db, org_id, user_id)
    course = await _course(db, org_id, course_id)
    memories = await recall(db, org_id, user_id)
    chunks = [
        {"id": str(row.id), "text": row.text}
        for row in await _chunks(db, org_id, course.id, user_id)
    ]
    if not chunks:
        raise ProfassistError(400, "Upload a course note before designing a rubric.")
    result = agents.run_course(
        "rubric",
        title="Group report",
        query="assessment rubric",
        chunks=rank_chunks("assessment rubric feedback", chunks, limit=3),
        clos=course.clos or CLOS,
        soul=(await _soul(db, org_id, user_id)) + "\n" + "\n".join(memories),
    )
    assessment = await _primary_assessment(db, org_id, course, user_id)
    assessment.brief = result.get("brief") or assessment.brief
    assessment.clos = course.clos or CLOS
    assessment.status = "draft"
    await db.execute(
        delete(RubricCriterion).where(
            RubricCriterion.organization_id == org_id,
            RubricCriterion.assessment_id == assessment.id,
        )
    )
    for ordinal, criterion in enumerate(result.get("criteria") or []):
        db.add(
            RubricCriterion(
                organization_id=org_id,
                assessment_id=assessment.id,
                ordinal=ordinal + 1,
                name=criterion.get("name") or f"Criterion {ordinal + 1}",
                weight=int(criterion.get("weight") or 1),
                levels=criterion.get("levels") or {},
            )
        )
    await db.flush()
    return await _assessment_dict(db, assessment)


async def _primary_assessment(
    db: AsyncSession, org_id: uuid.UUID, course: Course, user_id: uuid.UUID
) -> Assessment:
    result = await db.execute(
        select(Assessment).where(
            Assessment.organization_id == org_id,
            Assessment.course_id == course.id,
            Assessment.owner_user_id == user_id,
        )
    )
    row = result.scalars().first()
    if row:
        return row
    row = Assessment(
        organization_id=org_id,
        course_id=course.id,
        owner_user_id=user_id,
        title="Group report 1",
        brief="",
        clos=course.clos or CLOS,
        status="draft",
        external_id="asg-901",
    )
    db.add(row)
    await db.flush()
    return row


async def _assessment_dict(db: AsyncSession, row: Assessment) -> dict[str, Any]:
    result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.assessment_id == row.id)
        .order_by(RubricCriterion.ordinal)
    )
    criteria = [
        {
            "id": str(item.id),
            "name": item.name,
            "weight": item.weight,
            "levels": item.levels,
        }
        for item in result.scalars().all()
    ]
    return {
        "id": str(row.id),
        "title": row.title,
        "brief": row.brief,
        "status": row.status,
        "external_id": row.external_id,
        "criteria": criteria,
    }


async def get_assessment(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> dict | None:
    course = await _course(db, org_id, course_id)
    result = await db.execute(
        select(Assessment).where(
            Assessment.organization_id == org_id,
            Assessment.course_id == course.id,
            Assessment.owner_user_id == user_id,
        )
    )
    row = result.scalars().first()
    if row is None:
        return None
    return await _assessment_dict(db, row)


async def approve_assessment(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict[str, Any]:
    row = await _owned(db, Assessment, org_id, assessment_id, user_id)
    criteria = await db.execute(
        select(RubricCriterion).where(RubricCriterion.assessment_id == row.id)
    )
    if not list(criteria.scalars().all()):
        raise ProfassistError(400, "Design the rubric before you approve it.")
    row.status = "approved"
    db.add(
        Approval(
            organization_id=org_id,
            user_id=user_id,
            target_type="assessment",
            target_id=str(row.id),
            action="approved",
            note="",
        )
    )
    await reflect_on_change(
        db, org_id, user_id, "rubric", row.brief or "", row.brief or "", "rubric-approve"
    )
    return await _assessment_dict(db, row)


async def push_record(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    target_type: str,
    target_id: str,
    status: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        assert_can_push(status)
    except PermissionError as exc:
        raise ProfassistError(409, str(exc)) from exc
    receipt = get_connector().push({"type": target_type, "id": target_id, **payload})
    db.add(
        MoodlePush(
            organization_id=org_id,
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            payload=receipt,
        )
    )
    return receipt


async def sync_moodle(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> dict[str, Any]:
    connector = get_connector()
    created = {"courses": 0, "students": 0, "submissions": 0}
    for remote in connector.list_courses():
        result = await db.execute(
            select(Course).where(Course.organization_id == org_id, Course.code == remote["code"])
        )
        course = result.scalar_one_or_none()
        if course is None:
            course = Course(
                organization_id=org_id,
                code=remote["code"],
                title=remote["title"],
                term=remote.get("term") or "",
                external_id=str(remote["id"]),
                clos=CLOS,
            )
            db.add(course)
            await db.flush()
            created["courses"] += 1
        for person in connector.list_students(str(remote["id"])):
            existing = await db.execute(
                select(Student).where(
                    Student.organization_id == org_id, Student.external_id == str(person["id"])
                )
            )
            if existing.scalar_one_or_none() is None:
                db.add(
                    Student(
                        organization_id=org_id,
                        course_id=course.id,
                        external_id=str(person["id"]),
                        display_name=person["display_name"],
                        email=person.get("email") or "",
                        student_number=person.get("student_number") or "",
                    )
                )
                created["students"] += 1
        await db.flush()
        names = await _names(db, org_id, course.id)
        for assignment in connector.list_assignments(str(remote["id"])):
            found = await db.execute(
                select(Assessment).where(
                    Assessment.organization_id == org_id,
                    Assessment.external_id == str(assignment["id"]),
                )
            )
            assessment = found.scalar_one_or_none()
            if assessment is None:
                assessment = Assessment(
                    organization_id=org_id,
                    course_id=course.id,
                    owner_user_id=user_id,
                    title=assignment["name"],
                    brief="",
                    clos=course.clos or CLOS,
                    status="draft",
                    external_id=str(assignment["id"]),
                )
                db.add(assessment)
                await db.flush()
            for submission in connector.list_submissions(str(assignment["id"])):
                found_sub = await db.execute(
                    select(Submission).where(
                        Submission.organization_id == org_id,
                        Submission.external_id == str(submission["id"]),
                    )
                )
                if found_sub.scalar_one_or_none() is not None:
                    continue
                cleaned = scrub(submission["text"], names)
                if cleaned.quarantined:
                    # Still store it, but the model only ever sees scrubbed_text,
                    # and a quarantined submission cannot be graded.
                    pass
                row = Submission(
                    organization_id=org_id,
                    course_id=course.id,
                    assessment_id=assessment.id,
                    external_id=str(submission["id"]),
                    group_name=submission["group_name"],
                    topic=submission.get("topic") or "",
                    raw_text=submission["text"],
                    scrubbed_text=cleaned.text,
                    pii_report={
                        "replacements": len(cleaned.replacements),
                        "uncertain": cleaned.uncertain,
                        "quarantined": cleaned.quarantined,
                    },
                )
                db.add(row)
                await db.flush()
                await _remember_pii(db, org_id, cleaned.replacements, f"submission:{row.id}")
                created["submissions"] += 1
    return {"moodle_mode": connector.mode, **created}


async def grade_queue(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, Any]:
    course = await _course(db, org_id, course_id)
    assessment = await get_assessment(db, org_id, course.id, user_id)
    result = await db.execute(
        select(Submission).where(
            Submission.organization_id == org_id, Submission.course_id == course.id
        )
    )
    rows = []
    for submission in result.scalars().all():
        draft_result = await db.execute(
            select(GradeDraft)
            .where(
                GradeDraft.organization_id == org_id,
                GradeDraft.owner_user_id == user_id,
                GradeDraft.submission_id == submission.id,
            )
            .order_by(GradeDraft.created_at.desc())
        )
        draft = draft_result.scalars().first()
        rows.append(
            {
                "id": str(submission.id),
                "group_name": submission.group_name,
                "topic": submission.topic,
                "quarantined": bool((submission.pii_report or {}).get("quarantined")),
                "draft_id": str(draft.id) if draft else None,
                "draft_status": draft.status if draft else None,
                "blind": bool(draft.blind) if draft else False,
                "trace_url": (draft.trace_url or "") if draft else "",
            }
        )
    return {"course": _course_dict(course), "assessment": assessment, "submissions": rows}


async def get_submission(db: AsyncSession, org_id: uuid.UUID, submission_id: uuid.UUID) -> dict:
    row = await _owned(db, Submission, org_id, submission_id)
    return {
        "id": str(row.id),
        "group_name": row.group_name,
        "topic": row.topic,
        "raw_text": row.raw_text,
        "model_view": row.scrubbed_text,
        "pii_report": row.pii_report,
        "note": "The model only receives the model view. Names and IDs stay in your workspace.",
    }


async def run_grade(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, submission_id: uuid.UUID
) -> dict[str, Any]:
    submission = await _owned(db, Submission, org_id, submission_id)
    if (submission.pii_report or {}).get("quarantined"):
        raise ProfassistError(
            422,
            "This submission is quarantined because personal data could not be removed confidently.",
        )
    course = await _course(db, org_id, submission.course_id)
    await load_runtime(db, org_id, user_id)
    assessment = await _primary_assessment(db, org_id, course, user_id)
    if assessment.status != "approved":
        raise ProfassistError(400, "Approve the rubric before grading. The council will wait.")
    criteria_result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.assessment_id == assessment.id)
        .order_by(RubricCriterion.ordinal)
    )
    criteria = list(criteria_result.scalars().all())
    if not criteria:
        raise ProfassistError(400, "This rubric has no criteria yet.")
    existing_result = await db.execute(
        select(GradeDraft)
        .where(
            GradeDraft.organization_id == org_id,
            GradeDraft.owner_user_id == user_id,
            GradeDraft.submission_id == submission.id,
        )
        .order_by(GradeDraft.created_at.desc())
    )
    existing = existing_result.scalars().first()
    if existing and existing.status in {"approved", "pushed"}:
        raise ProfassistError(409, "This draft is already approved, so it was not regenerated.")
    memories = await recall(db, org_id, user_id)
    soul = (await _soul(db, org_id, user_id)) + "\n" + "\n".join(memories)
    results = []
    feedback_parts = []
    for criterion in criteria:
        outcome = agents.run_grading_council(
            submission.scrubbed_text,
            {"name": criterion.name, "levels": criterion.levels},
            soul,
            title=assessment.title,
        )
        judge = outcome["judge"]
        calibrator = stubs.grade_calibrator(
            {
                "judge_level": judge.get("level"),
                "vote_split": judge.get("vote_split"),
                "quote_count": len(judge.get("quotes") or []),
            }
        )
        calibrator["applied"] = False
        if judge.get("skip_calibrator"):
            calibrator["reason"] = "Skipped because the council had no reliable evidence."
        else:
            calibrator["reason"] = "Not trained, so the council level was left unchanged."
        results.append(
            {
                "criterion_id": str(criterion.id),
                "criterion": criterion.name,
                "votes": outcome["votes"],
                "debate_rounds": outcome.get("debate_rounds") or [],
                "judge": judge,
                "feedback": outcome["feedback"],
                "calibrator": calibrator,
            }
        )
        if outcome["feedback"]:
            feedback_parts.append(f"{criterion.name}: {outcome['feedback']}")
    draft = existing or GradeDraft(
        organization_id=org_id, owner_user_id=user_id, submission_id=submission.id
    )
    draft.owner_user_id = user_id
    draft.results = results
    draft.overall_feedback = "\n\n".join(feedback_parts)
    draft.status = "draft"
    draft.blind = is_blind_sample(submission.group_name)
    draft.blind_revealed = False
    draft.bundle_version = "poc-1"
    if outcome.get("trace_url"):
        draft.trace_url = outcome["trace_url"]
    draft.professor_levels = {}
    db.add(draft)
    await db.flush()
    return _draft_dict(draft, submission)


def _draft_dict(draft: GradeDraft, submission: Submission) -> dict[str, Any]:
    results, feedback = redact_blind(
        draft.results or [],
        draft.overall_feedback or "",
        bool(draft.blind),
        bool(draft.blind_revealed),
    )
    return {
        "id": str(draft.id),
        "submission_id": str(submission.id),
        "group_name": submission.group_name,
        "status": draft.status,
        "blind": bool(draft.blind),
        "blind_revealed": bool(draft.blind_revealed),
        "bundle_version": draft.bundle_version,
        "results": results,
        "overall_feedback": feedback,
        "professor_levels": draft.professor_levels or {},
        "model_view": submission.scrubbed_text,
        "calibrator_trained": False,
        "one_click": False,
        "one_click_reason": (
            "One-click approval stays off until the calibrator is trained and agrees "
            "with the council at p(keep) of at least 0.85."
        ),
        "trace_url": draft.trace_url or "",
    }


async def get_draft(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, draft_id: uuid.UUID
) -> dict[str, Any]:
    draft = await _owned(db, GradeDraft, org_id, draft_id, user_id)
    submission = await _owned(db, Submission, org_id, draft.submission_id)
    return _draft_dict(draft, submission)


async def reveal_draft(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, draft_id: uuid.UUID
) -> dict[str, Any]:
    draft = await _owned(db, GradeDraft, org_id, draft_id, user_id)
    draft.blind_revealed = True
    db.add(
        Approval(
            organization_id=org_id,
            user_id=user_id,
            target_type="grade",
            target_id=str(draft.id),
            action="revealed",
            note="Blind sample revealed after the professor chose to look.",
        )
    )
    submission = await _owned(db, Submission, org_id, draft.submission_id)
    return _draft_dict(draft, submission)


async def edit_draft(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    draft_id: uuid.UUID,
    feedback: str,
    levels: dict[str, str],
) -> dict[str, Any]:
    draft = await _owned(db, GradeDraft, org_id, draft_id, user_id)
    if draft.status != "draft":
        raise ProfassistError(409, "Approved drafts stay as you approved them.")
    before = _grade_view(draft.overall_feedback, draft.professor_levels)
    draft.overall_feedback = feedback
    draft.professor_levels = levels
    submission = await _owned(db, Submission, org_id, draft.submission_id)
    await reflect_on_change(
        db, org_id, user_id, "grade", before, _grade_view(feedback, levels), "grade-edit"
    )
    return _draft_dict(draft, submission)


async def approve_draft(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, draft_id: uuid.UUID
) -> dict[str, Any]:
    draft = await _owned(db, GradeDraft, org_id, draft_id, user_id)
    if draft.status != "draft":
        raise ProfassistError(409, "This draft is already approved.")
    if draft.blind and not draft.blind_revealed and not draft.professor_levels:
        raise ProfassistError(
            400,
            "This is a blind sample. Choose your levels, or reveal the council, before you approve.",
        )
    draft.status = "approved"
    db.add(
        Approval(
            organization_id=org_id,
            user_id=user_id,
            target_type="grade",
            target_id=str(draft.id),
            action="approved",
            note="",
        )
    )
    ai_text = "\n".join(str(item.get("feedback", "")) for item in (draft.results or []))
    submission = await _owned(db, Submission, org_id, draft.submission_id)
    await reflect_on_change(
        db,
        org_id,
        user_id,
        "grade",
        ai_text,
        _grade_view(draft.overall_feedback, draft.professor_levels),
        "grade-approve",
    )
    return _draft_dict(draft, submission)


async def push_draft(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, draft_id: uuid.UUID
) -> dict[str, Any]:
    draft = await _owned(db, GradeDraft, org_id, draft_id, user_id)
    submission = await _owned(db, Submission, org_id, draft.submission_id)
    receipt = await push_record(
        db,
        org_id,
        user_id,
        "grade",
        str(draft.id),
        draft.status,
        {
            "group": submission.group_name,
            "feedback": draft.overall_feedback,
            "levels": draft.professor_levels or {"council": "see draft"},
        },
    )
    draft.status = "pushed"
    return {"draft": _draft_dict(draft, submission), "receipt": receipt}


async def scan_integrity(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    course = await _course(db, org_id, course_id)
    await load_runtime(db, org_id, user_id)
    await db.execute(
        delete(IntegrityFlag).where(
            IntegrityFlag.organization_id == org_id,
            IntegrityFlag.owner_user_id == user_id,
            IntegrityFlag.course_id == course.id,
            IntegrityFlag.status == "open",
        )
    )
    result = await db.execute(
        select(Submission).where(
            Submission.organization_id == org_id, Submission.course_id == course.id
        )
    )
    rows = [
        {
            "id": str(row.id),
            "group_name": row.group_name,
            "topic": row.topic,
            "text": row.scrubbed_text,
        }
        for row in result.scalars().all()
    ]
    created = []
    for flag in compare_submissions(rows):
        viva = llm_complete("viva", {"passage": flag["passage_a"][:400]}).get("questions") or []
        row = IntegrityFlag(
            organization_id=org_id,
            owner_user_id=user_id,
            course_id=course.id,
            left_submission_id=uuid.UUID(flag["left_id"]),
            right_submission_id=uuid.UUID(flag["right_id"]),
            section=flag["section"],
            passage_a=flag["passage_a"],
            passage_b=flag["passage_b"],
            score=float(flag["score"]),
            kind=flag["kind"],
            viva=viva,
            rare_details=flag.get("rare_details") or [],
            status="open",
        )
        db.add(row)
        await db.flush()
        created.append(_flag_dict(row))
    return created


def _flag_dict(row: IntegrityFlag) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "section": row.section,
        "passage_a": row.passage_a,
        "passage_b": row.passage_b,
        "score": row.score,
        "kind": row.kind,
        "viva": row.viva,
        "rare_details": row.rare_details,
        "status": row.status,
        "left_submission_id": str(row.left_submission_id),
        "right_submission_id": str(row.right_submission_id),
        "note": "This is evidence for a viva, not a finding of copying.",
    }


async def list_flags(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict]:
    await _course(db, org_id, course_id)
    result = await db.execute(
        select(IntegrityFlag).where(
            IntegrityFlag.organization_id == org_id,
            IntegrityFlag.owner_user_id == user_id,
            IntegrityFlag.course_id == course_id,
        )
    )
    return [_flag_dict(row) for row in result.scalars().all()]


async def set_flag(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, flag_id: uuid.UUID, status: str
) -> dict[str, Any]:
    if status not in {"confirmed", "dismissed", "open"}:
        raise ProfassistError(400, "Use confirmed, dismissed, or open.")
    row = await _owned(db, IntegrityFlag, org_id, flag_id, user_id)
    row.status = status
    db.add(
        Approval(
            organization_id=org_id,
            user_id=user_id,
            target_type="integrity",
            target_id=str(row.id),
            action=status,
            note="",
        )
    )
    return _flag_dict(row)


async def list_students(db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID) -> dict:
    await _course(db, org_id, course_id)
    result = await db.execute(
        select(Student).where(Student.organization_id == org_id, Student.course_id == course_id)
    )
    students = [
        {
            "id": str(row.id),
            "external_id": row.external_id,
            "display_name": row.display_name,
            "email": row.email,
            "student_number": row.student_number,
        }
        for row in result.scalars().all()
    ]
    return {"students": students, "early_warning": stubs.at_risk_snapshot(students)}


def _grade_view(feedback: str, levels: dict | None) -> str:
    parts = [feedback or ""]
    for name, level in sorted((levels or {}).items()):
        parts.append(f"{name}: {level}")
    return "\n".join(parts)


async def _style_row(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, *, create: bool
) -> StyleProfile | None:
    result = await db.execute(
        select(StyleProfile).where(
            StyleProfile.organization_id == org_id, StyleProfile.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None and create:
        row = StyleProfile(organization_id=org_id, user_id=user_id, soul_md=DEFAULT_SOUL)
        db.add(row)
        await db.flush()
    return row


async def _course_codes(db: AsyncSession, org_id: uuid.UUID) -> list[str]:
    result = await db.execute(select(Course).where(Course.organization_id == org_id))
    return [row.code for row in result.scalars().all()]


async def refresh_about(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, source: str
) -> str:
    """Rewrite the portrait from what we know. Older text stays in history."""
    profile = await _style_row(db, org_id, user_id, create=True)
    assert profile is not None
    memories = await list_memories(db, org_id, user_id)
    drafted = condense_about(profile.soul_md or "", memories, await _course_codes(db, org_id))
    cleaned = scrub(drafted)
    text = "" if cleaned.quarantined else cleaned.text.strip()
    if text == (profile.about_md or "").strip():
        set_about(text)
        return text
    history = list(profile.about_history or [])
    if (profile.about_md or "").strip():
        history.append({"version": len(history) + 1, "text": profile.about_md, "source": source})
    profile.about_history = history[-20:]
    profile.about_md = text
    set_about(text)
    await db.flush()
    return text


async def reflect_on_change(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    before: str,
    after: str,
    source: str,
) -> None:
    """Compare her final version with the draft, then update her private memory."""
    for lesson in extract_lessons(kind, before, after):
        await remember(
            db,
            org_id,
            user_id,
            lesson["text"],
            kind=lesson["kind"],
            source=source,
        )
    await refresh_about(db, org_id, user_id, source)
    lessons = extract_lessons(kind, before, after)
    if not lessons:
        return
    seed = "Lessons from her latest edit:\n" + "\n".join(item["text"] for item in lessons)
    proposal = agents.run_reflection(seed)
    open_rows = (
        await db.execute(
            select(Reflection).where(
                Reflection.organization_id == org_id,
                Reflection.owner_user_id == user_id,
                Reflection.status == "proposed",
            )
        )
    ).scalars()
    for existing in open_rows:
        if same_lesson(existing.proposal, proposal) or any(
            lesson["text"][:80] in existing.proposal for lesson in lessons
        ):
            return
    db.add(
        Reflection(
            organization_id=org_id,
            owner_user_id=user_id,
            proposal=proposal,
            status="proposed",
        )
    )
    await db.flush()


async def get_style(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    profile = await _style_row(db, org_id, user_id, create=False)
    owner = await db.get(User, user_id)
    soul = profile.soul_md if profile and profile.soul_md else DEFAULT_SOUL
    about = profile.about_md if profile and profile.about_md else ""
    if not about:
        memories = await list_memories(db, org_id, user_id)
        about = condense_about(soul, memories, await _course_codes(db, org_id))
    return {
        "soul_md": soul,
        "about_md": about,
        "about_history": list(profile.about_history or []) if profile else [],
        "owner_name": owner.full_name if owner and owner.full_name else "",
        "template_name": (profile.template_key if profile else "").rsplit("/", 1)[-1],
    }


async def save_style(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, soul_md: str
) -> dict[str, Any]:
    profile = await _style_row(db, org_id, user_id, create=True)
    assert profile is not None
    before = profile.soul_md or ""
    profile.soul_md = soul_md
    await db.flush()
    await reflect_on_change(db, org_id, user_id, "style", before, soul_md, "soul.md")
    return await get_style(db, org_id, user_id)


async def save_about(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, about_md: str
) -> dict[str, Any]:
    profile = await _style_row(db, org_id, user_id, create=True)
    assert profile is not None
    cleaned = scrub(about_md or "")
    if cleaned.quarantined:
        raise ProfassistError(
            400, "That note still looks like it names a person. Remove the name and save again."
        )
    if cleaned.text.strip() == (profile.about_md or "").strip():
        return await get_style(db, org_id, user_id)
    history = list(profile.about_history or [])
    if (profile.about_md or "").strip():
        history.append({"version": len(history) + 1, "text": profile.about_md, "source": "edit"})
    profile.about_history = history[-20:]
    profile.about_md = cleaned.text.strip()
    set_about(profile.about_md)
    await db.flush()
    return await get_style(db, org_id, user_id)


async def reset_about(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    await refresh_about(db, org_id, user_id, "reset")
    return await get_style(db, org_id, user_id)


async def save_template(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, filename: str, data: bytes
) -> dict[str, Any]:
    name = (filename or "master.pptx").rsplit("/", 1)[-1]
    if not name.lower().endswith((".pptx", ".potx")):
        raise ProfassistError(400, "Upload a .pptx or .potx file.")
    if not data:
        raise ProfassistError(400, "That file is empty.")
    profile = await _style_row(db, org_id, user_id, create=True)
    assert profile is not None
    profile.template_key = save_bytes(
        f"{org_id}/{user_id}/template/{name}",
        data,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    await db.flush()
    return await get_style(db, org_id, user_id)


async def run_reflection(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    await load_runtime(db, org_id, user_id)
    result = await db.execute(
        select(GradeDraft).where(
            GradeDraft.organization_id == org_id, GradeDraft.owner_user_id == user_id
        )
    )
    changes = []
    for draft in result.scalars().all():
        for name, level in (draft.professor_levels or {}).items():
            council = next(
                (
                    item.get("judge", {}).get("level")
                    for item in draft.results or []
                    if item.get("criterion") == name
                ),
                None,
            )
            if council and level and level != council:
                changes.append(f"{name}: council {council}, you chose {level}")
    seed = (
        "The professor changed levels: " + "; ".join(changes)
        if changes
        else "No level changes are stored yet. Propose a cautious note she can ignore."
    )
    text = agents.run_reflection(seed)
    row = Reflection(
        organization_id=org_id, owner_user_id=user_id, proposal=text, status="proposed"
    )
    db.add(row)
    await db.flush()
    return {"id": str(row.id), "proposal": row.proposal, "status": row.status}


async def list_reflections(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Reflection).where(
            Reflection.organization_id == org_id, Reflection.owner_user_id == user_id
        )
    )
    return [
        {"id": str(row.id), "proposal": row.proposal, "status": row.status}
        for row in result.scalars().all()
    ]


async def approve_reflection(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, reflection_id: uuid.UUID
) -> dict[str, Any]:
    row = await _owned(db, Reflection, org_id, reflection_id, user_id)
    row.status = "approved"
    style = await db.execute(
        select(StyleProfile).where(
            StyleProfile.organization_id == org_id, StyleProfile.user_id == user_id
        )
    )
    profile = style.scalar_one_or_none()
    addition = f"\n\n# Learned from your edits\n\n{row.proposal}\n"
    if profile is None:
        db.add(
            StyleProfile(organization_id=org_id, user_id=user_id, soul_md=DEFAULT_SOUL + addition)
        )
    else:
        profile.soul_md = (profile.soul_md or "") + addition
    await refresh_about(db, org_id, user_id, "reflection-approve")
    return {"id": str(row.id), "proposal": row.proposal, "status": row.status}


def calibrator_page() -> dict[str, Any]:
    return stubs.grade_calibrator()


async def build_cited_deck(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, Any]:
    """Slide-studio skill: multi-hop retrieval, citations, gaps, then pptx."""
    from app.profassist.skills.slide_studio import run_slide_studio

    await load_runtime(db, org_id, user_id)
    course = await _course(db, org_id, course_id)
    objectives = [
        row["text"]
        for row in await list_objectives(db, org_id, course.id, user_id)
        if row["status"] == "approved"
    ]
    if not objectives:
        raise ProfassistError(400, "Approve an objective before building a cited deck.")
    materials = {
        row.id: row.filename
        for row in (
            await db.execute(
                select(Material).where(
                    Material.organization_id == org_id,
                    Material.course_id == course.id,
                    Material.owner_user_id == user_id,
                )
            )
        ).scalars()
    }
    chunks = []
    for row in await _chunks(db, org_id, course.id, user_id):
        chunks.append(
            {
                "id": str(row.id),
                "text": row.text,
                "filename": materials.get(row.material_id, "note"),
                "section": "note",
            }
        )
    if not chunks:
        raise ProfassistError(400, "Upload a course note before building a cited deck.")
    profile = await _style_row(db, org_id, user_id, create=False)
    template = read_bytes(profile.template_key) if profile and profile.template_key else None
    built = run_slide_studio(
        objectives, chunks, template=template, title=f"{course.code} cited deck"
    )
    deck = SlideDeck(
        organization_id=org_id,
        course_id=course.id,
        owner_user_id=user_id,
        title=f"{course.code} cited deck",
        slides=built["slides"],
        status="draft",
    )
    db.add(deck)
    await db.flush()
    if built["pptx"]:
        deck.storage_key = save_bytes(
            f"{org_id}/{user_id}/{course.id}/cited-{deck.id}.pptx",
            built["pptx"],
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    payload = _deck_dict(deck)
    payload["gaps"] = built["gaps"]
    payload["skill"] = built["skill"]
    return payload
