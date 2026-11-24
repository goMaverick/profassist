"""The only door to Moodle. Sync, push, and connection tests go through here.

Every call resolves one university's connection first. The process environment
is only used when an org has no row, and the scheduled job refuses to fan one
global token across unrelated universities.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.config import (
    moodle_base_url,
    moodle_mode,
    moodle_push_enabled,
    moodle_ws_token,
)
from app.profassist.models import (
    AiSettings,
    Course,
    MoodleConnection,
    MoodlePush,
    MoodleSyncRun,
    Student,
    Submission,
)
from app.profassist.moodle import MoodleConnectionSpec, _redact
from app.profassist.moodle_connection import activity_log_state
from app.profassist.moodle_schedule import (
    incremental_due,
    next_incremental,
    next_nightly,
    nightly_due,
)

_EMPTY_COUNTS = {"courses": 0, "students": 0, "submissions": 0}


def adapter(spec: MoodleConnectionSpec | None = None):
    """Fake or real client. Feature code should not call this."""
    from app.profassist.moodle import get_connector

    return get_connector(spec)


async def _connection_row(db: AsyncSession, org_id: uuid.UUID) -> MoodleConnection | None:
    result = await db.execute(
        select(MoodleConnection).where(MoodleConnection.organization_id == org_id)
    )
    return result.scalar_one_or_none()


async def connection_for(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    allow_env: bool = True,
) -> MoodleConnectionSpec | None:
    """Decrypt this org's connection, or fall back to the env seed.

    A row always wins: even a disabled row stops the env fallback, so an admin
    deleting a connection does not silently re-enable a shared token.
    """
    from app.core.config import settings
    from app.core.crypto import decrypt_value

    row = await _connection_row(db, org_id)
    if row is not None:
        if row.status == "disabled" or not row.ws_token_enc or not row.base_url:
            return None
        try:
            token = decrypt_value(row.ws_token_enc, settings.SECRET_KEY)
        except Exception:
            # A rotated SECRET_KEY strands the ciphertext. Treat it as unconfigured
            # rather than leaking a crypto error to the admin screen.
            return None
        return MoodleConnectionSpec(
            base_url=row.base_url,
            token=token,
            course_scope=dict(row.course_scope or {}),
            push_enabled=bool(row.push_enabled),
            source="org",
        )
    if not allow_env:
        return None
    base_url = moodle_base_url()
    token = moodle_ws_token()
    if base_url and token:
        return MoodleConnectionSpec(
            base_url=base_url,
            token=token,
            push_enabled=moodle_push_enabled(),
            source="env",
        )
    return None


def _checklist(ok: bool, error: str, info: dict[str, Any] | None = None, mode: str = "") -> dict:
    info = info or {}
    capabilities = info.get("capabilities") or {}
    return {
        "ok": ok,
        "mode": mode or moodle_mode(),
        "error": _redact(error),
        "site_url": info.get("site_url") or "",
        "site_name": info.get("site_name") or "",
        "release": info.get("release") or "",
        "version": info.get("version") or "",
        "siteid": info.get("siteid") or "",
        "capabilities": capabilities,
        "warnings": info.get("warnings") or [],
        "checklist": [
            {"key": "connection", "label": "Moodle answers", "ok": ok},
            {
                "key": "functions",
                "label": "Web-service functions advertised",
                "ok": bool(capabilities.get("functions")),
            },
            {
                "key": "downloadfiles",
                "label": "Can download submission files",
                "ok": bool(capabilities.get("downloadfiles")),
            },
            {
                "key": "uploadfiles",
                "label": "Can upload files",
                "ok": bool(capabilities.get("uploadfiles")),
            },
            {
                "key": "enablecompletion",
                "label": "Completion tracking is on",
                "ok": bool(capabilities.get("enablecompletion")),
            },
        ],
    }


async def _persist_check(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    status: str,
    error: str,
    info: dict[str, Any] | None,
) -> None:
    row = await _connection_row(db, org_id)
    if row is None:
        return
    row.status = status
    row.last_checked_at = datetime.now(UTC)
    row.last_check_error = _redact(error)
    if info:
        row.site_url = info.get("site_url") or ""
        row.site_name = info.get("site_name") or ""
        row.release = info.get("release") or ""
        row.version = info.get("version") or ""
        row.siteid = info.get("siteid") or ""
        row.capabilities = info.get("capabilities") or {}
    await db.flush()


async def test_connection(
    db: AsyncSession | None = None,
    org_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Ask Moodle for its site info, then persist the capability checklist."""
    from app.profassist.errors import ProfassistError

    spec = None
    if moodle_mode() == "real" and db is not None and org_id is not None:
        spec = await connection_for(db, org_id)
        if spec is None:
            return _checklist(False, "No Moodle connection is configured for this workspace.")
    client = adapter(spec)
    try:
        info = client.site_info()
    except ProfassistError as exc:
        error = _redact(exc.detail)
        if db is not None and org_id is not None:
            await _persist_check(db, org_id, status="error", error=error, info=None)
        return _checklist(False, error, mode=getattr(client, "mode", moodle_mode()))
    except Exception as exc:
        error = _redact(exc) or "Moodle could not be reached."
        if db is not None and org_id is not None:
            await _persist_check(db, org_id, status="error", error=error, info=None)
        return _checklist(False, error, mode=getattr(client, "mode", moodle_mode()))
    if db is not None and org_id is not None:
        await _persist_check(db, org_id, status="ok", error="", info=info)
    return _checklist(True, "", info=info, mode=getattr(client, "mode", moodle_mode()))


