# ProfAssist testing pack

This pack records the local end-to-end (E2E) verification of ProfAssist against the full Docker Compose stack, plus the unit and frontend suites that back it. It is the source of truth for the counts quoted in the [README](../README.md).

- **Date:** 2026-11-24.
- **Environment:** local Docker Compose (`docker-compose.yml` + `docker-compose.override.yml`), Windows host, Docker Desktop.
- **Source changes during E2E:** none. Nothing was committed.
- **Scope:** councils, Moodle, students/dropout, integrity, models/MLflow, Mem0, reflection/style, Langfuse, and the two test suites.

## 1. Stack state

### Commands

```powershell
docker compose build app frontend
docker compose up -d --no-deps --force-recreate app prefect-runner prefect-server frontend
docker compose exec -T app alembic current
```

### Result

- `alembic current` -> `0043_council_settings (head)`.
- API `GET /api/v1/health` -> `200 {"status":"healthy","max_upload_size_mb":50}`.
- Frontend `GET /api/health` -> `200`.
- MLflow `GET /health` -> `200`.
- Moodle mock `GET /health` -> `200 {"status":"ok","service":"moodle-mock","courses":1,"users":12}`.
- Prefect `GET /api/health` -> `200`.
- Restart count `0` for backend, Prefect runner/server, frontend, MLflow, mock, and Postgres.
- Postgres, mock, and MLflow were kept; app, Prefect runner/server, and frontend were recreated from rebuilt images.

> Infrastructure note: Docker Desktop was hung at the start (stale `docker stats` clients plus a shared `ci-runners` container leaking zombie `git` processes). Docker Desktop was restarted and the stack came back. This was a host/container issue, not an application failure.

## 2. Commands and exact counts

### Backend

```powershell
cd backend
uv run --frozen pytest -q
```

**1071 passed, 4 skipped, 125 warnings in 100.62s.**

The 4 skips are the destructive Alembic migration tests (`tests/test_migrations.py`); see section 8. The suite uses a mocked async session, so it needs no Postgres, Redis, Qdrant, MinIO, or model key.

### Frontend

```powershell
cd frontend
npm run type-check
npx vitest run
npx eslint "src/app/[locale]/(dashboard)/admin/councils" "src/components/profassist/studio-collab.tsx" "src/app/[locale]/(dashboard)/admin/integrations/moodle" "src/app/[locale]/(dashboard)/integrity"
npx prettier --check "src/app/[locale]/(dashboard)/admin/councils/page.tsx" "src/app/[locale]/(dashboard)/admin/councils/page.test.tsx"
```

- `type-check`: exit 0.
- `vitest`: **16 files passed, 107 tests passed** in 7.18s.
- `eslint`: exit 0, **0 errors, 2 warnings**: unused `showPassage` and `SubmissionCard` in `frontend/src/app/[locale]/(dashboard)/integrity/page.tsx`.
- `prettier --check`: all matched files pass.

### Count summary

| Suite | Command | Passed | Failed | Skipped | Notes |
|---|---|---:|---:|---:|---|
| Backend | `uv run --frozen pytest -q` | 1071 | 0 | 4 | 100.62s, 125 warnings |
| Frontend | `npx vitest run` | 107 | 0 | 0 | 16 files, 7.18s |
| Frontend type check | `npm run type-check` | - | 0 | - | exit 0 |
| Frontend lint | `npx eslint ...` | - | 0 | - | 2 warnings, no errors |
| Frontend format | `npx prettier --check ...` | - | 0 | - | all matched files pass |

## 3. Test matrix

