"""Scoped import, job orchestration, and release controls for Moodle dropout exports."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import pandas as pd
from prefect import flow
from sqlalchemy import select, text

from app.db.session import get_db_context
from app.profassist.dropout_models import (
    ProfAssistDropoutExport,
    ProfAssistDropoutIdentity,
    ProfAssistDropoutPrediction,
)
from app.profassist.ml.dropout.upstream.validation import (
    KEY_COLUMNS,
    _timestamp,
    _validate_outcome_frame,
    validate_snapshot_frame,
)
from app.profassist.ml.gateway import worker_job_timeout
from app.profassist.models import Approval, Course, ProfAssistMLJob, ProfAssistMLRelease, Student

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 96 * 1024 * 1024
SHA256_LENGTH = 64


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _manifest_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    ).encode("utf-8")


def _json(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"{label} contains a duplicate JSON field")
            out[key] = value
        return out

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _frame(raw: bytes, label: str) -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"{label} is not a valid UTF-8 CSV") from exc


def _validate_manifest(
    manifest: dict[str, Any],
    snapshot_bytes: bytes,
    outcome_bytes: bytes | None,
    *,
    org_id: uuid.UUID,
) -> tuple[str, list[str], dict[str, list[str]]]:
    if manifest.get("schema_version") != "1.0" or manifest.get("synthetic") is not False:
        raise ValueError(
            "Only a non-synthetic Moodle export with schema_version 1.0 can be imported."
        )
    export_id = manifest.get("export_id")
    if not isinstance(export_id, str) or not export_id.strip() or len(export_id) > 128:
        raise ValueError("Export manifest needs a non-empty export_id.")
    if manifest.get("platform_scope") != {"tenant_id": str(org_id)}:
        raise ValueError("Export manifest tenant scope does not match this workspace.")
    for key in (
        "exported_at",
        "timezone",
        "extraction_version",
        "included_event_categories",
        "coverage_limitations",
        "row_counts",
        "cohorts",
        "files",
    ):
        if key not in manifest:
            raise ValueError(f"Export manifest is missing {key}.")
    if manifest.get("timezone") != "UTC" or not isinstance(
        manifest.get("included_event_categories"), list
    ):
        raise ValueError("Export manifest must declare UTC and included Moodle event categories.")
    exported_at = manifest.get("exported_at")
    if not isinstance(exported_at, str):
        raise ValueError("Export manifest exported_at must be a UTC ISO 8601 timestamp.")
    try:
        exported_datetime = datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Export manifest exported_at must be a UTC ISO 8601 timestamp.") from exc
    if exported_datetime.tzinfo is None or exported_datetime.utcoffset() != timedelta(0):
        raise ValueError("Export manifest exported_at must be a UTC ISO 8601 timestamp.")
    if not isinstance(manifest.get("coverage_limitations"), list):
        raise ValueError("Export coverage_limitations must be an array.")
    files = manifest.get("files")
    allowed_files = {"raw/lms_snapshots.csv", "raw/student_outcomes.csv"}
    expected_files = (
        {"raw/lms_snapshots.csv", "raw/student_outcomes.csv"}
        if outcome_bytes is not None
        else {"raw/lms_snapshots.csv"}
    )
    if (
        not isinstance(files, dict)
        or not expected_files <= set(files)
        or set(files) - allowed_files
    ):
        raise ValueError(
            "Manifest checksums must name the snapshot export and, when training, its outcome export."
        )
    if outcome_bytes is not None and set(files) != expected_files:
        raise ValueError("Training manifest must checksum exactly the snapshot and outcome files.")
    expected_hashes = {"raw/lms_snapshots.csv": _sha(snapshot_bytes)}
    if outcome_bytes is not None:
        expected_hashes["raw/student_outcomes.csv"] = _sha(outcome_bytes)
    for path, digest in expected_hashes.items():
        details = files.get(path)
        if not isinstance(details, dict) or details.get("sha256") != digest:
            raise ValueError(f"Manifest checksum does not match {path}.")
    if outcome_bytes is None and "raw/student_outcomes.csv" in files:
        outcome_digest = (files["raw/student_outcomes.csv"] or {}).get("sha256")
        if (
            not isinstance(outcome_digest, str)
            or len(outcome_digest) != SHA256_LENGTH
            or any(char not in "0123456789abcdef" for char in outcome_digest)
        ):
            raise ValueError("Manifest outcome checksum must be a lowercase SHA-256 digest.")
    cohorts = manifest.get("cohorts")
    if (
        not isinstance(cohorts, list)
        or not cohorts
        or not all(isinstance(value, str) and value for value in cohorts)
    ):
        raise ValueError("Manifest cohorts must be a non-empty ordered array.")
    if len(set(cohorts)) != len(cohorts):
        raise ValueError("Manifest cohort identifiers must be unique.")
    split = manifest.get("split")
    if outcome_bytes is not None:
        if not isinstance(split, dict) or any(
            not isinstance(split.get(key), list) or not split[key]
            for key in ("train", "validation", "test")
        ):
            raise ValueError(
                "Training manifest needs explicit train, validation, and test cohort lists."
            )
        declared = split["train"] + split["validation"] + split["test"]
        if len(set(declared)) != len(declared) or set(declared) != set(cohorts):
            raise ValueError("Manifest cohort splits must cover each declared cohort exactly once.")
        if [cohorts.index(item) for item in declared] != sorted(
            cohorts.index(item) for item in declared
        ):
            raise ValueError("Manifest cohort splits must be chronological.")
    else:
        split = split if isinstance(split, dict) else {}
    return (
        export_id,
        cohorts,
        {
            key: list(value)
            for key, value in split.items()
            if key in {"train", "validation", "test"} and isinstance(value, list)
        },
    )


def _validate_rows(
    snapshot_bytes: bytes,
    outcome_bytes: bytes | None,
    manifest: dict[str, Any],
    *,
    org_id: uuid.UUID,
    course: Course,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    snapshots = _frame(snapshot_bytes, "Snapshot export")
    validate_snapshot_frame(snapshots)
    if set(snapshots["tenant_id"].astype(str)) != {str(org_id)}:
        raise ValueError("Snapshot rows must belong to this workspace tenant.")
    expected_course = str(course.external_id or "").strip()
    if not expected_course or set(snapshots["course_id"].astype(str)) != {expected_course}:
        raise ValueError("Snapshot course_id must match the selected Moodle course.")
    cohort_values = list(dict.fromkeys(snapshots["cohort_id"].astype(str).tolist()))
    if set(cohort_values) != set(manifest["cohorts"]):
        raise ValueError("Snapshot cohort IDs do not match the manifest.")
    starts: dict[str, datetime] = {}
    for cohort in manifest["cohorts"]:
        rows = snapshots.loc[snapshots["cohort_id"].astype(str) == cohort]
        cohort_starts, cutoffs = set(), set()
        for idx, row in rows.iterrows():
            cohort_starts.add(_timestamp(row["course_start_at"], "course_start_at", idx, []))
            cutoffs.add(_timestamp(row["snapshot_at"], "snapshot_at", idx, []))
        if len(cohort_starts) != 1 or len(cutoffs) != 1 or None in cohort_starts or None in cutoffs:
            raise ValueError(
                f"Cohort {cohort} has inconsistent course starts or cutoff timestamps."
            )
        start, cutoff = next(iter(cohort_starts)), next(iter(cutoffs))
        if cutoff - start != timedelta(days=35):
            raise ValueError(f"Cohort {cohort} must represent the course day-35 cutoff.")
        starts[cohort] = start
    if list(starts.values()) != sorted(starts.values()):
        raise ValueError(
            "Manifest cohorts are not chronological by their parsed course start times."
        )
    row_counts = manifest["row_counts"]
    if row_counts.get("lms_snapshots") != len(snapshots):
        raise ValueError("Manifest snapshot row count does not match the CSV.")
    outcomes = None
    if outcome_bytes is not None:
        outcomes = _frame(outcome_bytes, "Outcome export")
        _validate_outcome_frame(outcomes)
        if set(outcomes["tenant_id"].astype(str)) != {str(org_id)} or set(
            outcomes["course_id"].astype(str)
        ) != {expected_course}:
            raise ValueError("Outcome rows must match this workspace tenant and Moodle course.")
        if row_counts.get("student_outcomes") != len(outcomes) or len(outcomes) != len(snapshots):
            raise ValueError("Manifest outcome row count does not match its CSV or snapshot rows.")
        left = set(map(tuple, snapshots.loc[:, KEY_COLUMNS].astype(str).to_numpy()))
        right = set(map(tuple, outcomes.loc[:, KEY_COLUMNS].astype(str).to_numpy()))
        if left != right:
            raise ValueError("Outcome rows must exactly match snapshot join keys.")
        indexed = outcomes.set_index(list(KEY_COLUMNS), verify_integrity=True)
        for _, snapshot in snapshots.iterrows():
            key = tuple(str(snapshot[column]) for column in KEY_COLUMNS)
            outcome = indexed.loc[key]
            cutoff = _timestamp(snapshot["snapshot_at"], "snapshot_at", key, [])
            end = _timestamp(snapshot["course_end_at"], "course_end_at", key, [])
            withdrawn = _timestamp(outcome["withdrawn_at"], "withdrawn_at", key, [], blank_ok=True)
            observed = _timestamp(outcome["outcome_observed_at"], "outcome_observed_at", key, [])
            if outcome["final_outcome"] == "withdrawn" and (
                withdrawn is None or not cutoff < withdrawn <= end
            ):
                raise ValueError(
                    "Withdrawn outcomes must be after the cutoff and no later than course end."
                )
            if outcome["final_outcome"] in {"completed", "failed"} and observed < end + timedelta(
                days=14
            ):
                raise ValueError(
                    "Completed and failed outcomes must be mature through course end plus 14 days."
                )
    return snapshots, outcomes


async def import_export(
    db: Any,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    snapshot_bytes: bytes,
    manifest_bytes: bytes,
    outcome_bytes: bytes | None,
) -> dict[str, Any]:
    if (
        not snapshot_bytes
        or not manifest_bytes
        or len(snapshot_bytes) > MAX_FILE_BYTES
        or len(manifest_bytes) > 1024 * 1024
    ):
        return {"error": "Upload a day-35 snapshot CSV and a small export manifest."}
    if outcome_bytes is not None and len(outcome_bytes) > MAX_FILE_BYTES:
        return {"error": "Outcome export exceeds the 32 MiB limit."}
    if (
        len(snapshot_bytes) + len(manifest_bytes) + (len(outcome_bytes) if outcome_bytes else 0)
        > MAX_TOTAL_BYTES
    ):
        return {"error": "Combined export exceeds the 96 MiB limit."}
    course = await db.get(Course, course_id)
    if course is None or course.organization_id != org_id:
        return {"error": "Course not found in this workspace."}
    manifest = _json(manifest_bytes, "Export manifest")
    export_id, cohorts, split = _validate_manifest(
        manifest, snapshot_bytes, outcome_bytes, org_id=org_id
    )
    snapshots, outcomes = _validate_rows(
        snapshot_bytes, outcome_bytes, manifest, org_id=org_id, course=course
    )
    canonical_manifest = _manifest_bytes(manifest)
    combined_checksum = _sha(
        _canonical(
            {
                "manifest_sha256": _sha(canonical_manifest),
                "snapshots_sha256": _sha(snapshot_bytes),
                "outcomes_sha256": _sha(outcome_bytes or b""),
            }
        )
    )
    existing = await db.execute(
        select(ProfAssistDropoutExport).where(
            ProfAssistDropoutExport.organization_id == org_id,
            ProfAssistDropoutExport.course_id == course_id,
            ProfAssistDropoutExport.checksum == combined_checksum,
        )
    )
    row = existing.scalars().first()
    created = row is None
    if row is None:
        row = ProfAssistDropoutExport(
            organization_id=org_id,
            course_id=course_id,
            created_by=user_id,
            external_export_id=export_id,
            schema_version="1.0",
            checksum=combined_checksum,
            manifest_checksum=_sha(canonical_manifest),
            snapshots_sha256=_sha(snapshot_bytes),
            outcomes_sha256=_sha(outcome_bytes or b""),
            snapshots_csv=snapshot_bytes.decode("utf-8"),
            outcomes_csv=(outcome_bytes or b"").decode("utf-8"),
            manifest=manifest,
            cohorts=cohorts,
            row_count=len(snapshots),
            outcome_count=len(outcomes or []),
            status="validated",
        )
        db.add(row)
        await db.flush()
    return _export_card(row) | {"split": split, "reused": not created}


def _export_card(row: ProfAssistDropoutExport) -> dict[str, Any]:
    manifest = row.manifest or {}
    split = manifest.get("split") or {}
    return {
        "export_id": str(row.id),
        "course_id": str(row.course_id),
        "external_export_id": row.external_export_id,
        "schema_version": row.schema_version,
        "cohorts": list(row.cohorts or []),
        "split": split,
        "train_cohorts": split.get("train", []),
        "validation_cohorts": split.get("validation", []),
        "test_cohorts": split.get("test", []),
        "row_count": row.row_count,
        "outcome_count": row.outcome_count,
        "checksum": row.checksum,
        "manifest_checksum": row.manifest_checksum,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_exports(db: Any, org_id: uuid.UUID, course_id: uuid.UUID | None) -> dict[str, Any]:
    statement = (
        select(ProfAssistDropoutExport)
        .where(ProfAssistDropoutExport.organization_id == org_id)
        .order_by(ProfAssistDropoutExport.created_at.desc())
        .limit(100)
    )
    if course_id:
        statement = statement.where(ProfAssistDropoutExport.course_id == course_id)
    result = await db.execute(statement)
    return {"items": [_export_card(row) for row in result.scalars().all()]}


async def list_dropout_jobs(
    db: Any, org_id: uuid.UUID, course_id: uuid.UUID | None = None
) -> dict[str, Any]:
    statement = (
        select(ProfAssistMLJob)
        .where(
            ProfAssistMLJob.organization_id == org_id,
            ProfAssistMLJob.operation.in_(("dropout-score", "dropout-train", "dropout-monitor")),
        )
        .order_by(ProfAssistMLJob.created_at.desc())
        .limit(100)
    )
    if course_id is not None:
        statement = statement.where(
            (ProfAssistMLJob.course_id == course_id) | ProfAssistMLJob.course_id.is_(None)
        )
    result = await db.execute(statement)
    items = []
    for job in result.scalars().all():
        worker = (job.result or {}).get("worker_result") or {}
        summary = worker.get("summary") or {}
        items.append(
            {
                **_job_card(job),
                "model_name": job.model_name or None,
                "gate_passed": summary.get("gate_passed"),
                "result_summary": {
                    key: summary[key]
                    for key in (
                        "status",
                        "candidate_version",
                        "gate_passed",
                        "gate_decision",
                        "registration_status",
                        "model_version",
                        "batch_id",
                        "rows",
                        "prediction_count",
                        "drift_status",
                        "alert_count",
                    )
                    if key in summary
                }
                | (
                    {
                        "prediction_count": (job.result or {}).get("prediction_count"),
                        "batch_id": (job.result or {}).get("batch_id"),
                    }
                    if job.operation == "dropout-score"
                    else {}
                ),
                "export_id": (job.result or {}).get("export_id"),
            }
        )
    return {"items": items}


def _job_card(row: ProfAssistMLJob, *, reused: bool = False) -> dict[str, Any]:
    return {
        "job_id": str(row.id),
        "operation": row.operation,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "error": row.error or None,
        "model_version": row.model_version or None,
        "reused": reused,
    }


async def _queue_dropout(db: Any, job: ProfAssistMLJob) -> dict[str, Any]:
    previous_run_id = job.prefect_flow_run_id
    retrying = job.status == "failed" and bool(previous_run_id)
    idempotency_key = f"{job.id}:{previous_run_id}" if retrying else str(job.id)
    job.status, job.error = "queued", ""
    db.add(job)
    await db.flush()
    await db.commit()
    try:
        from prefect.deployments import run_deployment

        flow_run = await run_deployment(
            "profassist-dropout-job/dropout-job",
            parameters={"job_id": str(job.id)},
            timeout=0,
            idempotency_key=idempotency_key,
        )
        job.prefect_flow_run_id = str(getattr(flow_run, "id", "") or "")
    except Exception:
        job.status = "failed"
        job.error = "The dropout job could not be queued. Please retry."
    await db.execute(
        text("SELECT set_config('app.current_org', :org, true)"),
        {"org": str(job.organization_id)},
    )
    await db.flush()
    await db.refresh(job)
    return _job_card(job)


async def _export_for_job(
    db: Any, org_id: uuid.UUID, export_id: uuid.UUID
) -> ProfAssistDropoutExport | None:
    row = await db.get(ProfAssistDropoutExport, export_id)
    return (
        row
        if row is not None and row.organization_id == org_id and row.status == "validated"
        else None
    )


async def create_score_job(
    db: Any,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    export_id: uuid.UUID,
    identity_map: list[dict[str, str]],
) -> dict[str, Any]:
    export = await _export_for_job(db, org_id, export_id)
    if export is None:
        return {"error": "Validated export not found."}
    active_result = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.organization_id == org_id,
            ProfAssistMLRelease.model_kind == "dropout",
            ProfAssistMLRelease.course_id.is_(None),
            ProfAssistMLRelease.assignment_id.is_(None),
            ProfAssistMLRelease.active.is_(True),
            ProfAssistMLRelease.verified.is_(True),
            ProfAssistMLRelease.gate_passed.is_(True),
        )
        .order_by(ProfAssistMLRelease.created_at.desc())
        .limit(1)
    )
    release = active_result.scalars().first()
    if release is None:
        return {"error": "No approved course-withdrawal release is active for this workspace."}
    snapshots = _frame(export.snapshots_csv.encode("utf-8"), "Stored snapshot export")
    valid_keys = set(snapshots["student_key"].astype(str))
    normalized: dict[str, uuid.UUID] = {}
    external_ids: set[str] = set()
    for item in identity_map:
        if not isinstance(item, dict) or set(item) != {"student_key", "moodle_student_id"}:
            return {"error": "Identity mappings must contain student_key and moodle_student_id."}
        student_key = str(item["student_key"]).strip()
        external_id = str(item["moodle_student_id"]).strip()
        if (
            not student_key
            or not external_id
            or student_key not in valid_keys
            or student_key in normalized
            or external_id in external_ids
        ):
            return {"error": "Identity mappings must be unique and refer to export student keys."}
        normalized[student_key] = uuid.UUID(int=0)  # replaced by an enrolled Student below
        external_ids.add(external_id)
    if not normalized:
        return {
            "error": "Map at least one pseudonym to a currently enrolled student before scoring."
        }
    course_students_result = await db.execute(
        select(Student).where(
            Student.organization_id == org_id,
            Student.course_id == export.course_id,
            Student.external_id.in_(external_ids),
        )
    )
    by_external = {row.external_id: row for row in course_students_result.scalars().all()}
    if set(by_external) != external_ids:
        return {
            "error": "Each identity mapping must resolve to a student currently enrolled in this course."
        }
    student_ids = {
        str(row["student_key"]): by_external[str(row["moodle_student_id"])].id
        for row in identity_map
    }
    for student_key, student_id in student_ids.items():
        old_result = await db.execute(
            select(ProfAssistDropoutIdentity).where(
                ProfAssistDropoutIdentity.organization_id == org_id,
                ProfAssistDropoutIdentity.student_key == student_key,
            )
        )
        old = old_result.scalars().first()
        if old is not None and old.student_id != student_id:
            return {"error": "An existing pseudonym cannot be rebound to another student."}
        if old is None:
            db.add(
                ProfAssistDropoutIdentity(
                    organization_id=org_id, student_key=student_key, student_id=student_id
                )
            )
    filtered = snapshots.loc[snapshots["student_key"].astype(str).isin(student_ids)].reset_index(
        drop=True
    )
    csv_out = io.StringIO(newline="")
    filtered.to_csv(csv_out, index=False, lineterminator="\n")
    filtered_bytes = csv_out.getvalue().encode("utf-8")
    mapping_digest = _sha(
        _canonical(sorted((key, str(value)) for key, value in student_ids.items()))
    )
    fingerprint = _sha(
        _canonical(
            {
                "operation": "dropout-score",
                "export": export.checksum,
                "release": str(release.id),
                "mapping": mapping_digest,
                "snapshots": _sha(filtered_bytes),
            }
        )
    )
    found = await db.execute(
        select(ProfAssistMLJob).where(
            ProfAssistMLJob.organization_id == org_id,
            ProfAssistMLJob.operation == "dropout-score",
            ProfAssistMLJob.input_fingerprint == fingerprint,
        )
    )
    job = found.scalars().first()
    created = job is None
    if job is None:
        job = ProfAssistMLJob(
            organization_id=org_id,
            course_id=export.course_id,
            requested_by=user_id,
            operation="dropout-score",
            status="queued",
            input_fingerprint=fingerprint,
            source_version_ids=[str(value) for value in student_ids.values()],
            model_name=release.model_name,
            model_version=release.model_version,
            result={
                "export_id": str(export.id),
                "mapping": {key: str(value) for key, value in student_ids.items()},
                "release_id": str(release.id),
                "input_snapshot_sha256": _sha(filtered_bytes),
            },
        )
        card = await _queue_dropout(db, job)
        return card | {"reused": False}
    if job.status == "failed" or (job.status == "queued" and not job.prefect_flow_run_id):
        card = await _queue_dropout(db, job)
    else:
        card = _job_card(job)
    return card | {"reused": not created}


async def _active_dropout_release(db: Any, org_id: uuid.UUID) -> ProfAssistMLRelease | None:
    result = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.organization_id == org_id,
            ProfAssistMLRelease.model_kind == "dropout",
            ProfAssistMLRelease.course_id.is_(None),
            ProfAssistMLRelease.assignment_id.is_(None),
            ProfAssistMLRelease.active.is_(True),
            ProfAssistMLRelease.verified.is_(True),
            ProfAssistMLRelease.gate_passed.is_(True),
        )
        .order_by(ProfAssistMLRelease.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def create_train_job(
    db: Any,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    export_id: uuid.UUID,
    train_cohorts: list[str],
    validation_cohorts: list[str],
    test_cohorts: list[str],
) -> dict[str, Any]:
    export = await _export_for_job(db, org_id, export_id)
    if export is None or not export.outcomes_csv:
        return {"error": "A validated export with historical outcomes is required for training."}
    split = (export.manifest or {}).get("split") or {}
    if (
        train_cohorts != split.get("train")
        or validation_cohorts != split.get("validation")
        or test_cohorts != split.get("test", [])
    ):
        return {"error": "Training cohorts must exactly match the immutable export manifest split."}
    active = await _active_dropout_release(db, org_id)
    model_name = (
        active.model_name if active else os.getenv("DROPOUT_MODEL_NAME", "student-dropout").strip()
    )
    model_version = active.model_version if active else ""
    if not model_name:
        return {"error": "The course-withdrawal model name is not configured."}
    fingerprint = _sha(
        _canonical(
            {
                "operation": "dropout-train",
                "export": export.checksum,
                "split": split,
                "active_release": str(active.id) if active else None,
            }
        )
    )
    found = await db.execute(
        select(ProfAssistMLJob).where(
            ProfAssistMLJob.organization_id == org_id,
            ProfAssistMLJob.operation == "dropout-train",
            ProfAssistMLJob.input_fingerprint == fingerprint,
        )
    )
    job = found.scalars().first()
    created = job is None
    if job is None:
        job = ProfAssistMLJob(
            organization_id=org_id,
            requested_by=user_id,
            operation="dropout-train",
            status="queued",
            input_fingerprint=fingerprint,
            model_name=model_name,
            model_version=model_version,
            result={
                "export_id": str(export.id),
                "active_release_id": str(active.id) if active else None,
                "train_cohorts": train_cohorts,
                "validation_cohorts": validation_cohorts,
                "test_cohorts": test_cohorts,
            },
        )
        card = await _queue_dropout(db, job)
        return card | {"reused": False}
    if job.status == "failed" or (job.status == "queued" and not job.prefect_flow_run_id):
        card = await _queue_dropout(db, job)
    else:
        card = _job_card(job)
    return card | {"reused": not created}


async def create_monitor_job(
    db: Any,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    export_id: uuid.UUID,
    release_id: uuid.UUID | None,
) -> dict[str, Any]:
    export = await _export_for_job(db, org_id, export_id)
    if export is None:
        return {"error": "Validated export not found."}
    release = (
        await _active_dropout_release(db, org_id)
        if release_id is None
        else await db.get(ProfAssistMLRelease, release_id)
    )
    if (
        release is None
        or release.organization_id != org_id
        or release.model_kind != "dropout"
        or release.course_id is not None
        or release.assignment_id is not None
        or not release.verified
        or not release.gate_passed
        or release.action not in {"approve", "rollback"}
    ):
        return {"error": "Monitoring requires an approved organization-scoped dropout release."}
    fingerprint = _sha(
        _canonical(
            {"operation": "dropout-monitor", "export": export.checksum, "release": str(release.id)}
        )
    )
    found = await db.execute(
        select(ProfAssistMLJob).where(
            ProfAssistMLJob.organization_id == org_id,
            ProfAssistMLJob.operation == "dropout-monitor",
            ProfAssistMLJob.input_fingerprint == fingerprint,
        )
    )
    existing = found.scalars().first()
    if existing is not None:
        if existing.status == "failed" or (
            existing.status == "queued" and not existing.prefect_flow_run_id
        ):
            return await _queue_dropout(db, existing) | {"reused": True}
        return _job_card(existing) | {"reused": True}
    job = ProfAssistMLJob(
        organization_id=org_id,
        course_id=export.course_id,
        requested_by=user_id,
        operation="dropout-monitor",
        status="queued",
        input_fingerprint=fingerprint,
        model_name=release.model_name,
        model_version=release.model_version,
        result={
            "export_id": str(export.id),
            "release_id": str(release.id),
            "include_outcomes": bool(export.outcomes_csv),
        },
    )
    return await _queue_dropout(db, job) | {"reused": False}


async def list_dropout_releases(db: Any, org_id: uuid.UUID) -> dict[str, Any]:
    result = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.organization_id == org_id,
            ProfAssistMLRelease.model_kind == "dropout",
            ProfAssistMLRelease.course_id.is_(None),
            ProfAssistMLRelease.assignment_id.is_(None),
        )
        .order_by(ProfAssistMLRelease.created_at.desc())
        .limit(100)
    )
    return {
        "items": [
            {
                "release_id": str(row.id),
                "model_name": row.model_name,
                "model_version": row.model_version,
                "active": row.active,
                "verified": row.verified,
                "gate_passed": row.gate_passed,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "action": row.action,
                "gate_evidence": row.gate_evidence,
            }
            for row in result.scalars().all()
        ]
    }


async def _worker_post(operation: str, body: dict[str, Any]) -> dict[str, Any]:
    base = os.getenv("PLAGIARISM_WORKER_URL", "").strip().rstrip("/")
    token = os.getenv("PLAGIARISM_WORKER_TOKEN", "").strip()
    if not base:
        raise RuntimeError("private worker is not configured")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=worker_job_timeout()) as client:
        response = await client.post(f"{base}/jobs/{operation}", json=body, headers=headers)
        response.raise_for_status()
        result = response.json()
    if (
        result.get("schema_version") != 1
        or result.get("operation") != operation
        or result.get("status") != "completed"
        or not isinstance(result.get("result"), dict)
    ):
        raise ValueError("invalid private worker response")
    return {**result["result"], "artifacts": result.get("artifacts") or {}}


@flow(name="profassist-dropout-job", log_prints=False)
async def profassist_dropout_job_flow(job_id: str) -> dict[str, Any]:
    # A Prefect subprocess loads the flow without the API's ORM imports.
    import app.db.models  # noqa: F401

    try:
        job_uuid = uuid.UUID(job_id)
    except (ValueError, TypeError):
        return {"ok": False, "error": "invalid job"}
    async with get_db_context() as db:
        job = await db.get(ProfAssistMLJob, job_uuid)
        if job is None or not job.operation.startswith("dropout-"):
            return {"ok": False, "error": "job not found"}
        if job.status == "completed":
            return {"ok": True, "job_id": job_id, "status": job.status}
        job.status, job.error = "running", ""
        await db.flush()
        export = await _export_for_job(db, job.organization_id, uuid.UUID(job.result["export_id"]))
        if export is None:
            job.status, job.error = "failed", "The validated export is no longer available."
            return {"ok": False, "status": job.status}
        org_id = str(job.organization_id)
        scope = {"tenant_id": org_id}
        context: dict[str, Any] = {
            "job_id": job_id,
            "tracking_uri": os.getenv("MLFLOW_TRACKING_URI", "").strip(),
            "model_name": job.model_name,
            "version": job.model_version,
            "scope": scope,
        }
        if job.operation == "dropout-train" and not job.model_version:
            context.pop("version", None)
        files = {
            "snapshots.csv": {
                "encoding": "base64",
                "content": base64.b64encode(export.snapshots_csv.encode()).decode(),
            }
        }
        if job.operation == "dropout-score":
            mapping = job.result.get("mapping") or {}
            snapshot_frame = _frame(export.snapshots_csv.encode(), "Snapshot export")
            selected = snapshot_frame.loc[
                snapshot_frame["student_key"].astype(str).isin(mapping)
            ].reset_index(drop=True)
            stream = io.StringIO(newline="")
            selected.to_csv(stream, index=False, lineterminator="\n")
            files = {
                "snapshots.csv": {
                    "encoding": "base64",
                    "content": base64.b64encode(stream.getvalue().encode()).decode(),
                }
            }
            payload = {"files": files}
        elif job.operation == "dropout-train":
            files = {
                "manifest.json": {
                    "encoding": "base64",
                    "content": base64.b64encode(_manifest_bytes(export.manifest)).decode(),
                },
                "raw/lms_snapshots.csv": {
                    "encoding": "base64",
                    "content": base64.b64encode(export.snapshots_csv.encode()).decode(),
                },
                "raw/student_outcomes.csv": {
                    "encoding": "base64",
                    "content": base64.b64encode(export.outcomes_csv.encode()).decode(),
                },
            }
            payload = {
                "files": files,
                "train_cohorts": job.result["train_cohorts"],
                "validation_cohorts": job.result["validation_cohorts"],
                "test_cohorts": job.result["test_cohorts"],
            }
        else:
            if job.result.get("include_outcomes") and export.outcomes_csv:
                files["outcomes.csv"] = {
                    "encoding": "base64",
                    "content": base64.b64encode(export.outcomes_csv.encode()).decode(),
                }
            payload = {"files": files}
        body = {
            "schema_version": 1,
            "operation": job.operation,
            "context": context,
            "payload": payload,
        }
        await db.commit()
        try:
            result = await _worker_post(job.operation, body)
            await db.execute(
                text("SELECT set_config('app.current_org', :org, true)"), {"org": org_id}
            )
            if job.operation == "dropout-score":
                await _persist_predictions(db, job, export, result)
            elif job.operation == "dropout-train":
                await _persist_candidate(db, job, export, result)
            if job.operation == "dropout-score":
                summary = result.get("summary") or {}
                job.result = {
                    **(job.result or {}),
                    "prediction_count": len(result.get("predictions") or []),
                    "batch_id": summary.get("batch_id"),
                    "predictions_sha256": (result.get("artifacts") or {}).get("predictions.csv"),
                }
            else:
                job.result = {**(job.result or {}), "worker_result": result}
            if job.operation == "dropout-train":
                summary = result.get("summary") or {}
                job.model_version = str(
                    summary.get("candidate_version") or summary.get("model_version") or ""
                )
            job.status = "completed"
            await db.flush()
            return {"ok": True, "job_id": job_id, "status": job.status}
        except Exception:
            await db.rollback()
            await db.execute(
                text("SELECT set_config('app.current_org', :org, true)"), {"org": org_id}
            )
            failed_job = await db.get(ProfAssistMLJob, job_uuid)
            if failed_job is not None and failed_job.status != "completed":
                failed_job.status = "failed"
                failed_job.error = "The private dropout worker could not complete this job."
            return {"ok": False, "job_id": job_id, "status": "failed"}


async def _persist_predictions(
    db: Any, job: ProfAssistMLJob, export: ProfAssistDropoutExport, result: dict[str, Any]
) -> None:
    predictions = result.get("predictions")
    summary = result.get("summary") or {}
    if (
        not isinstance(predictions, list)
        or summary.get("model_name") != job.model_name
        or str(summary.get("model_version")) != job.model_version
    ):
        raise ValueError("Dropout score response is missing concrete model predictions.")
    mapping = job.result.get("mapping") or {}
    source = _frame(export.snapshots_csv.encode("utf-8"), "Stored snapshot export")
    expected_rows = source.loc[source["student_key"].astype(str).isin(mapping)]
    expected = {
        (
            str(row["tenant_id"]),
            str(row["student_key"]),
            str(row["course_id"]),
            str(row["cohort_id"]),
            str(row["snapshot_at"]),
        )
        for _, row in expected_rows.iterrows()
    }
    keys = set()
    batch_ids: set[str] = set()
    for row in predictions:
        if (
            not isinstance(row, dict)
            or row.get("student_key") in keys
            or row.get("student_key") not in mapping
        ):
            raise ValueError("Dropout scorer returned an unknown or duplicate pseudonym.")
        keys.add(row["student_key"])
        output_key = tuple(str(row.get(field, "")) for field in KEY_COLUMNS)
        if output_key not in expected:
            raise ValueError("Dropout scorer returned a row outside the mapped course export.")
        batch_ids.add(str(row.get("batch_id", "")))
        try:
            probability = float(row["dropout_probability"])
            cutoff = datetime.fromisoformat(str(row["snapshot_at"]).replace("Z", "+00:00"))
            predicted_at = datetime.fromisoformat(str(row["predicted_at"]).replace("Z", "+00:00"))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Dropout scorer returned malformed prediction fields.") from exc
        if (
            not 0 <= probability <= 1
            or row.get("prediction_status") != "scored"
            or row.get("risk_band") not in {"review", "routine"}
            or cutoff.tzinfo is None
            or cutoff.utcoffset() != timedelta(0)
            or predicted_at.tzinfo is None
            or predicted_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("Dropout scorer returned an invalid probability or status.")
        db.add(
            ProfAssistDropoutPrediction(
                organization_id=job.organization_id,
                course_id=export.course_id,
                export_id=export.id,
                student_id=uuid.UUID(mapping[row["student_key"]]),
                student_key=row["student_key"],
                cutoff_at=cutoff,
                predicted_at=predicted_at,
                probability=probability,
                risk_band=row["risk_band"],
                prediction_status=row["prediction_status"],
                model_name=job.model_name,
                model_version=job.model_version,
                feature_schema_version=str(row["feature_schema_version"]),
                training_data_hash=str(row["training_data_hash"]),
                batch_id=str(row["batch_id"]),
                export_checksum=export.checksum,
            )
        )
    if not predictions:
        raise ValueError("Dropout scorer returned no predictions for mapped learners.")
    if (
        len(batch_ids) != 1
        or "" in batch_ids
        or expected
        != {tuple(str(row.get(field, "")) for field in KEY_COLUMNS) for row in predictions}
    ):
        raise ValueError("Dropout scorer returned an incomplete or inconsistent batch.")


async def _persist_candidate(
    db: Any, job: ProfAssistMLJob, export: ProfAssistDropoutExport, result: dict[str, Any]
) -> None:
    summary = result.get("summary") or {}
    candidate_version = str(summary.get("candidate_version") or "")
    if not summary.get("gate_passed") or not candidate_version:
        return
    verify = await _worker_post(
        "dropout-verify-release",
        {
            "schema_version": 1,
            "operation": "dropout-verify-release",
            "context": {
                "job_id": str(uuid.uuid4()),
                "model_name": job.model_name,
                "version": candidate_version,
                "tracking_uri": os.getenv("MLFLOW_TRACKING_URI", "").strip(),
                "scope": {"tenant_id": str(job.organization_id)},
            },
            "payload": {"scope": {"tenant_id": str(job.organization_id)}},
        },
    )
    lineage_hash = verify.get("training_manifest_sha256")
    gate_hash = verify.get("gate_report_sha256")
    if (
        verify.get("model_name") != job.model_name
        or str(verify.get("model_version")) != candidate_version
        or verify.get("platform_scope") != {"tenant_id": str(job.organization_id)}
        or lineage_hash != export.manifest_checksum
        or verify.get("platform_snapshot_sha256") != export.snapshots_sha256
        or not verify.get("gate_passed")
        or not isinstance(gate_hash, str)
        or len(gate_hash) != SHA256_LENGTH
    ):
        raise ValueError("Dropout candidate failed scope, lineage or gate verification.")
    bundle_hash = verify.get("model_bundle_sha256")
    if not isinstance(bundle_hash, str) or len(bundle_hash) != SHA256_LENGTH:
        raise ValueError("Dropout release verification did not return a bundle checksum.")
    db.add(
        ProfAssistMLRelease(
            organization_id=job.organization_id,
            model_kind="dropout",
            model_name=job.model_name,
            model_version=candidate_version,
            course_id=None,
            assignment_id=None,
            snapshot_id=None,
            model_bundle_sha256=bundle_hash,
            gate_evidence={
                "gate_passed": True,
                "gate_report_sha256": gate_hash,
                "training_manifest_sha256": lineage_hash,
                "platform_scope": verify["platform_scope"],
                "export_id": str(export.id),
                "export_checksum": export.checksum,
                "training_summary": summary,
            },
            gate_passed=True,
            verified=True,
            active=False,
            action="candidate",
        )
    )


async def change_dropout_release(
    db: Any,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    release_id: uuid.UUID,
    reason: str,
    *,
    rollback: bool = False,
) -> dict[str, Any]:
    candidate = await db.get(ProfAssistMLRelease, release_id)
    if (
        candidate is None
        or candidate.organization_id != org_id
        or candidate.model_kind != "dropout"
        or candidate.course_id is not None
        or candidate.assignment_id is not None
    ):
        return {"error": "Dropout release not found."}
    if (
        not candidate.verified
        or not candidate.gate_passed
        or candidate.action == "candidate"
        and rollback
    ):
        return {
            "error": "Only a verified release that passed its gate can be activated or rolled back."
        }
    if candidate.active:
        return {"error": "This dropout release is already active."}
    base = os.getenv("PLAGIARISM_WORKER_URL", "").strip().rstrip("/")
    token = os.getenv("PLAGIARISM_WORKER_TOKEN", "").strip()
    body = {
        "schema_version": 1,
        "operation": "dropout-verify-release",
        "context": {
            "job_id": str(uuid.uuid4()),
            "model_name": candidate.model_name,
            "version": candidate.model_version,
            "tracking_uri": os.getenv("MLFLOW_TRACKING_URI", "").strip(),
            "scope": {"tenant_id": str(org_id)},
        },
        "payload": {"scope": {"tenant_id": str(org_id)}},
    }
    if not base:
        return {"error": "Private dropout worker is not configured."}
    await db.commit()
    await db.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org_id)})
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{base}/jobs/dropout-verify-release",
                json=body,
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            response.raise_for_status()
            output = response.json()
        verified = output.get("result") or {}
    except Exception:
        return {"error": "Private worker could not reverify this dropout release."}
    if (
        output.get("schema_version") != 1
        or output.get("operation") != "dropout-verify-release"
        or output.get("status") != "completed"
        or verified.get("model_name") != candidate.model_name
        or str(verified.get("model_version")) != candidate.model_version
        or verified.get("platform_scope") != {"tenant_id": str(org_id)}
        or verified.get("model_bundle_sha256") != candidate.model_bundle_sha256
        or not verified.get("gate_passed")
    ):
        return {
            "error": "Dropout candidate no longer matches its verified bundle and gate evidence."
        }
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"dropout-release:{org_id}"},
    )
    locked_candidate = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.id == release_id,
            ProfAssistMLRelease.organization_id == org_id,
        )
        .with_for_update()
    )
    candidate = locked_candidate.scalars().first()
    if candidate is None or not candidate.verified or not candidate.gate_passed or candidate.active:
        return {"error": "The dropout release is no longer eligible."}
    current = await db.execute(
        select(ProfAssistMLRelease)
        .where(
            ProfAssistMLRelease.organization_id == org_id,
            ProfAssistMLRelease.model_kind == "dropout",
            ProfAssistMLRelease.course_id.is_(None),
            ProfAssistMLRelease.assignment_id.is_(None),
            ProfAssistMLRelease.active.is_(True),
        )
        .with_for_update()
    )
    previous = current.scalars().first()
    if rollback and previous is None:
        return {"error": "There is no active dropout release to roll back from."}
    if previous:
        previous.active = False
    active = ProfAssistMLRelease(
        organization_id=org_id,
        model_kind="dropout",
        model_name=candidate.model_name,
        model_version=candidate.model_version,
        course_id=None,
        assignment_id=None,
        snapshot_id=None,
        model_bundle_sha256=candidate.model_bundle_sha256,
        gate_evidence=candidate.gate_evidence,
        gate_passed=True,
        verified=True,
        active=True,
        previous_release_id=previous.id if previous else None,
        action="rollback" if rollback else "approve",
        actor_user_id=user_id,
        reason=reason,
    )
    candidate.active = False
    db.add(active)
    db.add(
        Approval(
            organization_id=org_id,
            user_id=user_id,
            target_type="dropout_release",
            target_id=str(active.id),
            action=active.action,
            note=reason,
        )
    )
    await db.flush()
    return {
        "release_id": str(active.id),
        "model_name": active.model_name,
        "model_version": active.model_version,
        "active": True,
        "action": active.action,
        "previous_release_id": str(previous.id) if previous else None,
    }


async def list_student_predictions(
    db: Any, org_id: uuid.UUID, course_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    active = await _active_dropout_release(db, org_id)
    if active is None:
        return {}
    result = await db.execute(
        select(ProfAssistDropoutPrediction)
        .where(
            ProfAssistDropoutPrediction.organization_id == org_id,
            ProfAssistDropoutPrediction.course_id == course_id,
            ProfAssistDropoutPrediction.model_name == active.model_name,
            ProfAssistDropoutPrediction.model_version == active.model_version,
            ProfAssistDropoutPrediction.prediction_status == "scored",
        )
        .order_by(ProfAssistDropoutPrediction.predicted_at.desc())
    )
    output: dict[str, dict[str, Any]] = {}
    for row in result.scalars().all():
        output.setdefault(
            str(row.student_id),
            {
                "probability": row.probability,
                "risk_band": row.risk_band,
                "predicted_at": row.predicted_at.isoformat(),
                "model_version": row.model_version,
                "model_name": row.model_name,
                "batch_id": row.batch_id,
                "cutoff_at": row.cutoff_at.isoformat(),
                "coverage_status": "eligible",
            },
        )
    return output
