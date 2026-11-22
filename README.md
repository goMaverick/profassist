# ProfAssist

An AI assistant for one professor. It drafts course slides and notes, assessments and rubrics, grades with a council of agents, feedback, and similarity flags with viva questions. She approves every draft. Nothing is sent to Moodle until she does.

This proof of concept is generated from the [full-stack AI agent template](https://github.com/vstorm-co/full-stack-ai-agent-template) by Vstorm (`fastapi-fullstack` 0.2.21, MIT). The template supplies FastAPI, Next.js, LangGraph, Qdrant, MinIO, Prefect, Postgres, and organization workspaces. ProfAssist is the professor workflow on top of that. Billing is not included.

The screen set follows the ProfAssist architecture report: Home, Course studio, Review and grade, Integrity, Students, and My style, plus login and the organization workspace. The interface keeps the template's layout. An IBM Carbon skin is a follow-up, not this build.

## Run it on your laptop

You need Docker Desktop (or Docker Engine with Compose). In this folder:

```bash
docker compose up --build
```

The first start downloads images and installs Python and Node packages. It can take a while. When it is ready:

- The app is at <http://localhost:3000>
- The API docs are at <http://localhost:8000/docs>
- Prefect is at <http://localhost:4200>
- MinIO is at <http://localhost:9001> (user `profassist`, password `profassist-secret`)

### Demo login

| | |
|---|---|
| Email | `professor@demo.uowd.ac.ae` |
| Password | `ProfAssist-demo-1` |
| Workspace | University of Wollongong in Dubai |
| Course | MAAI903 AI Solutions Design & MLOps |

The database is seeded on startup: the professor, the university workspace, a lecture note, four students, and three fake Moodle group reports. Two of those reports share a method paragraph.

### What to click

1. Sign in. Home shows the course and a reminder that drafts stay drafts.
2. **Studio**. The lecture note is already indexed. Draft objectives, approve one, draft slides, download the PowerPoint, design a rubric, and approve it.
3. **Grade**. Open Group A and run the council. Read the quotes and the "why this level" note. Edit the feedback if you want, approve, then push. The push is recorded locally. Moodle is not contacted. Group B18 is a blind sample: choose a level, or reveal the council, before you can approve it.
4. **Integrity**. Scan. The shared method is shown side by side with viva questions. Confirm or dismiss it. A flag is evidence, not a verdict.
5. **Students** and **Quality**. Both say the model is not trained yet. The roster is real demo data. The risk column is empty on purpose.
6. **My style**. That is `soul.md`. Save it, or ask for a reflection and approve it before it changes the voice.

You can also upload your own `.txt`, `.md`, `.pdf`, or `.docx` note in the studio. If a name or ID cannot be removed confidently, the file is quarantined and is not sent to a model.

## If you have an LLM key

With no key, drafts are written by a built-in demo drafter so the whole path works offline. The drafter still goes through the same agents, the privacy gate, and the judge.

To use a real model, create `backend/.env` from the example and set a key. Docker Compose reads `backend/.env.example` and also picks up `LLM_API_KEY` or `OPENAI_API_KEY` from the shell.

```bash
cp backend/.env.example backend/.env
```

| Variable | What it does |
|---|---|
| `LLM_API_KEY` or `OPENAI_API_KEY` | Key for LiteLLM. Empty means the demo drafter. |
| `LLM_MODEL` | Model name. Default `gpt-4o-mini`. |
| `LLM_BASE_URL` | Optional OpenAI-compatible base URL. |
| `LLM_COUNCIL_MODELS` | Optional three models, comma-separated, for the grading council. |
| `MOODLE_MODE` | `fake` (default) or `real`. |
| `MOODLE_BASE_URL`, `MOODLE_WS_TOKEN` | Only for `real`. Reads use the Moodle REST API. Grade push stays disabled there. |
| `LANGFUSE_ENABLED` | Off by default. Set `true` plus `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to trace calls. |
| `DEMO_PROFESSOR_EMAIL` | Demo login email. |
| `DEMO_PROFESSOR_PASSWORD` | Demo login password. |
| `PROFASSIST_AUTO_SEED` | `true` in Compose. Seeds the demo workspace once. |

Do not commit a key. `backend/.env` is gitignored.

## AI settings, memory, and models

- **Agents.** LangGraph drafts live in `backend/app/profassist/agents.py` (objectives, slides, rubric, grading council, feedback, reflection) and `backend/app/profassist/skills/slide_studio.py` (cited decks). Studio, Grade, Integrity, My style, and Slide review call them. The template chat agent is a separate LangGraph assistant on the Chat screen (`backend/app/agents/langgraph_assistant.py`), reached at `/ws/agent`.
- **Add an agent.** Put a `StateGraph` in `backend/app/profassist/`, give it a prompt key in `backend/app/profassist/runtime.py`, and call it from `backend/app/profassist/service.py`. A skill can also be a folder under `backend/skills/<name>/SKILL.md` plus tool code the graph loads.
- **Tenants.** A university is an organization. Courses, the Moodle roster, and submissions are shared inside that university. Each professor's notes, objectives, slides, rubric, grade drafts, integrity flags, style, and memories are private to her (`owner_user_id` on those tables). Qdrant payloads include `organization_id` and `owner_user_id`. Files go in one MinIO bucket, under a key that includes the organization and the professor.
- **Langfuse** is at <http://localhost:3100>. Sign in with `professor@demo.uowd.ac.ae` / `ProfAssist-demo-1`. After you grade a group, open **View agent trail** on the Grade screen. That trace is a tree: Evidence, Strict, Supportive, Judge, then Feedback. Edit a prompt or persona in Langfuse (keep the `production` label). The next run uses that text. `/admin/ai` still turns chat on or off, sets the model, and toggles tools. Prompt text there is read-only and says whether the live copy is Langfuse, the database, or the code default.
- **Configure AI.** The API key stays in `LLM_API_KEY` or `OPENAI_API_KEY`. With no key, the demo drafter still runs and still writes Langfuse spans.
- **MLflow** is at <http://localhost:5000> after `docker compose up`. It stores runs in Postgres and artifacts in MinIO. **Models** in the admin tabs shows the grade calibrator and the early-warning model as not trained until something is registered. Nothing trains them in this build.
- **Memory.** Saving My style writes a memory for that professor only, after the privacy gate. She can read and delete memories on My style. When Mem0 is installed and an LLM key is set, the same text is also sent to self-hosted Mem0 (Qdrant). There is no Mem0 cloud account.

## What is real, and what is waiting

Real in this build:

- LangGraph flows for the course designer, the rubric, the grading council (evidence, strict, supportive) plus a judge, the feedback writer, viva questions, and a reflection loop.
- Retrieval over uploaded notes, with Qdrant when it is up and keyword overlap as well.
- PowerPoint export.
- A privacy gate that strips names, emails, phones, and IDs before a model call, and quarantines a file when that fails.
- Approval before any push.
- A fake Moodle connector (`MOODLE_MODE=fake`) with the same shape as an LTI 1.3 launch and the read-only Moodle REST API. Swap it by setting `MOODLE_MODE=real`.
- Organization workspaces. Every ProfAssist row is stored against one organization.

Not built, on purpose:

- The grade calibrator and the at-risk early-warning model. Their pages and `GET /api/v1/profassist/calibrator` plus the students payload return `not_trained` and no score.
- A live Moodle grade write. `real` mode can read. Push in `fake` mode only records the approved item.
- Docling and LlamaIndex. Parsing uses the template's PyMuPDF and python-docx path.
- Presidio. The privacy gate is a local equivalent. The token map stays in Postgres.
- Mem0, Kafka, DVC, MLflow, and the training pipeline from the report.
- IBM Carbon. The template interface is in place so Carbon can replace it later.
- Row-level security is installed for a `profassist_app` role. Compose connects as the Postgres superuser, which bypasses those policies, so isolation is also enforced on every query by `organization_id`.

## Tests

GitHub runs one job: Ruff, then the backend unit tests in `backend/tests/test_profassist.py`. Those tests do not need a database or an API key.