| Area | What is covered | Primary tests | E2E evidence |
|---|---|---|---|
| **Backend platform** | Auth, users, orgs, RAG, files, repositories, exceptions, OpenAPI, health, migrations guards | 67 `test_*.py` modules under `backend/tests/`, mocked async DB | `pytest` 1071 passed |
| **Frontend shell** | Auth store/hooks, API client, cookies, layout, command palette, UI primitives, council page, assignment pages, studio collab, login form, header utilities | 16 `*.test.tsx` / `*.test.ts` files | `vitest` 16 files / 107 tests |
| **Login and header navigation** | Two-column login form: controls, password visibility, submit, error banner, loading state (5 tests); header renders no top-level Home/Grading links and keeps brand/search/theme/menu (4 tests); studio collab roster copy (13 tests) | `components/auth/login-form.test.tsx`, `components/layout/header.test.tsx`, `components/profassist/studio-collab.test.tsx` | `vitest` 5 + 4 + 13 tests |
| **Material council** | Default roster, validation, enable/disable, chair-last ordering, persistence, reset, slide collaboration, slide review | `test_council_settings.py`, `test_slide_collab.py`, `test_slide_review.py`, `test_profassist.py`, `admin/councils/page.test.tsx` | Live single-week SSE with Design disabled |
| **Assignment council** | Deterministic checks, chair summary, rubric role, roster filtering, brief/rubric documents | `test_assignment_council.py`, `test_assignment_ai.py`, `test_assignment_doc.py`, assignment page tests | Rubric disabled -> Alignment, Brief, Chair only |
| **Grading council** | Level spread, debate threshold, quote verification, contradiction handling, no-reliable-evidence path, judge | `test_grading_context.py`, `test_agents.py`, `test_profassist.py` | Strict disabled -> Evidence and Supportive votes only |
| **Outline review** | Deterministic findings, severity, section/object ids, one-click fixes, reviewer roster, approval | `test_outline_ai.py`, `test_outline_doc.py`, `test_outline_context.py`, `test_course_dossier_migration.py` | Student disabled -> Balance reviewer only |
| **Moodle connector** | Mock catalogue, web-service calls, token encryption/redaction, SSRF, course scope, sync runs, activity features, schedule | `test_mock_moodle.py`, `test_moodle_connection.py`, `test_moodle_connection_migration.py`, `test_ssrf.py` | Test 200 + 5/5 checklist + 19 capabilities; sync 1/12/2/6/12; UI per-run 0 |
| **Dropout ML** | 14-feature contract, missing-feature data gap, threshold, bands, synthetic flag, no automatic actions, model cards | `test_ml_gateway.py`, `test_ml_admin.py` | 12 students, trained/synthetic, 5 review / 7 routine |
| **Integrity** | DB-backed flags, pair detail, matrix, confirm/dismiss, document text, no verdict | `test_integrity_board_db.py`, `test_profassist_security.py`, `test_profassist.py` | 6 groups, 3 pairs, 1 concern, real text, all flags open |
| **Mem0 mirror** | Postgres-first write, Qdrant mirror, lazy Mem0, failure swallowing, no PII | `test_memory_mirror.py` | Mem0 add + search returned 2 hits; Qdrant points 6 / 9 |
| **MLflow** | Reachability, model cards, worker settings, probe, contract, no invented versions | `test_ml_admin.py` | `reachable: true`, `http://mlflow:5000` |
| **Reflection / style** | Movement capture, reflection dedupe, auto-apply, history, About me rewrite, reset | `test_profassist_reflection.py`, `test_profassist_identity.py` | `status: applied`; About me 325 -> 109 chars; no Approve button |
| **Langfuse** | Trace URL construction, production prompt lookup, fallback order, actor hashing | `test_trace_urls.py`, `test_profassist_identity.py` | Assignment, grading, and outline trace URLs returned HTTP 200 |
| **Security** | SSRF, tenant isolation, RBAC/teams, PII gate, approval gate, token redaction | `test_ssrf.py`, `test_tenant_isolation.py`, `test_rbac_teams.py`, `test_profassist_security.py`, `test_security.py` | Moodle token never returned; no push without approval |

## 4. E2E results

| Area | Result | Detail |
|---|---|---|
| Stack health | **Pass** | API, frontend, MLflow, mock Moodle, Prefect all 200; migrations at head |
| Backend suite | **Pass** | 1071 passed, 4 skipped |
| Frontend suite | **Pass** | 16 files, 107 tests |
| Council settings | **Pass** | Four councils, ordered positions, exactly one chair each; saved rosters obeyed |
| Material council | **Pass** | Design disabled -> silent; Evidence spoke before Curriculum; roster restored |
| Assignment council | **Pass** | Rubric disabled -> Alignment, Brief, Chair only; 5 model-busy 503s then success |
| Grading council | **Pass** | Strict disabled -> Evidence and Supportive votes only; trace stored |
| Outline review | **Pass** | Student disabled -> Balance reviewer only; trace stored |
| Outline step save | **Found and fixed** | En dash range returned 500; fixed and covered by tests (section 7) |
| Moodle | **Pass** | Test 200, 5/5 checklist, 19 capabilities, sync ok, DB totals correct |
| Students at risk | **Pass** | 12 students; `student-dropout` trained/synthetic; 5 review / 7 routine |
| Integrity | **Pass** | 3 DB flags across method/findings/introduction; 6 groups, 3 pairs, 1 concern |
| Models / MLflow | **Pass** | Dropout ready/synthetic; passage-reuse not_installed; MLflow reachable |
| Mem0 | **Pass** | Add + search 2 hits; Qdrant points `mem0_profassist=6`, `mem0_profassist_entities=9` |
| Reflection / About me | **Pass** | Auto-applied; About me 325 -> 109 chars; no Approve button |
| Langfuse | **Pass** | Three trace URLs returned HTTP 200 |
| Frontend quality | **Pass with warnings** | Type-check 0; ESLint 0 errors / 2 warnings; Prettier pass |

