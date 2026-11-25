"""Professor workflows. Models draft. These functions refuse to push early."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.profassist import agents, stubs
from app.profassist.council_config import load_council_roles
from app.profassist.course_context import (
    grading_outline,
    load_outline,
    ready_chunks,
    trim_outline,
)
from app.profassist.course_memory.service import dossier_ai_context
from app.profassist.errors import ProfassistError
from app.profassist.grading import assert_can_push, is_blind_sample, redact_blind
from app.profassist.lessons import (
    condense_about,
    extract_lessons,
    identity_lines,
    same_lesson,
    split_identity,
)
from app.profassist.llm import complete as llm_complete
from app.profassist.llm import mode as llm_mode
from app.profassist.memory import list_memories, recall, remember
from app.profassist.models import (
    Approval,
    Assessment,
    Chunk,
    Course,
    CourseDossier,
    GradeDraft,
    IntegrityFlag,
    Material,
    MoodleActivity,
    MoodlePush,
    Objective,
    PiiVault,
    ProfessorMemory,
    Reflection,
    RubricCriterion,
    SlideDeck,
    Student,
    StyleProfile,
    Submission,
    SubmissionFile,
)
from app.profassist.pii import scrub
from app.profassist.rag import chunk_text, index_chunks, rank_chunks
from app.profassist.runtime import set_about
from app.profassist.settings_admin import load_runtime, professor_identity
from app.profassist.similarity import compare_submissions
from app.profassist.slide_memory import slide_preferences
from app.profassist.slides import build_pptx, deck_plan, render_thumbnails
from app.profassist.storage import extract_text, read_bytes, save_bytes

REFLECT_EVERY = 5

logger = logging.getLogger(__name__)

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


APPROVED_RUBRIC_LOCKED = (
    "Approved rubrics stay as you approved them. Create a new rubric to change it."
)


def _rubric_weight(value: Any) -> int:
    """Keep an explicit weight. A missing or unusable value becomes 1."""
    try:
        return max(0, min(1000, int(value)))
    except (TypeError, ValueError):
        return 1


def _rubric_criteria(criteria: list[Any]) -> list[dict[str, Any]]:
    """Normalise what the page, a paste, or Moodle sent before it reaches the table."""
    cleaned: list[dict[str, Any]] = []
    for item in criteria:
        if not isinstance(item, dict):
            raise ProfassistError(400, "Each criterion needs a name and its levels.")
        levels = item.get("levels")
        cleaned.append(
            {
                "name": str(item.get("name") or "").strip(),
                "weight": _rubric_weight(item.get("weight")),
                "levels": (
                    {str(key): str(value or "") for key, value in levels.items()}
                    if isinstance(levels, dict)
                    else {}
                ),
            }
        )
    return cleaned


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
        "last_sync_at": course.last_sync_at.isoformat() if course.last_sync_at else "",
        "last_sync_status": course.last_sync_status or "",
        "ai_instructions": course.ai_instructions or "",
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
    identity = await professor_identity(db, org_id, user_id)
    material_rows = await db.execute(
        select(Material).where(
            Material.organization_id == org_id,
            Material.owner_user_id == user_id,
            Material.status == "ready",
        )
    )
    documents = sum(
        1 for row in material_rows.scalars().all() if not (row.pii_report or {}).get("quarantined")
    )
    memory_topics = 0
    memory_assessments = 0
    if course_ids:
        dossier_rows = await db.execute(
            select(CourseDossier).where(
                CourseDossier.organization_id == org_id,
                CourseDossier.course_id == course_ids[0],
                CourseDossier.owner_user_id == user_id,
                CourseDossier.status == "ready",
            )
        )
        dossier = dossier_rows.scalars().first()
        body = dossier.body if dossier is not None and isinstance(dossier.body, dict) else {}
        memory_topics = len(body.get("topics") or [])
        memory_assessments = len(body.get("assessments") or [])
    reflection_rows = await db.execute(
        select(Reflection).where(
            Reflection.organization_id == org_id,
            Reflection.owner_user_id == user_id,
            Reflection.status == "proposed",
        )
    )
    reflections = len(list(reflection_rows.scalars().all()))
    from app.integrations.moodle.gateway import adapter

    connector = adapter()
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
        "professor": identity,
        "memory": {
            "documents": documents,
            "topics": memory_topics,
            "assessments": memory_assessments,
            "reflections": reflections,
        },
        "principle": "AI drafts only. Nothing is pushed to Moodle until you approve it.",
    }


async def _index_material(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    material: Material,
    text: str,
    user_id: uuid.UUID | None,
) -> None:
    """Chunk, embed, and only then mark the material ready.

    A failed model load or a rejected upsert leaves the material in ``error``
    with the reason in ``pii_report["index_error"]``. It is never marked ready,
    so drafting will not quote notes that have no vectors behind them.
    """
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
    try:
        if not rows:
            raise RuntimeError("There was no text to embed, so the material is not ready.")
        indexed = index_chunks(str(org_id), str(course_id), rows, owner_user_id=str(user_id or ""))
        if not indexed:
            raise RuntimeError(
                "The vector store is unreachable, so the notes were not indexed. "
                "Start Qdrant and re-run `uv run profassist cmd rag-reindex`."
            )
    except Exception as exc:
        material.status = "error"
        material.pii_report = {**(material.pii_report or {}), "index_error": str(exc)}
        return
    material.status = "ready"
    report = dict(material.pii_report or {})
    report.pop("index_error", None)
    material.pii_report = report


async def add_material(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
) -> dict[str, Any]:
    course = await _course(db, org_id, course_id)
    if len(data) > 25 * 1024 * 1024:
        raise ProfassistError(413, "Keep uploads under 25 MB.")
    raw = extract_text(filename, data)
    if not raw.strip():
        raise ProfassistError(400, "That file had no text to read.")
    cleaned = scrub(raw, await _names(db, org_id, course_id))
    allowed = (".pdf", ".docx", ".pptx", ".potx", ".txt", ".md", ".html", ".htm")
    if not filename.lower().endswith(allowed):
        raise ProfassistError(400, "Attach a PDF, DOCX, PPTX, HTML, TXT, or Markdown file.")
    storage_key = save_bytes(
        f"{org_id}/{user_id}/{course.id}/{filename}", data, "application/octet-stream"
    )
    material = Material(
        organization_id=org_id,
        course_id=course.id,
        owner_user_id=user_id,
        filename=filename,
        text_content=raw,
        scrubbed_text=cleaned.text,
        # Ready means "indexed with real vectors". Until _index_material
        # succeeds the file is deliberately not ready to quote.
        status="quarantined" if cleaned.quarantined else "processing",
        pii_report={
            "replacements": len(cleaned.replacements),
            "uncertain": cleaned.uncertain,
            "quarantined": cleaned.quarantined,
            "bytes": len(data),
        },
        storage_key=storage_key,
    )
    db.add(material)
    await db.flush()
    await _remember_pii(db, org_id, cleaned.replacements, f"material:{material.id}")
    try:
        await remember(
            db,
            org_id,
            user_id,
            f"Professor added {filename} as a course source.",
            kind="materials",
            source=f"material:{material.id}",
        )
        await maybe_propose_reflection(db, org_id, user_id, f"material:{material.id}")
    except Exception:
        logger.info("Material memory skipped; the upload stands")
    if not cleaned.quarantined:
        await _index_material(db, org_id, course.id, material, cleaned.text, user_id)
    return _material_dict(material)


def _material_dict(row: Material) -> dict[str, Any]:
    report = row.pii_report or {}
    insight = row.insight if isinstance(row.insight, dict) else {}
    topics = [
        str(item.get("name") or "").strip()
        for item in insight.get("topics") or []
        if isinstance(item, dict)
    ]
    terms = [
        str(item.get("term") or "").strip()
        for item in insight.get("key_terms") or []
        if isinstance(item, dict)
    ]
    tags: list[str] = []
    for value in [*topics, *terms]:
        if value and value not in tags:
            tags.append(value)
        if len(tags) >= 12:
            break
    return {
        "id": str(row.id),
        "filename": row.filename,
        "status": row.status,
        "index_error": report.get("index_error", ""),
        "pii_report": report,
        "size": int(report.get("bytes") or 0),
        "scrubbed": int(report.get("replacements") or 0) > 0,
        "insight_status": str(row.insight_status or ""),
        "kind": str(insight.get("document_kind") or ""),
        "tags": tags,
        "summary": str(insight.get("summary") or ""),
        "trace_url": str(row.trace_url or ""),
    }


async def delete_material(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
) -> dict[str, Any]:
    row = await db.get(Material, material_id)
    if (
        row is None
        or row.organization_id != org_id
        or row.course_id != course_id
        or row.owner_user_id != user_id
    ):
        raise ProfassistError(404, "That file is not in this course.")
    await db.execute(Chunk.__table__.delete().where(Chunk.material_id == row.id))
    await db.delete(row)
    await db.flush()
    dossier = (
        (
            await db.execute(
                select(CourseDossier).where(
                    CourseDossier.organization_id == org_id,
                    CourseDossier.course_id == course_id,
                    CourseDossier.owner_user_id == user_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if dossier is not None:
        dossier.status = "stale"
        await db.flush()
    return {"deleted": str(material_id)}


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


async def reindex_materials(
    db: AsyncSession,
    org_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Rebuild note chunks and vectors with the currently configured embeddings.

    Use after switching EMBEDDING_PROVIDER/EMBEDDING_MODEL or recreating the
    Qdrant collection. Quarantined notes are left untouched.
    """
    from app.profassist.rag import delete_chunks

    query = select(Material)
    if org_id is not None:
        query = query.where(Material.organization_id == org_id)
    if course_id is not None:
        query = query.where(Material.course_id == course_id)
    if user_id is not None:
        query = query.where(Material.owner_user_id == user_id)
    materials = list((await db.execute(query)).scalars().all())

    reindexed = 0
    skipped = 0
    failed: list[dict[str, str]] = []
    for material in materials:
        if (material.pii_report or {}).get("quarantined"):
            skipped += 1
            continue
        old_ids = [
            str(row_id)
            for row_id in (
                await db.execute(select(Chunk.id).where(Chunk.material_id == material.id))
            )
            .scalars()
            .all()
        ]
        await db.execute(delete(Chunk).where(Chunk.material_id == material.id))
        await db.flush()
        delete_chunks(old_ids)
        await _index_material(
            db,
            material.organization_id,
            material.course_id,
            material,
            material.scrubbed_text or material.text_content,
            material.owner_user_id or user_id,
        )
        if material.status == "ready":
            reindexed += 1
        else:
            failed.append(
                {
                    "id": str(material.id),
                    "filename": material.filename,
                    "error": str((material.pii_report or {}).get("index_error") or "not indexed"),
                }
            )
    return {
        "materials": len(materials),
        "reindexed": reindexed,
        "skipped": skipped,
        "failed": failed,
    }


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
        clos=course.clos or [],
        soul=(await _soul(db, org_id, user_id)) + "\n" + "\n".join(memories),
    )
    created = []
    for raw in result.get("objectives") or []:
        objective = agents.normalise_objective(raw)
        if objective is None:
            continue
        row = Objective(
            organization_id=org_id,
            course_id=course.id,
            owner_user_id=user_id,
            ordinal=len(created) + 1,
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


def _grounded_slides(slides: list[Any], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only slides whose bullets appear verbatim in the ready notes."""
    source = "\n".join(str(chunk.get("text") or "") for chunk in chunks)
    kept: list[dict[str, Any]] = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        bullets = [
            bullet
            for bullet in slide.get("bullets") or []
            if isinstance(bullet, str) and bullet and bullet in source
        ]
        if bullets:
            row = dict(slide)
            row["bullets"] = bullets
            kept.append(row)
    return kept


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
    dossier = await dossier_ai_context(db, org_id, user_id, course.id, budget=6000)
    preferences = await slide_preferences(db, org_id, user_id, f"{course.code} {query}")
    result = llm_complete(
        "slides",
        {
            "title": course.title,
            "chunks": ranked,
            "clos": course.clos or [],
            "soul": await _soul(db, org_id, user_id),
            "message": "",
            "dossier": dossier,
            "preferences": preferences,
        },
    )
    slides = _grounded_slides(result.get("slides") or [], ranked)
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
        "week": row.week,
        "instructions": row.instructions or "",
        "slides": row.slides,
        "previews": render_thumbnails(plan[:8]),
        "review": getattr(row, "review", None) or {},
        "review_trace_url": getattr(row, "review_trace_url", "") or "",
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
    row = await _owned(db, SlideDeck, org_id, deck_id, user_id)
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
    await reflect_on_change(
        db,
        org_id,
        user_id,
        "slides",
        "",
        _deck_text(row.slides),
        "deck-approve",
        propose=True,
    )
    return _deck_dict(row)


async def deck_bytes(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, deck_id: uuid.UUID
) -> tuple[str, bytes]:
    row = await _owned(db, SlideDeck, org_id, deck_id, user_id)
    data = read_bytes(row.storage_key) if row.storage_key else build_pptx(row.title, row.slides)
    return f"{row.title}.pptx", data


async def draft_assessment(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    assessment_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    await load_runtime(db, org_id, user_id)
    course = await _course(db, org_id, course_id)
    if assessment_id is not None:
        assessment = await _owned(db, Assessment, org_id, assessment_id, user_id)
        if assessment.course_id != course.id:
            raise ProfassistError(404, "Assessment not found in this course")
    else:
        assessment = await _primary_assessment(db, org_id, course, user_id)
    if assessment.status == "approved":
        raise ProfassistError(409, APPROVED_RUBRIC_LOCKED)
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
        clos=course.clos or [],
        soul=(await _soul(db, org_id, user_id)) + "\n" + "\n".join(memories),
    )
    assessment.brief = result.get("brief") or assessment.brief
    assessment.clos = course.clos or []
    assessment.status = "draft"
    await db.execute(
        delete(RubricCriterion).where(
            RubricCriterion.organization_id == org_id,
            RubricCriterion.assessment_id == assessment.id,
        )
    )
    for ordinal, criterion in enumerate(_rubric_criteria(result.get("criteria") or []), start=1):
        db.add(
            RubricCriterion(
                organization_id=org_id,
                assessment_id=assessment.id,
                ordinal=ordinal,
                name=criterion["name"] or f"Criterion {ordinal}",
                weight=criterion["weight"],
                levels=criterion["levels"],
            )
        )
    await db.flush()
    return await _assessment_dict(db, assessment)


async def _primary_assessment(
    db: AsyncSession, org_id: uuid.UUID, course: Course, user_id: uuid.UUID
) -> Assessment:
    result = await db.execute(
        select(Assessment)
        .where(
            Assessment.organization_id == org_id,
            Assessment.course_id == course.id,
            Assessment.owner_user_id == user_id,
        )
        # A draft is the working rubric. An approved one is only picked when it is all there is.
        .order_by(
            Assessment.status == "approved", Assessment.created_at.desc(), Assessment.id.desc()
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
        clos=course.clos or [],
        status="draft",
        external_id="asg-901",
    )
    db.add(row)
    await db.flush()
    return row


async def _assessment_dict(db: AsyncSession, row: Assessment) -> dict[str, Any]:
    result = await db.execute(
        select(RubricCriterion)
        .where(
            RubricCriterion.organization_id == row.organization_id,
            RubricCriterion.assessment_id == row.id,
        )
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
        "weight": row.weight,
        "kind": row.kind,
        "version": row.version,
        "alignment": row.alignment or {},
        "history_count": len(row.history or []),
        "criteria": criteria,
    }


async def get_assessment(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> dict | None:
    course = await _course(db, org_id, course_id)
    result = await db.execute(
        select(Assessment)
        .where(
            Assessment.organization_id == org_id,
            Assessment.course_id == course.id,
            Assessment.owner_user_id == user_id,
        )
        .order_by(
            Assessment.status == "approved", Assessment.created_at.desc(), Assessment.id.desc()
        )
    )
    row = result.scalars().first()
    if row is None:
        return None
    return await _assessment_dict(db, row)


async def list_assessments(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    course = await _course(db, org_id, course_id)
    result = await db.execute(
        select(Assessment)
        .where(
            Assessment.organization_id == org_id,
            Assessment.course_id == course.id,
            Assessment.owner_user_id == user_id,
        )
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
    )
    return [await _assessment_dict(db, row) for row in result.scalars().all()]


async def create_rubric(
    db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID, title: str
) -> dict[str, Any]:
    course = await _course(db, org_id, course_id)
    row = Assessment(
        organization_id=org_id,
        course_id=course.id,
        owner_user_id=user_id,
        title=title.strip() or "Untitled rubric",
        brief="",
        clos=course.clos or [],
        status="draft",
        external_id="",
        kind="assignment",
    )
    db.add(row)
    await db.flush()
    return await _assessment_dict(db, row)


async def save_rubric(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    assessment_id: uuid.UUID,
    criteria: list[dict[str, Any]],
    brief: str | None = None,
) -> dict[str, Any]:
    row = await _owned(db, Assessment, org_id, assessment_id, user_id)
    if row.status == "approved":
        raise ProfassistError(409, APPROVED_RUBRIC_LOCKED)
    before_criteria = await _stored_criteria(db, org_id, row.id)
    before_brief = row.brief or ""
    normalised = _rubric_criteria(criteria)
    if brief is not None:
        row.brief = brief
    await _apply_imported_criteria(db, org_id, row, normalised, "edit")
    await capture_movement(
        db,
        org_id,
        user_id,
        "rubric",
        _criteria_text(before_criteria),
        _criteria_text(normalised),
        "rubric-edit",
    )
    if (row.brief or "") != before_brief:
        await capture_movement(
            db, org_id, user_id, "objective", before_brief, row.brief or "", "rubric-edit"
        )
    return await _assessment_dict(db, row)


async def import_rubric(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    assessment_id: uuid.UUID,
    filename: str,
    data: bytes,
    pasted: str = "",
) -> dict[str, Any]:
    from app.profassist.rubric_build import parse_rubric_file, parse_rubric_text

    row = await _owned(db, Assessment, org_id, assessment_id, user_id)
    before_criteria = await _stored_criteria(db, org_id, row.id)
    if pasted.strip():
        criteria = parse_rubric_text(pasted)
    else:
        criteria = parse_rubric_file(filename or "rubric.txt", data)
    if not criteria:
        raise ProfassistError(
            400,
            "No criteria were found. Use lines like 'Criterion: Evidence' and 'Beginning: ...'.",
        )
    normalised = _rubric_criteria(criteria)
    await _apply_imported_criteria(db, org_id, row, normalised, "import")
    await capture_movement(
        db,
        org_id,
        user_id,
        "rubric",
        _criteria_text(before_criteria),
        _criteria_text(normalised),
        "rubric-import",
    )
    return await _assessment_dict(db, row)


async def check_rubric(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict[str, Any]:
    from app.profassist.rubric_build import alignment

    row = await _owned(db, Assessment, org_id, assessment_id, user_id)
    criteria = (
        await db.execute(
            select(RubricCriterion)
            .where(RubricCriterion.assessment_id == row.id)
            .order_by(RubricCriterion.ordinal)
        )
    ).scalars()
    payload = alignment(
        [{"name": item.name, "weight": item.weight, "levels": item.levels} for item in criteria],
        [str(item) for item in (row.clos or [])],
    )
    row.alignment = payload
    await db.flush()
    result = await _assessment_dict(db, row)
    result["alignment"] = payload
    return result


async def upload_submission_zip(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    assessment_id: uuid.UUID,
    data: bytes,
) -> dict[str, Any]:
    import io
    import zipfile

    course = await _course(db, org_id, course_id)
    assessment = await _owned(db, Assessment, org_id, assessment_id, user_id)
    names = await _names(db, org_id, course.id)
    added = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ProfassistError(400, "Upload a .zip of submission files.") from exc
    for name in archive.namelist():
        if name.endswith("/") or name.startswith("__MACOSX"):
            continue
        payload = archive.read(name)
        filename = name.rsplit("/", 1)[-1]
        group = (
            name.rsplit("/", 1)[0].rsplit("/", 1)[-1] if "/" in name else filename.rsplit(".", 1)[0]
        )
        external = f"upload-{assessment.id}-{name}"
        existing = await db.execute(
            select(Submission).where(
                Submission.organization_id == org_id, Submission.external_id == external
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        text, files = _remote_text(
            {"text": "", "files": [{"filename": filename, "content_type": "", "data": payload}]}
        )
        cleaned = scrub(text, names)
        row = Submission(
            organization_id=org_id,
            course_id=course.id,
            assessment_id=assessment.id,
            external_id=external,
            group_name=group or filename,
            topic="upload",
            raw_text=text,
            scrubbed_text=cleaned.text,
            origin="upload",
            pii_report={
                "replacements": len(cleaned.replacements),
                "uncertain": cleaned.uncertain,
                "quarantined": cleaned.quarantined,
            },
        )
        db.add(row)
        await db.flush()
        await _store_files(db, org_id, row, files)
        added += 1
    return {"added": added}


async def grade_assignment_batch(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict[str, Any]:
    await _owned(db, Assessment, org_id, assessment_id, user_id)
    from app.worker.tasks.profassist_tasks import grade_batch_flow

    return await grade_batch_flow(str(org_id), str(assessment_id), str(user_id))


async def approve_assessment(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict[str, Any]:
    row = await _owned(db, Assessment, org_id, assessment_id, user_id)
    if row.status == "approved":
        # Approving twice keeps the same approved copy instead of writing a second audit row.
        return await _assessment_dict(db, row)
    criteria = list(
        (
            await db.execute(
                select(RubricCriterion).where(
                    RubricCriterion.organization_id == org_id,
                    RubricCriterion.assessment_id == row.id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not criteria:
        raise ProfassistError(400, "Design the rubric before you approve it.")
    described = any(
        str(value or "").strip()
        for criterion in criteria
        for value in (criterion.levels or {}).values()
    )
    if not described:
        raise ProfassistError(400, "Describe at least one level before you approve the rubric.")
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
    criteria_text = _criteria_text(
        [
            {"name": criterion.name, "weight": criterion.weight, "levels": criterion.levels or {}}
            for criterion in criteria
        ]
    )
    await reflect_on_change(
        db, org_id, user_id, "rubric", "", criteria_text, "rubric-approve", propose=True
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
    from app.integrations.moodle.gateway import push as moodle_push

    receipt = await moodle_push({"type": target_type, "id": target_id, **payload}, db, org_id)
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


def _remote_text(submission: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    from app.profassist.storage import extract_text

    parts = [submission.get("text") or ""]
    files = []
    for item in submission.get("files") or []:
        data = item.get("data") or b""
        filename = item.get("filename") or "attachment"
        extracted = extract_text(filename, data) if data else ""
        if extracted.strip() and extracted.strip() not in parts[0]:
            parts.append(f"Attachment {filename}\n{extracted}")
        files.append({**item, "extracted_text": extracted})
    return "\n\n".join(part for part in parts if part.strip()), files


async def _fill_missing_files(
    db: AsyncSession,
    org_id: uuid.UUID,
    row: Submission,
    submission: dict[str, Any],
    names: list[str],
) -> None:
    """A later sync can add attachments that were not there the first time."""
    found = await db.execute(select(SubmissionFile).where(SubmissionFile.submission_id == row.id))
    if found.scalars().first() is not None:
        return
    text, files = _remote_text(submission)
    if not files:
        return
    cleaned = scrub(text, names)
    row.raw_text = text
    row.scrubbed_text = cleaned.text
    if submission.get("peer_reviews"):
        row.peer_reviews = submission["peer_reviews"]
    await _store_files(db, org_id, row, files)


async def _store_files(
    db: AsyncSession, org_id: uuid.UUID, row: Submission, files: list[dict[str, Any]]
) -> None:
    for item in files:
        data = item.get("data") or b""
        key = ""
        if data:
            key = save_bytes(
                f"{org_id}/submissions/{row.id}/{item.get('filename') or 'file'}",
                data,
                item.get("content_type") or "application/octet-stream",
            )
        db.add(
            SubmissionFile(
                organization_id=org_id,
                submission_id=row.id,
                filename=item.get("filename") or "attachment",
                media_type=item.get("content_type") or "",
                storage_key=key,
                extracted_text=item.get("extracted_text") or "",
            )
        )


async def _apply_imported_criteria(
    db: AsyncSession,
    org_id: uuid.UUID,
    assessment: Assessment,
    criteria: list[dict[str, Any]],
    source: str,
) -> None:
    from app.profassist.rubric_build import alignment

    if assessment.status == "approved":
        raise ProfassistError(409, APPROVED_RUBRIC_LOCKED)
    criteria = _rubric_criteria(criteria)
    existing = await db.execute(
        select(RubricCriterion).where(
            RubricCriterion.organization_id == org_id,
            RubricCriterion.assessment_id == assessment.id,
        )
    )
    current = [
        {"name": item.name, "weight": item.weight, "levels": item.levels}
        for item in existing.scalars().all()
    ]
    if current:
        history = list(assessment.history or [])
        history.append({"version": assessment.version, "source": source, "criteria": current})
        assessment.history = history[-12:]
        assessment.version += 1
    await db.execute(
        delete(RubricCriterion).where(
            RubricCriterion.organization_id == org_id,
            RubricCriterion.assessment_id == assessment.id,
        )
    )
    for ordinal, criterion in enumerate(criteria, start=1):
        db.add(
            RubricCriterion(
                organization_id=org_id,
                assessment_id=assessment.id,
                ordinal=ordinal,
                name=criterion["name"] or f"Criterion {ordinal}",
                weight=criterion["weight"],
                levels=criterion["levels"],
            )
        )
    assessment.alignment = alignment(criteria, [str(item) for item in (assessment.clos or [])])
    assessment.status = "draft"
    await db.flush()


async def sync_moodle(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Manual pull. The scheduled Prefect flow is the usual path."""
    from app.integrations.moodle.gateway import sync as gateway_sync

    return await gateway_sync(db, org_id, user_id, trigger="manual")


async def pull_moodle(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None, connector: Any
) -> dict[str, Any]:
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
                clos=[],
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
        board_assignments: list[dict[str, Any]] = []
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
                    clos=course.clos or [],
                    status="draft",
                    external_id=str(assignment["id"]),
                )
                db.add(assessment)
                await db.flush()
            board_item = {
                "number": str(assessment.external_id or assignment["id"] or "1"),
                "title": assessment.title,
                "submissions": [],
            }
            for submission in connector.list_submissions(str(assignment["id"]), str(remote["id"])):
                text, files = _remote_text(submission)
                cleaned = scrub(text, names)
                board_item["submissions"].append(
                    {
                        "id": str(submission["id"]),
                        "group_name": submission["group_name"],
                        "topic": submission.get("topic") or "",
                        "text": cleaned.text,
                    }
                )
                found_sub = await db.execute(
                    select(Submission).where(
                        Submission.organization_id == org_id,
                        Submission.external_id == str(submission["id"]),
                    )
                )
                existing_sub = found_sub.scalar_one_or_none()
                if existing_sub is not None:
                    await _fill_missing_files(db, org_id, existing_sub, submission, names)
                    continue
                row = Submission(
                    organization_id=org_id,
                    course_id=course.id,
                    assessment_id=assessment.id,
                    external_id=str(submission["id"]),
                    group_name=submission["group_name"],
                    topic=submission.get("topic") or "",
                    raw_text=text,
                    scrubbed_text=cleaned.text,
                    peer_reviews=submission.get("peer_reviews") or [],
                    origin="moodle",
                    author_external_id=str(submission.get("author_id") or ""),
                    pii_report={
                        "replacements": len(cleaned.replacements),
                        "uncertain": cleaned.uncertain,
                        "quarantined": cleaned.quarantined,
                    },
                )
                db.add(row)
                await db.flush()
                await _store_files(db, org_id, row, files)
                await _remember_pii(db, org_id, cleaned.replacements, f"submission:{row.id}")
                created["submissions"] += 1
            if len(board_item["submissions"]) >= 2:
                board_assignments.append(board_item)
            if assignment.get("rubric") and assessment.status != "approved":
                await _apply_imported_criteria(
                    db, org_id, assessment, assignment["rubric"], "moodle"
                )
        if board_assignments:
            # The integrity page reads an in-memory board. Register the pairs a
            # demo can inspect immediately after the sync, using scrubbed text.
            from app.profassist.integrity_board import register_synced_submissions

            register_synced_submissions(course.code, course.title, board_assignments)
        for workshop in connector.list_workshops(str(remote["id"])):
            found = await db.execute(
                select(Assessment).where(
                    Assessment.organization_id == org_id,
                    Assessment.external_id == str(workshop["id"]),
                )
            )
            assessment = found.scalar_one_or_none()
            if assessment is None:
                assessment = Assessment(
                    organization_id=org_id,
                    course_id=course.id,
                    owner_user_id=user_id,
                    title=workshop["name"],
                    brief="",
                    clos=course.clos or [],
                    status="draft",
                    external_id=str(workshop["id"]),
                    kind="workshop",
                )
                db.add(assessment)
                await db.flush()
            for submission in connector.list_workshop_submissions(str(workshop["id"])):
                found_sub = await db.execute(
                    select(Submission).where(
                        Submission.organization_id == org_id,
                        Submission.external_id == str(submission["id"]),
                    )
                )
                if found_sub.scalar_one_or_none() is not None:
                    continue
                text, files = _remote_text(submission)
                cleaned = scrub(text, names)
                row = Submission(
                    organization_id=org_id,
                    course_id=course.id,
                    assessment_id=assessment.id,
                    external_id=str(submission["id"]),
                    group_name=submission["group_name"],
                    topic=submission.get("topic") or "",
                    raw_text=text,
                    scrubbed_text=cleaned.text,
                    peer_reviews=submission.get("peer_reviews") or [],
                    origin="moodle",
                    author_external_id=str(submission.get("author_id") or ""),
                    pii_report={
                        "replacements": len(cleaned.replacements),
                        "uncertain": cleaned.uncertain,
                        "quarantined": cleaned.quarantined,
                    },
                )
                db.add(row)
                await db.flush()
                await _store_files(db, org_id, row, files)
                created["submissions"] += 1
        activity_note = ""
        try:
            activity_rows = connector.list_activity(str(remote["id"]))
        except ProfassistError as exc:
            # local_profassist_get_activity ships with the demo simulator. A stock
            # Moodle refuses it, which is a data gap, not a failed sync.
            activity_rows = []
            activity_note = f" Activity features were not available: {exc.detail}"
        stored = 0
        for activity in activity_rows:
            if not isinstance(activity, dict):
                continue
            student_external_id = str(activity.get("userid") or "")
            features = activity.get("features")
            if not student_external_id or not isinstance(features, dict):
                continue
            found_activity = await db.execute(
                select(MoodleActivity).where(
                    MoodleActivity.organization_id == org_id,
                    MoodleActivity.course_id == course.id,
                    MoodleActivity.student_external_id == student_external_id,
                )
            )
            row = found_activity.scalars().first()
            if row is None:
                row = MoodleActivity(
                    organization_id=org_id,
                    course_id=course.id,
                    student_external_id=student_external_id,
                )
                db.add(row)
            row.features = dict(features)
            row.source = connector.mode
            row.synced_at = datetime.now(UTC)
            stored += 1
        await db.flush()
        if stored:
            activity_note = f" Activity features stored for {stored} students."
        course.last_sync_at = datetime.now(UTC)
        course.last_sync_status = (
            f"Synced from {connector.mode} Moodle. "
            f"{created['submissions']} new submissions, {created['students']} new students."
            f"{activity_note}"
        )
    return {"moodle_mode": connector.mode, **created, "last_sync_status": course.last_sync_status}


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
                "assessment_id": str(submission.assessment_id),
                "origin": submission.origin,
                "files": len(
                    (
                        await db.execute(
                            select(SubmissionFile).where(
                                SubmissionFile.submission_id == submission.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                ),
                "peer_reviews": len(submission.peer_reviews or []),
                "quarantined": bool((submission.pii_report or {}).get("quarantined")),
                "draft_id": str(draft.id) if draft else None,
                "draft_status": draft.status if draft else None,
                "blind": bool(draft.blind) if draft else False,
                "trace_url": (draft.trace_url or "") if draft else "",
            }
        )
    assessments = await list_assessments(db, org_id, course.id, user_id)
    return {
        "course": _course_dict(course),
        "assessment": assessment,
        "assessments": assessments,
        "submissions": rows,
    }


async def get_submission(db: AsyncSession, org_id: uuid.UUID, submission_id: uuid.UUID) -> dict:
    row = await _owned(db, Submission, org_id, submission_id)
    return {
        "id": str(row.id),
        "group_name": row.group_name,
        "topic": row.topic,
        "raw_text": row.raw_text,
        "model_view": row.scrubbed_text,
        "pii_report": row.pii_report,
        "peer_reviews": row.peer_reviews or [],
        "origin": row.origin,
        "files": [
            {"filename": item.filename, "extracted_text": item.extracted_text[:500]}
            for item in (
                await db.execute(
                    select(SubmissionFile).where(SubmissionFile.submission_id == row.id)
                )
            ).scalars()
        ],
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
    await _course(db, org_id, submission.course_id)
    await load_runtime(db, org_id, user_id)
    grading_roles = await load_council_roles(db, org_id, "grading")
    personas = [
        role["role_key"]
        for role in grading_roles
        if role.get("kind") == "llm" and role.get("enabled")
    ]
    persona_config = {
        role["role_key"]: {
            "prompt_override": role.get("persona_prompt") or "",
            "model": role.get("model") or "",
        }
        for role in grading_roles
        if role.get("kind") == "llm" and role.get("enabled")
    }
    assessment = await db.get(Assessment, submission.assessment_id)
    if assessment is None or assessment.organization_id != org_id:
        raise ProfassistError(404, "This submission has no assignment in this workspace.")
    if assessment.owner_user_id and assessment.owner_user_id != user_id:
        raise ProfassistError(404, "This assignment belongs to another professor.")
    if assessment.status != "approved":
        raise ProfassistError(
            400, f"Approve the rubric on {assessment.title} before grading. The council will wait."
        )
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
    outline_row = await load_outline(db, org_id, user_id, submission.course_id)
    outline = grading_outline(trim_outline(outline_row)) if outline_row is not None else {}
    clos = [
        str(item.get("text") or item.get("code") or "") if isinstance(item, dict) else str(item)
        for item in assessment.clos or []
    ]
    clos = [code for code in clos if code]
    dossier = await dossier_ai_context(db, org_id, user_id, submission.course_id, budget=4000)
    results = []
    feedback_parts = []
    for criterion in criteria:
        peer_view = []
        for review in submission.peer_reviews or []:
            cleaned = scrub(str(review.get("text") or ""))
            if cleaned.quarantined:
                continue
            peer_view.append(
                {
                    "reviewer": review.get("reviewer") or "peer",
                    "text": cleaned.text,
                    "scores": review.get("scores") or {},
                }
            )
        outcome = agents.run_grading_council(
            submission.scrubbed_text,
            {"name": criterion.name, "levels": criterion.levels},
            soul,
            title=assessment.title,
            peer_reviews=peer_view,
            outline=outline,
            clos=clos,
            dossier=dossier,
            personas=personas,
            persona_config=persona_config,
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
        "grader_model": _grader_model(),
    }


def _grader_model() -> str:
    from app.profassist.providers import model_label
    from app.profassist.runtime import agent_route

    route = agent_route("persona_evidence")
    return model_label(route["provider"], route["model"])


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
    assessment = await db.get(Assessment, submission.assessment_id)
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
            "assignment_external_id": assessment.external_id if assessment else "",
            "author_external_id": submission.author_external_id,
            "grade": _grade_number(draft.professor_levels or {}),
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
    course = await _course(db, org_id, course_id)
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
    from app.profassist.ml.dropout_jobs import list_student_predictions

    predictions_by_student = await list_student_predictions(db, org_id, course_id)
    for student in students:
        student["dropout_prediction"] = predictions_by_student.get(student["id"])
    activity_result = await db.execute(
        select(MoodleActivity).where(
            MoodleActivity.organization_id == org_id,
            MoodleActivity.course_id == course.id,
        )
    )
    features_by_student = {
        row.student_external_id: row.features
        for row in activity_result.scalars().all()
        if row.student_external_id and row.features
    }
    return {
        "students": students,
        "course": {"id": str(course.id), "code": course.code, "title": course.title},
        "early_warning": stubs.at_risk_snapshot(
            students, course_code=course.code, features_by_student=features_by_student
        ),
    }


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


async def refresh_about(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, source: str
) -> str:
    """Rewrite the portrait from what we know. Older text stays in history."""
    profile = await _style_row(db, org_id, user_id, create=True)
    assert profile is not None
    memories = await list_memories(db, org_id, user_id)
    identity = await professor_identity(db, org_id, user_id)
    drafted = condense_about(profile.soul_md or "", memories, identity["courses"], identity)
    identity_lines, body = split_identity(drafted)
    cleaned = scrub(body)
    if cleaned.quarantined:
        text = "\n".join(identity_lines)
    else:
        body_text = cleaned.text.strip()
        parts = [*identity_lines]
        if body_text:
            parts.append(body_text)
        text = "\n".join(parts)
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


async def _apply_reflection_text(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal: str,
    identity: dict[str, Any],
) -> None:
    """Put a proposal in the editable portrait unless it is unsafe or unchanged."""
    profile = await _style_row(db, org_id, user_id, create=True)
    assert profile is not None
    _, body = split_identity(proposal or "")
    cleaned = scrub(body)
    if cleaned.quarantined:
        return
    body_lines = cleaned.text.strip().splitlines()
    header = "About this professor:"
    if body_lines and body_lines[0].strip().lower() == header.lower():
        body_lines = body_lines[1:]
    body_text = "\n".join(body_lines).strip()
    text = "\n".join([header, *identity_lines(identity), body_text]) if body_text else ""
    current = (profile.about_md or "").strip()
    if not text or text == current:
        return
    history = list(profile.about_history or [])
    if current:
        history.append(
            {"version": len(history) + 1, "text": profile.about_md, "source": "reflection-auto"}
        )
    profile.about_history = history[-20:]
    profile.about_md = text
    set_about(profile.about_md)


async def _apply_reflection(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    proposal: str,
    *,
    identity: dict[str, Any] | None = None,
    row: Reflection | None = None,
) -> Reflection:
    """Auto-apply one proposal and keep the reflection row for history."""
    identity = identity or await professor_identity(db, org_id, user_id)
    await _apply_reflection_text(db, org_id, user_id, proposal, identity)
    if row is None:
        row = Reflection(
            organization_id=org_id,
            owner_user_id=user_id,
            proposal=proposal or "",
            status="applied",
        )
        db.add(row)
    else:
        row.status = "applied"
    await db.flush()
    return row


def _criteria_text(criteria: list[dict[str, Any]] | None) -> str:
    """Readable criteria, including the level wording the professor kept."""
    lines: list[str] = []
    for item in criteria or []:
        levels = item.get("levels") or {}
        described = "; ".join(
            f"{str(key).strip()}: {str(value).strip()}"
            for key, value in levels.items()
            if str(value).strip()
        )
        name = str(item.get("name") or "").strip()
        weight = item.get("weight", "")
        line = f"{name} ({weight}%): {described}".strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _deck_text(slides: list[dict[str, Any]] | None) -> str:
    """Full deck content: title, bullets, and speaker notes."""
    blocks: list[str] = []
    for slide in slides or []:
        if not isinstance(slide, dict):
            continue
        title = str(slide.get("title") or "").strip()
        bullets = [
            str(bullet).strip() for bullet in slide.get("bullets") or [] if str(bullet).strip()
        ]
        notes = str(slide.get("speaker_notes") or "").strip()
        parts = [title]
        if bullets:
            parts.append("Bullets: " + " | ".join(bullets))
        if notes:
            parts.append("Notes: " + notes)
        block = "\n".join(part for part in parts if part)
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


async def _stored_criteria(
    db: AsyncSession, org_id: uuid.UUID, assessment_id: uuid.UUID
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(RubricCriterion)
        .where(
            RubricCriterion.organization_id == org_id,
            RubricCriterion.assessment_id == assessment_id,
        )
        .order_by(RubricCriterion.ordinal)
    )
    return [
        {"name": item.name, "weight": item.weight, "levels": item.levels or {}}
        for item in result.scalars().all()
    ]


async def remember_movement(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    before: str,
    after: str,
    source: str,
) -> list[dict[str, str]]:
    """Deterministic memory update. No model call, so edits stay cheap."""
    if org_id is None or user_id is None:
        return []
    lessons = extract_lessons(kind, before, after)
    for lesson in lessons:
        await remember(
            db,
            org_id,
            user_id,
            lesson["text"],
            kind=lesson["kind"],
            source=source,
        )
    await refresh_about(db, org_id, user_id, source)
    return lessons


async def maybe_propose_reflection(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, source: str
) -> Reflection | None:
    """Auto-apply at most one reflection after REFLECT_EVERY new memories."""
    if org_id is None or user_id is None:
        return None
    try:
        memories = (
            (
                await db.execute(
                    select(ProfessorMemory).where(
                        ProfessorMemory.organization_id == org_id,
                        ProfessorMemory.owner_user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        reflections = (
            (
                await db.execute(
                    select(Reflection).where(
                        Reflection.organization_id == org_id,
                        Reflection.owner_user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        latest = max(
            (row.created_at for row in reflections if getattr(row, "created_at", None) is not None),
            default=None,
        )
        fresh = [
            row
            for row in memories
            if latest is None
            or (getattr(row, "created_at", None) is not None and row.created_at > latest)
        ]
        if len(fresh) < REFLECT_EVERY:
            return None
        identity = await professor_identity(db, org_id, user_id)
        profile = await _style_row(db, org_id, user_id, create=False)
        voice = (profile.soul_md if profile else "") or DEFAULT_SOUL
        seed_lines = [f"New lessons since the last reflection ({source or 'edits'}):"]
        seed_lines.extend(f"- {row.text}" for row in fresh[-8:])
        seed_lines.extend(identity_lines(identity))
        if voice.strip():
            seed_lines.append("Current voice:\n" + voice.strip()[:900])
        proposal = (
            agents.run_reflection("\n".join(seed_lines), professor={**identity, "voice": voice})
            or ""
        )
        if any(same_lesson(row.proposal, proposal) for row in reflections):
            return None
        return await _apply_reflection(db, org_id, user_id, proposal, identity=identity)
    except Exception:
        logger.info("Reflection proposal skipped; the underlying save stands")
        return None


async def reflect_on_change(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    before: str,
    after: str,
    source: str,
    *,
    propose: bool = True,
) -> None:
    """Compare her final version with the draft, then update her private memory.

    ``propose=False`` keeps the deterministic memory update but skips the model.
    """
    try:
        lessons = await remember_movement(db, org_id, user_id, kind, before, after, source)
    except Exception:
        logger.info("Movement not captured; the underlying save stands")
        return
    if not propose or not lessons:
        return
    try:
        seed = "Lessons from her latest edit:\n" + "\n".join(item["text"] for item in lessons)
        proposal = agents.run_reflection(seed) or ""
        existing_rows = (
            await db.execute(
                select(Reflection).where(
                    Reflection.organization_id == org_id,
                    Reflection.owner_user_id == user_id,
                )
            )
        ).scalars()
        for existing in existing_rows:
            if same_lesson(existing.proposal, proposal) or any(
                lesson["text"][:80] in existing.proposal for lesson in lessons
            ):
                return
        await _apply_reflection(db, org_id, user_id, proposal)
    except Exception:
        logger.info("Reflection proposal skipped; the underlying save stands")


async def capture_movement(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    kind: str,
    before: str,
    after: str,
    source: str,
) -> None:
    """Remember the edit now, and let the portrait reflect once five pile up."""
    if org_id is None or user_id is None:
        return
    try:
        await remember_movement(db, org_id, user_id, kind, before, after, source)
        await maybe_propose_reflection(db, org_id, user_id, source)
    except Exception:
        logger.info("Movement not captured; the underlying save stands")


async def get_style(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    profile = await _style_row(db, org_id, user_id, create=False)
    owner = await db.get(User, user_id)
    identity = await professor_identity(db, org_id, user_id)
    soul = profile.soul_md if profile and profile.soul_md else DEFAULT_SOUL
    about = profile.about_md if profile and profile.about_md else ""
    if not about:
        memories = await list_memories(db, org_id, user_id)
        about = condense_about(soul, memories, identity["courses"], identity)
    return {
        "soul_md": soul,
        "about_md": about,
        "about_history": list(profile.about_history or []) if profile else [],
        "owner_name": owner.full_name if owner and owner.full_name else "",
        "owner_role": identity["role"],
        "courses": identity["courses"],
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
    try:
        await remember(
            db,
            org_id,
            user_id,
            "Voice: " + (soul_md or "")[:2000],
            kind="soul",
            source="soul.md",
        )
    except Exception:
        logger.info("Voice not remembered; the style save stands")
    await reflect_on_change(db, org_id, user_id, "style", before, soul_md, "soul.md")
    return await get_style(db, org_id, user_id)


async def save_about(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, about_md: str
) -> dict[str, Any]:
    profile = await _style_row(db, org_id, user_id, create=True)
    assert profile is not None
    identity = await professor_identity(db, org_id, user_id)
    _, body = split_identity(about_md or "")
    cleaned = scrub(body)
    if cleaned.quarantined:
        raise ProfassistError(
            400, "That note still looks like it names a person. Remove the name and save again."
        )
    header = "About this professor:"
    body_lines = cleaned.text.strip().splitlines()
    if body_lines and body_lines[0].strip().lower() == header.lower():
        body_lines = body_lines[1:]
    text = "\n".join([header, *identity_lines(identity), *body_lines])
    if text == (profile.about_md or "").strip():
        return await get_style(db, org_id, user_id)
    history = list(profile.about_history or [])
    if (profile.about_md or "").strip():
        history.append({"version": len(history) + 1, "text": profile.about_md, "source": "edit"})
    profile.about_history = history[-20:]
    profile.about_md = text
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
    identity = await professor_identity(db, org_id, user_id)
    profile = await _style_row(db, org_id, user_id, create=False)
    voice = (profile.soul_md if profile else "") or DEFAULT_SOUL
    professor = {**identity, "voice": voice}
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
    who = identity["name"] or "this professor"
    if identity["role"]:
        who = f"{who} — {identity['role']}"
    seed_lines = [f"Professor: {who}"]
    if identity["courses"]:
        seed_lines.append("Teaches: " + ", ".join(identity["courses"]))
    if voice.strip():
        seed_lines.append("Current voice:\n" + voice.strip()[:900])
    current = (profile.about_md if profile else "") or voice
    if current.strip():
        seed_lines.append("Current portrait:\n" + current.strip()[:900])
    if changes:
        seed_lines.append("Open grade-level changes: " + "; ".join(changes))
        seed_lines.append(
            "Rewrite the 'About this professor' portrait in under 120 words from these facts "
            "and the current portrait. Do not invent students, credentials, or titles. "
            "Return only the portrait."
        )
    else:
        seed_lines.append(
            "No grade-level changes are stored yet. Rewrite the 'About this professor' portrait "
            "in under 120 words from these facts and the current portrait. Do not invent a change, "
            "a student, a credential, or a title. Return only the portrait."
        )
    seed = "\n".join(seed_lines)
    text = agents.run_reflection(seed, professor=professor) or ""
    row = await _apply_reflection(db, org_id, user_id, text, identity=identity)
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
    if row.status == "applied":
        return {"id": str(row.id), "proposal": row.proposal, "status": row.status}
    await _apply_reflection(db, org_id, user_id, row.proposal or "", row=row)
    return {"id": str(row.id), "proposal": row.proposal, "status": row.status}


def calibrator_page() -> dict[str, Any]:
    return stubs.grade_calibrator()


def _grade_number(levels: dict[str, str]) -> float:
    scale = {"beginning": 50, "developing": 65, "proficient": 80, "advanced": 95}
    scores = [scale[value] for value in levels.values() if value in scale]
    if not scores:
        return 0
    return round(sum(scores) / len(scores), 1)


async def build_cited_deck(
    db: AsyncSession,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    week: int = 0,
    instructions: str = "",
) -> dict[str, Any]:
    """Slide-studio skill: multi-hop retrieval, citations, gaps, then pptx."""
    from app.profassist.skills.slide_studio import run_slide_studio

    await load_runtime(db, org_id, user_id)
    council_roles = await load_council_roles(db, org_id, "material")
    course = await _course(db, org_id, course_id)
    outline_row = await load_outline(db, org_id, user_id, course.id)
    outline = trim_outline(outline_row) if outline_row is not None else {}
    dossier = await dossier_ai_context(db, org_id, user_id, course.id, budget=6000)
    objectives = [
        row["text"]
        for row in await list_objectives(db, org_id, course.id, user_id)
        if row["status"] == "approved"
    ]
    title = f"{course.code} cited deck"
    if week:
        outline_week = next(
            (item for item in outline.get("weeks") or [] if int(item.get("week") or 0) == week),
            None,
        )
        if outline_week is not None:
            codes = set(outline_week.get("lo_codes") or [])
            wanted = [
                item.get("text")
                for item in outline.get("clos") or []
                if item.get("code") in codes and item.get("text")
            ]
            if wanted:
                objectives = wanted
            title = f"Week {week}: {outline_week.get('topic') or course.code}"[:255]
        else:
            from app.profassist.design import get_design

            design = await get_design(db, org_id, course.id, user_id)
            match = next(
                (item for item in design.get("weeks") or [] if int(item.get("week") or 0) == week),
                None,
            )
            if match:
                codes = set(match.get("clos") or [])
                wanted = [
                    item.get("text")
                    for item in design.get("clos") or []
                    if item.get("code") in codes and item.get("text")
                ]
                if wanted:
                    objectives = wanted
                title = f"Week {week}: {match.get('topic') or course.code}"[:255]
    used_outline_clos = False
    if not objectives:
        objectives = [
            str(item.get("text"))
            for item in outline.get("clos") or []
            if isinstance(item, dict) and item.get("text")
        ]
        used_outline_clos = bool(objectives)
    if not objectives and isinstance(dossier, dict):
        outcomes = dossier.get("outcomes")
        clos = outcomes.get("clos") if isinstance(outcomes, dict) else None
        objectives = [
            str(item.get("text"))
            for item in clos or []
            if isinstance(item, dict) and item.get("text")
        ]
    if not objectives:
        raise ProfassistError(400, "Approve an objective before building a cited deck.")
    chunks = [
        {
            "id": item["id"],
            "text": item["text"],
            "filename": item.get("filename") or "note",
            "section": "note",
        }
        for item in await ready_chunks(db, org_id, user_id, course.id)
    ]
    if not chunks:
        raise ProfassistError(400, "Upload a course note before building a cited deck.")
    note = (instructions or course.ai_instructions or "").strip()
    if instructions:
        course.ai_instructions = note
    deck_note = note
    if used_outline_clos:
        deck_note = f"{note}\n\nDrafted from the official outline CLOs.".strip()
    preferences = await slide_preferences(db, org_id, user_id, f"{course.code} {title} {deck_note}")
    profile = await _style_row(db, org_id, user_id, create=False)
    template = read_bytes(profile.template_key) if profile and profile.template_key else None
    built = run_slide_studio(
        objectives,
        chunks,
        template=template,
        title=title,
        instructions=deck_note,
        outline=outline,
        dossier=dossier,
        preferences=preferences,
    )
    deck = SlideDeck(
        organization_id=org_id,
        course_id=course.id,
        owner_user_id=user_id,
        title=title,
        week=week,
        instructions=deck_note,
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
    payload["preferences"] = preferences
    try:
        review = agents.run_slide_review(
            _review_deck_payload(deck, built["gaps"]),
            outline=outline,
            dossier=dossier,
            preferences=preferences,
            chunks=chunks,
            council_roles=council_roles,
        )
    except Exception:
        logger.info("Deck review failed; the cited deck stands")
        review = {}
    if review:
        _store_review(deck, review)
        await db.flush()
    payload["review"] = review
    payload["review_trace_url"] = deck.review_trace_url or ""
    payload["trace_url"] = built.get("trace_url") or ""
    return payload


def _review_deck_payload(row: SlideDeck, gaps: list[str] | None = None) -> dict[str, Any]:
    """The deck as the reviewer sees it. No storage key and no owner id."""
    return {
        "title": row.title or "",
        "week": row.week,
        "instructions": row.instructions or "",
        "slides": list(row.slides or []),
        "gaps": list(gaps or []),
    }


def _store_review(row: SlideDeck, review: dict[str, Any]) -> None:
    row.review = dict(review)
    row.review_trace_url = str(review.get("trace_url") or "")


async def review_deck(db: AsyncSession, org: Any, user: Any, deck_id: uuid.UUID) -> dict[str, Any]:
    """Owner-scoped review of a stored deck. It advises; it does not rewrite."""
    from app.profassist.course_context import load_outline, trim_outline
    from app.profassist.course_memory.service import dossier_ai_context
    from app.profassist.slide_memory import slide_preferences

    deck = await _owned(db, SlideDeck, org.id, deck_id, user.id)
    await load_runtime(db, org.id, user.id)
    council_roles = await load_council_roles(db, org.id, "material")
    outline_row = await load_outline(db, org.id, user.id, deck.course_id)
    outline = trim_outline(outline_row) if outline_row is not None else {}
    dossier = await dossier_ai_context(db, org.id, user.id, deck.course_id, budget=6000)
    query = f"{deck.title or ''} {deck.instructions or ''}".strip()
    preferences = await slide_preferences(db, org.id, user.id, query)
    chunks = [
        {
            "id": item["id"],
            "text": item["text"],
            "filename": item.get("filename") or "note",
            "section": "note",
        }
        for item in await ready_chunks(db, org.id, user.id, deck.course_id)
    ]
    review = agents.run_slide_review(
        _review_deck_payload(deck),
        outline=outline,
        dossier=dossier,
        preferences=preferences,
        chunks=chunks,
        council_roles=council_roles,
    )
    _store_review(deck, review)
    await db.flush()
    return {"review": review, "trace_url": review.get("trace_url") or ""}
