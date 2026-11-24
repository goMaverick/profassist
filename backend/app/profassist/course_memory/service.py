"""Persisted course memory: load inputs, rebuild dossiers, serve AI context.

Every query is tenant-scoped by organization, course, and professor. A rebuild
is idempotent by content hash, a single-file rebuild only touches that file, and
the merged body is always bounded before it is stored or served.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist import course_context
from app.profassist.course_memory.cleaners import content_hash
from app.profassist.course_memory.graph import (
    extract_material_dossier,
    pii_gate_dossier,
    run_memory_state,
)
from app.profassist.course_memory.merge import PRUNE_ORDER, merge_dossiers, shrink_dossier
from app.profassist.errors import ProfassistError
from app.profassist.models import Chunk, CourseDossier, Material

MATERIAL_CHUNK_LIMIT = 40
CHUNK_TEXT_LIMIT = 4000
CONTEXT_BUDGET = 8000

__all__ = [
    "dossier_ai_context",
    "load_dossier",
    "load_memory_inputs",
    "pii_gate_dossier",
    "rebuild_course_memory",
    "rebuild_material",
]


async def _load_outline_row(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
):
    """Wrapped so a test can supply an outline without a database."""
    return await course_context.load_outline(db, org_id, user_id, course_id)


async def _official_outline(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    outline: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(outline, dict):
        return dict(outline)
    try:
        row = await _load_outline_row(db, org_id, user_id, course_id)
    except Exception:
        return {}
    if row is None:
        return {}
    try:
        official = course_context.trim_outline(row)
    except Exception:
        return {}
    # trim_outline is staff-facing but omits the assessment map; the merge needs
    # the weights so the official outline can win a conflict.
    tasks = (getattr(row, "body", None) or {}).get("assessment_tasks")
    if tasks:
        official = {**official, "assessment_tasks": tasks}
    return official


async def _ready_materials(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> list[Material]:
    result = await db.execute(
        select(Material).where(
            Material.organization_id == org_id,
            Material.course_id == course_id,
            Material.owner_user_id == user_id,
            Material.status == "ready",
        )
    )
    rows = list(result.scalars().all())
    return [
        row
        for row in rows
        if str(row.status or "") == "ready" and not (row.pii_report or {}).get("quarantined")
    ]


async def _chunks_by_material(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    material_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    if not material_ids:
        return {}
    result = await db.execute(
        select(Chunk)
        .where(
            Chunk.organization_id == org_id,
            Chunk.course_id == course_id,
            Chunk.owner_user_id == user_id,
            Chunk.material_id.in_(material_ids),
        )
        .order_by(Chunk.material_id, Chunk.ordinal)
    )
    grouped: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in result.scalars().all():
        bucket = grouped.setdefault(row.material_id, [])
        if len(bucket) >= MATERIAL_CHUNK_LIMIT:
            continue
        text = str(row.text or "")[:CHUNK_TEXT_LIMIT]
        if text.strip():
            bucket.append({"ordinal": int(row.ordinal or 0), "text": text})
    return grouped


async def load_memory_inputs(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    *,
    outline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ready materials with bounded chunks, plus the trimmed official outline."""
    rows = await _ready_materials(db, org_id, user_id, course_id)
    chunks = await _chunks_by_material(db, org_id, user_id, course_id, [row.id for row in rows])
    materials: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        materials.append(
            {
                "material_id": str(row.id),
                "id": str(row.id),
                "filename": row.filename,
                "ordinal": index,
                "content_hash": content_hash(row.scrubbed_text or ""),
                "chunks": chunks.get(row.id, []),
                "row": row,
            }
        )
    official = await _official_outline(db, org_id, user_id, course_id, outline)
    return {"materials": materials, "official": official}


def _course_code(official: dict[str, Any]) -> str:
    code = str(official.get("code") or "").strip()
    if code:
        return code
    basics = official.get("basics")
    if isinstance(basics, dict):
        return str(basics.get("code") or "").strip()
    return ""