## 5. Council E2E detail

All calls used `Authorization: Bearer <demo token>` and `X-Organization-Id: <UOWD org>`.

`GET /api/v1/profassist/admin/councils` returned four councils, ordered positions, and exactly one chair each:

- material: creator -> curriculum -> evidence -> design -> chair
- assignment: creator -> alignment -> brief -> rubric -> chair
- grading: evidence -> strict -> supportive -> chair
- outline: curriculum -> alignment -> balance -> student -> chair

### Material

Changed roster saved: creator(1), evidence(2), curriculum(3), design(4, disabled), chair(5). A live single-week collaboration (`POST /profassist/courses/{id}/slides/collaborate`, then the SSE stream) produced:

```text
start
message creator    "I drafted 2 slides ..."
message evidence
message curriculum
message chair
final
```

`design` did not speak, and Evidence preceded Curriculum. The roster was restored to defaults afterwards.

### Assignment

With **Rubric** disabled, created `E2E Operations Review` and refined it. The model returned `503` five times (`The model is busy right now. Try again in a minute.`) before succeeding on the sixth attempt. The refine and explicit review both returned `roles = ["alignment", "brief", "chair"]`; the transcript contains Alignment, Brief, and Chair only. Rubric is absent. The temporary assessment was deleted after the screenshot, so the expected two Moodle assessments (901, 902) remain.

### Grading

Approved the Operations rubric, disabled **Strict**, and graded the Group A submission. Draft votes contained personas **evidence** and **supportive** only; there was no Strict vote on any criterion. Restored.

### Outline

Created and populated a PIPE903 outline, disabled **Student**, and ran a council review. The findings reviewer set was `["balance"]`; Student was absent. Restored.

All four councils were confirmed back at defaults after the checks.

## 6. Trace URLs and screenshots

### Langfuse traces

These are local URLs from the E2E run. They returned HTTP 200 from `http://localhost:3100` at verification time.

| Flow | Trace |
|---|---|
| Assignment refine | <http://localhost:3100/project/profassist-project/traces/15a70ef67b3a769eda0b191aeed49cb2> |
| Assignment review | <http://localhost:3100/project/profassist-project/traces/672e2696791a68cbb913106499f23e56> |
| Grading council | <http://localhost:3100/project/profassist-project/traces/f42898bc3078bb5d5b012a9802d62da9> |
| Outline review | <http://localhost:3100/project/profassist-project/traces/0fd8c7d261b065e1e2cce76fdc020441> |

### Screenshots

The eleven images below are copied from `frontend/screenshots-final/` into `docs/images/` with stable names. They are not re-captured by this document.

| Screenshot | Dimensions | Bytes | What it shows |
|---|---:|---:|---|
| [login.png](images/login.png) | 1440x1000 | 174,081 | Two-column sign-in; feature icons on the left; password visibility toggle; empty form, no demo credentials |
| [dashboard.png](images/dashboard.png) | 1440x1489 | 196,373 | Workspace after sign-in; left sidebar is the only workspace nav; utilities-only top bar |
| [councils-material.png](images/councils-material.png) | 1440x900 | 105,998 | Council settings, Material tab; Creator -> Curriculum -> Evidence -> Design -> Chair |
| [councils-assignment.png](images/councils-assignment.png) | 1440x900 | 106,354 | Assignment tab; Creator -> Alignment -> Brief -> Rubric -> Chair |
| [studio-council-five.png](images/studio-council-five.png) | 1440x1350 | 152,850 | Material Designer live council; Creator + three reviewers + Chair; Deck ready 80/100 |
| [assignment-council-final.png](images/assignment-council-final.png) | 1440x1100 | 164,638 | Assignment transcript with Alignment, Brief, Chair; no Rubric reviewer |
| [integrity-db-final.png](images/integrity-db-final.png) | 1440x1000 | 72,924 | DB-backed integrity board; 6 groups, 3 pairs, concern with real text |
| [students-dropout-final.png](images/students-dropout-final.png) | 1440x1182 | 182,805 | Demo model badge; 5 High / 7 Low |
| [moodle-connection-final.png](images/moodle-connection-final.png) | 1440x1876 | 206,224 | Verified connection, capability checklist, schedule/last run, sync history |
| [admin-models-final.png](images/admin-models-final.png) | 1440x1032 | 168,892 | Dropout ready/synthetic; plagiarism not installed; MLflow reachable |
| [style-reflection.png](images/style-reflection.png) | 1440x1668 | 207,791 | Auto-applied reflection history; no Approve button |

