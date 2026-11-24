# ProfAssist

**AI drafting for one professor, with a council of reviewers and a human approval gate.**

> **Status: proof of concept (POC).** ProfAssist is a working professor workflow built on the [Vstorm full-stack AI agent template](https://github.com/vstorm-co/full-stack-ai-agent-template) (FastAPI + Next.js + LangGraph + PostgreSQL + Qdrant + MinIO + Prefect). It is not a production student system: the Moodle connector is demonstrated against a bundled simulator, the dropout model is a synthetic demo artifact, and the plagiarism worker is an external contract that is not installed here.

ProfAssist drafts course outlines, materials, assignments, rubrics, grades, feedback, and similarity flags. Every artifact stays a draft. Nothing is pushed to Moodle until the professor approves it. Student risk is advisory. An integrity flag is evidence for a conversation, never a verdict.

## Screenshots

| Sign in | Dashboard |
|---|---|
| ![Login](docs/images/login.png) | ![Dashboard](docs/images/dashboard.png) |
| Two-column sign-in: feature icons on the left, email and password with a visibility toggle on the right. The form starts empty - there are no demo credentials. | The workspace after sign-in. The left sidebar is the only workspace navigation; the top bar carries utilities only. |

| Council settings - Material | Council settings - Assignment |
|---|---|
| ![Material council settings](docs/images/councils-material.png) | ![Assignment council settings](docs/images/councils-assignment.png) |
| Creator → Curriculum → Evidence → Design → Chair. Roles can be reordered, disabled, or given their own model and persona. | Creator → Alignment → Brief → Rubric → Chair. The flow preview is the speaking order; the chair always runs last. |

| Material Designer - live council | Assignment council - filtered roster |
|---|---|
| ![Five-role material collaboration](docs/images/studio-council-five.png) | ![Assignment council transcript](docs/images/assignment-council-final.png) |
| A single-week request runs the Creator and the enabled reviewers, then the Chair. The deck is ready at 80/100. | With Rubric disabled, the transcript contains Alignment, Brief, and Chair only. Disabled roles do not speak. |

| Integrity - DB-backed board | Students - dropout early warning |
|---|---|
| ![Integrity board](docs/images/integrity-db-final.png) | ![Students at risk](docs/images/students-dropout-final.png) |
| Six groups, three pairs to read, real submission text, and a concern stored in Postgres. Flags are evidence, not guilt. | The demo model is labelled synthetic. Bands are review/routine in the API and High/Low in the UI: 5 review, 7 routine. Nothing changes enrolment, messages, or marks. |

| Moodle connection | Admin - ML models |
|---|---|
| ![Moodle connection](docs/images/moodle-connection-final.png) | ![ML models](docs/images/admin-models-final.png) |
| Verified connection, capability checklist, schedule, last run, and sync history. The token is encrypted and never returned. | Dropout is ready but synthetic; passage-reuse is not installed; MLflow is reachable. No pass/fail model is shown because none exists. |

| My style - auto-applied reflection | |
|---|---|
| ![Style reflection](docs/images/style-reflection.png) | |
| Reflection history after auto-apply. The About me portrait was rewritten; there is no Approve button because the proposal is applied and kept in history. | |

### Navigation

The **left sidebar is the only workspace navigation**. The top bar carries utilities only: the brand, search, theme, the organization switcher, and the profile menu, with the **Ask ProfAssist** chat entry point in the page header below it. There are no top-level Home or Grading links in the header.

## What it does

### Four design surfaces

| Surface | Route | What the professor gets |
|---|---|---|
| **Course Designer** | `/outline` | A ten-step subject outline: course details, CLOs/PLOs, weekly schedule, readings, assessment map, policies, attachments, and a generated PDF/DOCX. |
| **Material Designer** | `/studio` | Notes become a cited slide deck for a chosen week, with speaker notes, source passages, gap notes, thumbnails, and PowerPoint export. |
| **Assignment Designer** | `/assignments` | An assignment brief, ideas and exemplars, group allocation, a rubric, and a council review before publishing. |
| **Rubric builder** | `/rubric` | Criteria and four levels, inline editing, versions, alignment checks, and import from paste, DOCX, PDF, or XLSX. |

### Assess, students, and style

- **Grading.** The grading council votes on the rubric, a judge reconciles the votes, the professor edits the level and comment, and only then can a grade be pushed. If the votes are not supported by quotes from the submission, the level is left to the professor instead of being invented.
- **Integrity.** Scans compare submissions, store flags in Postgres, and show the two documents side by side with highlighted passages and viva questions. The board supports confirm, dismiss, and pair review.
- **Students.** The roster is listed with an advisory course-withdrawal score and a clear data-gap state when the 14 required features are missing. There is no pass/fail prediction and no automatic intervention.
- **My style.** `soul.md`, an editable **About me** portrait, private memories, and reflection history. A reflection is applied automatically when the threshold is reached, the portrait is rewritten, and the previous wording stays in history.
- **Sign-in.** A two-column sign-in page: feature icons and the workspace promise on the left, email and password on the right, with a show/hide password toggle. The form starts empty; there are no fake demo credentials.
- **Home and chat.** A professor home with briefing facts and a universal chat sheet that streams tool cards and citations. The chat can call the same tools as the FastMCP server, but a push or delete still waits for confirmation.

## Architecture

```mermaid
flowchart LR
    B[Next.js 15 UI<br/>App Router + BFF] -->|JWT cookie / REST / SSE| A[FastAPI<br/>routes → services → repositories]
    A --> PG[(PostgreSQL 16<br/>source of truth)]
    A --> R[(Redis<br/>cache + rate limit)]
    A --> Q[(Qdrant<br/>notes, memory mirror)]
    A --> M[(MinIO<br/>files + deck artifacts)]
    A --> P[Prefect<br/>Moodle sync jobs]
    A --> L[LiteLLM<br/>OpenAI, Gemini, Anthropic, ...]
    A --> LF[Langfuse<br/>traces + prompt labels]
    A --> ML[MLflow<br/>tracking server]
    A --> MO[Moodle web service<br/>or bundled mock]
    A --> W[External plagiarism worker<br/>JSON contract]
    P --> MO
```

The request path is deliberately conventional: an API route validates and authorizes, a service owns the workflow, a repository owns SQL, and the service returns a Pydantic response. Professor-owned rows carry `organization_id` and `owner_user_id`; course-owned rows are scoped to the organization.

### Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic (`0043_council_settings` is head), pytest |
| Frontend | Next.js 15 App Router, React 19, TypeScript, Tailwind CSS 4, Zustand, TanStack Query, next-intl |
| AI | LangGraph graphs, LiteLLM providers, Langfuse traces and `production` prompt labels |
| Retrieval | Local fastembed embeddings by default, Qdrant `profassist` collection, keyword-overlap fallback |
| Data | PostgreSQL (primary), Redis (cache/limits), MinIO (S3-compatible files), Qdrant (vectors) |
| Operations | Docker Compose, Prefect server + runner, MLflow, Langfuse, Nginx |
| Identity | JWT access/refresh cookies, bcrypt passwords, shared `X-API-Key` for service calls, organization memberships |

### AI councils

Four councils are configured per university. Defaults live in code; a saved roster in `pa_council_roles` replaces the default for that organization. The list order is the speaking order, the chair is always last, and exactly one chair is required.

| Council | Default roster | What it does |
|---|---|---|
| **Material** | Creator → Curriculum → Evidence → Design → Chair | The Creator drafts a week's deck; deterministic reviewers check curriculum fit, evidence/citations, and design; the Chair returns a verdict and score. The collaboration stream repairs structural issues for up to two rounds and stops on a pass, a pause, or when a repair would require inventing content. |
| **Assignment** | Creator → Alignment → Brief → Rubric → Chair | The Creator drafts the brief and rubric; Alignment, Brief, and Rubric run deterministic checks; the Chair summarises only the findings that exist. A clean assignment comes back clean. |
| **Grading** | Evidence, Strict, Supportive → Chair/judge | Three personas vote per criterion with verbatim quotes. If the spread exceeds the configured threshold, they debate for up to three rounds; the judge then reconciles. Quotes not present in the submission are rejected, and a "no reliable evidence" result leaves the level to the professor. |
| **Outline** | Curriculum → Alignment → Balance → Student → Chair | Pre-approval review of the subject outline. Every finding names a real section and object, carries a severity, and offers a one-click fix. High findings do not block approval; they are shown. |

**Edit them at `/admin/councils`.** The page is restricted to app admins and is scoped to the active organization. For each role the admin can enable or disable it, change its label, choose its provider/model, edit its persona prompt, and reorder it. Material and Assignment also accept custom LLM reviewer roles. **Reset** deletes the organization's rows so the code default speaks again. The page changes the actual graph, not a mock.

**Langfuse boundary: prompts yes, roster no.** Prompt text is resolved in this order: Langfuse `production` label → database copy → code default. For global agents, `/admin/ai` edits the prompt: each save writes a database version and, when Langfuse is enabled, publishes a new `production` version there. The database copy is the fallback when Langfuse is off or unreachable. The council *roster* (which roles run, in what order, enabled/disabled, model, persona) is Postgres only; editing a Langfuse prompt cannot add or remove a council member. `/admin/ai` also controls the provider, model, tools, chat on/off, and shows which prompt copy is live. Traces are opened after the privacy gate, and the acting tenant/professor are stored as short hashes rather than emails.

Prompt URLs follow `http://localhost:3100/project/profassist-project/prompts/<name>`; trace URLs follow `.../traces/<id>`.

## RAG, document memory, and the course dossier

- **Course files.** Upload `.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.potx`, `.html`, or `.htm`. Files are parsed locally (PyMuPDF for PDF, python-docx for DOCX, python-pptx for decks), passed through the privacy gate, chunked, embedded, and stored. A file that fails the PII gate is quarantined and never sent to a model.
- **Retrieval.** The default embedder is local fastembed (`BAAI/bge-small-en-v1.5`, 384 dimensions), so no note text leaves the machine. Vectors go to the Qdrant `profassist` collection when it is reachable; keyword overlap always runs, so a stopped vector store does not block drafting.
- **Course dossier.** The course memory service builds one dossier per organization, course, and professor from the official outline and ready materials, then merges it with source authority. A rebuild is idempotent by content hash. The stored body is bounded and the served context is trimmed to the caller's budget (4,000-8,000 characters). The dossier status is `ready` or `stale`; a stale dossier is never silently presented as current.
- **Collections and sync sources.** The template's RAG API and CLI are still available for organization-wide knowledge bases: `rag-ingest`, `rag-search`, `rag-collections`, `rag-sources`, and Google Drive / S3 sync connectors. See [docs/commands.md](docs/commands.md) and [docs/architecture.md](docs/architecture.md).
- **What a draft receives.** The prompt gets the official outline, the dossier, retrieved note passages with citations, and the professor's labelled **About this professor** section. It does not get another professor's notes or memories.

## Machine learning

ProfAssist exposes exactly two upstream models and no pass/fail model. There is no model in the upstream repository that predicts a grade, a pass, or a fail, and this build does not invent one.

| Model | Kind | Status in this build | Runtime |
|---|---|---|---|
| `student-dropout` | Early warning (course withdrawal) | `ready`, synthetic demo artifact, threshold `0.1` | In-process scikit-learn adapter |
| `passage-reuse` | Integrity | `not_installed` unless `PLAGIARISM_WORKER_URL` is set | External JSON worker |

### Dropout is withdrawal, not pass/fail

- The target is **withdrawal after the day-35 snapshot and by course end**, conditional on active enrolment. It is not failure and not university departure.
- The adapter scores only when all 14 allowlisted activity features are present. A missing row is a **data gap**, not a low risk. A blank score is shown as blank.
- Bands are `review` when the score is at or above the bundle threshold and `routine` otherwise. The raw number is kept as `risk`. The UI labels the two bands High and Low for readability.
- `automatic_actions` is always `false`. The score never changes enrolment, sends a message, or changes a grade.
- The shipped bundle is trained on a seeded 480-row synthetic Moodle-shaped dataset. `artifacts/metrics.json` marks it `"synthetic": true`, and the Students page and Admin → Models page both say so.

### Plagiarism is an external worker contract

- No plagiarism model or artifacts are vendored in this repository. ProfAssist calls an external worker over JSON at `POST {PLAGIARISM_WORKER_URL}/score` with a 60-second timeout and an optional bearer token.
- The worker owns the model, threshold, and matching. ProfAssist validates `schema_version`, `scope`, and `display_flags`, stores the returned flags, and returns the worker result unchanged.
- Without a worker URL the status is `not_installed`, and scoring raises a fixed `503` ("The plagiarism worker is not available"). There are no fake scores and no invented excerpts in error messages.
- The upstream PAN 2013 threshold `0.922696` is corpus-specific and must be re-selected; it is not a general-purpose cut-off.

### MLflow

MLflow runs at <http://localhost:5000> with its own Postgres database and artifacts in MinIO (`s3://profassist/mlflow`). It is a tracking server, not a training pipeline. No training run is registered by this build. The Admin → Models response reports MLflow as reachable only when a call succeeds, and it reports a model version only when MLflow actually returns one.

## Moodle

Each university connects its own Moodle site at **Admin → Moodle** (`/admin/integrations/moodle`). One row in `pa_moodle_connections` holds the site address, the encrypted web-service token, the course scope, and the push flag.

- **Read path.** Courses, enrolled students, assignments, latest submission attempts, submission files, rubrics, and workshops come through the Moodle web service. A sync writes courses, students, assessments, submissions, files, groups, and activity features to Postgres.
- **Schedule.** Prefect runs the pull every 30 minutes by default (a university can pause it or pick another interval) plus a nightly full sync. **Sync now** is the manual backup.
- **Connection page.** Test connection returns a five-item checklist (Moodle answers, functions, download files, upload files, completion) and the advertised capability count. The page also shows the course scope, schedule, run history, and activity-log state, and it distinguishes **Last run** (rows imported this run) from **Currently synced** (stored totals).
- **Push.** Grade writes are **off** by default (`MOODLE_PUSH_ENABLED=false`). A grade reaches Moodle only after the professor approves it and an admin enables push. In `fake` mode the push is recorded locally and Moodle is not contacted.
- **Bundled simulator.** `backend/mock_moodle/` is a demo Moodle with one course, twelve users, two assessments, six submissions, three shared passages, a workshop, and activity logs. It runs as the `moodle-mock` service on port 8090 and exposes `local_profassist_get_activity`, a demo-only function. A stock Moodle refuses that function; the connector treats the refusal as a data gap and continues.
- **Why activity logs are demo-only.** The 14 dropout features are imported into `pa_moodle_activity` through `local_profassist_get_activity`. A real site needs a reviewed plugin or an equivalent export before those features exist.
- **The E2E run imported** one course, 12 students, 2 assessments, 6 submissions, and 12 activity rows. The "last run" counters are rows imported **this run**; an idempotent re-sync correctly reports zero new rows while the database totals remain 1/12/2/6/12.

See [docs/moodle-connector.md](docs/moodle-connector.md) for the token, SSRF, scope, and error-mapping rules.

## Memory

- **Postgres is the source of truth.** Every memory write goes to `pa_memories` first. Recall, the memory list, and the memory panel read from Postgres.
- **Qdrant is a mirror.** After the Postgres write, a copy is upserted into the `profassist_memory` collection with a 64-dimensional hash embedding. If Qdrant is down, the failure is logged and the Postgres copy remains.
- **Mem0 is an optional mirror.** Mem0 support is present but disabled unless `MEM0_ENABLED=true` and an LLM key is configured. It is never the source of truth; its hits are merged after Postgres and a failure is swallowed. The local override in this working copy enables it with a local fastembed embedder, which is why the E2E run could add and search memories (2 hits) and why Qdrant showed points for `mem0_profassist` and `mem0_profassist_entities`.
- **Reflection auto-applies.** After enough new lessons, or on demand from **My style**, the reflection agent rewrites the professor's portrait. The new text is applied to **About me**, the previous wording stays in history, and the reflection row is kept. `/style` therefore has no Approve button; the history is the audit trail. Shared prompts are never rewritten by a reflection.
- **Privacy.** Memory text is scrubbed before storage. Student names, emails, IDs, and other PII do not enter memory, and memory does not cross tenant or professor scope.

See [docs/memory.md](docs/memory.md) for the Mem0 embedder and telemetry settings.

## Security and trust boundaries

| Control | How it is implemented |
|---|---|
| **PII before a model call** | A local regex gate removes names, emails, phones, student IDs, and bare long IDs. Optional Presidio is available. If a personal-data pattern is still present after replacement, the file or text is quarantined and not sent. The token map stays in Postgres (`pa_pii_vault`), never in the prompt. |
| **Tenant scope** | A university is an organization. Course- and roster-level rows carry `organization_id`; professor-owned rows also carry `owner_user_id`. Routes resolve the active organization and services filter by it. Qdrant payloads include both ids. |
| **Row-level security caveat** | RLS policies and a `profassist_app` role exist, including on `pa_council_roles`. Docker Compose connects as the Postgres superuser, which bypasses RLS, so the application-level organization filter is what actually holds in this stack. Do not describe RLS alone as the isolation boundary. |
| **Connector token encryption** | The Moodle web-service token is stored as `enc:` Fernet ciphertext derived from `SECRET_KEY`. Only the last four characters are kept in clear as a hint. The token is never returned by the API. A blank token on update keeps the stored ciphertext; a new token rotates it and resets the connection to `unverified`. |
| **Token redaction** | Every Moodle error path strips `wstoken=...` and `token=...` before the message reaches storage, a log line, an API response, or the audit row. `httpx` error strings use the same scrubber. |
| **SSRF protection** | Production requires `https://`. Loopback, private, link-local, CGNAT, and unsupported schemes are rejected after host resolution. `http://localhost` is accepted only with `MOODLE_ALLOW_PRIVATE=true`, which is a development convenience. |
| **Admin authorization** | Council settings, Moodle connection changes, and ML administration require `is_app_admin` **and** an organization the admin belongs to. A professor can read the redacted Moodle status for grading/outline pages but cannot change the connection. Professor-owned resources are owner-scoped; a foreign course returns 404 before a dossier lookup. |
| **No automatic push** | Every artifact is a draft. A grade push requires the professor's approval and `MOODLE_PUSH_ENABLED=true`; one-click approve and automatic push are off. A chat tool that would push or delete waits for confirmation. |
| **Abuse limits** | Authentication endpoints are limited per IP (default 5 requests per 15 minutes). The E2E run hit the limit after repeated browser logins, which is expected protection, not an application failure. |
| **Secrets** | Keys come from environment variables. `.env` and `backend/.env` are gitignored, provider keys are never returned, and the shared API key is compared with `secrets.compare_digest`. |
| **No Kafka** | This POC does not publish to Kafka, so there is no event stream and no Kafka dedupe path to reason about. Idempotency is handled where it exists: Moodle sync runs are recorded per run, and dossier rebuilds are keyed by content hash. |

## Run it locally

### Prerequisites

- Docker Desktop (or Docker Engine with Compose v2).
- Several GB of free memory for the full stack (Postgres, Redis, Qdrant, MinIO, Prefect, Langfuse, ClickHouse, MLflow, backend, frontend).
- A Google AI Studio key (`GEMINI_API_KEY`) for live drafting, the AI agent, and Mem0. Without one, drafting fails with an explicit `503`; nothing is fabricated.

### Start (one command)

```bash
cp .env.example .env
# open .env and set GEMINI_API_KEY=...   (LLM_MODEL is optional)

make demo
```

`make demo` builds the app, prefect-runner, and frontend images, starts the stack, and waits for `/api/v1/health`. Without `make`, use the platform script: `powershell -ExecutionPolicy Bypass -File scripts/demo.ps1` on Windows, or `sh scripts/demo.sh` on Linux/macOS/WSL. The plain Docker path is equivalent:

```bash
docker compose up -d --build
```

The first start downloads images and installs Python and Node packages, so it takes a while. The backend entrypoint runs `alembic upgrade head` before starting Uvicorn. Confirm the migration state:

```bash
docker compose exec app alembic current

# 0043_council_settings (head)
```

### URLs

| Service | URL | Notes |
|---|---|---|
| ProfAssist | <http://localhost:3000> | Next.js app |
| API docs | <http://localhost:8000/docs> | OpenAPI, local/staging only |
| API health | <http://localhost:8000/api/v1/health> | `{"status":"healthy",...}` |
| Moodle mock | <http://localhost:8090/health> | Bundled simulator |
| Langfuse | <http://localhost:3100> | Traces and prompt labels |
| MLflow | <http://localhost:5000> | Tracking UI |
| Prefect | <http://localhost:4200> | Flow runs and schedule |
| MinIO console | <http://localhost:9001> | User `profassist`, password `profassist-secret` |
| Qdrant | <http://localhost:6333> | Vector store API |
| PostgreSQL | `localhost:5432` | Database `profassist` |
| Redis | `localhost:6379` | Cache and rate limits |

### Keys, models, and what is on

The only required value is **`GEMINI_API_KEY`** in the root `.env`. One Gemini key serves drafting, the AI agent, and Mem0; `LLM_API_KEY` / `OPENAI_API_KEY` are optional overrides, and `LLM_MODEL` / `AI_MODEL` default to `gemini/gemini-3.5-flash-lite`. A prefixed model (`gemini/...`, `openai/...`) selects the provider whose key is spent. Other supported providers include Anthropic, xAI, Mistral, Azure OpenAI, AWS Bedrock, Ollama, and any OpenAI-compatible base URL.

- **The key is never committed.** `.env` is gitignored and the tracked `.env.example` holds placeholders only. In a shared repo, each person copies `.env.example` to `.env` and adds their own key once; nothing else needs to change.
- **Mem0 is on.** Compose sets `MEM0_ENABLED=true` with the local `fastembed` embedder (`BAAI/bge-small-en-v1.5`, 384 dims) and its history at `/app/data/mem0.db` on the `mem0_data` volume. Postgres remains the source of truth; if Mem0 is unavailable, the Postgres copy still answers.
- **Langfuse and MLflow are on** in the bundled stack (URLs below). `/admin/ai` lists each provider and whether its environment key is set; it never shows the key. Each model-backed council role can use its own provider/model from `/admin/councils`.
- **The Moodle connection is preconfigured** against the bundled mock (`MOODLE_BASE_URL=http://moodle-mock:8090`, `demo-token`, private hosts allowed). Open `/admin/integrations/moodle` and use **Test** and **Sync now**; the mock is seeded with one course, 12 students, 2 assessments, and 6 submissions.

### Create a login

**The repository does not seed an application user.** A fresh database has no professor login, and the old demo credentials in earlier documentation do not exist here. The local E2E environment used `professor@demo.uowd.ac.ae` inside a manually created University of Wollongong in Dubai workspace; that account was created in that environment, not by a seed script.

Create your own account:

1. Open <http://localhost:3000/register> and register with any email and a password of at least 8 characters.
2. **The first user to register** is automatically promoted to app-admin and gets a Personal organization, so register before sharing the URL. That is the account to use for `/admin/councils`, `/admin/models`, and `/admin/integrations/moodle`.
3. To promote a later account, run:

```bash
docker compose exec app profassist cmd create-app-admin you@example.edu
```

4. For a university workspace, create a team organization in **Workspace**, then create a course. To reproduce the screenshots, point the Moodle connection at the bundled simulator and run **Sync now**; the repo intentionally ships no real student records.

Langfuse has its own local seeded demo user in `docker-compose.yml`; that is the Langfuse UI login, not a ProfAssist login.

## Testing

Full commands, counts, trace URLs, screenshots, and known skips are in **[docs/testing-pack.md](docs/testing-pack.md)**.

- **Backend:** `1071 passed, 4 skipped, 125 warnings in 100.62s` with `uv run --frozen pytest -q`.
- **Frontend:** `16 files passed, 107 tests passed` with `npx vitest run`.
- **Type-check:** exit 0. **ESLint:** 0 errors, 2 warnings in `frontend/src/app/[locale]/(dashboard)/integrity/page.tsx` (unused `showPassage` and `SubmissionCard`). **Prettier:** all checked files pass.
- **E2E:** a local Docker Compose run covered councils, Moodle, students, integrity, models, Mem0, reflection, and Langfuse. All four findings from that run were fixed (en dash 500, Material collaboration copy, Moodle last-run labels, and the MLflow cache race). It is documented in the testing pack with the exact traces and screenshots. CI runs Ruff, type check, the backend suite, the frontend type check/lint/build, and the frontend unit tests; it does **not** run a Playwright journey (the old demo-mode journey was removed).

The 4 skips are the destructive Alembic migration tests. They run only when `TEST_DATABASE_URL` points at a dedicated database; see the testing pack for the exact command.

## Known limitations

| Area | Limitation |
|---|---|
| **Moodle** | The bundled `moodle-mock` is the only Moodle exercised end to end. The real connector reads through the web service, but no live Moodle or live grade push was performed. `MOODLE_PUSH_ENABLED=false` by default. |
| **Plagiarism** | No worker, model, or artifacts are included. `passage-reuse` remains `not_installed`; scoring returns a fixed `503` until an external worker is configured. No fake similarity scores. |
| **Dropout model** | The model predicts **course withdrawal**, not pass/fail. The bundle is synthetic (480 seeded rows), and the demo threshold is `0.1`. There is no training loop or model promotion. |
| **Data and license** | No real student records are in the repository. The app is MIT-licensed as generated from the template, but the vendored `student-dropout` port has **no upstream LICENSE file**; it is included for contract/demo purposes only, and redistribution or production use needs written permission from the upstream author. |
| **Migrations** | 4 destructive migration tests skip unless a dedicated test database is configured. The compose database user is a superuser, so RLS is not the effective boundary in this stack. |
| **Memory** | Mem0 is optional and off in a clean environment. Postgres is always the source of truth; Qdrant and Mem0 are mirrors. |
| **Not implemented** | No Kafka, DVC, Evidently, SHAP, XGBoost training, LlamaIndex, student-facing notice, regrade queue, or AI-text detector. Kafka being absent means there is no event dedupe path to test. |

## Repository map

```text
backend/
  app/
    api/routes/v1/          # Auth, orgs, RAG, councils, ML admin, Moodle, profassist routes
    services/               # Business logic and orchestration
    repositories/           # SQLAlchemy data access
    schemas/                # Pydantic Create/Update/Response models
    db/models/              # SQLAlchemy 2 models
    agents/                 # Template LangGraph chat assistant
    profassist/             # Professor workflow
      agents.py             # Course, rubric, grading, feedback, reflection graphs
      service.py            # Use cases and artifact lifecycle
      council_config.py     # Four council defaults, validation, persistence
      assignment_council.py # Assignment reviewers + chair
      outline_review.py     # Outline reviewers + findings
      integrity_board.py    # DB-backed integrity board and pair views
      moodle.py             # Web-service client, fake mode, redaction
      moodle_connection.py  # Per-org encrypted connection
      course_memory/        # Dossier extraction, merge, budget, AI context
      ml/                   # Dropout adapter, external worker gateway, upstream port
      pii.py                # Privacy gate and quarantine
      rag.py                # Notes chunking, embeddings, Qdrant, keyword fallback
    worker/                 # Prefect flows and deployments
  alembic/versions/         # 0043_council_settings is head
  mock_moodle/              # Bundled Moodle simulator
  tests/                    # 67 test modules, mocked DB, no external services
frontend/
  src/app/[locale]/         # App Router: (auth), (dashboard), marketing
  src/components/           # Professor UI, councils, chat, layout
  src/stores/               # Zustand auth/state
  e2e/                      # Playwright skeleton (local/manual)
docs/                       # Architecture, ML, Moodle, memory, testing pack, images
docker-compose.yml          # Full local stack
```

## Documentation

- [Testing pack](docs/testing-pack.md) - commands, counts, matrix, traces, failures, skips.
- [Architecture](docs/architecture.md) - layers, auth, files, RAG.
- [ML](docs/ml.md) - dropout and passage-reuse contracts.
- [Moodle connector](docs/moodle-connector.md) - token, SSRF, scope, activity logs.
- [Memory](docs/memory.md) - Postgres, Qdrant, Mem0.
- [Prompts](docs/prompts.md) - global prompt versioning, fallback order, council prompts.
- [Permissions](docs/permissions.md), [Security](SECURITY.md), [Configuration](docs/configuration.md), [Commands](docs/commands.md).
- [Status vs design](docs/STATUS_VS_DESIGN.md) - what is done, partial, stubbed, or not done against the architecture report.

## License

The template and this repository are MIT-licensed; see [LICENSE](LICENSE), which retains the Vstorm copyright. The `student-dropout` upstream port has no LICENSE file; see [docs/ml.md](docs/ml.md) and `backend/app/profassist/ml/dropout/NOTICE.md`. Do not redistribute that port or use it in production without written permission.
