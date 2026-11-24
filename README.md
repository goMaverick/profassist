# ProfAssist

**AI drafting for one professor, with a council of LLM reviewers and a human approval gate.**

> **Status: proof of concept (POC).** Built on the [Vstorm full-stack AI agent template](https://github.com/vstorm-co/full-stack-ai-agent-template) (FastAPI + Next.js + LangGraph). Not a production student system: Moodle is exercised against a bundled simulator, the dropout model is a synthetic demo artifact, and the plagiarism worker is an external contract that is not installed here.

- **Draft courses** - a ten-step subject outline with CLOs/PLOs, weekly schedule, readings, assessment map, and PDF/DOCX export.
- **Cited decks** - notes become a slide deck with source passages, speaker notes, gap notes, and PowerPoint export.
- **Assignments and rubrics** - brief, exemplars, group allocation, a four-level rubric, and a council review before publishing.
- **Grade, integrity, dropout** - an advisory grading council with verbatim quotes, a DB-backed similarity board, and a course-withdrawal early warning.

Every artifact stays a draft. Nothing reaches Moodle until the professor approves it. A similarity flag is evidence for a conversation, never a verdict. Student risk is advisory only.

## Quick start

```bash
cp .env.example .env          # then set GEMINI_API_KEY=...
make demo                     # Windows: powershell -ExecutionPolicy Bypass -File scripts/demo.ps1
# open http://localhost:3000, register - the first user becomes the app admin
```

Needs Docker Desktop (or Docker Engine + Compose v2) and a Google AI Studio key in `GEMINI_API_KEY`. `make demo` builds the images, starts the stack, and waits for `/api/v1/health`; the backend runs `alembic upgrade head` before Uvicorn. The first start downloads images and packages, so it is slow once. Without `make`, `docker compose up -d --build` is equivalent. Sign-in form is empty by design: register first, there are no demo credentials.

## Screens

| Sign in | Dashboard |
|---|---|
| ![Login](docs/images/login.png) | ![Dashboard](docs/images/dashboard.png) |
| Two-column sign-in; the form starts empty, there are no demo credentials. | Workspace after sign-in; the left sidebar is the only workspace navigation. |

| Councils - Material | Councils - Outline |
|---|---|
| ![Material council settings](docs/images/councils-material.png) | ![Outline council settings](docs/images/councils-outline.png) |
| Creator -> Curriculum -> Evidence -> Design -> Chair, each with its own model and persona. | Creator -> Curriculum -> Alignment -> Balance -> Student -> Chair; every reviewer is an LLM agent. |

| Material Designer - live council | Assignment council - filtered roster |
|---|---|
| ![Five-role material collaboration](docs/images/studio-council-five.png) | ![Assignment council transcript](docs/images/assignment-council-final.png) |
| One week runs the Creator, the enabled reviewers, then the Chair; deck ready at 80/100. | With Rubric disabled, only Alignment, Brief, and Chair speak. |

| Integrity - DB-backed board | Students - dropout early warning |
|---|---|
| ![Integrity board](docs/images/integrity-db-final.png) | ![Students at risk](docs/images/students-dropout-final.png) |
| Six groups, three pairs, real submission text; flags are evidence, not guilt. | Synthetic demo model: 5 review / 7 routine (High/Low in the UI); no enrolment, message, or mark changes. |

| Moodle connection | Admin - ML models |
|---|---|
| ![Moodle connection](docs/images/moodle-connection-final.png) | ![ML models](docs/images/admin-models-final.png) |
| Verified connection, capability checklist, schedule, last run, and sync history. | Dropout ready but synthetic; passage-reuse not installed; MLflow reachable; no pass/fail model. |

| My style - auto-applied reflection | |
|---|---|
| ![Style reflection](docs/images/style-reflection.png) | |
| Reflection applied automatically; the About me portrait was rewritten and the old wording stays in history. | |

The left sidebar is the only workspace navigation. The top bar carries utilities only: brand, search, theme, organization switcher, profile.

## What is inside

| Surface | Route | What the professor gets |
|---|---|---|
| **Course Designer** | `/outline` | Ten-step subject outline: details, CLOs/PLOs, weekly schedule, readings, assessment map, policies, PDF/DOCX. |
| **Material Designer** | `/studio` | Cited slide deck for a week: speaker notes, source passages, gap notes, thumbnails, PowerPoint export. |
| **Assignment Designer** | `/assignments` | Brief, ideas and exemplars, group allocation, rubric, council review before publishing. |
| **Rubric builder** | `/rubric` | Criteria and four levels, inline editing, versions, alignment checks, import from paste/DOCX/PDF/XLSX. |
| **Grading** | `/grade` | Council votes per criterion with verbatim quotes, a judge, then a professor edit and explicit push. |
| **Integrity** | `/integrity` | DB-backed flags, side-by-side pairs with highlighted passages, viva questions, confirm/dismiss. |
| **Students at risk** | `/students` | Roster with an advisory course-withdrawal score and an explicit data-gap state. |
| **My style** | `/style` | `soul.md`, editable About me portrait, private memories, reflection history. |
| **Home** | `/dashboard` | Briefing facts for the week and quick access to the four designers. |
| **Chat** | `/chat` | Universal chat sheet with streamed tool cards and citations; a push or delete asks first. |
| **Admin** | `/admin/*` | Councils, AI settings, ML models, Moodle connection, users and organization. |

## Councils

**All council roles are LLM agents now; there are no code-check roles.** Each role carries its own prompt, provider, and model, and the chair always runs last.

- Edit at **`/admin/councils`** (app admins, scoped to the active organization): add a custom LLM reviewer (Material, Assignment, Outline), remove, reorder, enable/disable, edit the persona prompt, choose the model.
- Default rosters: Material `Creator -> Curriculum -> Evidence -> Design -> Chair`; Assignment `Creator -> Alignment -> Brief -> Rubric -> Chair`; Grading `Evidence / Strict / Supportive -> Chair judge`; Outline `Creator -> Curriculum -> Alignment -> Balance -> Student -> Chair`.
- Left-to-right is the speaking order. Exactly one chair is required, and a disabled role does not speak.
- The roster is Postgres (`pa_council_roles`); council prompts live in the same table. Global agent prompts live in Langfuse.
- **Reset** deletes the organization's rows so the code default speaks again. A row saved by an older build can still be labelled "Legacy code check"; no default role uses it.

## Machine learning

| Model | Predicts | Status in this build |
|---|---|---|
| `student-dropout` | Course withdrawal | `ready`, synthetic demo artifact, threshold `0.1` |
| `passage-reuse` | Submission similarity | `not_installed` unless `PLAGIARISM_WORKER_URL` is set |

- **Dropout is withdrawal, not pass/fail.** Target: withdrawal after the day-35 snapshot and by course end. All 14 allowlisted activity features are required - a missing one is a data gap, not a low score. `automatic_actions` is always `false`.
- **Plagiarism is an external worker contract.** Postgres stores the flags the worker returns; without a worker URL scoring returns a fixed `503`. The PAN 2013 threshold `0.922696` is corpus-specific and must be re-selected.
- **MLflow is a tracking server, not a training pipeline.** No training run is registered, and Admin -> Models reports reachable only when a probe succeeds.
- No model predicts a pass or a fail, and there are no fake scores or invented excerpts.

## Moodle

- Per-university connection at `/admin/integrations/moodle`: site URL, encrypted token, course scope, push flag. **Test connection** returns a five-item checklist and the advertised capability count.
- Reads courses, students, assignments, submissions, files, rubrics, and workshops into Postgres. Prefect pulls every 30 minutes plus a nightly full sync; **Sync now** is the manual backup.
- The bundled simulator (`backend/mock_moodle/`, port 8090) is preconfigured in Compose: 1 course, 12 students, 2 assessments, 6 submissions.
- Activity logs (`local_profassist_get_activity`, demo-only) feed the 14 dropout features. A stock Moodle refuses that function, which is treated as a data gap.
- **Push is off** (`MOODLE_PUSH_ENABLED=false`). A grade reaches Moodle only after the professor approves it and an admin enables push; in fake mode the push is recorded locally.

## Memory and prompts

- **Postgres is the source of truth** (`pa_memories`). Qdrant (`profassist_memory`) and optional Mem0 are mirrors; if a mirror is down the failure is logged and Postgres still answers.
- **Per professor:** every draft gets that professor's `soul.md`, About me portrait, and labelled memories - never another professor's.
- **Global prompts:** Langfuse `production` -> database version -> code default. `/admin/ai` saves a database version and publishes a Langfuse version; code defaults bootstrap a fresh install.
- **Council prompts** are per organization in Postgres. Editing a Langfuse prompt cannot add or remove a council seat.
- **Reflection auto-applies.** The portrait is rewritten, the previous wording stays in history, and `/style` has no Approve button. Memory text is PII-scrubbed before storage.

## Security

- **PII gate before any model call.** Names, emails, phones, and student IDs are replaced locally; a file that still fails the gate is quarantined. The token map stays in Postgres (`pa_pii_vault`), never in a prompt.
- **Tenant scope in code.** Course and roster rows carry `organization_id`, professor-owned rows also carry `owner_user_id`, and services filter by both. RLS policies exist, but Compose connects as the Postgres superuser, so the service filters are the effective boundary - not RLS alone.
- **Moodle secrets.** The token is Fernet-encrypted from `SECRET_KEY`, never returned by the API, and `wstoken=` / `token=` are scrubbed from every error path. SSRF protection rejects loopback, private, link-local, and CGNAT hosts after resolution; `MOODLE_ALLOW_PRIVATE=true` is a development-only exception.
- **Admin and owner checks.** Councils, Moodle connection changes, and ML administration require `is_app_admin` plus organization membership; a professor can read redacted Moodle status but not change it. A foreign course returns 404 before any lookup.
- **No automatic writes.** Every artifact is a draft; a grade push needs professor approval and `MOODLE_PUSH_ENABLED=true`, and chat tools that push or delete ask first. Auth endpoints are rate-limited (5 per 15 minutes per IP). There is no Kafka, so there is no event dedupe path to test.

## Testing

**1112 backend tests passed, 4 skipped** (`uv run --frozen pytest -q`) and **117 frontend tests** in 16 files (`npx vitest run`). Type-check exits 0; ESLint reports 0 errors and 2 warnings (unused `showPassage` and `SubmissionCard` in `frontend/src/app/[locale]/(dashboard)/integrity/page.tsx`); Prettier passes.

- The 4 skips are the destructive Alembic migration tests; they run only when `TEST_DATABASE_URL` points at a dedicated database.
- The local E2E run, its traces, screenshots, findings, and fixes are in **[docs/testing-pack.md](docs/testing-pack.md)**.
- CI runs Ruff, type check, the backend suite, and frontend type-check/lint/build. It does not run a Playwright journey.

## Known limits

- **Mock Moodle only.** No live Moodle site or live grade push was exercised; `MOODLE_PUSH_ENABLED=false` by default.
- **Plagiarism worker not installed.** No model, artifacts, or scores ship here; `passage-reuse` stays `not_installed` and returns a fixed `503`.
- **Dropout is synthetic and withdrawal-only.** A 480-row seeded bundle, threshold `0.1`, no pass/fail model, no training loop, no model promotion.
- **Upstream license and data.** No real student records. The vendored `student-dropout` port has no upstream LICENSE file, so redistribution or production use needs written permission from the upstream author.

## Repository map

| Path | What lives there |
|---|---|
| `backend/app/profassist/` | Councils, grading, outline, integrity, Moodle, course memory, ML, PII, RAG |
| `backend/app/profassist/ml/` | Dropout adapter, external plagiarism gateway, upstream port |
| `backend/alembic/versions/` | Migrations; `0043_council_settings` is head |
| `backend/tests/` | 70 test modules, mocked async DB, no external services |
| `backend/mock_moodle/` | Bundled Moodle simulator |
| `frontend/src/app/[locale]/` | Next.js App Router: auth, dashboard, marketing |
| `frontend/src/components/` | Professor UI, councils, chat, layout |
| `docker-compose.yml`, `Makefile`, `scripts/` | Full local stack and demo scripts |
| `docs/` | Architecture, ML, Moodle, memory, prompts, testing pack, images |

<details>
<summary><strong>Architecture and stack</strong></summary>

```mermaid
flowchart LR
    B[Next.js 15 UI<br/>App Router + BFF] -->|JWT cookie / REST / SSE| A[FastAPI<br/>routes -> services -> repositories]
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

An API route validates and authorizes, a service owns the workflow, a repository owns SQL, and the service returns a Pydantic response.

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic (`0043_council_settings` is head), pytest |
| Frontend | Next.js 15 App Router, React 19, TypeScript, Tailwind CSS 4, Zustand, TanStack Query, next-intl |
| AI | LangGraph graphs, LiteLLM providers, Langfuse traces and `production` prompt labels |
| Retrieval | Local fastembed embeddings by default, Qdrant `profassist` collection, keyword-overlap fallback |
| Data | PostgreSQL (primary), Redis (cache/limits), MinIO (S3-compatible files), Qdrant (vectors) |
| Operations | Docker Compose, Prefect server + runner, MLflow, Langfuse, Nginx |
| Identity | JWT access/refresh cookies, bcrypt passwords, shared `X-API-Key` for service calls, organization memberships |

</details>

<details>
<summary><strong>Services and URLs</strong></summary>

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

Confirm migrations with `docker compose exec app alembic current` (expect `0043_council_settings (head)`).

</details>

<details>
<summary><strong>Environment variables, keys, and providers</strong></summary>

The only required value is **`GEMINI_API_KEY`** in the root `.env`. One Gemini key serves drafting, the AI agent, and Mem0. `LLM_API_KEY` / `OPENAI_API_KEY` are optional overrides; `.env.example` sets `LLM_MODEL` and `AI_MODEL` to `gemini/gemini-3.5-flash-lite`. A prefixed model (`gemini/...`, `openai/...`) selects the provider whose key is spent. Anthropic, xAI, Mistral, Azure OpenAI, AWS Bedrock, Ollama, and any OpenAI-compatible base URL are also supported.

- **The key is never committed.** `.env` and `backend/.env` are gitignored; `.env.example` holds placeholders only.
- **Mem0 is on** in Compose (`MEM0_ENABLED=true`) with the local `fastembed` embedder (`BAAI/bge-small-en-v1.5`, 384 dims) and `/app/data/mem0.db` on the `mem0_data` volume. Postgres remains the source of truth.
- **Langfuse and MLflow are on** in the bundled stack. `/admin/ai` lists each provider and whether its key is set; it never shows the key.
- **The Moodle connection is preconfigured** against the mock (`MOODLE_BASE_URL=http://moodle-mock:8090`, `MOODLE_WS_TOKEN=demo-token`, `MOODLE_ALLOW_PRIVATE=true`). Use **Test** and **Sync now**.
- Prompt URLs follow `http://localhost:3100/project/profassist-project/prompts/<name>`; trace URLs follow `.../traces/<id>`.
- See [docs/configuration.md](docs/configuration.md) for the full list.

</details>

<details>
<summary><strong>Create a login and a university workspace</strong></summary>

The repository seeds no application user. A fresh database has no professor login.

1. Open <http://localhost:3000/register> and register with any email and a password of at least 8 characters.
2. **The first user to register** is promoted to app-admin and gets a Personal organization, so register before sharing the URL. That account owns `/admin/councils`, `/admin/models`, and `/admin/integrations/moodle`.
3. Promote a later account with:

```bash
docker compose exec app profassist cmd create-app-admin you@example.edu
```

4. For the university flow, create a team organization in **Workspace**, then a course. To reproduce the screenshots, point Moodle at the bundled simulator and run **Sync now**.

Langfuse has its own seeded demo user in `docker-compose.yml`; that is the Langfuse UI login, not a ProfAssist login.

</details>

<details>
<summary><strong>Security controls in detail</strong></summary>

| Control | How it is implemented |
|---|---|
| **PII before a model call** | A local regex gate removes names, emails, phones, student IDs, and bare long IDs; optional Presidio is available. If a personal-data pattern is still present after replacement, the file or text is quarantined and not sent. The token map stays in Postgres (`pa_pii_vault`), never in the prompt. |
| **Tenant scope** | A university is an organization. Course- and roster-level rows carry `organization_id`; professor-owned rows also carry `owner_user_id`. Routes resolve the active organization and services filter by it. Qdrant payloads include both ids. |
| **Row-level security caveat** | RLS policies and a `profassist_app` role exist, including on `pa_council_roles`. Docker Compose connects as the Postgres superuser, which bypasses RLS, so the application-level organization filter is what actually holds in this stack. Do not describe RLS alone as the isolation boundary. |
| **Connector token encryption** | The Moodle web-service token is stored as `enc:` Fernet ciphertext derived from `SECRET_KEY`. Only the last four characters remain in clear as a hint. A blank token on update keeps the ciphertext; a new token rotates it and resets the connection to `unverified`. |
| **Token redaction** | Every Moodle error path strips `wstoken=...` and `token=...` before the message reaches storage, a log line, an API response, or the audit row. |
| **SSRF protection** | Production requires `https://`. Loopback, private, link-local, CGNAT, and unsupported schemes are rejected after host resolution. `http://localhost` is accepted only with `MOODLE_ALLOW_PRIVATE=true`. |
| **Admin authorization** | Council settings, Moodle connection changes, and ML administration require `is_app_admin` and an organization the admin belongs to. Professor-owned resources are owner-scoped; a foreign course returns 404 before a dossier lookup. |
| **No automatic push** | Every artifact is a draft. A grade push requires the professor's approval and `MOODLE_PUSH_ENABLED=true`. A chat tool that would push or delete waits for confirmation. |
| **Abuse limits** | Authentication endpoints are limited per IP (default 5 requests per 15 minutes). |
| **Secrets** | Keys come from environment variables; provider keys are never returned; the shared API key is compared with `secrets.compare_digest`. |
| **No Kafka** | This POC does not publish to Kafka, so there is no event stream and no Kafka dedupe path. Idempotency exists where implemented: per-run Moodle sync rows and content-hash dossier rebuilds. |

</details>

<details>
<summary><strong>Machine learning detail</strong></summary>

**Dropout is withdrawal.** The target is withdrawal after the day-35 snapshot and by course end, conditional on active enrolment - not failure and not university departure. The adapter scores only when all 14 allowlisted activity features are present; a missing row is a **data gap**, not a low risk. Bands are `review` at or above the bundle threshold and `routine` otherwise; the raw number is kept as `risk`, and the UI shows High/Low. The shipped bundle is trained on a seeded 480-row synthetic Moodle-shaped dataset; `artifacts/metrics.json` marks it `"synthetic": true`.

**Plagiarism.** ProfAssist calls an external worker at `POST {PLAGIARISM_WORKER_URL}/score` with a 60-second timeout and an optional bearer token. The worker owns the model, threshold, and matching; ProfAssist validates `schema_version`, `scope`, and `display_flags`, stores the returned flags, and returns the result unchanged. Without a worker URL the status is `not_installed` and scoring raises a fixed `503`. See [docs/ml.md](docs/ml.md).

**MLflow.** Runs at <http://localhost:5000> with its own Postgres database and artifacts in MinIO (`s3://profassist/mlflow`). It is a tracking server; no training run is registered. A model version is reported only when MLflow actually returns one.

</details>

<details>
<summary><strong>RAG, document memory, and the course dossier</strong></summary>

- **Course files.** Upload `.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.potx`, `.html`, or `.htm`. Files are parsed locally (PyMuPDF, python-docx, python-pptx), passed through the privacy gate, chunked, embedded, and stored. A file that fails the PII gate is quarantined and never sent to a model.
- **Retrieval.** The default embedder is local fastembed (`BAAI/bge-small-en-v1.5`, 384 dimensions), so no note text leaves the machine. Vectors go to the Qdrant `profassist` collection when reachable; keyword overlap always runs.
- **Course dossier.** One dossier per organization, course, and professor, built from the official outline and ready materials and merged with source authority. Rebuilds are idempotent by content hash, the stored body is bounded, and served context is trimmed to a 4,000-8,000 character budget. Status is `ready` or `stale`; a stale dossier is never presented as current.
- **Collections and sync sources.** The template RAG API and CLI remain available: `rag-ingest`, `rag-search`, `rag-collections`, `rag-sources`, plus Google Drive / S3 sync connectors. See [docs/commands.md](docs/commands.md) and [docs/architecture.md](docs/architecture.md).
- **What a draft receives.** The official outline, the dossier, retrieved note passages with citations, and the professor's labelled **About this professor** section. Never another professor's notes or memories.

</details>

<details>
<summary><strong>Repository tree</strong></summary>

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
  tests/                    # 70 test modules, mocked DB, no external services
frontend/
  src/app/[locale]/         # App Router: (auth), (dashboard), marketing
  src/components/           # Professor UI, councils, chat, layout
  src/stores/               # Zustand auth/state
  e2e/                      # Playwright skeleton (local/manual)
docs/                       # Architecture, ML, Moodle, memory, testing pack, images
docker-compose.yml          # Full local stack
```

</details>

<details>
<summary><strong>Documentation, known limitations in full, and license</strong></summary>

Docs:

- [Testing pack](docs/testing-pack.md) - commands, counts, matrix, traces, failures, skips.
- [Architecture](docs/architecture.md) - layers, auth, files, RAG.
- [ML](docs/ml.md) - dropout and passage-reuse contracts.
- [Moodle connector](docs/moodle-connector.md) - token, SSRF, scope, activity logs.
- [Memory](docs/memory.md) - Postgres, Qdrant, Mem0.
- [Prompts](docs/prompts.md) - global prompt versioning, fallback order, council prompts.
- [Permissions](docs/permissions.md), [Security](SECURITY.md), [Configuration](docs/configuration.md), [Commands](docs/commands.md).
- [Status vs design](docs/STATUS_VS_DESIGN.md) - what is done, partial, stubbed, or not done against the architecture report.

Other limitations:

- 4 destructive migration tests skip unless a dedicated test database is configured.
- Mem0 is optional and off in a clean environment; Postgres is always the source of truth.
- Not implemented: Kafka, DVC, Evidently, SHAP, XGBoost training, LlamaIndex, student-facing notice, regrade queue, or AI-text detector.
- CI has no Playwright journey; the E2E in the testing pack is a local manual run.
- The API uses `review` / `routine`; the Students screen displays High / Low. The raw `risk` value is unchanged.

License: the template and this repository are MIT-licensed; see [LICENSE](LICENSE), which retains the Vstorm copyright. The `student-dropout` upstream port has no LICENSE file; see [docs/ml.md](docs/ml.md) and `backend/app/profassist/ml/dropout/NOTICE.md`. Do not redistribute that port or use it in production without written permission.

</details>
