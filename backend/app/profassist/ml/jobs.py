"""Durable orchestration for scoped model jobs.

Only opaque job IDs are sent through Prefect. Private text is reconstructed by
the flow from immutable source-version rows and sent to the internal worker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from typing import Any

import httpx
from prefect import flow
from sqlalchemy import func, select
from sqlalchemy import text as sql_text

from app.db.session import get_db_context
from app.profassist.ml.gateway import worker_job_timeout
from app.profassist.models import (
    Assessment,
    Course,
    IntegrityDatasetSnapshot,
    IntegrityFlag,
    IntegrityPairReview,
    IntegritySourceVersion,
    ProfAssistMLJob,
    ProfAssistMLRelease,
    Submission,
)
from app.profassist.tracking import training_namespace


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(
    versions: list[IntegritySourceVersion], model_name: str, model_version: str
) -> str:
    value = {
        "operation": "plagiarism-score",
        "versions": sorted(str(row.id) for row in versions),
        "model_name": model_name,
        "model_version": model_version,
    }
    return _hash(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _snapshot_review_payload(
    review: IntegrityPairReview, reports_by_version: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """Serialize one immutable review revision for the upstream snapshot contract."""
    left_version, right_version = str(review.left_version_id), str(review.right_version_id)
    left_report, right_report = (
        reports_by_version.get(left_version),
        reports_by_version.get(right_version),
    )
    if left_report is None or right_report is None:
        raise ValueError("snapshot review refers to an unknown source version")
    return {
        "review_id": str(review.id),
        "revision": review.revision,
        "left": {"report_id": left_report["report_id"], "version_id": left_version},
        "right": {"report_id": right_report["report_id"], "version_id": right_version},
        "coverage": "full",
        "reused": review.decision == "flag",
        "spans": review.spans,
    }


def _snapshot_worker_evidence(
    result: dict[str, Any], *, scope: dict[str, str], input_sha256: str
) -> tuple[str, str]:
    """Validate distinct input and derived-corpus hashes from the worker."""
    dataset_sha256 = result.get("dataset_sha256")
    manifest_sha256 = result.get("manifest_sha256")
    if (
        result.get("scope") != scope
        or result.get("input_sha256") != input_sha256
        or not isinstance(dataset_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", dataset_sha256) is None
        or not isinstance(manifest_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is None
    ):
        raise ValueError("worker snapshot evidence mismatch")
    return dataset_sha256, manifest_sha256


async def create_integrity_job(
    db: Any,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    assessment_id: uuid.UUID,
) -> dict[str, Any]:
    # Serialize version numbering and request fingerprint creation per scoped
    # assignment so simultaneous clicks converge on one immutable input set.
    await db.execute(
        sql_text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"{organization_id}:{course_id}:{assessment_id}"},
    )
    course = await db.get(Course, course_id)
    assessment = await db.get(Assessment, assessment_id)
    if (
        course is None
        or assessment is None
        or course.organization_id != organization_id
        or assessment.organization_id != organization_id
        or assessment.course_id != course_id
        or assessment.owner_user_id not in {None, user_id}
    ):
        return {"error": "That assignment is not in this workspace."}

    active_result = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.organization_id == organization_id,
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
    active_release = active_result.scalars().first()
    model_name = (
        active_release.model_name
        if active_release
        else os.getenv("PASSAGE_REUSE_MODEL_NAME", "").strip()
    )
    model_version = (
        active_release.model_version
        if active_release
        else os.getenv("PASSAGE_REUSE_MODEL_VERSION", "").strip()
    )
    if not model_name or not model_version:
        return {"error": "No approved passage reuse model version is active for this scope."}

    rows_result = await db.execute(
        select(Submission)
        .where(
            Submission.organization_id == organization_id,
            Submission.course_id == course_id,
            Submission.assessment_id == assessment_id,
        )
        .order_by(Submission.id)
    )
    submissions = list(rows_result.scalars().all())
    versions: list[IntegritySourceVersion] = []
    from app.profassist.pii import scrub

    for submission in submissions:
        text = scrub(str(submission.scrubbed_text or submission.raw_text or "")).text
        digest = _hash(text)
        existing = await db.execute(
            select(IntegritySourceVersion).where(
                IntegritySourceVersion.organization_id == organization_id,
                IntegritySourceVersion.submission_id == submission.id,
                IntegritySourceVersion.content_hash == digest,
            )
        )
        version = existing.scalars().first()
        if version is None:
            max_result = await db.execute(
                select(func.max(IntegritySourceVersion.version)).where(
                    IntegritySourceVersion.organization_id == organization_id,
                    IntegritySourceVersion.submission_id == submission.id,
                )
            )
            version = IntegritySourceVersion(
                organization_id=organization_id,
                course_id=course_id,
                assessment_id=assessment_id,
                submission_id=submission.id,
                version=int(max_result.scalar() or 0) + 1,
                content_hash=digest,
                text_content=text,
            )
            db.add(version)
            await db.flush()
        versions.append(version)
    if len(versions) < 2:
        return {"error": "At least two reports are needed to compare this assignment."}

    fingerprint = _fingerprint(versions, model_name, model_version)
    found = await db.execute(
        select(ProfAssistMLJob).where(
            ProfAssistMLJob.organization_id == organization_id,
            ProfAssistMLJob.operation == "plagiarism-score",
            ProfAssistMLJob.input_fingerprint == fingerprint,
        )
    )
    job = found.scalars().first()
    created = job is None
    if created:
        job = ProfAssistMLJob(
            organization_id=organization_id,
            course_id=course_id,
            assignment_id=assessment_id,
            requested_by=user_id,
            operation="plagiarism-score",
            status="queued",
            input_fingerprint=fingerprint,
            source_version_ids=[str(row.id) for row in versions],
            model_name=model_name,
            model_version=model_version,
        )
        db.add(job)
        await db.flush()
    should_dispatch = (
        created
        or job.status == "failed"
        or (job.status == "queued" and not job.prefect_flow_run_id)
    )
    if should_dispatch:
        previous_flow_run_id = job.prefect_flow_run_id
        job.status = "queued"
        job.error = ""
        # Prefect may start immediately; make the durable envelope visible first.
        await db.commit()
        try:
            from prefect.deployments import run_deployment

            flow_run = await run_deployment(
                "profassist-ml-job/ml-job",
                parameters={"job_id": str(job.id)},
                timeout=0,
                idempotency_key=(
                    f"{job.id}:{previous_flow_run_id}" if previous_flow_run_id else str(job.id)
                ),
            )
            job.prefect_flow_run_id = str(getattr(flow_run, "id", "") or "")
        except Exception:
            job.status = "failed"
            job.error = "The model job could not be queued. Please retry."
        await db.execute(
            sql_text("SELECT set_config('app.current_org', :org, true)"),
            {"org": str(organization_id)},
        )
        await db.flush()
    return {
        "job_id": str(job.id),
        "status": job.status,
        "assignment_id": str(assessment_id),
        "model_version": job.model_version,
        "reused": not created,
    }


async def get_job(
    db: Any, organization_id: uuid.UUID, user_id: uuid.UUID, job_id: uuid.UUID
) -> dict[str, Any] | None:
    row = await db.get(ProfAssistMLJob, job_id)
    if row is None or row.organization_id != organization_id:
        return None
    if row.requested_by != user_id:
        assessment = await db.get(Assessment, row.assignment_id) if row.assignment_id else None
        if (
            assessment is None
            or assessment.organization_id != organization_id
            or assessment.owner_user_id not in {None, user_id}
        ):
            return None
    return {
        "job_id": str(row.id),
        "status": row.status,
        "operation": row.operation,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "error": row.error or None,
        "snapshot_id": (row.result or {}).get("snapshot_id"),
        "release_id": (row.result or {}).get("release_id"),
        "gate_passed": (row.result or {}).get("gate_passed"),
        "input_sha256": (row.result or {}).get("input_sha256"),
        "dataset_sha256": (row.result or {}).get("dataset_sha256"),
        "manifest_sha256": (row.result or {}).get("manifest_sha256"),
    }


@flow(name="profassist-ml-job", log_prints=True)
async def profassist_ml_job_flow(job_id: str) -> dict[str, Any]:
    """Load durable inputs, call private worker, and atomically persist evidence."""
    # Prefect serializes the flow function in a clean subprocess, so a module
    # side-effect import is not sufficient to register FK targets there.
    import app.db.models  # noqa: F401

    try:
        job_uuid = uuid.UUID(job_id)
    except (ValueError, TypeError):
        return {"ok": False, "error": "invalid job"}
    async with get_db_context() as db:
        job = await db.get(ProfAssistMLJob, job_uuid)
        if job is None:
            return {"ok": False, "error": "job not found"}
        if job.status == "completed":
            return {"ok": True, "job_id": job_id, "status": job.status}
        job.status = "running"
        job.error = ""
        await db.flush()
        versions_result = await db.execute(
            select(IntegritySourceVersion).where(
                IntegritySourceVersion.organization_id == job.organization_id,
                IntegritySourceVersion.id.in_(
                    [uuid.UUID(value) for value in job.source_version_ids]
                ),
            )
        )
        versions_by_id = {str(row.id): row for row in versions_result.scalars().all()}
        versions = [
            versions_by_id[version_id]
            for version_id in job.source_version_ids
            if version_id in versions_by_id
        ]
        submissions_result = await db.execute(
            select(Submission).where(
                Submission.organization_id == job.organization_id,
                Submission.id.in_([row.submission_id for row in versions]),
            )
        )
        submissions = {str(row.id): row for row in submissions_result.scalars().all()}
        reports = []
        for version in versions:
            submission = submissions.get(str(version.submission_id))
            if submission is not None:
                reports.append(
                    {
                        "report_id": str(submission.id),
                        "version_id": str(version.id),
                        "text": version.text_content,
                    }
                )
        if len(reports) < 2:
            job.status = "failed"
            job.error = "The assignment inputs are no longer available. Please retry."
            return {"ok": False, "status": job.status}
        course = await db.get(Course, job.course_id)
        scope = {
            "institution_id": str(job.organization_id),
            "course_id": str(getattr(course, "external_id", "") or job.course_id),
            "assignment_id": str(job.assignment_id),
        }
        context: dict[str, Any] = {
            "job_id": job_id,
            "model_name": job.model_name,
            "version": job.model_version,
            "scope": scope,
        }
        if job.operation == "plagiarism-score":
            payload: dict[str, Any] = {"scope": scope, "reports": reports}
        elif job.operation == "plagiarism-snapshot":
            snapshot = await db.get(IntegrityDatasetSnapshot, uuid.UUID(job.result["snapshot_id"]))
            if snapshot is None or snapshot.organization_id != job.organization_id:
                job.status = "failed"
                job.error = "The dataset snapshot is unavailable. Please retry."
                return {"ok": False, "status": job.status}
            review_result = await db.execute(
                select(IntegrityPairReview).where(
                    IntegrityPairReview.organization_id == job.organization_id,
                    IntegrityPairReview.id.in_([uuid.UUID(value) for value in snapshot.review_ids]),
                )
            )
            reports_by_version = {row["version_id"]: row for row in reports}
            reviews_by_id = {str(review.id): review for review in review_result.scalars().all()}
            if set(reviews_by_id) != set(snapshot.review_ids):
                job.status = "failed"
                job.error = "The frozen review revisions are unavailable. Please retry."
                return {"ok": False, "status": job.status}
            review_payload = [
                _snapshot_review_payload(reviews_by_id[review_id], reports_by_version)
                for review_id in snapshot.review_ids
            ]
            context = {"job_id": job_id, "scope": scope}
            payload = {"scope": scope, "reports": reports, "reviews": review_payload}
        elif job.operation == "plagiarism-train":
            snapshot = await db.get(IntegrityDatasetSnapshot, uuid.UUID(job.result["snapshot_id"]))
            if (
                snapshot is None
                or snapshot.organization_id != job.organization_id
                or not snapshot.manifest_checksum
            ):
                job.status = "failed"
                job.error = "The dataset manifest is unavailable. Please retry."
                return {"ok": False, "status": job.status}
            context = {
                "job_id": job_id,
                "scope": scope,
                "tracking_uri": os.getenv("MLFLOW_TRACKING_URI", "").strip(),
                "model_name": job.model_name,
                "version": job.model_version,
            }
            payload = {"snapshot_manifest_sha256": snapshot.manifest_checksum}
        else:
            job.status = "failed"
            job.error = "Unsupported model operation."
            return {"ok": False, "status": job.status}
        body = {
            "schema_version": 1,
            "operation": job.operation,
            "context": context,
            "payload": payload,
        }
        # Release the read transaction and make running visible before the
        # potentially slow private worker request.
        await db.commit()
        try:
            base = os.getenv("PLAGIARISM_WORKER_URL", "").strip().rstrip("/")
            token = os.getenv("PLAGIARISM_WORKER_TOKEN", "").strip()
            if not base:
                raise RuntimeError("worker is unconfigured")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            async with httpx.AsyncClient(timeout=worker_job_timeout()) as client:
                response = await client.post(
                    f"{base}/jobs/{job.operation}", json=body, headers=headers
                )
                response.raise_for_status()
                output = response.json()
            if (
                output.get("schema_version") != 1
                or output.get("operation") != job.operation
                or output.get("status") != "completed"
                or not isinstance(output.get("result"), dict)
            ):
                raise ValueError("invalid worker response")
            await db.execute(
                sql_text("SELECT set_config('app.current_org', :org, true)"),
                {"org": str(job.organization_id)},
            )
            result = output["result"]
            if job.operation == "plagiarism-snapshot":
                snapshot = await db.get(
                    IntegrityDatasetSnapshot, uuid.UUID(job.result["snapshot_id"])
                )
                if snapshot is None:
                    raise ValueError("worker snapshot evidence mismatch")
                dataset_sha256, manifest_sha256 = _snapshot_worker_evidence(
                    result, scope=scope, input_sha256=snapshot.checksum
                )
                snapshot.manifest_checksum = manifest_sha256
                snapshot.status = "completed"
                job.result = {
                    "snapshot_id": str(snapshot.id),
                    "input_sha256": result["input_sha256"],
                    "dataset_sha256": dataset_sha256,
                    "manifest_sha256": manifest_sha256,
                    "review_count": int(result.get("review_count") or 0),
                }
                job.status = "completed"
                await db.flush()
                return {"ok": True, "job_id": job_id, "status": job.status}
            if job.operation == "plagiarism-train":
                snapshot = await db.get(
                    IntegrityDatasetSnapshot, uuid.UUID(job.result["snapshot_id"])
                )
                summary = result.get("summary", result)
                if not isinstance(summary, dict) or snapshot is None:
                    raise ValueError("worker training result incomplete")
                if "summary" in result and (
                    summary.get("platform_scope") != scope
                    or summary.get("platform_snapshot_sha256") != snapshot.manifest_checksum
                ):
                    raise ValueError("worker training result does not match the training dataset")
                if summary.get("gate_passed") is False and not summary.get("candidate_version"):
                    job.result = {
                        "snapshot_id": str(snapshot.id),
                        "gate_passed": False,
                        "training_run_id": summary.get("mlflow_run_id"),
                    }
                    job.status = "completed"
                    await db.flush()
                    return {"ok": True, "job_id": job_id, "status": job.status, "gate_passed": False}
                candidate_version = str(
                    summary.get("candidate_version") or summary.get("model_version") or ""
                )
                candidate_name = str(summary.get("model_name") or "")
                if "summary" in result:
                    if not candidate_name and isinstance(summary.get("mlflow_run_id"), str):
                        candidate_name = await training_namespace(summary["mlflow_run_id"])
                    expected_corpus = snapshot.manifest_checksum
                else:
                    candidate_name = candidate_name or job.model_name
                    expected_corpus = snapshot.checksum
                    if candidate_name != job.model_name:
                        raise ValueError("worker training model name mismatch")
                if not candidate_version or not candidate_name:
                    raise ValueError("worker training result incomplete")
                verify_body = {
                    "schema_version": 1,
                    "operation": "plagiarism-verify-release",
                    "context": {
                        "job_id": str(uuid.uuid5(job_uuid, "verify-release")),
                        "tracking_uri": os.getenv("MLFLOW_TRACKING_URI", "").strip(),
                        "model_name": candidate_name,
                        "version": candidate_version,
                    },
                    "payload": {"scope": scope},
                }
                async with httpx.AsyncClient(timeout=worker_job_timeout()) as client:
                    verified_response = await client.post(
                        f"{base}/jobs/plagiarism-verify-release", json=verify_body, headers=headers
                    )
                    verified_response.raise_for_status()
                    verified_envelope = verified_response.json()
                verified = (
                    verified_envelope.get("result")
                    if (
                        verified_envelope.get("schema_version") == 1
                        and verified_envelope.get("operation") == "plagiarism-verify-release"
                        and verified_envelope.get("status") == "completed"
                    )
                    else None
                )
                release_data = (verified or {}).get("release") or {}
                if (
                    verified is None
                    or verified.get("scope") != scope
                    or release_data.get("model_name") != candidate_name
                    or str(release_data.get("model_version")) != candidate_version
                    or release_data.get("platform_scope") != scope
                    or release_data.get("training_corpus_sha256") != expected_corpus
                    or not isinstance(release_data.get("model_bundle_sha256"), str)
                    or len(release_data["model_bundle_sha256"]) != 64
                ):
                    raise ValueError("worker release verification failed")
                gate_passed = bool(release_data.get("gate_passed")) and bool(
                    summary.get("gate_passed", True)
                )
                release = ProfAssistMLRelease(
                    organization_id=job.organization_id,
                    model_kind="plagiarism",
                    model_name=candidate_name,
                    model_version=candidate_version,
                    course_id=job.course_id,
                    assignment_id=job.assignment_id,
                    snapshot_id=snapshot.id,
                    model_bundle_sha256=release_data["model_bundle_sha256"],
                    gate_evidence={
                        "gate_passed": gate_passed,
                        "gate_report_artifact": release_data.get("gate_report_artifact"),
                        "gate_report_sha256": release_data.get("gate_report_sha256"),
                        "training_corpus_sha256": release_data.get("training_corpus_sha256"),
                        "training_summary": summary,
                    },
                    gate_passed=gate_passed,
                    verified=True,
                    active=False,
                    action="candidate",
                )
                db.add(release)
                job.result = {
                    "snapshot_id": str(snapshot.id),
                    "release_id": str(release.id),
                    "candidate_version": candidate_version,
                    "gate_passed": gate_passed,
                    "training_run_id": summary.get("mlflow_run_id"),
                }
                job.status = "completed"
                await db.flush()
                return {
                    "ok": True,
                    "job_id": job_id,
                    "status": job.status,
                    "gate_passed": gate_passed,
                }
            flags = result.get("display_flags")
            if not isinstance(flags, list):
                raise ValueError("invalid score result")
            by_report = {item["report_id"]: item for item in reports}
            version_by_report = {item["report_id"]: item["version_id"] for item in reports}
            if result.get("scope") != scope:
                raise ValueError("worker scope mismatch")
            worker_model = result.get("model") or {}
            if worker_model.get("name") != job.model_name or str(
                worker_model.get("version")
            ) != str(job.model_version):
                raise ValueError("worker model mismatch")
            pending_flags: list[IntegrityFlag] = []
            seen_pairs: set[tuple[str, str]] = set()
            for flag in flags:
                report_a = flag.get("report_a") if isinstance(flag.get("report_a"), dict) else {}
                report_b = flag.get("report_b") if isinstance(flag.get("report_b"), dict) else {}
                left_id = str(
                    flag.get("left_report_id")
                    or flag.get("report_a_id")
                    or report_a.get("report_id")
                    or ""
                )
                right_id = str(
                    flag.get("right_report_id")
                    or flag.get("report_b_id")
                    or report_b.get("report_id")
                    or ""
                )
                if left_id not in by_report or right_id not in by_report or left_id == right_id:
                    raise ValueError("worker returned an unknown report")
                if not report_a or not report_b:
                    raise ValueError("worker omitted report provenance")
                if report_a.get("version_id") != version_by_report[left_id]:
                    raise ValueError("worker source version mismatch")
                if report_b.get("version_id") != version_by_report[right_id]:
                    raise ValueError("worker source version mismatch")
                left = submissions.get(left_id)
                right = submissions.get(right_id)
                if left is None or right is None or left.group_name == right.group_name:
                    continue
                seen_pairs.add(tuple(sorted((left_id, right_id))))
                passages = flag.get("passages") or []
                if not passages and isinstance(flag.get("representative"), dict):
                    representative = flag["representative"]
                    passages = [
                        {
                            "left": representative.get("matched_text")
                            or representative.get("query_text")
                            or "",
                            "right": representative.get("matched_text")
                            or representative.get("source_text")
                            or "",
                            "score": representative.get("review_score") or flag.get("score") or 0,
                        }
                    ]
                for passage in passages:
                    side_a = passage.get("left") if isinstance(passage.get("left"), dict) else {}
                    side_b = passage.get("right") if isinstance(passage.get("right"), dict) else {}
                    text_a = side_a.get("text") if side_a else passage.get("left")
                    text_b = side_b.get("text") if side_b else passage.get("right")
                    raw_score = float(
                        passage.get("score") or passage.get("similarity") or flag.get("score") or 0
                    )
                    if raw_score > 1:
                        raw_score /= 100
                    start_a, end_a = side_a.get("start"), side_a.get("end")
                    start_b, end_b = side_b.get("start"), side_b.get("end")
                    if None not in (start_a, end_a):
                        if (
                            not isinstance(start_a, int)
                            or not isinstance(end_a, int)
                            or not (0 <= start_a < end_a <= len(by_report[left_id]["text"]))
                        ):
                            raise ValueError("worker offset invalid")
                        if text_a and by_report[left_id]["text"][start_a:end_a] != text_a:
                            raise ValueError("worker excerpt mismatch")
                    if None not in (start_b, end_b):
                        if (
                            not isinstance(start_b, int)
                            or not isinstance(end_b, int)
                            or not (0 <= start_b < end_b <= len(by_report[right_id]["text"]))
                        ):
                            raise ValueError("worker offset invalid")
                        if text_b and by_report[right_id]["text"][start_b:end_b] != text_b:
                            raise ValueError("worker excerpt mismatch")
                    if start_a is None or start_b is None:
                        raise ValueError("worker offsets missing")
                    if (
                        side_a.get("report_id") != left_id
                        or side_a.get("version_id") != version_by_report[left_id]
                        or side_b.get("report_id") != right_id
                        or side_b.get("version_id") != version_by_report[right_id]
                    ):
                        raise ValueError("worker passage provenance mismatch")
                    pending_flags.append(
                        IntegrityFlag(
                            organization_id=job.organization_id,
                            course_id=job.course_id,
                            owner_user_id=None,
                            left_submission_id=left.id,
                            right_submission_id=right.id,
                            section=str(passage.get("section") or "body")[:64],
                            passage_a=str(text_a or passage.get("text_a") or "")[:10000],
                            passage_b=str(text_b or passage.get("text_b") or "")[:10000],
                            score=raw_score,
                            kind="worker",
                            source="worker",
                            job_id=job.id,
                            left_version_id=uuid.UUID(version_by_report[left_id]),
                            right_version_id=uuid.UUID(version_by_report[right_id]),
                            left_start=start_a,
                            left_end=end_a,
                            right_start=start_b,
                            right_end=end_b,
                            status="open",
                        )
                    )
            # A successful worker result covers clear pairs too. Persist a zero
            # coverage row so the board does not silently fill those pairs with
            # the legacy heuristic after an authoritative score.
            for index, left_report in enumerate(reports):
                for right_report in reports[index + 1 :]:
                    left_id, right_id = left_report["report_id"], right_report["report_id"]
                    pair_key = tuple(sorted((left_id, right_id)))
                    if pair_key in seen_pairs:
                        continue
                    left = submissions.get(left_id)
                    right = submissions.get(right_id)
                    if left is None or right is None or left.group_name == right.group_name:
                        continue
                    pending_flags.append(
                        IntegrityFlag(
                            organization_id=job.organization_id,
                            course_id=job.course_id,
                            owner_user_id=None,
                            left_submission_id=left.id,
                            right_submission_id=right.id,
                            section="coverage",
                            passage_a="",
                            passage_b="",
                            score=0,
                            kind="worker",
                            source="worker",
                            job_id=job.id,
                            left_version_id=uuid.UUID(version_by_report[left_id]),
                            right_version_id=uuid.UUID(version_by_report[right_id]),
                            status="open",
                        )
                    )
            # Replace only the previous worker result for this exact assignment.
            old_result = await db.execute(
                select(IntegrityFlag)
                .join(ProfAssistMLJob, IntegrityFlag.job_id == ProfAssistMLJob.id)
                .where(
                    IntegrityFlag.organization_id == job.organization_id,
                    IntegrityFlag.course_id == job.course_id,
                    ProfAssistMLJob.assignment_id == job.assignment_id,
                    IntegrityFlag.source == "worker",
                    IntegrityFlag.status == "open",
                )
            )
            for previous in old_result.scalars().all():
                previous.status = "superseded"
            db.add_all(pending_flags)
            job.result = {"flag_count": len(flags), "run_id": str(result.get("run_id") or "")}
            job.status = "completed"
            await db.flush()
            return {"ok": True, "job_id": job_id, "status": job.status, "flag_count": len(flags)}
        except Exception:
            await db.execute(
                sql_text("SELECT set_config('app.current_org', :org, true)"),
                {"org": str(job.organization_id)},
            )
            job.status = "failed"
            job.error = "The private model worker could not score this assignment. Please retry."
            await db.flush()
            return {"ok": False, "job_id": job_id, "status": job.status}
