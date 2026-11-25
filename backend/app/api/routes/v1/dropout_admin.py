"""Admin-only import, training, scoring, monitoring, and release controls for dropout risk."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import CurrentAppAdmin, DBSession
from app.profassist.deps import ProfOrg
from app.profassist.errors import ProfassistError

router = APIRouter()


class DropoutIdentity(BaseModel):
    student_key: str = Field(min_length=1, max_length=128)
    moodle_student_id: str = Field(min_length=1, max_length=64)


class DropoutScoreBody(BaseModel):
    export_id: uuid.UUID
    identity_map: list[DropoutIdentity] = Field(min_length=1, max_length=100_000)


class DropoutTrainBody(BaseModel):
    export_id: uuid.UUID
    train_cohorts: list[str] = Field(min_length=1, max_length=64)
    validation_cohorts: list[str] = Field(min_length=1, max_length=64)
    test_cohorts: list[str] = Field(default_factory=list, max_length=64)


class DropoutMonitorBody(BaseModel):
    export_id: uuid.UUID
    release_id: uuid.UUID | None = None


class DropoutReleaseActionBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _error(result: dict) -> dict:
    if "error" in result:
        raise ProfassistError(409, str(result["error"]))
    return result


@router.post("/admin/ml/dropout/exports")
async def dropout_export_import(
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
    course_id: uuid.UUID = Form(...),
    snapshots_file: UploadFile = File(...),
    manifest_file: UploadFile = File(...),
    outcomes_file: UploadFile | None = File(default=None),
) -> dict:
    from app.profassist.ml.dropout_jobs import import_export

    snapshots = await snapshots_file.read()
    manifest = await manifest_file.read()
    outcomes = await outcomes_file.read() if outcomes_file is not None else None
    try:
        result = await import_export(db, org.id, user.id, course_id, snapshots, manifest, outcomes)
    except ValueError as exc:
        raise ProfassistError(422, str(exc)) from exc
    return _error(result)


@router.get("/admin/ml/dropout/exports")
async def dropout_export_list(
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
    course_id: uuid.UUID | None = None,
) -> dict:
    del user
    from app.profassist.ml.dropout_jobs import list_exports

    return await list_exports(db, org.id, course_id)


@router.get("/admin/ml/dropout/jobs")
async def dropout_job_list(
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
    course_id: uuid.UUID | None = None,
) -> dict:
    del user
    from app.profassist.ml.dropout_jobs import list_dropout_jobs

    return await list_dropout_jobs(db, org.id, course_id)


@router.post("/admin/ml/dropout/score")
async def dropout_score_create(
    body: DropoutScoreBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.ml.dropout_jobs import create_score_job

    return _error(
        await create_score_job(
            db, org.id, user.id, body.export_id, [item.model_dump() for item in body.identity_map]
        )
    )


@router.post("/admin/ml/dropout/train")
async def dropout_train_create(
    body: DropoutTrainBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.ml.dropout_jobs import create_train_job

    return _error(
        await create_train_job(
            db,
            org.id,
            user.id,
            body.export_id,
            body.train_cohorts,
            body.validation_cohorts,
            body.test_cohorts,
        )
    )


@router.post("/admin/ml/dropout/monitor")
async def dropout_monitor_create(
    body: DropoutMonitorBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict:
    from app.profassist.ml.dropout_jobs import create_monitor_job

    return _error(await create_monitor_job(db, org.id, user.id, body.export_id, body.release_id))


@router.get("/admin/ml/dropout/releases")
async def dropout_release_list(user: CurrentAppAdmin, org: ProfOrg, db: DBSession) -> dict:
    del user
    from app.profassist.ml.dropout_jobs import list_dropout_releases

    return await list_dropout_releases(db, org.id)


@router.post("/admin/ml/dropout/releases/{release_id}/approve")
async def dropout_release_approve(
    release_id: uuid.UUID,
    body: DropoutReleaseActionBody,
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
) -> dict:
    from app.profassist.ml.dropout_jobs import change_dropout_release

    return _error(await change_dropout_release(db, org.id, user.id, release_id, body.reason))


@router.post("/admin/ml/dropout/releases/{release_id}/rollback")
async def dropout_release_rollback(
    release_id: uuid.UUID,
    body: DropoutReleaseActionBody,
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
) -> dict:
    from app.profassist.ml.dropout_jobs import change_dropout_release

    return _error(
        await change_dropout_release(db, org.id, user.id, release_id, body.reason, rollback=True)
    )