async def _load_dossier_row(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> CourseDossier | None:
    result = await db.execute(
        select(CourseDossier).where(
            CourseDossier.organization_id == org_id,
            CourseDossier.course_id == course_id,
            CourseDossier.owner_user_id == user_id,
        )
    )
    return result.scalars().first()


def _dossier_dict(row: CourseDossier) -> dict[str, Any]:
    return {
        "id": str(row.id or ""),
        "version": int(row.version or 1),
        "status": str(row.status or ""),
        "trace_url": str(row.trace_url or ""),
        "body": dict(row.body or {}),
        "history": list(row.history or []),
    }


def _material_summary(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for spec in materials:
        row = spec.get("row")
        if row is None:
            continue
        summary.append(
            {
                "material_id": str(getattr(row, "id", spec.get("material_id") or "")),
                "filename": str(getattr(row, "filename", spec.get("filename") or "")),
                "insight_status": str(getattr(row, "insight_status", "") or ""),
                "trace_url": str(getattr(row, "trace_url", "") or ""),
            }
        )
    return summary


def _upsert_dossier(
    existing: CourseDossier | None,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    body: dict[str, Any],
    trace_url: str | None,
) -> CourseDossier:
    """Store the merged body stamped with the version the row now carries.

    ``merge_dossiers`` always starts at version 1, so the body is stamped here
    once the row's own version is known; otherwise the API serves a body whose
    version disagrees with its row.
    """
    if existing is not None:
        version = int(existing.version or 1) + 1
        history = list(existing.history or [])
        history.append(
            {
                "version": int(existing.version or 1),
                "status": str(existing.status or ""),
                "trace_url": str(existing.trace_url or ""),
            }
        )
        existing.version = version
        existing.body = {**body, "version": version}
        existing.status = "ready"
        existing.trace_url = trace_url or ""
        existing.history = history[-5:]
        return existing
    return CourseDossier(
        id=uuid.uuid4(),
        organization_id=org_id,
        course_id=course_id,
        owner_user_id=user_id,
        version=1,
        body={**body, "version": 1},
        status="ready",
        trace_url=trace_url or "",
        history=[],
    )


async def _save_dossier(
    db: AsyncSession,
    row: CourseDossier,
    *,
    inserted: bool,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    body: dict[str, Any],
    trace_url: str | None,
) -> CourseDossier:
    """Persist the dossier; losing a concurrent insert must not fail the rebuild.

    Two rebuilds can both read "no row" and then insert. The unique constraint
    keeps one; the loser retries once as an update of the winner inside a
    savepoint, so the material insight writes in this transaction survive.
    """
    if not inserted:
        await db.flush()
        return row
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        winner = await _load_dossier_row(db, org_id, user_id, course_id)
        if winner is None:
            raise
        row = _upsert_dossier(winner, org_id, user_id, course_id, body, trace_url)
        await db.flush()
    return row


async def rebuild_course_memory(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Extract changed files, merge, and persist the course dossier.

    A file whose scrubbed content hash still matches its ready insight is not
    sent to the model again. ``force=True`` rebuilds every file.
    """
    inputs = await load_memory_inputs(db, org_id, user_id, course_id)
    official = inputs.get("official") or {}
    course_code = _course_code(official)
    existing = await _load_dossier_row(db, org_id, user_id, course_id)

    specs: list[dict[str, Any]] = []
    pending = 0
    for spec in inputs.get("materials") or []:
        row = spec.get("row")
        if row is None:
            continue
        entry = dict(spec)
        unchanged = (
            not force
            and str(getattr(row, "insight_status", "") or "") == "ready"
            and isinstance(getattr(row, "insight", None), dict)
            and (row.insight or {}).get("content_hash") == spec.get("content_hash")
        )
        if unchanged:
            dossier = dict(row.insight or {})
            dossier.setdefault("filename", spec.get("filename") or row.filename)
            dossier.setdefault("material_id", spec.get("material_id") or str(row.id))
            entry["dossier"] = dossier
        else:
            pending += 1
        specs.append(entry)

    if (
        not force
        and pending == 0
        and existing is not None
        and existing.body
        and str(existing.status or "") == "ready"
    ):
        return {
            "dossier": _dossier_dict(existing),
            "materials": _material_summary(specs),
            "trace_url": str(existing.trace_url or ""),
        }

    result, trace_url = run_memory_state(specs, official, course_code=course_code)
    dossiers = {
        str(item.get("material_id") or ""): item
        for item in result.get("dossiers") or []
        if isinstance(item, dict)
    }
    failures = {
        str(item.get("material_id") or "")
        for item in result.get("errors") or []
        if isinstance(item, dict)
    }

    for spec in specs:
        row = spec.get("row")
        if row is None:
            continue
        material_id = str(spec.get("material_id") or "")
        if material_id in failures:
            row.insight_status = "failed"
            continue
        dossier = dossiers.get(material_id)
        if dossier is None:
            row.insight_status = "skipped"
            continue
        if not spec.get("chunks") and "dossier" not in spec:
            row.insight_status = "skipped"
            continue
        persisted = {key: value for key, value in dossier.items() if key != "skipped"}
        persisted["content_hash"] = spec.get("content_hash") or ""
        row.insight = persisted
        row.insight_status = "ready"
        row.trace_url = trace_url or ""

    merged = result.get("merged")
    if not isinstance(merged, dict) or not merged:
        merged = merge_dossiers(result.get("dossiers") or [], official or None)
    merged = shrink_dossier(merged)
    dossier_row = _upsert_dossier(existing, org_id, user_id, course_id, merged, trace_url)
    dossier_row = await _save_dossier(
        db,
        dossier_row,
        inserted=existing is None,
        org_id=org_id,
        user_id=user_id,
        course_id=course_id,
        body=merged,
        trace_url=trace_url,
    )
    return {
        "dossier": _dossier_dict(dossier_row),
        "materials": _material_summary(specs),
        "trace_url": trace_url or "",
    }


async def rebuild_material(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
) -> dict[str, Any]:
    """Re-extract one file and mark the course dossier stale."""
    row = await db.get(Material, material_id)
    if row is None or row.organization_id != org_id or row.owner_user_id != user_id:
        raise ProfassistError(404, "That file is not in this course.")

    result = await db.execute(
        select(Chunk)
        .where(
            Chunk.organization_id == org_id,
            Chunk.owner_user_id == user_id,
            Chunk.material_id == row.id,
        )
        .order_by(Chunk.ordinal)
    )
    chunks: list[dict[str, Any]] = []
    for chunk in result.scalars().all():
        if len(chunks) >= MATERIAL_CHUNK_LIMIT:
            break
        text = str(chunk.text or "")[:CHUNK_TEXT_LIMIT]
        if text.strip():
            chunks.append({"ordinal": int(chunk.ordinal or 0), "text": text})

    outcome = extract_material_dossier(
        material_id=str(row.id),
        filename=row.filename,
        chunks=chunks,
        query=row.filename or "",
    )
    if "error" in outcome:
        row.insight_status = "failed"
    else:
        dossier = dict(outcome.get("dossier") or {})
        dossier["content_hash"] = content_hash(row.scrubbed_text or "")
        row.insight = dossier
        row.insight_status = "ready"
    # This path runs no graph of its own, so an older full-rebuild trace must
    # not be shown as if it belonged to this single file.
    row.trace_url = ""

    dossier_row = await _load_dossier_row(db, org_id, user_id, row.course_id)
    if dossier_row is not None:
        dossier_row.status = "stale"
    await db.flush()
    return {
        "material": {
            "material_id": str(row.id),
            "filename": row.filename,
            "insight_status": str(row.insight_status or ""),
        },
        "dossier": _dossier_dict(dossier_row) if dossier_row is not None else None,
    }


async def load_dossier(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> dict[str, Any] | None:
    """The bounded merged body, or None when the course has no dossier."""
    row = await _load_dossier_row(db, org_id, user_id, course_id)
    if row is None or not isinstance(row.body, dict):
        return None
    # `shrink_dossier` pops list values; never let that touch the stored body.
    return shrink_dossier(copy.deepcopy(row.body))


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _fit_budget(body: dict[str, Any], budget: int) -> dict[str, Any]:
    """Trim a merged dossier further than the global budget, cheapest first."""
    data = shrink_dossier(body)
    if _size(data) <= budget:
        return data
    for section in PRUNE_ORDER:
        value = data.get(section)
        if isinstance(value, list):
            while value and _size(data) > budget:
                value.pop()
        elif isinstance(value, dict):
            for key in ("mappings", "plos", "clos"):
                rows = value.get(key)
                if isinstance(rows, list):
                    while rows and _size(data) > budget:
                        rows.pop()
        elif isinstance(value, str):
            while value and _size(data) > budget:
                value = value[: len(value) // 2] if len(value) > 40 else ""
                data[section] = value
        if _size(data) <= budget:
            return data
    provenance = data.get("provenance")
    if isinstance(provenance, list):
        while provenance and _size(data) > budget:
            provenance.pop()
    return data


async def dossier_ai_context(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    budget: int = CONTEXT_BUDGET,
) -> dict[str, Any]:
    """Course memory for an AI payload. Empty when missing or stale."""
    row = await _load_dossier_row(db, org_id, user_id, course_id)
    if row is None or str(row.status or "") != "ready":
        return {}
    if not isinstance(row.body, dict) or not row.body:
        return {}
    limit = int(budget or 0)
    if limit <= 0:
        return {}
    return _fit_budget(copy.deepcopy(row.body), limit)
