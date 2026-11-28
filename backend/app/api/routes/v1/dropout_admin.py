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
    if result.get("error"):
        raise ProfassistError(409, str(result["error"]))
    return result


@router.post("/admin/ml/dropout/exports")
async def dropout_export_import(
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
    course_id: uuid.UUID = Form(...),
    training_file: UploadFile | None = File(default=None),
    confirmed_moodle: bool = Form(default=False),
    synthetic: bool = Form(default=False),
    snapshots_file: UploadFile | None = File(default=None),
    manifest_file: UploadFile | None = File(default=None),
    outcomes_file: UploadFile | None = File(default=None),
) -> dict:
    from app.profassist.ml.dropout_jobs import MAX_FILE_BYTES, import_export, split_training_csv

    try:
        if training_file is not None:
            if any(file is not None for file in (snapshots_file, manifest_file, outcomes_file)):
                raise ValueError(
                    "Upload one training CSV or use the original separate export files."
                )
            if not synthetic and not confirmed_moodle:
                raise ValueError(
                    "Confirm that the CSV contains historical data exported from Moodle."
                )
            from app.profassist.models import Course

            course = await db.get(Course, course_id)
            if course is None or course.organization_id != org.id:
                raise ProfassistError(404, "Course not found in this workspace.")
            snapshots, manifest, outcomes = split_training_csv(
                await training_file.read(MAX_FILE_BYTES + 1),
                org.id,
                synthetic=synthetic,
                course_external_id=str(course.external_id or ""),
            )
        elif snapshots_file is not None and manifest_file is not None:
            snapshots = await snapshots_file.read(MAX_FILE_BYTES + 1)
            manifest = await manifest_file.read(1024 * 1024 + 1)
            outcomes = await outcomes_file.read(MAX_FILE_BYTES + 1) if outcomes_file else None
        else:
            raise ValueError("Upload a training CSV.")
        result = await import_export(db, org.id, user.id, course_id, snapshots, manifest, outcomes)
    except ValueError as exc:
        raise ProfassistError(422, str(exc)) from exc
    response = _error(result)
    await db.commit()
    return response


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
