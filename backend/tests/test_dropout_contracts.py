"""Validation for imported Moodle export manifests and immutable lineage."""

import hashlib
import json
import uuid

import pytest

from app.profassist.ml.dropout_jobs import _json, _manifest_bytes, _validate_manifest


def _manifest(org_id: uuid.UUID, snapshots: bytes, outcomes: bytes) -> dict:
    cohorts = ["cohort-a", "cohort-b", "cohort-c"]
    return {
        "schema_version": "1.0",
        "synthetic": False,
        "export_id": "moodle-export-2026-01",
        "platform_scope": {"tenant_id": str(org_id)},
        "exported_at": "2026-01-05T12:00:00Z",
        "timezone": "UTC",
        "extraction_version": "moodle-history-v1",
        "included_event_categories": ["course_view", "resource_view"],
        "coverage_limitations": ["Events outside Moodle retention are unavailable."],
        "row_counts": {"lms_snapshots": 3, "student_outcomes": 3},
        "cohorts": cohorts,
        "split": {"train": [cohorts[0]], "validation": [cohorts[1]], "test": [cohorts[2]]},
        "files": {
            "raw/lms_snapshots.csv": {"sha256": hashlib.sha256(snapshots).hexdigest()},
            "raw/student_outcomes.csv": {"sha256": hashlib.sha256(outcomes).hexdigest()},
        },
    }


def test_noncanonical_upload_has_stable_worker_manifest_checksum() -> None:
    org_id = uuid.uuid4()
    snapshots, outcomes = b"snapshots", b"outcomes"
    manifest = _manifest(org_id, snapshots, outcomes)
    uploaded = json.dumps(manifest, indent=4).encode("utf-8")
    parsed = _json(uploaded, "manifest")

    _validate_manifest(parsed, snapshots, outcomes, org_id=org_id)
    stored_worker_bytes = _manifest_bytes(parsed)

    assert uploaded != stored_worker_bytes
    assert hashlib.sha256(stored_worker_bytes).hexdigest() == hashlib.sha256(
        _manifest_bytes(_json(stored_worker_bytes, "stored manifest"))
    ).hexdigest()


def test_training_manifest_requires_all_three_split_sets() -> None:
    org_id = uuid.uuid4()
    snapshots, outcomes = b"snapshots", b"outcomes"
    manifest = _manifest(org_id, snapshots, outcomes)
    del manifest["split"]["test"]

    with pytest.raises(ValueError, match="train, validation, and test"):
        _validate_manifest(manifest, snapshots, outcomes, org_id=org_id)
