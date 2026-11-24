"""The official course outline and ready notes in one bounded shape.

Assignment drafting, the grading council, and slide studio all read the same
course context here. The outline is trimmed to staff-facing sections only:
basics, lecture, description, program, PLOs, CLOs, weeks, readings, outcome
measures, and policies. Student data is never part of an outline body.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.models import Chunk, Course, Material, SubjectOutline
from app.profassist.outline_data import BASICS_FIELDS, LECTURE_FIELDS
from app.profassist.rag import keyword_score

# Bounds. A chunk is one note passage; the model never needs the whole file.
CHUNK_LIMIT = 8
CHUNK_CHARS = 1200
CHUNK_BUDGET = 6000
OUTLINE_BUDGET = 8000
GRADING_OUTLINE_BUDGET = 3500

TEXT_LIMIT = 2000
SHORT_LIMIT = 300
LIST_LIMIT = 20
WEEK_LIMIT = 16
READING_LIMIT = 15


def _text(value: Any, limit: int = TEXT_LIMIT) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:limit]


def _code(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _rows(result: Any) -> list[Any]:
    return list(result.scalars().all())


def _rank_key(row: SubjectOutline) -> tuple[int, str]:
    """Published first, then the most recently touched outline."""
    stamp = row.updated_at or row.created_at
    return (1 if str(row.status or "") == "published" else 0, stamp.isoformat() if stamp else "")


async def load_outline(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> SubjectOutline | None:
    """The professor's latest outline for a course, matched by id or course code."""
    result = await db.execute(
        select(SubjectOutline).where(
            SubjectOutline.organization_id == org_id,
            SubjectOutline.owner_user_id == user_id,
        )
    )
    rows = _rows(result)
    if not rows:
        return None
    course = await db.get(Course, course_id)
    wanted = _code(getattr(course, "code", "")) if course is not None else ""
    matches = []
    for row in rows:
        basics = (row.body or {}).get("basics") or {}
        row_code = _code(basics.get("code") or row.code)
        if row.course_id == course_id or (wanted and row_code == wanted):
            matches.append(row)
    if not matches:
        return None
    matches.sort(key=_rank_key, reverse=True)
    return matches[0]