**Missing selected screenshots:** none. `login.png` and `dashboard.png` are now copied into `docs/images/`. The remaining files in `frontend/screenshots-final/` (outline, rubric, assignments, integrity-groups-final, assignment-council-page) were deliberately not copied.

## 7. E2E failures: root cause and status

All four findings named in the E2E report are fixed in the current tree: the en dash 500, the Material collaboration copy, the Moodle counter clarity, and the MLflow reachability cache race.

| # | Finding | Root cause (evidence) | Status |
|---|---|---|---|
| 1 | **Outline step save returned 500 on an en dash range.** `PUT /profassist/outlines/{id}/step` with `step=grades` and `85 – 84%` failed with `json.decoder.JSONDecodeError: Invalid \uXXXX escape` at `backend/app/profassist/outline.py`. | `save_step` did `json.loads(strip_contacts(json.dumps(payload)))`. The phone regex rewrote digits inside the JSON escape `\u2013`, corrupting it into an invalid escape. Reproduced standalone: `strip_contacts(json.dumps(demo_outline()["grades"]))` corrupts `\u2013`; `ensure_ascii=False` round-trips correctly. | **Fixed.** `save_step` now scrubs string leaves with `strip_contacts_in_payload(payload)` before serialization (`outline.py:181-185`). Regression tests: `test_save_step_keeps_an_en_dash_range_in_the_grades`, `test_save_step_route_saves_an_en_dash_grades_step`, plus `test_save_step_still_scrubs_a_contact_in_a_string_leaf` and `test_save_step_strict_gate_still_quarantines_student_pii` in `backend/tests/test_outline_doc.py`. |
| 2 | **Material collaboration copy counted the full roster even after a role was disabled.** The header said `5 agents` and named curriculum, evidence, and design after Design was disabled. | `frontend/src/components/profassist/studio-collab.tsx:498-499` now derives the badge from `state.roles` (`state.roles.length + 1`, so `5 agents` with every seat enabled and `4 agents` when one is disabled); `:521-522` says the `enabled reviewers` each check a different angle instead of naming fixed seats. | **Fixed.** Tests in `frontend/src/components/profassist/studio-collab.test.tsx` (13 tests) assert `5 agents` for the full roster, `4 agents` with Design disabled, the generic `enabled reviewers` copy, and no literal `5 agents` when the stream names only four seats. Full frontend suite: 107 tests in 16 files. |
| 3 | **Moodle "last run" shows 0 courses / 0 students / 0 submissions while DB totals are correct.** | `status.counts` and the Moodle screen report rows imported **this run**. An idempotent re-sync imports nothing new, so it reports 0. The database and API totals remain 1 course / 12 students / 2 assessments / 6 submissions / 12 activity rows. | **Fixed (UX).** The page now labels the two rows **Last run** and **Currently synced** (`frontend/src/app/[locale]/(dashboard)/admin/integrations/moodle/page.tsx:521-529`), so per-run zeros are distinguishable from stored totals. Not data loss. |
| 4 | **MLflow reachability flapped once.** The first `/profassist/admin/models` read after restart returned `reachable: false`, then `true` on retry and in the screenshot. | Ten-second reachability cache racing the MLflow startup; no lasting failure. | **Fixed.** Only a successful reachability result is cached; a failure is never cached, so the next read recovers (`backend/app/profassist/tracking.py:23-25,111-121`). The screenshot and later reads show `reachable: true`. |
| 5 | **Auth rate limiting during repeated browser logins.** | Default auth limit is 5 requests per 15 minutes per IP; the run hit `Rate limit exceeded for category 'auth'` (665s). Screenshots used the already-issued JWT cookie. | **Expected protection.** Not an application failure. |
| 6 | **Model returned 503 five times during the assignment run.** | External Gemini rate limiting ("The model is busy right now. Try again in a minute."); the sixth attempt succeeded. | **External / transient.** No code defect; retries succeeded. |

### Reproduction of the en dash regression (fixed)

The failing payload was:

```json
{"grades": [{"band": "High Distinction", "range": "85 – 84%", "grade": "HD"}]}
```

The narrow test that now proves the fix:

```powershell
cd backend
uv run pytest tests/test_outline_doc.py -k "en_dash" -q
```

