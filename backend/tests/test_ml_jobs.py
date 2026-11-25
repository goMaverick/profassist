"""Focused worker-payload contract tests for immutable ML job inputs."""

import uuid
from types import SimpleNamespace

import pytest

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

    assert _snapshot_worker_evidence(
        worker_result, scope=scope, input_sha256=input_hash
    ) == (dataset_hash, manifest_hash)
    with pytest.raises(ValueError, match="snapshot evidence"):
        _snapshot_worker_evidence(worker_result, scope=scope, input_sha256="d" * 64)
