# Private model worker runtime

ProfAssist calls the model worker over the Compose-only `backend` network. The
worker listens on port 8081 inside that network; it has no published host port.
`GET /health` is a fixed liveness response. `POST /jobs/{operation}` requires a
bearer token and a version 1 envelope with a UUID `context.job_id`, a matching
`operation`, and object-valued `context` and `payload`. The HTTP shim forwards
that envelope to `python -m profassist_worker OP --input ...
--output ... --work-dir ...` and returns the CLI result. It only allows the
eight operation names implemented by the integration worker.
The worker overwrites `context.tracking_uri` from `MLFLOW_TRACKING_URI` and
sets `context.encoder_dir` to `/app/models/minilm`, so callers cannot choose a
registry endpoint or host path.

The worker writes mode-0600 request and result files to the private
`profassist_worker_data` volume. Each UUID has a stable job directory and each
scope is mapped to a SHA-256-derived directory name. Identical retries return
the stored result; reuse of a UUID with a different envelope is rejected. The
worker returns fixed error messages and does not include CLI stderr or input
data in its HTTP errors. Operations have a configurable 300-second default
timeout. The API service and Prefect runner share the bearer token and URL.
When an assignment has no active release row yet, the API uses the configured
seed as its baseline for scoring, snapshot creation, and training. Set
`PASSAGE_REUSE_MODEL_NAME` and `PASSAGE_REUSE_MODEL_VERSION` to the exact
registered name and concrete version of a worker-verified seed bundle. The
workflow stays unavailable until an active release or verified seed is
configured.

## Build and run

The worker image must be built from the same source revision as the upstream
`student-dropout-mlops` integration checkout, with both model runtime dependency
sets installed. The Compose shim is built on top of that private local image;
it does not fetch or publish an image. Set these values in the shell or a local
`.env` file used by Compose:

```dotenv
PROFASSIST_WORKER_BASE_IMAGE=profassist_mlops_worker_base:integration
PROFASSIST_MLOPS_SOURCE=/absolute/path/to/student-dropout-mlops
PROFASSIST_MINILM_MODEL_DIR=/absolute/path/to/student-dropout-mlops/models/minilm
PROFASSIST_WORKER_TOKEN=replace-with-a-random-local-secret
PROFASSIST_WORKER_TIMEOUT_SECONDS=300
PLAGIARISM_WORKER_URL=http://profassist-worker:8081
PASSAGE_REUSE_MODEL_NAME=passage-reuse
PASSAGE_REUSE_MODEL_VERSION=1
```

Build the upstream combined worker image and the small HTTP shim, then start
the stack:

```sh
docker compose --profile mlops build profassist-worker-base profassist-worker
docker compose --profile mlops up -d
```

`profassist-worker-base` builds `Dockerfile.worker` directly from the configured
separate `student-dropout-mlops` checkout. Use its `integration/profassist-workers`
branch and verify the source revision before building. The image includes the
`src/profassist_worker`, `src/dropout`, and `src/plagiarism` packages and MLflow
3.18.0. Compose mounts the staged MiniLM model read-only at
`/app/models/minilm`. Keep the image in the private deployment registry or
local image store. Do not use a public registry for student data or model
artifacts.

The local example MLflow server is also pinned to 3.18.0 and uses the dedicated
`mlflow` PostgreSQL database plus the `profassist/mlflow` MinIO artifact root.
Worker and Prefect containers receive the internal MLflow URL, S3-compatible
endpoint, and credentials needed for direct artifact access. The API exposes
the MLflow UI at localhost:5000 for local development; worker port 8081 remains
private.

## Runtime checks

Run the fake CLI smoke test without downloading models or starting Docker:

```sh
python3 private-worker/smoke_test.py
docker compose config --quiet
```

For an actual scoring rehearsal, use only the verified seed release and
synthetic or authorized fixtures. Inspect the worker and Prefect logs for
operation status; the worker volume retains immutable request/result files and
scope-local artifacts for retry and audit. Do not mount Moodle identity exports
or raw student files into the worker image.

## Browser verification

The [integration screenshots](images/mlops-integration/) show a completed
plagiarism scan, a matched passage, a live reviewed-dataset freeze, and the
Students and Models views populated with verified synthetic dropout results.