Expected: `2 passed` (service-level and route-level), with the PII scrub tests still green.

## 8. Known skips and limitations

- **4 backend skips** are the destructive Alembic tests in `backend/tests/test_migrations.py`. The two guard tests always run and prove that the `profassist` database name is refused. The upgrade/downgrade/cycle/current tests skip unless `TEST_DATABASE_URL` is set.
- **No real Moodle.** Only the bundled `moodle-mock` simulator was exercised. The real connector reads through the web service, but no live site was contacted.
- **No plagiarism worker.** `passage-reuse` is intentionally `not_installed`; no worker, model, artifacts, or similarity scores are in this repository.
- **No model training.** The dropout bundle is the shipped synthetic artifact. There is no training loop, promotion, or pass/fail model.
- **No Moodle push.** `MOODLE_PUSH_ENABLED=false`; no grade was written to a real Moodle.
- **Mem0 is optional.** A clean compose environment leaves it off. The local override used for E2E enabled it with a local fastembed embedder.
- **Playwright is not in CI.** `.github/workflows/ci.yml` runs backend lint/format/type/test and frontend type-check/lint/build; the old demo-mode journey was removed. The E2E in this pack is a local manual run.
- **UI labels differ from the API.** The API uses `review` / `routine`; the Students screen displays High / Low. The raw `risk` value is unchanged.
- **RLS is not the effective boundary in Compose.** Policies exist for `profassist_app`, but Compose connects as the Postgres superuser. The organization/owner filters in services are what hold.
- **No Kafka.** There is no event stream and no Kafka dedupe path. Idempotency is limited to what is implemented: per-run Moodle sync rows and content-hash dossier rebuilds.
- **Not implemented:** student-facing notice/regrade workflow, AI-text detector, DVC, Evidently, SHAP, XGBoost training, LlamaIndex, UAE-region hosting.

## 9. Destructive migration tests

The migration tests run `alembic upgrade head` and `alembic downgrade base`. They are destructive by design, so they never use `DATABASE_URL` and they refuse the `profassist` database. Point them at a dedicated database.

### PowerShell

```powershell
docker compose exec db createdb -U postgres profassist_test
$env:TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/profassist_test"
cd backend
uv run pytest tests/test_migrations.py -v
```

### Bash

```bash
docker compose exec db createdb -U postgres profassist_test
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/profassist_test
cd backend
uv run pytest tests/test_migrations.py -v
```

Expected with the variable set: the two guard tests plus the four destructive tests run (upgrade head, downgrade base, upgrade/downgrade cycle, current matches head). Expected without it: the four destructive tests skip with `TEST_DATABASE_URL is not set -- destructive migration tests are skipped so they cannot wipe the developer database`.

> Never point `TEST_DATABASE_URL` at `profassist`. The guard rejects the developer database name, and the test derives both the async and sync drivers from the URL.

## 10. Reproduce the local verification

1. Start the full stack:

```bash
docker compose up --build
```

2. Confirm health and migrations:

```bash
docker compose exec app alembic current
curl http://localhost:8000/api/v1/health
curl http://localhost:8090/health
curl http://localhost:5000/health
```

3. Register the first app user at <http://localhost:3000/register>. The first user is auto-promoted to app-admin and gets a Personal workspace. Create a team workspace and a course for the university flow.

4. Configure the mock Moodle connection from **Admin -> Moodle**. In this compose stack the app already has `MOODLE_BASE_URL=http://moodle-mock:8090`, `MOODLE_WS_TOKEN=demo-token`, and `MOODLE_ALLOW_PRIVATE=true`; the connection page can use those values. Leave push off.

5. Run **Sync now**, then open Students, Integrity, Grading, and Admin -> Models. The expected mock totals are 1 course, 12 students, 2 assessments, 6 submissions, and 12 activity rows.

6. Run the suites from section 2. For the local E2E, repeat the council changes in section 5, then restore each council to defaults.

## 11. What was not reproduced or claimed

- No real Moodle site, no real grade push, and no live student data.
- No plagiarism worker or passage-reuse artifact.
- No model training or promotion; the dropout model is the shipped synthetic bundle.
- No pass/fail model; none exists upstream.
- No Kafka, DVC, Evidently, SHAP, XGBoost training, or LlamaIndex flow.
- The five model-busy `503` responses were external provider rate limiting, not an app defect.
- The Docker Desktop hang was host infrastructure, not the application.
- The temporary `E2E Operations Review` assessment was deleted after its screenshot; its trace and screenshot are preserved, but the assignment URL is no longer live.
