# Machine learning in ProfAssist

ProfAssist exposes two models from one upstream project and nothing else:

| Name | Kind | Status | Runtime |
| --- | --- | --- | --- |
| `student-dropout` | `early-warning` | `ready` or `not_trained` | In-process scikit-learn adapter |
| `passage-reuse` | `integrity` | `configured` or `not_installed` | External JSON worker |

There is **no pass/fail model**. The upstream repository has no model that predicts a
grade, a pass, or a fail, and ProfAssist does not invent one. The only models are the
course-withdrawal model and the passage-reuse algorithm.

`app/profassist/ml/gateway.py` is the honest boundary. `model_cards()` describes both
models, `dropout_status()` wraps the adapter, and `plagiarism_status()` reports whether
the worker is configured. The gateway never fabricates a score, a version, or a license.

## Provenance

- Upstream: <https://github.com/maxser0v/student-dropout-mlops>
- Snapshot: commit history on `main` as of 2026-11-22. No upstream commit SHA is pinned
  in this repository; `NOTICE.md` records the date only. Do not claim a SHA that was
  never captured.
- The upstream project ships **no LICENSE file**. The `upstream/` directory is a
  substantial port of upstream code: the validation, training, feature, score, registry,
  monitor, model_io, lineage, and gates modules, plus copied documentation. It is not
  merely feature names or the pipeline shape.
- The port is included for contract/demo purposes only. Redistribution or production use
  requires written permission from the upstream author. Do not describe it as
  "contract-only" or claim a license the upstream project never granted.
- Do not copy further upstream training code, notebooks, or data into this repository.

## Data and artifact gaps

- The upstream training CSVs are not in Git, and the upstream DVC remote is empty. There
  are no real student records in this repository.
- `app/profassist/ml/dropout/artifacts/model.joblib` is a logistic-regression pipeline fit
  by `train_synthetic.py` on a seeded 480-row synthetic Moodle-shaped bundle. It is a
  demo artifact, not a real student model. `artifacts/metrics.json` marks it
  `"synthetic": true`.
- The plagiarism runtime has **no artifacts in Git**. It is an external worker contract.
- The dropout bundle owns its decision threshold. The shipped demo bundle stores
  `0.1`; the adapter defaults to `0.15` only when a bundle has no threshold. The
  upstream published model card describes `0.15`, so treat no value as interchangeable
  with another.

## `student-dropout` (course withdrawal)

- Target: withdrawal after the day-35 snapshot and by course end, conditional on active
  enrolment at the cutoff. It is not university departure and not failure.
- The adapter needs all 14 allowlisted features:
  `active_days_14d`, `active_days_previous_14d`, `interactions_14d`,
  `interactions_previous_14d`, `resource_views_14d`, `forum_posts_14d`,
  `late_submissions_to_date`, `assignments_due_to_date`, `scores_available_count`,
  `mean_score_pct_to_date`, `missed_assignments`, `activity_change`,
  `days_since_last_activity`, `no_activity_history`.
- Moodle activity features are pulled into `pa_moodle_activity` with
  `local_profassist_get_activity`, a demo-only function in the bundled simulator. A
  stock Moodle does not expose it; the sync treats that refusal as a data gap and
  continues.
- `list_students()` passes the stored rows as `features_by_student`. `map_student()`
  leaves a missing row blank, so a blank score is a data gap, not a low risk. A caller
  can also pass a complete snapshot as `student["features"]`. The adapter scores only
  when every one of the 14 columns is present; anything less stays unscored.
- Bands are `review` when `score >= threshold` and `routine` otherwise. The raw number is
  kept as `risk`. There are no invented high/medium/low bands.
- `synthetic` reflects the bundle (with the training metrics sidecar as the fallback for
  the shipped archive). `automatic_actions` is always `false`: no enrolment change, no
  message, no grade.

## `passage-reuse` (integrity)

The plagiarism model is **not vendored**. ProfAssist calls an external worker over JSON.

### Configuration

- `PLAGIARISM_WORKER_URL`: base URL of the worker. Without it the status is
  `not_installed` and scoring raises a fixed 503.
- `PLAGIARISM_WORKER_TOKEN`: optional bearer token. The status reports only whether a
  token is set; it never returns the value.
- `plagiarism_status(probe=False)` performs no network call. `probe=True` calls
  `/health` with a 3-second timeout and reports `reachable` without raising.

### Input contract (ProfAssist to worker)

`POST {PLAGIARISM_WORKER_URL}/score`

```json
{
  "scope": {"assignment_id": "a1"},
  "reports": [{"report_id": "r1", "document_id": "d1", "text": "..."}],
  "source_reports": [{"report_id": "s1", "document_id": "d2", "text": "..."}]
}
```

`source_reports` is included only when the caller provides it. The request has a
60-second timeout. When a token is set, the request adds `Authorization: Bearer <token>`.

### Output contract (worker to ProfAssist)

```json
{
  "schema_version": "1.0",
  "scope": {"assignment_id": "a1"},
  "display_flags": [{"report_id": "r1", "severity": "review", "passages": []}],
  "run_id": "worker-run-id"
}
```

The gateway validates that the result is an object with matching `schema_version` and
`scope` and that `display_flags` is a list of objects, then returns the worker result
unchanged.

### Failure behaviour

Any network error, non-2xx response, invalid JSON, or contract violation becomes
`ProfassistError(503, "The plagiarism worker is not available. Configure it in ML
settings.")`. The message never contains excerpts, report text, a token, or a worker
payload.

### Threshold warning

The upstream PAN 2013 passage-reuse result reports a threshold of `0.922696`. That value
is **PAN-specific** and must be re-selected for this corpus. Do not present it as a
general-purpose cut-off, and do not let the worker silently reuse it on new data.

### Integrity integration

ProfAssist stores the returned flags and displays them to the professor. It does not
recompute the similarity, store a model, or ship an excerpt in an error message. The
worker owns the model, the threshold, and the matching.

## Admin and registry status

`/admin/models` still returns the existing MLflow payload. It now also includes
`gateway.models`, the two cards above, so the page can distinguish "not in MLflow" from
"not trained" and from "external worker not configured". MLflow versions are reported
only when MLflow actually returns them; the gateway does not invent a version.

## Intentionally not implemented

- No pass/fail model, because none exists upstream.
- No training loop, no model promotion, and no automatic intervention.
- No vendored plagiarism code or artifacts.
- No invented scores when the 14 features or the worker are missing.
- No upstream license claim while the upstream repository has no LICENSE file.
