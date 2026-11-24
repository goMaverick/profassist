"""Per-professor briefing: real facts in, one traced draft out, always an answer.

Every fact is read from this organization and this professor's own rows. The
model may phrase the brief; it may not invent a count, a course, or a student.
If the model is unavailable the deterministic fallback still describes the real
day, and the professor's dashboard never shows an error page for it.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist import agents
from app.profassist.errors import ProfassistError
from app.profassist.models import CourseDossier, Material, Reflection
from app.profassist.service import home
from app.profassist.settings_admin import load_runtime, professor_identity

logger = logging.getLogger(__name__)

MAX_COURSES = 3
HEADLINE_LIMIT = 90
BULLET_LIMIT = 240
BULLET_COUNT = 3
SUMMARY_LIMIT = 600
LIST_LIMIT = 12


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _number(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _names(rows: Any) -> list[str]:
    """Readable names from the dossier lists, deduped and bounded."""
    names: list[str] = []
    for row in rows or []:
        if isinstance(row, dict):
            name = _text(row.get("name"), 120)
        elif isinstance(row, str):
            name = _text(row, 120)
        else:
            name = ""
        if name and name not in names:
            names.append(name)
        if len(names) >= LIST_LIMIT:
            break
    return names


def _conflicts(rows: Any) -> list[str]:
    labels: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        field = _text(row.get("field"), 60)
        winner = _text(row.get("winner"), 80)
        if not field and not winner:
            continue
        label = f"{field or 'A field'}: {winner}" if winner else field
        if label not in labels:
            labels.append(label)
        if len(labels) >= 6:
            break
    return labels


def _greeting(now: datetime | None = None) -> str:
    """The server's local clock. No user timezone is claimed."""
    hour = (now or datetime.now().astimezone()).hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


