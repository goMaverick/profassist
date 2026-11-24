"""One prompt to a finishable assignment brief and rubric.

A draft stays a draft until the professor finishes it. The eleven report
sections come from the template, never from the model. A question changes
nothing; an approved rubric is locked.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DBSession
from app.profassist.assignment_council import run_assignment_council
from app.profassist.assignment_data import (
    CLASS_DETAILS,
    REPORT_SECTIONS,
    empty_document,
    fixed_report_sections,
)
from app.profassist.assignment_doc import render_docx, render_pdf
from app.profassist.council_config import load_council_roles
from app.profassist.course_context import course_ai_context
from app.profassist.deps import ProfOrg
from app.profassist.errors import ProfassistError
from app.profassist.groupwork import _assignment_public
from app.profassist.models import Assessment, Course, GroupAssignment, RubricCriterion
from app.profassist.observe import step_trace_url
from app.profassist.pii import scrub
from app.profassist.service import capture_movement
from app.profassist.settings_admin import load_runtime
from app.profassist.slide_memory import artifact_preferences

logger = logging.getLogger(__name__)

router = APIRouter()

CLASS_KEYS: tuple[str, ...] = tuple(key for _label, key in CLASS_DETAILS)
LEVELS: tuple[str, ...] = ("beginning", "developing", "proficient", "advanced")
RUBRIC_TOTAL = 100

MEDIA = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class AssistCreateBody(BaseModel):
    course_id: uuid.UUID
    message: str = ""
    mode: Literal["create"] = "create"


class AssistRefineBody(BaseModel):
    message: str = ""
    mode: Literal["refine"] = "refine"


class ManualAssignmentBody(BaseModel):
    """A manual save. Omitted fields are left alone; an omitted document is kept."""

    document: dict[str, Any] | None = None
    title: str | None = None
    weight: int | None = None
    due: str | None = None


def _assignment_text(document: dict[str, Any] | None) -> str:
    """Readable brief text for memory, without a schema change."""
    payload = document or {}
    parts = [
        f"{key}: {value}"
        for key, value in (payload.get("class_details") or {}).items()
        if _text(value)
    ]
    parts.extend(_text(item) for item in payload.get("overview") or [] if _text(item))
    for key in ("problem_choices", "deliverables", "report_sections"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                fields = ", ".join(
                    f"{name}: {_text(value)}" for name, value in item.items() if _text(value)
                )
                if fields:
                    parts.append(fields)
    return "\n".join(parts)


def _rubric_text(rubric: list[dict[str, Any]] | None) -> str:
    lines: list[str] = []
    for criterion in rubric or []:
        levels = criterion.get("levels") or {}
        described = "; ".join(
            f"{level}: {_text(value)}" for level, value in levels.items() if _text(value)
        )
        line = f"{_text(criterion.get('name'))} ({criterion.get('weight', 0)}%): {described}"
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def _assignment_meta(row: GroupAssignment) -> str:
    return f"{_text(row.title)}\n{int(row.weight or 0)}\n{_text(row.due)}"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _weight(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    digits = re.findall(r"\d+", str(value))
    return int(digits[0]) if digits else default


def _course_payload(course: Course) -> dict[str, str]:
    return {
        "id": str(course.id),
        "code": course.code,
        "title": course.title,
        "term": course.term,
    }


def _outcomes(course: Course) -> list[str]:
    return [text for text in (_text(item) for item in course.clos or []) if text]


async def _owned_course(db: DBSession, org_id: uuid.UUID, course_id: uuid.UUID) -> Course:
    course = await db.get(Course, course_id)
    if course is None or course.organization_id != org_id:
        raise ProfassistError(404, "That course is not in this university.")
    return course


async def _owned_assignment(
    db: DBSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> GroupAssignment:
    row = await db.get(GroupAssignment, assignment_id)
    if row is None or row.organization_id != org_id or row.owner_user_id != user_id:
        raise ProfassistError(404, "That assignment is not in your workspace.")
    return row


def _stored_document(row: GroupAssignment) -> dict[str, Any]:
    """The document as saved. Missing sections stay missing so finish can block.

    Extra keys the professor saved are kept: the renderer ignores what it does
    not know, so they are harmless here and losing them would be surprising.
    """
    raw = dict(getattr(row, "document", None) or {})
    document = dict(raw)
    details = raw.get("class_details")
    document["class_details"] = dict(details) if isinstance(details, dict) else {}
    document["overview"] = [
        text for text in (_text(item) for item in raw.get("overview") or []) if text
    ]
    document["problem_choices"] = [
        item for item in raw.get("problem_choices") or [] if isinstance(item, dict)
    ]
    document["deliverables"] = [
        item for item in raw.get("deliverables") or [] if isinstance(item, dict)
    ]
    document["report_sections"] = [
        item for item in raw.get("report_sections") or [] if isinstance(item, dict)
    ]
    return document


def _clean_strings(value: Any) -> list[str] | None:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None
    return [text for text in (_text(item) for item in value) if text]


def _clean_problems(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, list):
        return None
    result: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            problem = _text(item.get("problem") or item.get("title"))
            description = _text(item.get("description") or item.get("detail"))
        else:
            problem, description = _text(item), ""
        if problem:
            result.append({"problem": problem, "description": description})
    return result


def _clean_deliverables(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, list):
        return None
    result: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            title = _text(item.get("title") or item.get("name"))
            description = _text(item.get("description") or item.get("detail"))
        else:
            title, description = _text(item), ""
        if title:
            result.append({"title": title, "description": description})
    return result


def _clean_class_details(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {key: _text(value.get(key)) for key in CLASS_KEYS if key in value}


def _normalised_sections(document: dict[str, Any]) -> list[dict[str, str]]:
    """Always the eleven template sections; only the guidelines may come from a draft."""
    stored = [item for item in document.get("report_sections") or [] if isinstance(item, dict)]
    by_number = {_text(item.get("number")): item for item in stored if _text(item.get("number"))}
    sections: list[dict[str, str]] = []
    for index, template in enumerate(REPORT_SECTIONS):
        existing = by_number.get(template["number"])
        if existing is None and index < len(stored):
            existing = stored[index]
        guidelines = _text((existing or {}).get("guidelines")) or template["guidelines"]
        sections.append(
            {
                "number": template["number"],
                "section": template["section"],
                "guidelines": guidelines,
            }
        )
    return sections


def _apply_guidelines(sections: list[dict[str, str]], value: Any) -> None:
    if not isinstance(value, list):
        return
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        number = _text(item.get("number"))
        guidelines = _text(item.get("guidelines") or item.get("text") or item.get("description"))
        if not guidelines:
            continue
        target = (
            next((row for row in sections if row["number"] == number), None) if number else None
        )
        if target is None and index < len(sections):
            target = sections[index]
        if target is not None:
            target["guidelines"] = guidelines


def _normalise_document(document: dict[str, Any]) -> dict[str, Any]:
    details = dict(document.get("class_details") or {})
    for key in CLASS_KEYS:
        details.setdefault(key, "")
    normalised = dict(document)
    normalised["class_details"] = details
    normalised["overview"] = [
        text for text in (_text(item) for item in document.get("overview") or []) if text
    ]
    normalised["problem_choices"] = [
        _dict_item(item) for item in document.get("problem_choices") or [] if isinstance(item, dict)
    ]
    normalised["deliverables"] = [
        _dict_item(item) for item in document.get("deliverables") or [] if isinstance(item, dict)
    ]
    normalised["report_sections"] = _normalised_sections(document)
    return normalised


def _dict_item(item: dict[str, Any]) -> dict[str, str]:
    return {str(key): _text(value) for key, value in item.items()}


def _apply_document(current: dict[str, Any], delta: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Merge only recognised fields. Section numbers and titles stay on the template."""
    before = _normalise_document(current)
    document = _normalise_document(current)
    changed = False

    if "class_details" in delta:
        details = _clean_class_details(delta.get("class_details"))
        if details and details != document["class_details"]:
            document["class_details"].update(details)
            changed = True
    if "overview" in delta:
        overview = _clean_strings(delta.get("overview"))
        if overview is not None and overview != document["overview"]:
            document["overview"] = overview
            changed = True
    if "problem_choices" in delta:
        problems = _clean_problems(delta.get("problem_choices"))
        if problems is not None and problems != document["problem_choices"]:
            document["problem_choices"] = problems
            changed = True
    if "deliverables" in delta:
        deliverables = _clean_deliverables(delta.get("deliverables"))
        if deliverables is not None and deliverables != document["deliverables"]:
            document["deliverables"] = deliverables
            changed = True
    if "report_sections" in delta:
        sections = _normalised_sections(document)
        _apply_guidelines(sections, delta.get("report_sections"))
        if sections != document["report_sections"]:
            document["report_sections"] = sections
            changed = True

    return document, changed or document != before


