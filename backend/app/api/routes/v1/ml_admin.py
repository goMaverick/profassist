"""Admin ML control room.

Read-only views over the honest gateway plus one explicit worker probe. Nothing
here scores a student, invents a metric, or returns the plagiarism worker token
or a credential-bearing URL.
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.api.deps import CurrentAppAdmin, DBSession
from app.profassist.deps import ProfOrg
from app.profassist.ml.gateway import (
    PLAGIARISM_DATA_NEEDED,
    PLAGIARISM_SCHEMA_VERSION,
    dropout_status,
    model_cards,
    plagiarism_status,
)
from app.profassist.tracking import list_registered_models_async, training_metrics

router = APIRouter()


class PlagiarismSnapshotBody(BaseModel):
    course_id: uuid.UUID
    assessment_id: uuid.UUID


class PlagiarismTrainBody(BaseModel):
    snapshot_id: uuid.UUID
    synthetic: bool = False


class ReleaseActionBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


_PROBE_TIMEOUT_SECONDS = 3.5
_PROBE_FAILED = (
    "The plagiarism worker did not answer its health check within 3 seconds. "
    "Check PLAGIARISM_WORKER_URL and the worker log."
)
_PROBE_UNCONFIGURED = (
    "No plagiarism worker URL is configured. Set PLAGIARISM_WORKER_URL in the "
    "server environment and restart the API."
)


def _safe_host(url: str) -> str | None:
    """Return a hostname only when the URL carries no credentials."""
    candidate = (url or "").strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate if "//" in candidate else f"//{candidate}")
    if parsed.username or parsed.password:
        return None
    return parsed.hostname


def _worker_settings() -> dict[str, Any]:
    raw_url = os.getenv("PLAGIARISM_WORKER_URL", "").strip()
    return {
        "worker_url_set": bool(raw_url),
        "worker_token_set": bool(os.getenv("PLAGIARISM_WORKER_TOKEN", "").strip()),
        "worker_host": _safe_host(raw_url),
        "env_only": True,
    }


def _probe_payload(status: dict[str, Any]) -> dict[str, Any]:
    worker_url = str(status.get("worker_url") or "")
    payload: dict[str, Any] = {
        "configured": bool(status.get("configured")),
        "reachable": status.get("reachable"),
        "status": status.get("status"),
        "probe": True,
        "token_set": bool(status.get("token_set")),
        "worker_url_set": bool(worker_url),
        "worker_host": _safe_host(worker_url),
    }
    if not worker_url:
        payload["error"] = _PROBE_UNCONFIGURED
    elif payload["reachable"] is not True:
        payload["error"] = _PROBE_FAILED
    return payload


@router.get("/admin/ml/models")
async def ml_models(user: CurrentAppAdmin, org: ProfOrg) -> dict[str, Any]:
    """Model cards, MLflow reachability, and env-only worker settings."""
    del user, org
    cards = model_cards()
    features = dropout_status().get("features") or []
    for card in cards:
        if card.get("name") == "student-dropout":
            # The gateway card lists the feature contract; the adapter owns the names.
            card["features"] = features
    registry = await list_registered_models_async()
    return {
        "models": cards,
        "mlflow": {
            "reachable": bool(registry.get("reachable")),
            "tracking_uri": registry.get("tracking_uri"),
        },
        "settings": _worker_settings(),
    }


@router.post("/admin/ml/plagiarism/probe")
async def probe_plagiarism_worker(user: CurrentAppAdmin, org: ProfOrg) -> dict[str, Any]:
    """Call the external worker's /health once with a three-second timeout.

    The probe runs in a worker thread so a slow socket cannot block the event
    loop. Any failure is a fixed, redacted message.
    """
    del user, org
    try:
        status = await asyncio.wait_for(
            asyncio.to_thread(plagiarism_status, probe=True),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except Exception:
        return {
            "configured": False,
            "reachable": False,
            "status": "not_installed",
            "probe": True,
            "token_set": bool(os.getenv("PLAGIARISM_WORKER_TOKEN", "").strip()),
            "worker_url_set": bool(os.getenv("PLAGIARISM_WORKER_URL", "").strip()),
            "worker_host": _safe_host(os.getenv("PLAGIARISM_WORKER_URL", "")),
            "error": _PROBE_FAILED,
        }
    return _probe_payload(status)


@router.get("/admin/ml/plagiarism/contract")
async def plagiarism_contract(user: CurrentAppAdmin, org: ProfOrg) -> dict[str, Any]:
    """The static worker JSON contract from docs/ml.md. No secrets, no URLs."""
    del user, org
    return {
        "schema_version": PLAGIARISM_SCHEMA_VERSION,
        "endpoint": "POST {PLAGIARISM_WORKER_URL}/score",
        "timeout_seconds": 60,
        "auth": "Optional Authorization: Bearer <PLAGIARISM_WORKER_TOKEN>.",
        "request": {
            "scope": {"assignment_id": "a1"},
            "reports": [{"report_id": "r1", "document_id": "d1", "text": "..."}],
            "source_reports": [{"report_id": "s1", "document_id": "d2", "text": "..."}],
        },
        "request_notes": {
            "source_reports": "Included only when the caller provides it.",
            "reports": "ProfAssist sends stable report and document ids plus text.",
        },
        "response": {
            "schema_version": PLAGIARISM_SCHEMA_VERSION,
            "scope": {"assignment_id": "a1"},
            "display_flags": [{"report_id": "r1", "severity": "review", "passages": []}],
            "run_id": "worker-run-id",
        },
        "response_notes": {
            "validation": (
                "The gateway requires an object with matching schema_version and "
                "scope and a display_flags list of objects."
            ),
            "failure": (
                "Any network error, non-2xx response, invalid JSON, or contract "
                "violation becomes a fixed 503 with no excerpt or token."
            ),
        },
        "data_needed": PLAGIARISM_DATA_NEEDED,
        "threshold_note": "0.922696 is PAN-specific and must be re-selected for this corpus.",
        "license": "not vendored; external worker required",
    }


@router.get("/admin/ml/jobs")
async def ml_job_list(
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
    operation: str | None = None,
    course_id: uuid.UUID | None = None,
    assessment_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    del user
    from app.profassist.ml.training import list_jobs

    return await list_jobs(db, org.id, operation, course_id, assessment_id)


@router.get("/admin/ml/jobs/{job_id}/metrics")
async def ml_job_metrics(
    job_id: uuid.UUID, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict[str, float | str]:
    from app.profassist.errors import ProfassistError
    from app.profassist.models import ProfAssistMLJob, ProfAssistMLRelease

    del user
    job = await db.get(ProfAssistMLJob, job_id)
    if (
        job is None
        or job.organization_id != org.id
        or job.operation not in {"dropout-train", "plagiarism-train"}
    ):
        raise ProfassistError(404, "Training run not found.")
    if job.status != "completed":
        return {}

    result = job.result or {}
    summary = (result.get("worker_result") or {}).get("summary") or {}
    run_id = result.get("training_run_id") or summary.get("mlflow_run_id")
    if not run_id and result.get("release_id"):
        release = await db.get(ProfAssistMLRelease, uuid.UUID(result["release_id"]))
        if release and release.organization_id == org.id:
            legacy = (release.gate_evidence or {}).get("training_summary") or {}
            run_id = legacy.get("mlflow_run_id")
    return (
        await training_metrics(run_id, job.operation) if isinstance(run_id, str) and run_id else {}
    )


_REVIEW_COLUMNS = (
    "left_version_id",
    "right_version_id",
    "decision",
    "left_start",
    "left_end",
    "right_start",
    "right_end",
    "note",
)
_REVIEW_CSV_LIMIT = 1024 * 1024


def _parse_review_csv(raw: bytes, course_id: uuid.UUID, assessment_id: uuid.UUID) -> list:
    from app.api.routes.v1.profassist import IntegrityReviewBody

    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    if tuple(next(reader, ())) != _REVIEW_COLUMNS:
        raise ValueError("Use the review CSV sample's column headers and order.")
    reviews = []
    seen = set()
    for row in reader:
        line = reader.line_num
        if len(row) != len(_REVIEW_COLUMNS) or len(reviews) >= 500:
            raise ValueError(f"Line {line}: use the sample format and at most 500 reviewed pairs.")
        left, right, decision, *rest = row
        *offsets, note = rest
        decision = decision.strip().lower()
        if (
            decision not in {"ok", "flag"}
            or (decision == "ok" and any(offsets))
            or (decision == "flag" and not all(offsets))
        ):
            raise ValueError(
                f"Line {line}: use ok with blank offsets or flag with all four offsets."
            )
        try:
            review = IntegrityReviewBody(
                course_id=course_id,
                assessment_id=assessment_id,
                left_version_id=left,
                right_version_id=right,
                decision=decision,
                spans=[dict(zip(_REVIEW_COLUMNS[3:7], offsets, strict=True))]
                if decision == "flag"
                else [],
                note=note,
            )
        except ValidationError as exc:
            raise ValueError(
                f"Line {line}: check the report version IDs, offsets, and note."
            ) from exc
        pair = tuple(sorted((review.left_version_id, review.right_version_id)))
        if pair[0] == pair[1] or pair in seen:
            raise ValueError(f"Line {line}: report pairs must be distinct and appear once.")
        seen.add(pair)
        reviews.append((pair, line, review))
    if not reviews:
        raise ValueError("Include at least one reviewed report pair.")
    return sorted(reviews, key=lambda entry: entry[0])


async def _current_review_reports(db, org_id, user_id, course_id, assessment_id):
    from app.profassist.errors import ProfassistError
    from app.profassist.models import Assessment, IntegritySourceVersion, Submission

    assessment = await db.get(Assessment, assessment_id)
    if (
        assessment is None
        or assessment.organization_id != org_id
        or assessment.course_id != course_id
        or assessment.owner_user_id not in {None, user_id}
    ):
        raise ProfassistError(404, "Assignment not found.")
    result = await db.execute(
        select(IntegritySourceVersion, Submission.group_name)
        .join(Submission, Submission.id == IntegritySourceVersion.submission_id)
        .where(
            IntegritySourceVersion.organization_id == org_id,
            IntegritySourceVersion.course_id == course_id,
            IntegritySourceVersion.assessment_id == assessment_id,
            Submission.organization_id == org_id,
        )
        .order_by(IntegritySourceVersion.submission_id, IntegritySourceVersion.version.desc())
    )
    latest = {}
    for version, group in result.all():
        latest.setdefault(version.submission_id, (version, group))
    return list(latest.values())


@router.get("/admin/ml/plagiarism/reviews/report-versions")
async def plagiarism_review_report_versions(
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
    course_id: uuid.UUID,
    assessment_id: uuid.UUID,
) -> dict[str, Any]:
    reports = await _current_review_reports(db, org.id, user.id, course_id, assessment_id)
    return {
        "items": [
            {"version_id": str(version.id), "group": group, "text": version.text_content}
            for version, group in reports
        ]
    }


@router.post("/admin/ml/plagiarism/reviews/import")
async def plagiarism_reviews_import(
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
    course_id: uuid.UUID = Form(...),
    assessment_id: uuid.UUID = Form(...),
    reviews_file: UploadFile = File(...),
) -> dict[str, Any]:
    from app.api.routes.v1.profassist import integrity_review_create
    from app.profassist.errors import ProfassistError
    from app.profassist.ml.training import create_snapshot_job

    raw = await reviews_file.read(_REVIEW_CSV_LIMIT + 1)
    if len(raw) > _REVIEW_CSV_LIMIT:
        raise ProfassistError(422, "Review CSV must be no larger than 1 MiB.")
    try:
        reviews = _parse_review_csv(raw, course_id, assessment_id)
    except (ValueError, csv.Error) as exc:
        raise ProfassistError(422, str(exc)) from exc
    reports = await _current_review_reports(db, org.id, user.id, course_id, assessment_id)
    versions = {version.id for version, _ in reports}
    for pair, line, review in reviews:
        if not set(pair) <= versions:
            raise ProfassistError(
                422, f"Line {line}: use current report versions from this assignment."
            )
        saved = await integrity_review_create(review, user, org, db)
        if not saved.get("saved"):
            raise ProfassistError(422, f"Line {line}: {saved['error']}")
    job = await create_snapshot_job(db, org.id, user.id, course_id, assessment_id)
    return {"review_count": len(reviews), "snapshot_job": job}


@router.post("/admin/ml/plagiarism/text-pairs/import")
async def plagiarism_text_pairs_import(
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
    course_id: uuid.UUID = Form(...),
    assessment_id: uuid.UUID = Form(...),
    text_pairs_file: UploadFile = File(...),
    synthetic: bool = Form(default=False),
) -> dict[str, Any]:
    from app.profassist.errors import ProfassistError
    from app.profassist.ml.text_pairs import MAX_BYTES, parse_text_pairs
    from app.profassist.ml.training import create_text_pair_snapshot

    try:
        reports, reviews = parse_text_pairs(await text_pairs_file.read(MAX_BYTES + 1))
    except (ValueError, csv.Error) as exc:
        raise ProfassistError(422, str(exc)) from exc
    return await create_text_pair_snapshot(
        db, org.id, user.id, course_id, assessment_id, reports, reviews, synthetic=synthetic
    )


@router.post("/admin/ml/plagiarism/snapshot")
async def plagiarism_snapshot_create(
    body: PlagiarismSnapshotBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict[str, Any]:
    from app.profassist.ml.training import create_snapshot_job

    return await create_snapshot_job(db, org.id, user.id, body.course_id, body.assessment_id)


@router.post("/admin/ml/plagiarism/train")
async def plagiarism_train_create(
    body: PlagiarismTrainBody, user: CurrentAppAdmin, org: ProfOrg, db: DBSession
) -> dict[str, Any]:
    from app.profassist.ml.training import create_training_job

    return await create_training_job(
        db, org.id, user.id, body.snapshot_id, synthetic=body.synthetic
    )


@router.get("/admin/ml/releases")
async def ml_release_list(
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
    model_kind: str | None = None,
    course_id: uuid.UUID | None = None,
    assessment_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    del user
    from app.profassist.ml.training import list_releases

    return await list_releases(db, org.id, model_kind, course_id, assessment_id)


@router.post("/admin/ml/releases/{release_id}/approve")
async def ml_release_approve(
    release_id: uuid.UUID,
    body: ReleaseActionBody,
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
) -> dict[str, Any]:
    from app.profassist.ml.training import change_release

    result = await change_release(db, org.id, user.id, release_id, body.reason)
    if "error" in result:
        from app.profassist.errors import ProfassistError

        raise ProfassistError(409, result["error"])
    return result


@router.post("/admin/ml/releases/{release_id}/rollback")
async def ml_release_rollback(
    release_id: uuid.UUID,
    body: ReleaseActionBody,
    user: CurrentAppAdmin,
    org: ProfOrg,
    db: DBSession,
) -> dict[str, Any]:
    from app.profassist.ml.training import change_release

    result = await change_release(db, org.id, user.id, release_id, body.reason, rollback=True)
    if "error" in result:
        from app.profassist.errors import ProfassistError

        raise ProfassistError(409, result["error"])
    return result
