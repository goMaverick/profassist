"""Review-cohort snapshots, training jobs, and transactional release controls."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any

import httpx
from prefect.deployments import run_deployment
from sqlalchemy import select, text

from app.profassist.models import (
    Assessment,
    Course,
    IntegrityDatasetSnapshot,
    IntegrityPairReview,
    IntegritySourceVersion,
    ProfAssistMLJob,
    ProfAssistMLRelease,
)


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _dispatch(db: Any, job: ProfAssistMLJob) -> dict[str, Any]:
    previous_flow_run_id = job.prefect_flow_run_id
    job.status = "queued"
    job.error = ""
    await db.commit()
    try:
        run = await run_deployment(
            "profassist-ml-job/ml-job",
            parameters={"job_id": str(job.id)},
            timeout=0,
            idempotency_key=(
                f"{job.id}:{previous_flow_run_id}" if previous_flow_run_id else str(job.id)
            ),
        )
        job.prefect_flow_run_id = str(getattr(run, "id", "") or "")
    except Exception:
        job.status = "failed"
        job.error = "The model job could not be queued. Please retry."
    await db.execute(
        text("SELECT set_config('app.current_org', :org, true)"),
        {"org": str(job.organization_id)},
    )
    await db.flush()
    await db.refresh(job)
    return _job_card(job)


async def _queue(db: Any, job: ProfAssistMLJob) -> dict[str, Any]:
    db.add(job)
    await db.flush()
    return await _dispatch(db, job)


def _job_card(row: ProfAssistMLJob) -> dict[str, Any]:
    result = row.result if isinstance(row.result, dict) else {}
    return {
        "job_id": str(row.id),
        "operation": row.operation,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "error": row.error or None,
        "model_version": row.model_version,
        "snapshot_id": result.get("snapshot_id"),
        "release_id": result.get("release_id"),
        "gate_passed": result.get("gate_passed"),
    }


async def create_snapshot_job(
    db: Any, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID, assessment_id: uuid.UUID
) -> dict[str, Any]:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"snapshot:{org_id}:{assessment_id}"},
    )
    course = await db.get(Course, course_id)
    assessment = await db.get(Assessment, assessment_id)
    if (
        course is None
        or assessment is None
        or course.organization_id != org_id
        or assessment.organization_id != org_id
        or assessment.course_id != course_id
        or assessment.owner_user_id not in {None, user_id}
    ):
        return {"error": "Assignment not found."}
    versions_result = await db.execute(
        select(IntegritySourceVersion)
        .where(
            IntegritySourceVersion.organization_id == org_id,
            IntegritySourceVersion.course_id == course_id,
            IntegritySourceVersion.assessment_id == assessment_id,
        )
        .order_by(IntegritySourceVersion.submission_id, IntegritySourceVersion.version.desc())
    )
    all_versions = list(versions_result.scalars().all())
    latest_by_submission: dict[str, IntegritySourceVersion] = {}
    for version in all_versions:
        latest_by_submission.setdefault(str(version.submission_id), version)
    current_ids = {row.id for row in latest_by_submission.values()}
    if len(current_ids) < 2:
        return {"error": "At least two immutable report versions are required."}
    reviews_result = await db.execute(
        select(IntegrityPairReview)
        .where(
            IntegrityPairReview.organization_id == org_id,
            IntegrityPairReview.assessment_id == assessment_id,
        )
        .order_by(IntegrityPairReview.created_at.desc(), IntegrityPairReview.revision.desc())
    )
    latest_reviews: dict[tuple[str, str], IntegrityPairReview] = {}
    for review in reviews_result.scalars().all():
        key = tuple(sorted((str(review.left_version_id), str(review.right_version_id))))
        latest_reviews.setdefault(key, review)
    eligible = [
        review
        for review in latest_reviews.values()
        if review.left_version_id in current_ids
        and review.right_version_id in current_ids
        and review.decision in {"ok", "flag"}
        and (review.decision != "flag" or bool(review.spans))
    ]
    if not eligible:
        return {
            "error": "Review at least one complete report pair before creating a dataset snapshot."
        }
    reports = [
        {"report_id": str(row.submission_id), "version_id": str(row.id), "text": row.text_content}
        for row in sorted(latest_by_submission.values(), key=lambda item: str(item.submission_id))
    ]
    reviews = []
    for review in eligible:
        left = next(row for row in reports if row["version_id"] == str(review.left_version_id))
        right = next(row for row in reports if row["version_id"] == str(review.right_version_id))
        reviews.append(
            {
                "review_id": str(review.id),
                "revision": review.revision,
                "left": {"report_id": left["report_id"], "version_id": left["version_id"]},
                "right": {"report_id": right["report_id"], "version_id": right["version_id"]},
                "coverage": "full",
                "reused": review.decision == "flag",
                "spans": review.spans,
            }
        )
    snapshot_input = {
        "scope": {
            "institution_id": str(org_id),
            "course_id": str(course.external_id or course.id),
            "assignment_id": str(assessment_id),
        },
        "reports": reports,
        "reviews": reviews,
    }
    active_result = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.organization_id == org_id,
            ProfAssistMLRelease.model_kind == "plagiarism",
            ProfAssistMLRelease.course_id == course_id,
            ProfAssistMLRelease.assignment_id == assessment_id,
            ProfAssistMLRelease.active.is_(True),
            ProfAssistMLRelease.verified.is_(True),
            ProfAssistMLRelease.gate_passed.is_(True),
        )
        .order_by(ProfAssistMLRelease.created_at.desc())
        .limit(1)
    )
    active = active_result.scalars().first()
    model_name = active.model_name if active else os.getenv("PASSAGE_REUSE_MODEL_NAME", "").strip()
    model_version = (
        active.model_version if active else os.getenv("PASSAGE_REUSE_MODEL_VERSION", "").strip()
    )
    if not model_name or not model_version:
        return {"error": "The approved baseline model is not configured."}
    checksum = _digest(snapshot_input)
    existing = await db.execute(
        select(IntegrityDatasetSnapshot).where(
            IntegrityDatasetSnapshot.organization_id == org_id,
            IntegrityDatasetSnapshot.assessment_id == assessment_id,
            IntegrityDatasetSnapshot.checksum == checksum,
        )
    )
    snapshot = existing.scalars().first()
    if snapshot is None:
        snapshot = IntegrityDatasetSnapshot(
            organization_id=org_id,
            course_id=course_id,
            assessment_id=assessment_id,
            created_by=user_id,
            checksum=checksum,
            report_version_ids=[str(row.id) for row in latest_by_submission.values()],
            review_ids=[str(row.id) for row in eligible],
            status="queued",
        )
        db.add(snapshot)
        await db.flush()
    fingerprint = _digest({"operation": "plagiarism-snapshot", "checksum": checksum})
    job_result = await db.execute(
        select(ProfAssistMLJob).where(
            ProfAssistMLJob.organization_id == org_id,
            ProfAssistMLJob.operation == "plagiarism-snapshot",
            ProfAssistMLJob.input_fingerprint == fingerprint,
        )
    )
    job = job_result.scalars().first()
    if job is not None:
        card = (
            await _dispatch(db, job)
            if job.status == "failed" or (job.status == "queued" and not job.prefect_flow_run_id)
            else _job_card(job)
        )
        return card | {"snapshot_id": str(snapshot.id), "reused": True}
    job = ProfAssistMLJob(
        organization_id=org_id,
        course_id=course_id,
        assignment_id=assessment_id,
        requested_by=user_id,
        operation="plagiarism-snapshot",
        status="queued",
        input_fingerprint=fingerprint,
        source_version_ids=[str(row.id) for row in latest_by_submission.values()],
        model_name=model_name,
        model_version=model_version,
        result={"snapshot_id": str(snapshot.id)},
    )
    card = await _queue(db, job)
    return card | {"snapshot_id": str(snapshot.id), "reused": False}


async def create_training_job(
    db: Any, org_id: uuid.UUID, user_id: uuid.UUID, snapshot_id: uuid.UUID
) -> dict[str, Any]:
    snapshot = await db.get(IntegrityDatasetSnapshot, snapshot_id)
    if (
        snapshot is None
        or snapshot.organization_id != org_id
        or snapshot.status != "completed"
        or not snapshot.manifest_checksum
    ):
        return {"error": "A verified immutable dataset snapshot is required before training."}
    assessment = await db.get(Assessment, snapshot.assessment_id)
    if (
        assessment is None
        or assessment.organization_id != org_id
        or assessment.course_id != snapshot.course_id
        or assessment.owner_user_id not in {None, user_id}
    ):
        return {"error": "Assignment not found."}
    active_result = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.organization_id == org_id,
            ProfAssistMLRelease.model_kind == "plagiarism",
            ProfAssistMLRelease.course_id == snapshot.course_id,
            ProfAssistMLRelease.assignment_id == snapshot.assessment_id,
            ProfAssistMLRelease.active.is_(True),
            ProfAssistMLRelease.verified.is_(True),
            ProfAssistMLRelease.gate_passed.is_(True),
        )
        .order_by(ProfAssistMLRelease.created_at.desc())
        .limit(1)
    )
    active = active_result.scalars().first()
    model_name = active.model_name if active else os.getenv("PASSAGE_REUSE_MODEL_NAME", "").strip()
    model_version = (
        active.model_version if active else os.getenv("PASSAGE_REUSE_MODEL_VERSION", "").strip()
    )
    if not model_name or not model_version:
        return {"error": "A concrete active comparison release is required before training."}
    fingerprint = _digest(
        {
            "operation": "plagiarism-train",
            "snapshot": snapshot.manifest_checksum,
            "model_name": model_name,
            "model_version": model_version,
        }
    )
    existing = await db.execute(
        select(ProfAssistMLJob).where(
            ProfAssistMLJob.organization_id == org_id,
            ProfAssistMLJob.operation == "plagiarism-train",
            ProfAssistMLJob.input_fingerprint == fingerprint,
        )
    )
    job = existing.scalars().first()
    if job:
        card = (
            await _dispatch(db, job)
            if job.status == "failed" or (job.status == "queued" and not job.prefect_flow_run_id)
            else _job_card(job)
        )
        return card | {"reused": True}
    job = ProfAssistMLJob(
        organization_id=org_id,
        course_id=snapshot.course_id,
        assignment_id=snapshot.assessment_id,
        requested_by=user_id,
        operation="plagiarism-train",
        status="queued",
        input_fingerprint=fingerprint,
        source_version_ids=list(snapshot.report_version_ids),
        model_name=model_name,
        model_version=model_version,
        result={"snapshot_id": str(snapshot.id)},
    )
    return await _queue(db, job) | {"reused": False}


async def list_jobs(
    db: Any,
    org_id: uuid.UUID,
    operation: str | None,
    course_id: uuid.UUID | None,
    assessment_id: uuid.UUID | None,
) -> dict[str, Any]:
    statement = (
        select(ProfAssistMLJob)
        .where(ProfAssistMLJob.organization_id == org_id)
        .order_by(ProfAssistMLJob.created_at.desc())
        .limit(100)
    )
    if operation:
        statement = statement.where(ProfAssistMLJob.operation == operation)
    if course_id:
        statement = statement.where(ProfAssistMLJob.course_id == course_id)
    if assessment_id:
        statement = statement.where(ProfAssistMLJob.assignment_id == assessment_id)
    result = await db.execute(statement)
    return {"items": [_job_card(row) for row in result.scalars().all()]}


async def list_releases(
    db: Any,
    org_id: uuid.UUID,
    model_kind: str | None,
    course_id: uuid.UUID | None,
    assessment_id: uuid.UUID | None,
) -> dict[str, Any]:
    statement = (
        select(ProfAssistMLRelease)
        .where(ProfAssistMLRelease.organization_id == org_id)
        .order_by(ProfAssistMLRelease.created_at.desc())
        .limit(100)
    )
    if model_kind:
        statement = statement.where(ProfAssistMLRelease.model_kind == model_kind)
    if course_id:
        statement = statement.where(ProfAssistMLRelease.course_id == course_id)
    if assessment_id:
        statement = statement.where(ProfAssistMLRelease.assignment_id == assessment_id)
    result = await db.execute(statement)
    return {
        "items": [
            {
                "release_id": str(row.id),
                "model_name": row.model_name,
                "model_version": row.model_version,
                "active": row.active,
                "verified": row.verified,
                "gate_passed": row.gate_passed,
                "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "action": row.action,
            }
            for row in result.scalars().all()
        ]
    }


async def change_release(
    db: Any,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    release_id: uuid.UUID,
    reason: str,
    *,
    rollback: bool = False,
) -> dict[str, Any]:
    candidate = await db.get(ProfAssistMLRelease, release_id)
    if candidate is None or candidate.organization_id != org_id:
        return {"error": "Release not found."}
    if not candidate.verified or not candidate.gate_passed:
        return {"error": "Only a verified candidate that passed its gate can be activated."}
    if rollback and (
        candidate.action not in {"approve", "rollback"}
        or candidate.previous_release_id is None
        or candidate.active
    ):
        return {"error": "Rollback requires a previously activated eligible release."}
    if (
        candidate.model_kind != "plagiarism"
        or candidate.course_id is None
        or candidate.assignment_id is None
    ):
        return {"error": "This release scope cannot be activated by the plagiarism control."}
    course = await db.get(Course, candidate.course_id)
    if course is None or course.organization_id != org_id:
        return {"error": "Release scope is unavailable."}
    scope = {
        "institution_id": str(org_id),
        "course_id": str(course.external_id or course.id),
        "assignment_id": str(candidate.assignment_id),
    }
    base = os.getenv("PLAGIARISM_WORKER_URL", "").strip().rstrip("/")
    token = os.getenv("PLAGIARISM_WORKER_TOKEN", "").strip()
    if not base:
        return {"error": "The private worker cannot verify this release."}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    verify_body = {
        "schema_version": 1,
        "operation": "plagiarism-verify-release",
        "context": {
            "job_id": str(uuid.uuid4()),
            "tracking_uri": os.getenv("MLFLOW_TRACKING_URI", "").strip(),
            "model_name": candidate.model_name,
            "version": candidate.model_version,
        },
        "payload": {"scope": scope},
    }
    # Do not hold a database transaction open over an HTTP worker call.
    await db.commit()
    await db.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org_id)})
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{base}/jobs/plagiarism-verify-release", json=verify_body, headers=headers
            )
            response.raise_for_status()
            envelope = response.json()
        verification = envelope.get("result") or {}
        release_data = verification.get("release") or {}
    except Exception:
        return {"error": "The private worker could not verify this release."}
    if (
        envelope.get("schema_version") != 1
        or envelope.get("operation") != "plagiarism-verify-release"
        or envelope.get("status") != "completed"
        or verification.get("scope") != scope
        or release_data.get("platform_scope") != scope
        or release_data.get("model_name") != candidate.model_name
        or str(release_data.get("model_version")) != candidate.model_version
        or release_data.get("model_bundle_sha256") != candidate.model_bundle_sha256
        or not release_data.get("gate_passed")
    ):
        return {"error": "The candidate no longer matches its verified bundle and gate evidence."}
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {
            "key": f"release:{org_id}:{candidate.model_kind}:{candidate.course_id}:{candidate.assignment_id}"
        },
    )
    locked = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.id == release_id,
            ProfAssistMLRelease.organization_id == org_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    candidate = locked.scalars().first()
    if candidate is None or not candidate.verified or not candidate.gate_passed:
        return {"error": "The candidate is no longer eligible."}
    result = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.organization_id == org_id,
            ProfAssistMLRelease.model_kind == candidate.model_kind,
            ProfAssistMLRelease.course_id == candidate.course_id,
            ProfAssistMLRelease.assignment_id == candidate.assignment_id,
            ProfAssistMLRelease.active.is_(True),
        )
        .with_for_update()
    )
    previous = result.scalars().first()
    if previous and previous.id == candidate.id:
        return {
            "release_id": str(previous.id),
            "active": True,
            "model_version": previous.model_version,
            "action": previous.action,
        }
    if rollback and previous is None:
        return {"error": "There is no active release to roll back from."}
    if previous:
        previous.active = False
    if rollback:
        # Candidate is the older verified release requested by the caller.
        target = candidate
        action = "rollback"
    else:
        target = candidate
        action = "approve"
    activated = ProfAssistMLRelease(
        organization_id=org_id,
        model_kind=target.model_kind,
        model_name=target.model_name,
        model_version=target.model_version,
        course_id=target.course_id,
        assignment_id=target.assignment_id,
        snapshot_id=target.snapshot_id,
        model_bundle_sha256=target.model_bundle_sha256,
        gate_evidence=target.gate_evidence,
        gate_passed=True,
        verified=True,
        active=True,
        previous_release_id=previous.id if previous else None,
        action=action,
        actor_user_id=user_id,
        reason=reason.strip(),
    )
    db.add(activated)
    await db.flush()
    return {
        "release_id": str(activated.id),
        "active": True,
        "model_name": activated.model_name,
        "model_version": activated.model_version,
        "action": activated.action,
    }
