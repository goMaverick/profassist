"""Focused worker-payload contract tests for immutable ML job inputs."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.profassist.ml import jobs
from app.profassist.ml.jobs import _snapshot_review_payload, _snapshot_worker_evidence


def test_snapshot_worker_payload_preserves_selected_review_revision() -> None:
    left_version, right_version = uuid.uuid4(), uuid.uuid4()
    review = SimpleNamespace(
        id=uuid.uuid4(),
        revision=2,
        left_version_id=left_version,
        right_version_id=right_version,
        decision="flag",
        spans=[{"left_start": 12, "left_end": 19, "right_start": 7, "right_end": 14}],
    )
    reports = {
        str(left_version): {"report_id": "report-left", "version_id": str(left_version)},
        str(right_version): {"report_id": "report-right", "version_id": str(right_version)},
    }

    payload = _snapshot_review_payload(review, reports)

    assert payload["revision"] == 2
    assert payload["review_id"] == str(review.id)
    assert payload["left"]["report_id"] == "report-left"
    assert payload["right"]["report_id"] == "report-right"
    assert payload["spans"] == review.spans


def test_snapshot_worker_evidence_checks_input_hash_separately_from_corpus_hash() -> None:
    scope = {"institution_id": "tenant", "course_id": "course", "assignment_id": "assignment"}
    input_hash = "a" * 64
    dataset_hash = "b" * 64
    manifest_hash = "c" * 64
    worker_result = {
        "scope": scope,
        "input_sha256": input_hash,
        "dataset_sha256": dataset_hash,
        "manifest_sha256": manifest_hash,
    }

    assert _snapshot_worker_evidence(worker_result, scope=scope, input_sha256=input_hash) == (
        dataset_hash,
        manifest_hash,
    )
    with pytest.raises(ValueError, match="snapshot evidence"):
        _snapshot_worker_evidence(worker_result, scope=scope, input_sha256="d" * 64)


@pytest.mark.anyio
@pytest.mark.parametrize("passed", [True, False])
async def test_training_uses_the_assignment_candidate_and_records_the_gate_result(
    passed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, course, assessment, job_id = [uuid.uuid4() for _ in range(4)]
    scope = {"institution_id": str(org), "course_id": str(course), "assignment_id": str(assessment)}
    snapshot = SimpleNamespace(
        id=uuid.uuid4(), organization_id=org, checksum="a" * 64, manifest_checksum="b" * 64
    )
    versions = [
        SimpleNamespace(id=uuid.uuid4(), submission_id=uuid.uuid4(), text_content="Text")
        for _ in range(2)
    ]
    job = SimpleNamespace(
        organization_id=org,
        course_id=course,
        assignment_id=assessment,
        status="queued",
        operation="plagiarism-train",
        model_name="seed-model",
        model_version="1",
        source_version_ids=[str(version.id) for version in versions],
        result={"snapshot_id": str(snapshot.id)},
    )
    db = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
    added = []
    db.add = added.append
    db.get = AsyncMock(
        side_effect=lambda model, _id: {
            jobs.ProfAssistMLJob: job,
            jobs.IntegrityDatasetSnapshot: snapshot,
            jobs.Course: None,
        }[model]
    )

    def rows(values):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: values))

    db.execute = AsyncMock(
        side_effect=[
            rows(versions),
            rows([SimpleNamespace(id=row.submission_id) for row in versions]),
            None,
        ]
    )

    @asynccontextmanager
    async def context():
        yield db

    calls = []
    candidate_name = "passage-reuse-platform-scoped"

    class Worker:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def post(self, url, *, json, headers):
            calls.append(json)
            if json["operation"] == "plagiarism-train":
                payload = {
                    "summary": {
                        "platform_scope": scope,
                        "platform_snapshot_sha256": snapshot.manifest_checksum,
                        "candidate_version": "2" if passed else None,
                        "gate_passed": passed,
                        "mlflow_run_id": "candidate-run",
                    },
                }
            else:
                assert json["context"]["job_id"] != str(job_id)
                assert json["context"]["model_name"] == candidate_name
                payload = {
                    "scope": scope,
                    "release": {
                        "model_version": "2",
                        "model_name": candidate_name,
                        "platform_scope": scope,
                        "training_corpus_sha256": snapshot.manifest_checksum,
                        "model_bundle_sha256": "c" * 64,
                        "gate_passed": True,
                    },
                }
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "schema_version": 1,
                    "operation": json["operation"],
                    "status": "completed",
                    "result": payload,
                },
            )

    monkeypatch.setattr(jobs, "get_db_context", context)
    monkeypatch.setattr(jobs.httpx, "AsyncClient", Worker)
    monkeypatch.setattr(jobs, "training_namespace", AsyncMock(return_value=candidate_name))
    monkeypatch.setenv("PLAGIARISM_WORKER_URL", "http://worker.test")

    result = await jobs.profassist_ml_job_flow.fn(str(job_id))

    assert result["status"] == "completed"
    assert job.result["gate_passed"] is passed
    assert job.result["training_run_id"] == "candidate-run"
    assert len(calls) == (2 if passed else 1)
    assert len(added) == (1 if passed else 0)