async def push(
    item: dict[str, Any],
    db: AsyncSession | None = None,
    org_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    from app.profassist.errors import ProfassistError

    spec = None
    if moodle_mode() == "real" and db is not None and org_id is not None:
        spec = await connection_for(db, org_id)
        if spec is None:
            raise ProfassistError(503, "No Moodle connection is configured for this workspace.")
    try:
        return adapter(spec).push(item)
    except ProfassistError as exc:
        raise ProfassistError(exc.status, _redact(exc.detail)) from None


async def launch(claims: dict[str, Any]) -> dict[str, Any]:
    return adapter().lti_launch(claims)


async def _sync(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    *,
    trigger: str,
    spec: MoodleConnectionSpec | None,
) -> dict[str, Any]:
    from app.profassist.errors import ProfassistError
    from app.profassist.service import pull_moodle

    client = adapter(spec)
    status_code = 0
    try:
        result = await pull_moodle(db, org_id, user_id, client)
        status = "ok"
        error = ""
    except ProfassistError as exc:
        result = dict(_EMPTY_COUNTS)
        status = "error"
        error = _redact(exc.detail)
        status_code = exc.status
    except Exception as exc:
        result = dict(_EMPTY_COUNTS)
        status = "error"
        error = _redact(exc) or "Moodle sync failed."
        status_code = 503
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
        # Audit-only commit: raising below rolls the request transaction back,
        # which would otherwise discard the failed-run row. The row is the only
        # record that this sync was attempted, so make it durable first.
        await db.commit()
        raise ProfassistError(status_code or 503, error)
    payload = await status_for(db, org_id)
    payload.update(result)
    payload["trigger"] = trigger
    return payload


async def sync(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    *,
    trigger: str,
) -> dict[str, Any]:
    """Pull into local tables. trigger is schedule, nightly, or manual."""
    from app.profassist.errors import ProfassistError

    spec = None
    if moodle_mode() == "real":
        spec = await connection_for(db, org_id)
        if spec is None:
            error = "No Moodle connection is configured for this workspace."
            db.add(
                MoodleSyncRun(
                    organization_id=org_id,
                    user_id=user_id,
                    trigger=trigger,
                    mode="real",
                    status="error",
                    counts=dict(_EMPTY_COUNTS),
                    error=error,
                )
            )
            await db.flush()
            await db.commit()
            raise ProfassistError(503, error)
    return await _sync(db, org_id, user_id, trigger=trigger, spec=spec)


async def sync_scheduled(db: AsyncSession, *, full: bool) -> dict[str, Any]:
    """Prefect entry. Each university keeps its own interval, pause, and nightly hour."""
    orgs = (await db.execute(select(AiSettings.organization_id))).scalars().all()
    course_orgs = (await db.execute(select(Course.organization_id).distinct())).scalars().all()
    targets = list(dict.fromkeys([*orgs, *course_orgs]))
    configured = (
        (await db.execute(select(MoodleConnection.organization_id).distinct())).scalars().all()
    )
    # A single env token may serve a single-campus deployment. Once any org has a
    # row, or more than one org is a target, the env seed is not fanned across
    # universities: orgs without their own connection are skipped.
    allow_env = moodle_mode() == "real" and not configured and len(targets) <= 1
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
        spec = None
        if moodle_mode() == "real":
            spec = await connection_for(db, org_id, allow_env=allow_env)
            if spec is None:
                skipped += 1
                continue
        await _sync(db, org_id, None, trigger=trigger, spec=spec)
        ran += 1
    return {"ran": ran, "skipped": skipped, "full": full}


async def _totals(db: AsyncSession, org_id: uuid.UUID) -> dict[str, int]:
    """What the workspace holds now, not what the last run happened to import.

    An idempotent re-sync imports zero new rows, so ``counts`` alone reads as an
    empty connection even though the courses, students, and submissions are all
    still there.
    """
    totals: dict[str, int] = {}
    for key, model in (
        ("courses", Course),
        ("students", Student),
        ("submissions", Submission),
    ):
        result = await db.execute(
            select(func.count()).select_from(model).where(model.organization_id == org_id)
        )
        totals[key] = int(result.scalar_one() or 0)
    return totals


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
    row = await _connection_row(db, org_id)
    now = datetime.now(UTC)
    incremental = next_incremental(
        last_incremental.created_at if last_incremental else None,
        minutes,
        paused,
        now,
    )
    nightly_at = next_nightly(hour, nightly, now)
    activity_logs = await activity_log_state(db, org_id)
    return {
        "mode": moodle_mode(),
        "paused": paused,
        "interval_minutes": minutes,
        "nightly_enabled": nightly,
        "nightly_hour_utc": hour,
        "last_sync": last.created_at.isoformat() if last and last.created_at else "",
        "last_trigger": last.trigger if last else "",
        "last_status": last.status if last else "",
        "last_error": _redact(last.error) if last else "",
        "counts": last.counts if last else {},
        "totals": await _totals(db, org_id),
        "next_run": incremental.isoformat() if incremental else "",
        "next_nightly": nightly_at.isoformat() if nightly_at else "",
        "primary": "schedule",
        "last_full": last_full.created_at.isoformat() if last_full and last_full.created_at else "",
        "connection": {
            "configured": bool(row and row.ws_token_enc),
            "status": row.status if row else "unconfigured",
            "push_enabled": bool(row.push_enabled) if row else moodle_push_enabled(),
            "site_url": row.site_url if row else "",
            "release": row.release if row else "",
            "siteid": row.siteid if row else "",
            "last_checked_at": (
                row.last_checked_at.isoformat() if row and row.last_checked_at else ""
            ),
            "last_check_error": _redact(row.last_check_error) if row else "",
        },
        "activity_logs": activity_logs,
    }


async def audit_for(db: AsyncSession, org_id: uuid.UUID, limit: int = 10) -> dict[str, Any]:
    runs = (
        (
            await db.execute(
                select(MoodleSyncRun)
                .where(MoodleSyncRun.organization_id == org_id)
                .order_by(MoodleSyncRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    pushes = (
        (
            await db.execute(
                select(MoodlePush)
                .where(MoodlePush.organization_id == org_id)
                .order_by(MoodlePush.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "runs": [
            {
                "id": str(run.id),
                "trigger": run.trigger,
                "mode": run.mode,
                "status": run.status,
                "counts": run.counts or {},
                "error": _redact(run.error),
                "created_at": run.created_at.isoformat() if run.created_at else "",
            }
            for run in runs
        ],
        "pushes": [
            {
                "id": str(push_row.id),
                "target_type": push_row.target_type,
                "target_id": push_row.target_id,
                "accepted": bool((push_row.payload or {}).get("accepted")),
                "created_at": (push_row.created_at.isoformat() if push_row.created_at else ""),
            }
            for push_row in pushes
        ],
    }


async def _last(db: AsyncSession, org_id: uuid.UUID, trigger: str | None) -> MoodleSyncRun | None:
    query = select(MoodleSyncRun).where(MoodleSyncRun.organization_id == org_id)
    if trigger:
        query = query.where(MoodleSyncRun.trigger == trigger)
    query = query.order_by(MoodleSyncRun.created_at.desc())
    return (await db.execute(query)).scalars().first()
