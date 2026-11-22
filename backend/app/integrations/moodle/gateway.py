"""The only door to Moodle. Sync, push, and connection tests go through here."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.config import moodle_mode
from app.profassist.models import AiSettings, Course, MoodleSyncRun
from app.profassist.moodle_schedule import (
    incremental_due,
    next_incremental,
    next_nightly,
    nightly_due,
)


def adapter():
    """Fake or real client. Feature code should not call this."""
    from app.profassist.moodle import get_connector

    return get_connector()


def test_connection() -> dict[str, Any]:
    client = adapter()
    try:
        courses = client.list_courses()
    except Exception as exc:
        return {"ok": False, "mode": getattr(client, "mode", moodle_mode()), "error": str(exc)}
    return {
        "ok": True,
        "mode": client.mode,
        "courses": len(courses),
        "error": "",
    }


async def push(item: dict[str, Any]) -> dict[str, Any]:
    return adapter().push(item)


async def launch(claims: dict[str, Any]) -> dict[str, Any]:
    return adapter().lti_launch(claims)


async def sync(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    *,
    trigger: str,
) -> dict[str, Any]:
    """Pull into local tables. trigger is schedule, nightly, or manual."""
    from app.profassist.service import pull_moodle

    client = adapter()
    try:
        result = await pull_moodle(db, org_id, user_id, client)
        status = "ok"
        error = ""
    except Exception as exc:
        result = {"courses": 0, "students": 0, "submissions": 0}
        status = "error"
        error = str(exc)
    db.add(
        MoodleSyncRun(
            organization_id=org_id,
            user_id=user_id,
            trigger=trigger,
            mode=getattr(client, "mode", moodle_mode()),
            status=status,
            counts=result,
            error=error,
        )
    )
    await db.flush()
    if status == "error":
        from app.profassist.errors import ProfassistError

        raise ProfassistError(502, error)
    payload = await status_for(db, org_id)
    payload.update(result)
    payload["trigger"] = trigger
    return payload


async def sync_scheduled(db: AsyncSession, *, full: bool) -> dict[str, Any]:
    """Prefect entry. Each university keeps its own interval, pause, and nightly hour."""
    orgs = (await db.execute(select(AiSettings.organization_id))).scalars().all()
    course_orgs = (await db.execute(select(Course.organization_id).distinct())).scalars().all()
    targets = list(dict.fromkeys([*orgs, *course_orgs]))
    ran = 0
    skipped = 0
    now = datetime.now(UTC)
    for org_id in targets:
        settings = (
            await db.execute(select(AiSettings).where(AiSettings.organization_id == org_id))
        ).scalar_one_or_none()
        paused = bool(settings.moodle_sync_paused) if settings else False
        minutes = settings.moodle_sync_minutes if settings else 30
        nightly = bool(settings.moodle_nightly_enabled) if settings else True
        hour = settings.moodle_nightly_hour if settings else 2
        last = await _last(db, org_id, "schedule")
        last_full = await _last(db, org_id, "nightly")
        if full:
            if not nightly_due(last_full.created_at if last_full else None, hour, nightly, now):
                skipped += 1
                continue
            trigger = "nightly"
        else:
            if not incremental_due(last.created_at if last else None, minutes, paused, now):
                skipped += 1
                continue
            trigger = "schedule"
        await sync(db, org_id, None, trigger=trigger)
        ran += 1
    return {"ran": ran, "skipped": skipped, "full": full}


async def status_for(db: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    settings = (
        await db.execute(select(AiSettings).where(AiSettings.organization_id == org_id))
    ).scalar_one_or_none()
    paused = bool(settings.moodle_sync_paused) if settings else False
    minutes = settings.moodle_sync_minutes if settings else 30
    nightly = bool(settings.moodle_nightly_enabled) if settings else True
    hour = settings.moodle_nightly_hour if settings else 2
    last = await _last(db, org_id, None)
    last_incremental = await _last(db, org_id, "schedule")
    last_full = await _last(db, org_id, "nightly")
    now = datetime.now(UTC)
    incremental = next_incremental(
        last_incremental.created_at if last_incremental else None,
        minutes,
        paused,
        now,
    )
    nightly_at = next_nightly(hour, nightly, now)
    return {
        "mode": moodle_mode(),
        "paused": paused,
        "interval_minutes": minutes,
        "nightly_enabled": nightly,
        "nightly_hour_utc": hour,
        "last_sync": last.created_at.isoformat() if last and last.created_at else "",
        "last_trigger": last.trigger if last else "",
        "last_status": last.status if last else "",
        "last_error": last.error if last else "",
        "counts": last.counts if last else {},
        "next_run": incremental.isoformat() if incremental else "",
        "next_nightly": nightly_at.isoformat() if nightly_at else "",
        "primary": "schedule",
        "last_full": last_full.created_at.isoformat() if last_full and last_full.created_at else "",
    }


async def _last(db: AsyncSession, org_id: uuid.UUID, trigger: str | None) -> MoodleSyncRun | None:
    query = select(MoodleSyncRun).where(MoodleSyncRun.organization_id == org_id)
    if trigger:
        query = query.where(MoodleSyncRun.trigger == trigger)
    query = query.order_by(MoodleSyncRun.created_at.desc())
    return (await db.execute(query)).scalars().first()