def _clean_rubric(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("rubric") or value.get("criteria") or value.get("rows") or []
    if not isinstance(value, list):
        return []
    rubric: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name") or item.get("criterion") or item.get("title"))
        if not name:
            continue
        raw_levels = item.get("levels")
        levels: dict[str, str] = {}
        if isinstance(raw_levels, dict):
            levels = {
                level: _text(raw_levels.get(level))
                for level in LEVELS
                if _text(raw_levels.get(level))
            }
        else:
            levels = {level: _text(item.get(level)) for level in LEVELS if _text(item.get(level))}
        rubric.append(
            {
                "name": name[:255],
                "weight": _weight(item.get("weight"), 0),
                "levels": levels,
            }
        )
    return rubric


def _validate_rubric(rubric: list[dict[str, Any]]) -> None:
    if not rubric:
        raise ProfassistError(400, "The rubric needs at least one criterion.")
    total = sum(int(criterion.get("weight") or 0) for criterion in rubric)
    if total != RUBRIC_TOTAL:
        raise ProfassistError(400, f"Rubric weights must total {RUBRIC_TOTAL}, not {total}.")


async def _criteria(
    db: DBSession, org_id: uuid.UUID, assessment_id: uuid.UUID | None
) -> list[dict[str, Any]]:
    if assessment_id is None:
        return []
    result = await db.execute(
        select(RubricCriterion)
        .where(
            RubricCriterion.organization_id == org_id,
            RubricCriterion.assessment_id == assessment_id,
        )
        .order_by(RubricCriterion.ordinal)
    )
    return [
        {
            "name": criterion.name,
            "weight": int(criterion.weight or 0),
            "levels": dict(criterion.levels or {}),
        }
        for criterion in result.scalars().all()
    ]


async def _replace_rubric(
    db: DBSession, org_id: uuid.UUID, assessment_id: uuid.UUID, rubric: list[dict[str, Any]]
) -> None:
    await db.execute(delete(RubricCriterion).where(RubricCriterion.assessment_id == assessment_id))
    for ordinal, criterion in enumerate(rubric, start=1):
        db.add(
            RubricCriterion(
                organization_id=org_id,
                assessment_id=assessment_id,
                ordinal=ordinal,
                name=criterion["name"],
                weight=int(criterion["weight"]),
                levels=criterion.get("levels") or {},
            )
        )
    await db.flush()


def _brief_text(document: dict[str, Any], course: Course) -> str:
    details = document.get("class_details") or {}
    parts = [
        _text(details.get("assessment")) or "Assessment",
        f"{course.code} {course.title}",
        f"Weight {_text(details.get('weight')) or '0%'}.",
    ]
    parts.extend(_text(item) for item in document.get("overview") or [])
    for item in document.get("deliverables") or []:
        if isinstance(item, dict):
            title = _text(item.get("title"))
            description = _text(item.get("description"))
            if title:
                parts.append(f"Deliverable {title}: {description}")
    parts.append(
        "The report has eleven sections: "
        + "; ".join(
            f"{item['number']} {item['section']}" for item in _normalised_sections(document)
        )
        + "."
    )
    parts.append(f"Rubric weights must total {RUBRIC_TOTAL}.")
    return "\n".join(part for part in parts if part)


DOCUMENT_ALIASES: dict[str, str] = {
    "brief": "overview",
    "introduction": "overview",
    "summary": "overview",
    "description": "overview",
    "problems": "problem_choices",
    "scenarios": "problem_choices",
    "tasks": "problem_choices",
    "outputs": "deliverables",
    "details": "class_details",
    "course_details": "class_details",
}

CORRECTIVE_DOCUMENT_PROMPT = (
    "Return the document object with non-empty overview, problem_choices, and deliverables."
)


def _map_aliases(document: dict[str, Any]) -> dict[str, Any]:
    """Map the model's field aliases while keeping unknown keys and any canonical value."""
    mapped = dict(document)
    for alias, canonical in DOCUMENT_ALIASES.items():
        if alias not in document:
            continue
        value = document.get(alias)
        if mapped.get(canonical) in (None, "", [], {}):
            if canonical == "overview" and isinstance(value, str):
                mapped[canonical] = [value]
            else:
                mapped[canonical] = value
        mapped.pop(alias, None)
    return mapped


def _model_document(drafted: dict[str, Any]) -> dict[str, Any]:
    for key in ("document", "assignment", "sections"):
        value = drafted.get(key)
        if isinstance(value, dict):
            return _map_aliases(value)
    return _map_aliases(drafted)


def _is_hollow_document(document: dict[str, Any]) -> bool:
    return not any(document.get(key) for key in ("overview", "problem_choices", "deliverables"))


def _corrective_payload(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = _text(payload.get("prompt"))
    suffix = f" {CORRECTIVE_DOCUMENT_PROMPT}" if prompt else CORRECTIVE_DOCUMENT_PROMPT
    return {**payload, "prompt": f"{prompt}{suffix}".strip()}


def _reply(drafted: dict[str, Any], fallback: str) -> str:
    return _text(drafted.get("reply")) or fallback


async def _ensure_assessment(
    db: DBSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    row: GroupAssignment,
    document: dict[str, Any],
    outcomes: list[str],
) -> Assessment:
    if row.assessment_id is not None:
        assessment = await db.get(Assessment, row.assessment_id)
        if assessment is not None:
            return assessment
    assessment = Assessment(
        organization_id=org_id,
        course_id=row.course_id,
        owner_user_id=user_id,
        title=row.title,
        brief=_brief_text(document, await _owned_course(db, org_id, row.course_id)),
        clos=outcomes,
        status="draft",
        external_id=f"assignment:{row.number}",
        weight=int(row.weight or 0),
        kind="group" if row.group_mode == "group" else "assignment",
    )
    db.add(assessment)
    await db.flush()
    row.assessment_id = assessment.id
    return assessment


def _sync_details(
    row: GroupAssignment, document: dict[str, Any], course: Course, *, details_changed: bool
) -> None:
    """Keep the row in step with the document, without reverting a manual edit.

    Title, weight, and due change only when the request touched class details.
    A refine that changes the overview must not put back a weight the professor
    has since edited on the assignment page.
    """
    details = document.get("class_details") or {}
    if details_changed:
        title = _text(details.get("assessment"))
        if title:
            row.title = title[:255]
        weight = _weight(details.get("weight"), 0)
        if weight:
            row.weight = weight
        due = _text(details.get("report_due"))
        if due and not _text(row.due):
            row.due = due[:64]
    if not _text(details.get("course")):
        details["course"] = f"{course.code} {course.title}"
    if not _text(details.get("weight")) and row.weight:
        details["weight"] = f"{row.weight}%"


EXPECTED_SECTIONS: dict[str, dict[str, str]] = {
    template["number"]: template for template in REPORT_SECTIONS
}


def _manual_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProfassistError(400, f"{label} must be a list.")
    return value


def _manual_overview(value: Any) -> list[str]:
    items = _manual_list(value, "overview")
    if any(not isinstance(item, str) for item in items):
        raise ProfassistError(400, "overview must be a list of text.")
    return list(items)


def _manual_problems(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _manual_list(value, "problem_choices"):
        if not isinstance(item, dict):
            raise ProfassistError(400, "Every problem choice must be an object.")
        problem = item.get("problem")
        description = item.get("description")
        if not isinstance(problem, str) or not isinstance(description, str):
            raise ProfassistError(400, "Every problem choice needs a problem and a description.")
        result.append({**item, "problem": problem, "description": description})
    return result


def _manual_deliverables(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _manual_list(value, "deliverables"):
        if not isinstance(item, dict):
            raise ProfassistError(400, "Every deliverable must be an object.")
        title = item.get("title")
        description = item.get("description")
        if not isinstance(title, str) or not isinstance(description, str):
            raise ProfassistError(400, "Every deliverable needs a title and a description.")
        result.append({**item, "title": title, "description": description})
    return result


def _manual_sections(value: Any) -> list[dict[str, Any]]:
    """Exactly the eleven fixed numbers, once each, in template order."""
    items = _manual_list(value, "report_sections")
    if len(items) != len(REPORT_SECTIONS):
        raise ProfassistError(400, "The report needs all eleven sections.")
    expected = [template["number"] for template in REPORT_SECTIONS]
    rows: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ProfassistError(400, "Every report section must be an object.")
        number = _text(item.get("number"))
        if number not in EXPECTED_SECTIONS:
            raise ProfassistError(400, "The report sections must be numbered 1 to 11.")
        if number in rows:
            raise ProfassistError(400, f"Report section {number} appears twice.")
        guidelines = item.get("guidelines", "")
        if not isinstance(guidelines, str):
            raise ProfassistError(400, "Section guidelines must be text.")
        title = _text(item.get("section")) or EXPECTED_SECTIONS[number]["section"]
        rows[number] = {**item, "number": number, "section": title, "guidelines": guidelines}
    for number in expected:
        if number not in rows:
            raise ProfassistError(400, f"The report is missing section {number}.")
    return [rows[number] for number in expected]


def _manual_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfassistError(400, "The document must be an object.")
    for key in ("class_details", "overview", "problem_choices", "deliverables", "report_sections"):
        if key not in value:
            raise ProfassistError(400, f"The document is missing {key}.")
    if not isinstance(value["class_details"], dict):
        raise ProfassistError(400, "class_details must be an object.")
    document = dict(value)
    document["class_details"] = dict(value["class_details"])
    document["overview"] = _manual_overview(value["overview"])
    document["problem_choices"] = _manual_problems(value["problem_choices"])
    document["deliverables"] = _manual_deliverables(value["deliverables"])
    document["report_sections"] = _manual_sections(value["report_sections"])
    return document


def _temp_number() -> str:
    return f"NEW-{uuid.uuid4().hex[:6].upper()}"


@router.post("/assignments/assist")
async def create_assignment(
    body: AssistCreateBody, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    """Draft a whole brief and rubric from one prompt. There is no template fallback."""
    from app.profassist.llm import complete

    await load_runtime(db, org.id, user.id)
    council_roles = await load_council_roles(db, org.id, "assignment")
    course = await _owned_course(db, org.id, body.course_id)
    cleaned = scrub(body.message or "")
    if cleaned.quarantined:
        raise ProfassistError(400, "That request still looks like it names a student.")

    row = GroupAssignment(
        organization_id=org.id,
        owner_user_id=user.id,
        course_id=course.id,
        number=_temp_number(),
        title="New assignment",
        body="",
        document={},
        blind=False,
        group_mode="individual",
        status="draft",
    )
    db.add(row)
    await db.flush()

    outcomes = _outcomes(course)
    context = await course_ai_context(db, org.id, user.id, course.id, query=cleaned.text)
    preferences = await artifact_preferences(
        db, org.id, user.id, f"{course.code} {cleaned.text} create"
    )
    payload = {
        "prompt": cleaned.text,
        "course": _course_payload(course),
        "outcomes": outcomes,
        "report_sections": fixed_report_sections(),
        "existing": empty_document(),
        "outline": context["outline"],
        "chunks": context["chunks"],
        "dossier": context.get("dossier") or {},
        "preferences": preferences,
    }
    drafted = complete("assignment_text", payload)
    trace_url = step_trace_url() or ""
    document, _ = _apply_document(empty_document(), _model_document(drafted))
    document = _normalise_document(document)
    if _is_hollow_document(document):
        drafted = complete("assignment_text", _corrective_payload(payload))
        document, _ = _apply_document(empty_document(), _model_document(drafted))
        document = _normalise_document(document)

    rubric = _clean_rubric(
        complete(
            "rubric",
            {
                "brief": _brief_text(document, course),
                "clos": outcomes,
                "existing": [],
                "outline": context["outline"],
                "chunks": context["chunks"],
                "dossier": context.get("dossier") or {},
                "preferences": preferences,
            },
        )
    )
    _validate_rubric(rubric)

    _sync_details(row, document, course, details_changed=True)
    review = run_assignment_council(
        document,
        rubric,
        outcomes,
        context["outline"],
        context.get("dossier") or {},
        council_roles,
    )
    document["review"] = review
    if not row.title:
        row.title = "New assignment"
    row.document = document
    row.lo_codes = outcomes
    await db.flush()

    assessment = await _ensure_assessment(db, org.id, user.id, row, document, outcomes)
    assessment.title = row.title
    assessment.weight = int(row.weight or 0)
    assessment.brief = _brief_text(document, course)
    assessment.clos = outcomes
    await _replace_rubric(db, org.id, assessment.id, rubric)
    await db.flush()
    await capture_movement(
        db, org.id, user.id, "objective", "", _assignment_text(document), "assignment-create"
    )
    await capture_movement(
        db, org.id, user.id, "rubric", "", _rubric_text(rubric), "assignment-create"
    )

    return {
        "reply": _reply(drafted, "Draft ready."),
        "assignment": _assignment_public(row, [], []),
        "document": document,
        "rubric": rubric,
        "review": review,
        "trace_url": trace_url,
    }


@router.post("/assignments/{assignment_id}/assist")
async def refine_assignment(
    assignment_id: uuid.UUID,
    body: AssistRefineBody,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
) -> dict:
    """Apply only the change the model reports. A question leaves the draft alone."""
    from app.profassist.llm import complete

    row = await _owned_assignment(db, org.id, user.id, assignment_id)
    if row.assessment_id is not None:
        assessment = await db.get(Assessment, row.assessment_id)
        if assessment is not None and assessment.status == "approved":
            raise ProfassistError(
                409, "The rubric is approved. Withdraw the approval before you change it."
            )

    await load_runtime(db, org.id, user.id)
    council_roles = await load_council_roles(db, org.id, "assignment")
    course = await _owned_course(db, org.id, row.course_id)
    cleaned = scrub(body.message or "")
    if cleaned.quarantined:
        raise ProfassistError(400, "That request still looks like it names a student.")

    document = _stored_document(row)
    rubric = await _criteria(db, org.id, row.assessment_id)
    before_document_text = _assignment_text(document)
    before_rubric_text = _rubric_text(rubric)
    outcomes = _outcomes(course)
    context = await course_ai_context(db, org.id, user.id, course.id, query=cleaned.text)
    preferences = await artifact_preferences(
        db, org.id, user.id, f"{course.code} {cleaned.text} refine"
    )
    payload = {
        "prompt": cleaned.text,
        "mode": "refine",
        "course": _course_payload(course),
        "outcomes": outcomes,
        "report_sections": fixed_report_sections(),
        "existing": document,
        "rubric": rubric,
        "outline": context["outline"],
        "chunks": context["chunks"],
        "dossier": context.get("dossier") or {},
        "preferences": preferences,
    }
    drafted = complete("assignment_text", payload)
    trace_url = step_trace_url() or ""
    delta = _model_document(drafted)
    updated, changed = _apply_document(document, delta)
    if _is_hollow_document(updated):
        drafted = complete("assignment_text", _corrective_payload(payload))
        delta = _model_document(drafted)
        updated, changed = _apply_document(document, delta)

    new_rubric = rubric
    raw_rubric = drafted.get("rubric")
    rubric_changed = False
    if raw_rubric is not None:
        cleaned_rubric = _clean_rubric(raw_rubric)
        _validate_rubric(cleaned_rubric)
        if cleaned_rubric != rubric:
            new_rubric = cleaned_rubric
            rubric_changed = True

    if not changed and not rubric_changed:
        return {
            "reply": _reply(drafted, "No change was needed."),
            "assignment": _assignment_public(row, [], []),
            "document": document,
            "rubric": rubric,
            "review": document.get("review") or {},
            "changed": False,
            "trace_url": trace_url,
        }

    _sync_details(
        row, updated, course, details_changed=isinstance(delta.get("class_details"), dict)
    )
    review = run_assignment_council(
        updated,
        new_rubric,
        outcomes,
        context["outline"],
        context.get("dossier") or {},
        council_roles,
    )
    updated["review"] = review
    row.document = updated
    row.lo_codes = outcomes
    await db.flush()

    assessment = await _ensure_assessment(db, org.id, user.id, row, updated, outcomes)
    assessment.title = row.title
    assessment.weight = int(row.weight or 0)
    assessment.brief = _brief_text(updated, course)
    assessment.clos = outcomes
    if rubric_changed:
        await _replace_rubric(db, org.id, assessment.id, new_rubric)
    await db.flush()
    if _assignment_text(updated) != before_document_text:
        await capture_movement(
            db,
            org.id,
            user.id,
            "objective",
            before_document_text,
            _assignment_text(updated),
            "assignment-refine",
        )
    if rubric_changed:
        await capture_movement(
            db,
            org.id,
            user.id,
            "rubric",
            before_rubric_text,
            _rubric_text(new_rubric),
            "assignment-refine",
        )

    return {
        "reply": _reply(drafted, "Updated."),
        "assignment": _assignment_public(row, [], []),
        "document": updated,
        "rubric": new_rubric,
        "review": review,
        "changed": True,
        "trace_url": trace_url,
    }


@router.post("/assignments/{assignment_id}/review")
async def review_assignment(
    assignment_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
) -> dict:
    """Ask the assignment council to review the saved draft. No draft is rewritten."""
    row = await _owned_assignment(db, org.id, user.id, assignment_id)
    await load_runtime(db, org.id, user.id)
    council_roles = await load_council_roles(db, org.id, "assignment")
    course = await _owned_course(db, org.id, row.course_id)
    document = _stored_document(row)
    rubric = await _criteria(db, org.id, row.assessment_id)
    outcomes = _outcomes(course)
    context = await course_ai_context(
        db, org.id, user.id, course.id, query=f"{row.title} {row.number} assignment review"
    )
    review = run_assignment_council(
        document,
        rubric,
        outcomes,
        context["outline"],
        context.get("dossier") or {},
        council_roles,
    )
    document["review"] = review
    row.document = document
    await db.flush()
    return {"review": review, "trace_url": review.get("trace_url") or ""}


@router.put("/assignments/{assignment_id}")
async def save_assignment(
    assignment_id: uuid.UUID,
    body: ManualAssignmentBody,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
) -> dict:
    """Save the professor's own edits. The rubric is never changed here."""
    row = await _owned_assignment(db, org.id, user.id, assignment_id)
    before_document = _stored_document(row)
    before_meta = _assignment_meta(row)
    if body.document is not None:
        row.document = _manual_document(body.document)
    if body.title is not None:
        row.title = body.title.strip()[:255]
    if body.weight is not None:
        row.weight = int(body.weight)
    if body.due is not None:
        row.due = body.due.strip()[:64]
    await db.flush()

    document = _stored_document(row)
    if _assignment_text(before_document) != _assignment_text(document):
        await capture_movement(
            db,
            org.id,
            user.id,
            "objective",
            _assignment_text(before_document),
            _assignment_text(document),
            "assignment-edit",
        )
    if _assignment_meta(row) != before_meta:
        await capture_movement(
            db,
            org.id,
            user.id,
            "rubric",
            before_meta,
            _assignment_meta(row),
            "assignment-edit",
        )
    if row.assessment_id is not None:
        assessment = await db.get(Assessment, row.assessment_id)
        if assessment is not None:
            course = await _owned_course(db, org.id, row.course_id)
            assessment.title = row.title
            assessment.weight = int(row.weight or 0)
            assessment.brief = _brief_text(document, course)
            await db.flush()
    return {
        "assignment": _assignment_public(row, [], []),
        "document": document,
        "rubric": await _criteria(db, org.id, row.assessment_id),
    }


@router.post("/assignments/{assignment_id}/finish")
async def finish_assignment(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    """Publish a complete brief. Every gate names what is still missing."""
    row = await _owned_assignment(db, org.id, user.id, assignment_id)
    document = _stored_document(row)
    rubric = await _criteria(db, org.id, row.assessment_id)

    if not _text(row.title) or row.title == "New assignment":
        raise ProfassistError(400, "Name the assessment before you finish it.")
    if int(row.weight or 0) <= 0:
        raise ProfassistError(400, "Set the assessment weight before you finish it.")
    if not _text(row.due):
        raise ProfassistError(400, "Set the due date before you finish it.")
    sections = document.get("report_sections") or []
    if len(sections) != len(REPORT_SECTIONS) or any(
        not _text(item.get("number")) or not _text(item.get("section")) for item in sections
    ):
        raise ProfassistError(400, "The brief needs all eleven report sections.")
    if _is_hollow_document(document):
        raise ProfassistError(
            400, "The brief needs an overview, problem choices, and deliverables."
        )
    _validate_rubric(rubric)

    row.status = "published"
    await db.flush()
    _index_assignment(str(org.id), str(user.id), row, document, rubric)
    return {
        "assignment": _assignment_public(row, [], []),
        "document": document,
        "rubric": rubric,
    }


@router.get("/assignments/{assignment_id}/artifact")
async def assignment_artifact(
    assignment_id: uuid.UUID, user: CurrentUser, org: ProfOrg, db: DBSession
) -> dict:
    row = await _owned_assignment(db, org.id, user.id, assignment_id)
    return {
        "assignment": _assignment_public(row, [], []),
        "document": _stored_document(row),
        "rubric": await _criteria(db, org.id, row.assessment_id),
    }


@router.get("/assignments/{assignment_id}/document")
async def assignment_document(
    assignment_id: uuid.UUID,
    user: CurrentUser,
    org: ProfOrg,
    db: DBSession,
    kind: str = "pdf",
) -> Response:
    """Render the saved document. A draft can be downloaded before it is published."""
    row = await _owned_assignment(db, org.id, user.id, assignment_id)
    document = _stored_document(row)
    if kind == "pdf":
        data = render_pdf(document)
    elif kind == "docx":
        data = render_docx(document)
    else:
        raise ProfassistError(400, "Choose pdf or docx.")
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", _text(row.title) or "assignment").strip("-")
    return Response(
        content=data,
        media_type=MEDIA[kind],
        headers={
            "Content-Disposition": f'attachment; filename="{filename or "assignment"}.{kind}"'
        },
    )


def _index_assignment(
    organization_id: str,
    user_id: str,
    row: GroupAssignment,
    document: dict[str, Any],
    rubric: list[dict[str, Any]],
) -> None:
    """Best-effort vector copy. Postgres remains the source of the assignment."""
    try:
        from app.core.config import settings
        from app.profassist.similarity import hash_embed

        if not settings.QDRANT_HOST:
            return
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        text = "\n".join(
            [
                _text((document.get("class_details") or {}).get("assessment")),
                *[_text(item) for item in document.get("overview") or []],
                *[
                    f"{item.get('name')} {item.get('weight')}%"
                    for item in rubric
                    if isinstance(item, dict)
                ],
            ]
        )
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT or 6333)
        name = "profassist_assignment"
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=64, distance=Distance.COSINE),
            )
        client.upsert(
            collection_name=name,
            points=[
                PointStruct(
                    id=str(row.id),
                    vector=hash_embed(text, 64),
                    payload={
                        "organization_id": organization_id,
                        "owner_user_id": user_id,
                        "assignment_id": str(row.id),
                        "course_id": str(row.course_id),
                        "kind": "assignment",
                        "text": text[:2000],
                    },
                )
            ],
        )
    except Exception:
        logger.info("Assignment vector was not written")
