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
6. **My style**. That is `soul.md`, plus **About me**. About me is rebuilt for the signed-in professor after she approves or edits. Save it, edit it, or reset it. A reflection can propose a style change. It is not applied until she approves it, and it never rewrites the shared prompts.

You can also upload your own `.txt`, `.md`, `.pdf`, or `.docx` note in the studio. If a name or ID cannot be removed confidently, the file is quarantined and is not sent to a model.

## If you have an LLM key

With no key, drafts are written by a built-in demo drafter so the whole path works offline. The drafter still goes through the same agents, the privacy gate, and the judge.

To use a real model, create `backend/.env` from the example and set a key. Docker Compose reads `backend/.env.example` and also picks up `LLM_API_KEY` or `OPENAI_API_KEY` from the shell.

```bash
cp backend/.env.example backend/.env
```

| Variable | What it does |
|---|---|
| `OPENAI_API_KEY` or `LLM_API_KEY` | OpenAI. Empty means the demo drafter for that provider. |
| `ANTHROPIC_API_KEY` | Anthropic. |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Google Gemini. |
| `XAI_API_KEY` | xAI Grok. |
| `MISTRAL_API_KEY` | Mistral. |
| `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` | Azure OpenAI. The model field is the deployment name. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` | AWS Bedrock. |
| `OLLAMA_API_BASE` | Ollama or another local server, for example `http://host.docker.internal:11434`. |
| `LLM_BASE_URL` | Any OpenAI-compatible base URL. Use with `LLM_API_KEY` if that server wants a key. |
| `LLM_MODEL` | Default model name when an agent has no choice of its own. |
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
- **Providers and debate.** `/admin/ai` lists each provider and whether its environment key is set. It never shows the key. Pick a provider and model per agent, including a different one for each council member. Test connection sends one short LiteLLM call. If the graders are more than the chosen number of levels apart, they debate for up to the chosen number of rounds, then the judge decides. Each round is stored on the grade and appears in the Langfuse trace. With no keys, the demo drafter still runs those rounds.
- **MLflow** is at <http://localhost:5000> after `docker compose up`. It stores runs in Postgres and artifacts in MinIO. **Models** in the admin tabs shows the grade calibrator and the early-warning model as not trained until something is registered. Nothing trains them in this build.
- **Memory.** Approving or editing a grade, a rubric, slides, an objective, or My style writes a lesson for that professor only, after the privacy gate. A repeated lesson updates the old one. She can read and delete memories on My style. Each row shows her name, the source, and the time. When Mem0 is installed and an LLM key is set, the same text is also sent to self-hosted Mem0 (Qdrant). There is no Mem0 cloud account.
- **About this professor.** Every model call adds a labelled `About this professor` section for the signed-in professor in this university. It is built from her memories, style, and courses, then rewritten (not appended) after each approval or edit. Older wording is kept on her profile. Langfuse shows that section on the generation after the privacy gate. It is not copied onto another professor and it does not change the Langfuse production prompts.

## What is real, and what is waiting

Real in this build:

- LangGraph flows for the course designer, the rubric, the grading council (evidence, strict, supportive) plus a judge, the feedback writer, viva questions, and a reflection loop.
- Retrieval over uploaded notes, with Qdrant when it is up and keyword overlap as well.
- PowerPoint export with a title, agenda, sections, notes, sources, and a references slide. A `.pptx` or `.potx` master can set the page size. Slide review shows thumbnails.
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
