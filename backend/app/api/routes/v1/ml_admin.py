"""Admin ML control room.

Read-only views over the honest gateway plus one explicit worker probe. Nothing
here scores a student, invents a metric, or returns the plagiarism worker token
or a credential-bearing URL.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter
from pydantic import BaseModel, Field

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
) -> dict[str, float]:
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

    return await create_training_job(db, org.id, user.id, body.snapshot_id)


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
