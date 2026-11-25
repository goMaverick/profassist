# Dropout risk workflow

Dropout risk uses an immutable Moodle day-35 export, runs scoring/training in the private worker, and joins scored results to students in ProfAssist. The live Moodle connector currently syncs only a feature subset; it cannot reconstruct historical timestamps, day-35 snapshots, or mature outcomes. An admin must import the validated export. Synthetic fixtures are for isolated rehearsals and are rejected by production import.

## Import data

Upload multipart form data to `POST /api/v1/profassist/admin/ml/dropout/exports`:

- `course_id`: ProfAssist course UUID. CSV `course_id` values must match its external Moodle course ID. CSV `tenant_id` and manifest `platform_scope.tenant_id` must match the current organization UUID.
- `snapshots_file`: UTF-8 `lms_snapshots.csv` following the upstream day-35 snapshot contract. `student_key` is a stable pseudonym; keep names, emails, and Moodle user IDs out of CSVs.
- `manifest_file`: UTF-8 JSON with `schema_version: "1.0"`, `synthetic: false`, `export_id`, `exported_at`, `timezone: "UTC"`, `extraction_version`, `included_event_categories`, `coverage_limitations`, `row_counts`, ordered `cohorts`, and SHA-256 `files` entries. JSON whitespace and key order are accepted; validated JSON is canonicalized before its immutable checksum is stored and sent to the worker.
- `outcomes_file` (training only): UTF-8 `student_outcomes.csv`, with one mature outcome per snapshot key. Withdrawals must be after the day-35 cutoff and by course end. Completed/failed outcomes must be observed at least 14 days after course end. Outcomes are never included in scoring payloads.

For training, the manifest must checksum exactly `raw/lms_snapshots.csv` and `raw/student_outcomes.csv`. It must declare non-empty `train`, `validation`, and `test` cohort lists that are disjoint, chronological, and cover all cohorts. Each cohort has one course start and a cutoff exactly 35 days later. `GET /api/v1/profassist/admin/ml/dropout/exports?course_id=<course UUID>` lists imports and returns the declared `train_cohorts`, `validation_cohorts`, and `test_cohorts` for the UI.

## Score and activate

`POST /api/v1/profassist/admin/ml/dropout/score` accepts an `export_id` and a score-time identity mapping:

```json
{
  "export_id": "<validated export UUID>",
  "identity_map": [
    {"student_key": "pseudonym-1", "moodle_student_id": "<Moodle user ID>"}
  ]
}
```

Each mapping must resolve to a currently enrolled student in the selected ProfAssist course. Pseudonyms cannot be rebound to another student. The backend keeps the mapping private, filters the worker input to mapped rows, and stores predictions by tenant, course, student, export, and active model version. Outcomes and identity mappings are not sent to the worker. The Students API joins these results and returns `dropout_prediction` for scored learners.

Queue training with `POST /api/v1/profassist/admin/ml/dropout/train`, passing `export_id` and the exact three cohort arrays returned by the import. Bootstrap training is allowed before the first release; later training uses the active approved model as its comparison version. A passing candidate still requires admin review and approval. Use `POST /api/v1/profassist/admin/ml/dropout/releases/{release_id}/approve` with a reason to activate or the matching `/rollback` route to roll back. Both actions reverify bundle bytes, tenant scope, and gate evidence. Scoring always uses the active approved release. Queue monitoring with `POST /api/v1/profassist/admin/ml/dropout/monitor` and a validated export plus optional approved release ID. `GET .../jobs` and `GET .../releases` show job and release state.

All these routes are admin-only and tenant-scoped. Imports are size-limited and immutable. A model score is evidence for human review, not a student determination.

## Synthetic rehearsal

The separate upstream `student-dropout-mlops` checkout provides deterministic snapshot/outcome/manifest fixtures and tiny copied/independent plagiarism fixtures via `scripts/generate_worker_fixtures.py`. Dropout fixture manifests retain `synthetic: true` and use a fixture-only registry; they cannot pass this production importer or be approved as a live model. Fixture checks exercise the data and worker contracts only. They do not establish predictive accuracy or validate a live Moodle server export.