def _outcomes(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in value or []:
        if isinstance(item, dict):
            code = _text(item.get("code"), 32)
            text = _text(item.get("text") or item.get("outcome"))
        else:
            code, text = "", _text(item)
        if code or text:
            result.append({"code": code, "text": text})
        if len(result) >= LIST_LIMIT:
            break
    return result


def _weeks(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        try:
            week = int(item.get("week") or 0)
        except (TypeError, ValueError):
            week = 0
        result.append(
            {
                "week": week,
                "topic": _text(item.get("topic"), SHORT_LIMIT),
                "lo_codes": [str(code) for code in item.get("lo_codes") or []][:LIST_LIMIT],
                "session_type": _text(item.get("session_type"), 64),
                "delivery": _text(item.get("delivery"), 64),
                "assessment_note": _text(item.get("assessment_note"), SHORT_LIMIT),
            }
        )
        if len(result) >= WEEK_LIMIT:
            break
    return result


def _readings(value: Any) -> list[str]:
    result: list[str] = []
    for item in value or []:
        if isinstance(item, dict):
            text = _text(item.get("citation") or item.get("title") or item.get("text"), SHORT_LIMIT)
        else:
            text = _text(item, SHORT_LIMIT)
        if text:
            result.append(text)
        if len(result) >= READING_LIMIT:
            break
    return result


def _outcome_measures(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in value or []:
        if isinstance(item, dict):
            code = _text(item.get("lo_code") or item.get("code"), 32)
            measures = item.get("measures") or item.get("measure") or item.get("text")
        else:
            code, measures = _text(item, 32), ""
        if isinstance(measures, list):
            measures = ", ".join(str(part).strip() for part in measures if str(part).strip())
        measures = _text(measures, SHORT_LIMIT)
        if code or measures:
            result.append({"lo_code": code, "measures": measures})
        if len(result) >= LIST_LIMIT:
            break
    return result


def _policies(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in value or []:
        if isinstance(item, dict):
            key = _text(item.get("key"), 64)
            title = _text(item.get("title"), 255)
            body = _text(item.get("body") or item.get("text"), SHORT_LIMIT)
        else:
            key, title, body = "", _text(item, 255), ""
        if key or title or body:
            result.append({"key": key, "title": title, "body": body})
        if len(result) >= LIST_LIMIT:
            break
    return result


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def _shrink(outline: dict[str, Any], budget: int) -> dict[str, Any]:
    """Drop the least important sections first until the payload fits."""
    if _size(outline) <= budget:
        return outline
    result = dict(outline)
    for key in ("policies", "readings", "plos", "weeks", "outcome_measures", "clos"):
        while result.get(key) and _size(result) > budget:
            result[key] = list(result[key])[:-1]
    for key in ("description", "program"):
        while result.get(key) and _size(result) > budget:
            result[key] = str(result[key])[:-200]
    return result


def trim_outline(row: SubjectOutline) -> dict[str, Any]:
    """Staff-facing outline only. There is no student section to leak."""
    body = dict(row.body or {})
    basics = body.get("basics") or {}
    lecture = body.get("lecture") or {}
    outline = {
        "code": _text(getattr(row, "code", ""), 32),
        "name": _text(getattr(row, "name", ""), 255),
        "status": _text(getattr(row, "status", ""), 32),
        "basics": {
            key: _text(basics.get(key), SHORT_LIMIT)
            for key in BASICS_FIELDS
            if _text(basics.get(key), SHORT_LIMIT)
        },
        "lecture": {
            key: _text(lecture.get(key), SHORT_LIMIT)
            for key in LECTURE_FIELDS
            if _text(lecture.get(key), SHORT_LIMIT)
        },
        "description": _text(body.get("description")),
        "program": _text(body.get("program")),
        "plos": _outcomes(body.get("plos")),
        "clos": _outcomes(body.get("clos")),
        "weeks": _weeks(body.get("weeks")),
        "readings": _readings(body.get("readings")),
        "outcome_measures": _outcome_measures(body.get("outcome_measures")),
        "policies": _policies(body.get("policies") or body.get("policy_documents")),
    }
    return _shrink(outline, OUTLINE_BUDGET)


def grading_outline(outline: dict[str, Any] | None) -> dict[str, Any]:
    """The part of the outline the council needs: CLOs, weeks, and the map."""
    if not outline:
        return {}
    projected = {
        "code": outline.get("code") or "",
        "name": outline.get("name") or "",
        "clos": outline.get("clos") or [],
        "weeks": [
            {
                "week": week.get("week"),
                "topic": week.get("topic"),
                "lo_codes": week.get("lo_codes") or [],
            }
            for week in outline.get("weeks") or []
        ],
        "outcome_measures": outline.get("outcome_measures") or [],
    }
    return _shrink(projected, GRADING_OUTLINE_BUDGET)


async def ready_chunks(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every chunk of every ready material. No truncation, no ranking."""
    materials = {
        row.id: row.filename
        for row in _rows(
            await db.execute(
                select(Material).where(
                    Material.organization_id == org_id,
                    Material.course_id == course_id,
                    Material.owner_user_id == user_id,
                    Material.status == "ready",
                )
            )
        )
    }
    if not materials:
        return []
    chunks = []
    for row in _rows(
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
    ):
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


def rank_chunks(
    chunks: list[dict[str, Any]], query: str, limit: int = CHUNK_LIMIT
) -> list[dict[str, Any]]:
    """Keyword rank when a prompt is available; otherwise keep document order."""
    if not (query or "").strip():
        return list(chunks)[:limit]
    scored = [
        (keyword_score(query, chunk.get("text") or ""), index, chunk)
        for index, chunk in enumerate(chunks)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [chunk for _score, _index, chunk in scored[:limit]]


def cap_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep ids and text, bounded per chunk and overall."""
    picked: list[dict[str, Any]] = []
    used = 0
    for chunk in chunks:
        text = _text(chunk.get("text"), CHUNK_CHARS)
        if not text:
            continue
        remaining = CHUNK_BUDGET - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining]
        picked.append(
            {
                "id": str(chunk.get("id") or ""),
                "text": text,
                "filename": _text(chunk.get("filename"), 255),
            }
        )
        used += len(text)
        if len(picked) >= CHUNK_LIMIT:
            break
    return picked


async def course_ai_context(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    *,
    query: str = "",
    limit: int = CHUNK_LIMIT,
) -> dict[str, Any]:
    """`{outline, chunks, dossier}`; each is empty when the course has none."""
    from app.profassist.course_memory.service import dossier_ai_context

    row = await load_outline(db, org_id, user_id, course_id)
    outline = trim_outline(row) if row is not None else {}
    chunks = await ready_chunks(db, org_id, user_id, course_id)
    dossier = await dossier_ai_context(db, org_id, user_id, course_id, budget=6000)
    return {
        "outline": outline,
        "chunks": cap_chunks(rank_chunks(chunks, query, limit)),
        "dossier": dossier,
    }