async def _ready_materials(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> int:
    result = await db.execute(
        select(Material).where(
            Material.organization_id == org_id,
            Material.course_id == course_id,
            Material.owner_user_id == user_id,
            Material.status == "ready",
        )
    )
    rows = list(result.scalars().all())
    return sum(1 for row in rows if not (row.pii_report or {}).get("quarantined"))


async def _ready_dossier(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> CourseDossier | None:
    result = await db.execute(
        select(CourseDossier).where(
            CourseDossier.organization_id == org_id,
            CourseDossier.course_id == course_id,
            CourseDossier.owner_user_id == user_id,
            CourseDossier.status == "ready",
        )
    )
    return result.scalars().first()


async def _reflections(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> tuple[int, str]:
    result = await db.execute(
        select(Reflection)
        .where(
            Reflection.organization_id == org_id,
            Reflection.owner_user_id == user_id,
            Reflection.status == "proposed",
        )
        .order_by(Reflection.created_at.desc())
    )
    rows = list(result.scalars().all())
    latest = _text(rows[0].proposal, 400) if rows else ""
    return len(rows), latest


def _bullets(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    bullets: list[str] = []
    for item in value:
        text = _text(item, BULLET_LIMIT)
        if text:
            bullets.append(text)
        if len(bullets) >= BULLET_COUNT:
            break
    return bullets


ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("/grade", ("grade", "draft", "submission", "approve")),
    ("/assignments", ("assignment", "rubric", "assessment")),
    ("/studio", ("studio", "slide", "deck", "material")),
    ("/outline", ("outline", "clo", "outcome", "course")),
)


def _route_for(text: str) -> str:
    """The page a focus sentence points at, or an empty string when it is unclear."""
    lowered = (text or "").lower()
    for href, words in ROUTES:
        if any(word in lowered for word in words):
            return href
    return ""


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _fallback(counts: dict[str, int], memory: dict[str, int]) -> dict[str, Any]:
    """A deterministic brief built only from the real counts."""
    waiting = counts["waiting_approval"]
    flags = counts["open_flags"]
    submissions = counts["submissions"]
    reflections = counts["open_reflections"]
    materials = counts["ready_materials"]
    topics = memory["topics"]
    assessments = memory["assessments"]

    if waiting:
        headline = f"{waiting} {_plural(waiting, 'grade draft')} in progress"
        focus = "Open the grade queue"
        href = "/grade"
    elif flags:
        headline = f"{flags} integrity {_plural(flags, 'flag')} need a look"
        focus = "Review flagged work"
        href = "/grade"
    elif submissions:
        headline = f"{submissions} {_plural(submissions, 'submission')} in the grading queue"
        focus = "Start grading"
        href = "/grade"
    elif assessments:
        headline = f"{assessments} {_plural(assessments, 'assessment')} mapped in course memory"
        focus = "Review the assessment map"
        href = "/assignments"
    elif reflections:
        headline = f"{reflections} {_plural(reflections, 'reflection')} ready to review"
        focus = "Review your reflection"
        href = "/outline"
    elif topics:
        headline = f"Your course memory has {topics} {_plural(topics, 'topic')}"
        focus = "Continue your outline"
        href = "/outline"
    elif materials:
        headline = f"{materials} course {_plural(materials, 'document')} read and ready"
        focus = "Build from your materials"
        href = "/studio"
    else:
        headline = "Your day is clear \u2014 nothing is waiting"
        focus = "Continue your outline"
        href = "/outline"

    bullets = [
        (
            f"{counts['drafts']} {_plural(counts['drafts'], 'draft')} in the workspace, "
            f"{counts['approved']} approved and {counts['pushed']} pushed."
        ),
        (
            f"{submissions} {_plural(submissions, 'submission')} in the grading queue, "
            f"{flags} open integrity {_plural(flags, 'flag')}."
        ),
        (
            f"{materials} course {_plural(materials, 'document')} read, {topics} "
            f"{_plural(topics, 'topic')} and {assessments} "
            f"{_plural(assessments, 'assessment')} in memory; {reflections} open "
            f"{_plural(reflections, 'reflection')}."
        ),
    ]
    return {
        "headline": _text(headline, HEADLINE_LIMIT),
        "bullets": [_text(item, BULLET_LIMIT) for item in bullets],
        "focus": focus,
        "href": href,
    }


async def build_briefing(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Gather the professor's real facts, draft once, and never raise for the model."""
    await load_runtime(db, org_id, user_id)
    home_data = await home(db, org_id, user_id)
    identity = await professor_identity(db, org_id, user_id)
    courses = list(home_data.get("courses") or [])
    if course_id is not None:
        wanted = str(course_id)
        courses = [row for row in courses if str(row.get("id")) == wanted]
        if not courses:
            raise ProfassistError(404, "Course not found in this workspace")
    selected = courses[:MAX_COURSES]

    course_facts: list[dict[str, Any]] = []
    documents_total = 0
    dossiers_total = 0
    for course in selected:
        current_id = uuid.UUID(str(course["id"]))
        ready = await _ready_materials(db, org_id, user_id, current_id)
        dossier = await _ready_dossier(db, org_id, user_id, current_id)
        documents_total += ready
        if dossier is not None:
            dossiers_total += 1
        course_facts.append(
            {
                "code": _text(course.get("code"), 32),
                "title": _text(course.get("title"), 120),
                "term": _text(course.get("term"), 32),
                "ready_materials": ready,
                "memory_ready": dossier is not None,
            }
        )

    first_course = selected[0] if selected else None
    first_body: dict[str, Any] = {}
    if first_course is not None:
        first_dossier = await _ready_dossier(
            db, org_id, user_id, uuid.UUID(str(first_course["id"]))
        )
        if first_dossier is not None and isinstance(first_dossier.body, dict):
            first_body = first_dossier.body

    memory_summary = _text(first_body.get("summary"), SUMMARY_LIMIT)
    memory_topics = _names(first_body.get("topics"))
    memory_assessments = _names(first_body.get("assessments"))
    memory_conflicts = _conflicts(first_body.get("conflicts"))

    open_reflections, latest_reflection = await _reflections(db, org_id, user_id)
    waiting = max(
        0,
        _number(home_data.get("drafts"))
        - _number(home_data.get("approved"))
        - _number(home_data.get("pushed")),
    )
    counts = {
        "courses": len(courses),
        "courses_listed": len(selected),
        "submissions": _number(home_data.get("submissions")),
        "drafts": _number(home_data.get("drafts")),
        "approved": _number(home_data.get("approved")),
        "pushed": _number(home_data.get("pushed")),
        "open_flags": _number(home_data.get("open_flags")),
        "waiting_approval": waiting,
        "open_reflections": open_reflections,
        "ready_materials": documents_total,
        "ready_dossiers": dossiers_total,
    }
    facts = {
        "professor": {
            "name": _text(identity.get("name"), 120),
            "role": _text(identity.get("role"), 60),
            "courses": [_text(code, 32) for code in identity.get("courses") or [] if code],
        },
        "counts": counts,
        "courses": course_facts,
        "memory": {
            "course": _text((first_course or {}).get("code"), 32),
            "summary": memory_summary,
            "topics": memory_topics,
            "assessments": memory_assessments,
            "conflicts": memory_conflicts,
        },
        "reflection": {"open": open_reflections, "latest": latest_reflection},
        "moodle_mode": _text(home_data.get("moodle_mode"), 32),
    }

    degraded = False
    headline = ""
    bullets: list[str] = []
    focus = ""
    trace_url: str | None = None
    try:
        drafted = agents.run_briefing(facts)
        headline = _text(drafted.get("headline"), HEADLINE_LIMIT)
        bullets = _bullets(drafted.get("bullets"))
        focus = _text(drafted.get("focus"), 160)
        trace_url = drafted.get("trace_url") or None
    except Exception:
        degraded = True
        logger.warning("Briefing model was unavailable; using the deterministic brief")

    fallback = _fallback(
        counts,
        {
            "topics": len(memory_topics),
            "assessments": len(memory_assessments),
        },
    )
    if not headline:
        headline = fallback["headline"]
    if not focus:
        focus = fallback["focus"]
    if len(bullets) < BULLET_COUNT:
        for item in fallback["bullets"]:
            if item not in bullets and len(bullets) < BULLET_COUNT:
                bullets.append(item)
    bullets = bullets[:BULLET_COUNT]

    return {
        "greeting": _greeting(),
        "name": _text(identity.get("name"), 120),
        "headline": _text(headline, HEADLINE_LIMIT),
        "bullets": bullets,
        "focus": focus,
        "focus_href": _route_for(focus) or fallback["href"],
        "trace_url": trace_url if not degraded else None,
        "memory": {
            "documents": documents_total,
            "topics": len(memory_topics),
            "assessments": len(memory_assessments),
            "conflicts": len(memory_conflicts),
        },
        "counts": counts,
        "degraded": degraded,
    }
