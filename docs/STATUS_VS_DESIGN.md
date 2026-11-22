# ProfAssist POC against the architecture report

This table compares the UOWD MAAI903 ProfAssist design with what this repository runs today. Status is one of Done, Partial, Stubbed, or Not done.

| Item | Status | Note |
| --- | --- | --- |
| Home | Done | Course, queue, and connector status for the signed-in professor. |
| Course studio | Done | Upload notes, draft objectives, approve them. |
| Course design assistant | Done | Weeks, outcomes, and an assessment plan. She edits the draft and approves it. It reads her notes and About section. |
| Slide generator | Done | Slide studio plans, retrieves, cites, and exports a deck for a chosen week. |
| Slide review | Done | Sources sit beside each slide, with thumbnails of the deck. |
| Assessment designer | Done | Draft a rubric, then approve it before grading. |
| Rubric builder | Done | Blank rubric, AI suggestion, inline edit, versions, alignment check, and import from paste, docx, pdf, or xlsx. |
| Review and grade | Done | Council draft, professor edit, approve, then push. |
| Feedback editor | Done | She can rewrite the comment before approval. |
| Integrity | Done | Winnowing similarity plus viva questions. A flag is not a verdict. |
| Students | Partial | Roster is listed. Early-warning scores are not produced. |
| Quality and cost | Partial | Langfuse traces each run. There is no cost dashboard. |
| Grader council | Done | Evidence, strict, and supportive votes, then a judge. |
| Council debate | Done | If levels disagree past the admin threshold, members revise for up to N rounds. |
| My style | Done | `soul.md`, plus About me, memories, and suggested style updates. |
| Self-improvement | Done | Approval or an edit writes a lesson, updates memory, and rewrites About me. |
| About this professor | Done | Built per professor and university, injected into every prompt, labelled in Langfuse after the privacy gate. She can view, edit, or reset it. History keeps older wording. Shared prompts stay unchanged. |
| Course designer agent | Done | LangGraph drafts objectives from her notes. |
| Rubric agent | Done | LangGraph drafts criteria and levels. |
| Grading council agent | Done | Three personas, optional debate, then the judge. |
| Feedback writer | Done | Drafts the comment from the approved level and a real quote. |
| Reflection agent | Done | Runs after approval or an edit, and still on request from My style. |
| Slide studio skill | Done | Multi-hop retrieval, citations, gaps, and a full PowerPoint deck. |
| LiteLLM providers | Done | OpenAI, Anthropic, Gemini, xAI, Mistral, Azure, Bedrock, Ollama, and an OpenAI-compatible base. Keys stay in the environment. |
| Demo mode without a key | Done | A local drafter returns JSON and still writes traces. |
| Human approval | Done | Nothing is pushed until she approves. One-click approve stays off. |
| Privacy gate | Partial | Regex removal plus an optional Presidio pass. Docling is a hook only. |
| Per-professor memory | Partial | Postgres and Qdrant always. Mem0 only when the library and a model key are present. Lessons update a matching row instead of appending forever. |
| soul.md | Done | Her voice. A reflection changes it only after she accepts the suggestion. |
| Prompt management | Done | Langfuse `production` prompts, then the database, then the code default. `/admin/ai` does not edit prompt text. |
| Langfuse traces | Done | Nested spans after the privacy gate, with the About section labelled on the prompt. |
| Grade calibrator | Stubbed | The page and the endpoint return `not_trained` and no score. |
| At-risk early warning | Stubbed | The page lists the 14 upstream course-withdrawal features. The public model repo has no training CSV or saved model in git, so no score is shown. A score would stay advisory. |
| Fake Moodle | Done | Assignments with files and a workshop. A Prefect job is the main pull, every 30 minutes unless the university pauses it or picks another interval. A separate nightly full sync is on by default. Sync now is the backup. |
| Real Moodle | Partial | Reads courses, people, assignments, submission files, rubrics, and workshops through the web service. Grade push calls `mod_assign_save_grade` only when `MOODLE_PUSH_ENABLED=true`. |
| Manual submission upload | Done | A zip of files can be attached to an assignment when Moodle is not available. |
| Tenant isolation | Partial | A university is an organization. Professor-owned rows are filtered in the app. Postgres RLS exists, but the compose database role is a superuser, so the app filter is what holds. |
| Qdrant, Postgres, MinIO, Prefect | Done | Notes, memory, files, and the grade batch worker. |
| MLflow | Partial | The server is in compose. No training run is registered. |
| python-pptx | Done | Title, agenda, sections, content, two columns, quote, chart or table, summary, references, notes, slide numbers, image placeholder, and an optional master file. |
| Blind sample | Done | One group in twenty is hidden until she chooses or reveals it. |
| IBM Carbon | Partial | Professor shell, home, outline, assessments, and login use Carbon, IBM Plex, and Carbon icons. Other template screens keep their layout inside that shell. |
| Subject outline wizard | Done | Steps follow the faculty template, then a PDF and DOCX. Files are indexed per professor and course. |
| Outline review | Done | One reviewer or the council. Findings have a severity, a section, and a one-click fix. High findings do not block approval. |
| Council animation | Done | Marking, debate, judge, and feedback play as avatar cards. Demo mode replays a timed script. |
| University logo | Done | The UOW logotype is the default org logo in the header, on login, and on the subject outline. |
| Kafka | Not done | The app does not publish events to Kafka. |
| DVC | Not done | No dataset versioning. |
| Evidently | Not done | No drift reports. |
| SHAP | Not done | No explanation plots. The judge's reason is the explanation. |
| XGBoost training | Not done | The calibrator and the risk model are not trained. |
| LlamaIndex | Not done | Retrieval uses hash embeddings and keyword overlap. |
| UAE-region hosting | Not done | Compose runs locally. No region pin. |
| Student notice and regrade workflow | Not done | There is no student-facing notice or regrade queue. |
| AI-text detector as evidence | Not done | Left out on purpose. Integrity uses similarity and a conversation. |
