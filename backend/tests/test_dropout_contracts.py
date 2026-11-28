"""Validation for imported Moodle export manifests and immutable lineage."""

import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.profassist.ml.dropout_jobs import (
    _json,
    _manifest_bytes,
    _prediction_explanation,
    _validate_manifest,
    _validate_rows,
    split_training_csv,
)


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
    assert (
        hashlib.sha256(stored_worker_bytes).hexdigest()
        == hashlib.sha256(
            _manifest_bytes(_json(stored_worker_bytes, "stored manifest"))
        ).hexdigest()
    )


def test_training_manifest_requires_all_three_split_sets() -> None:
    org_id = uuid.uuid4()
    snapshots, outcomes = b"snapshots", b"outcomes"
    manifest = _manifest(org_id, snapshots, outcomes)
    del manifest["split"]["test"]

    with pytest.raises(ValueError, match="train, validation, and test"):
        _validate_manifest(manifest, snapshots, outcomes, org_id=org_id)


def test_prediction_explanation_accepts_legacy_rows_and_validates_worker_values() -> None:
    assert _prediction_explanation(None) is None
    assert _prediction_explanation("[]") is None
    assert _prediction_explanation('[{"feature":"active_days_14d","value":1,"effect":0.7}]') == [
        {"feature": "active_days_14d", "value": 1, "effect": 0.7}
    ]
    with pytest.raises(ValueError, match="invalid explanation factor"):
        _prediction_explanation([{"feature": "student_name", "value": None, "effect": 0.7}])


def test_combined_csv_keeps_outcomes_out_of_model_inputs() -> None:
    sample = (
        Path(__file__).resolve().parents[2] / "frontend/public/samples/dropout-training-sample.csv"
    ).read_bytes()
    org = uuid.uuid4()
    with pytest.raises(ValueError, match="Synthetic data"):
        split_training_csv(sample, org)
    # Use the synthetic rows to exercise the importer contract without saving an export.
    combined = sample.replace(b"synthetic_moodle", b"moodle").replace(
        b"fixture-tenant", str(org).encode()
    )
    snapshots, manifest_bytes, outcomes = split_training_csv(combined, org)
    manifest = _json(manifest_bytes, "Generated manifest")
    _, _, split = _validate_manifest(manifest, snapshots, outcomes, org_id=org)
    snapshot_rows, outcome_rows = _validate_rows(
        snapshots, outcomes, manifest, org_id=org, course=SimpleNamespace(external_id="COURSE_01")
    )
    assert split == {"train": ["2024_S1"], "validation": ["2024_S2"], "test": ["2025_S1"]}
    assert "final_outcome" not in snapshot_rows.columns
    assert outcome_rows is not None and len(outcome_rows) == len(snapshot_rows) == 120
    assert split_training_csv(combined, org) == (snapshots, manifest_bytes, outcomes)


def test_synthetic_csv_is_bound_to_selected_workspace_and_course() -> None:
    sample = (
        Path(__file__).resolve().parents[2] / "frontend/public/samples/dropout-training-sample.csv"
    ).read_bytes()
    org = uuid.uuid4()
    snapshots, manifest_bytes, outcomes = split_training_csv(
        sample, org, synthetic=True, course_external_id="SELECTED_COURSE"
    )
    manifest = _json(manifest_bytes, "Generated manifest")
    assert manifest["synthetic"] is True and manifest["fixture_only"] is True
    assert manifest["provenance"] == "synthetic_platform_fixture"
    _validate_manifest(manifest, snapshots, outcomes, org_id=org)
    _validate_rows(
        snapshots,
        outcomes,
        manifest,
        org_id=org,
        course=SimpleNamespace(external_id="SELECTED_COURSE"),
    )
