"""Artifact-first outline generation and refinement."""

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

import app.profassist.outline as outline
from app.profassist.errors import ProfassistError
from app.profassist.outline_data import (
    GENAI_POINTS,
    GRADES,
    LATE_SUBMISSION,
    empty_outline,
)

KEY_NAMES = (
    "OPENAI_API_KEY",
    "LLM_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "MISTRAL_API_KEY",
    "AZURE_API_KEY",
    "AZURE_API_BASE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "OLLAMA_API_BASE",
    "LLM_BASE_URL",
)


class _DB:
    def __init__(self, row):
        self.row = row

    async def get(self, model, ident):
        return self.row if ident == self.row.id else None

    async def flush(self):
        return None


def _row(**overrides):
    row = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        code="NEW-ABC123",
        name="New subject",
        status="draft",
        course_id=None,
        body=empty_outline(),
        pdf_key="",
        docx_key="",
        instructions="",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _wire(monkeypatch, row, *, sources=None, chunks=None, dossier=None, preferences=None):
    course = SimpleNamespace(id=uuid.uuid4(), code="MAAI903", ai_instructions="")

    async def fake_get_outline(*args):
        return row

    async def fake_load_runtime(*args):
        return None

    async def fake_course_for(db_session, org_id, body):
        return course

    async def fake_sources(*args):
        return list(sources or [])

    async def fake_chunks(*args):
        return list(chunks or [])

    async def fake_dossier(*args, **kwargs):
        return dict(dossier or {})

    monkeypatch.setattr(outline, "get_outline", fake_get_outline)
    monkeypatch.setattr(outline, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(outline, "_course_for", fake_course_for)
    monkeypatch.setattr(outline, "_source_materials", fake_sources)
    monkeypatch.setattr(outline, "_ready_chunks", fake_chunks)

    async def fake_preferences(*args, **kwargs):
        return list(preferences or [])

    monkeypatch.setattr(outline, "dossier_ai_context", fake_dossier)
    monkeypatch.setattr(outline, "artifact_preferences", fake_preferences)
    return course


def _fake_model(monkeypatch, payload: dict[str, Any]) -> list[dict[str, Any]]:
    from app.profassist.runtime import bind_runtime

    bind_runtime({}, {}, {"provider": "openai", "model": "gpt-4o-mini", "agents": {}})
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls: list[dict[str, Any]] = []

    class Response:
        choices = [SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]

    def fake_generate(provider_id, model, messages, **kwargs):
        calls.append(
            {"provider": provider_id, "model": model, "messages": messages, "kwargs": kwargs}
        )
        return Response()

    monkeypatch.setattr("app.profassist.providers.generate", fake_generate)
    return calls


def _system(messages: object) -> str:
    assert isinstance(messages, list)
    return next(message["content"] for message in messages if message["role"] == "system")


def _clear_keys(monkeypatch) -> None:
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_generate_outline_normalises_arrays_and_keeps_template_fixed_sections(
    monkeypatch,
    fake_langfuse: str,
) -> None:
    row = _row()
    _wire(monkeypatch, row)
    calls = _fake_model(
        monkeypatch,
        {
            "reply": "Drafted from your notes.",
            "basics": {"name": "Cloud Systems", "code": "CS 501", "credit_points": 6},
            "lecture": {"day": "Monday", "time": "09:00"},
            "description": "A subject about clouds.",
            "plos": [{"code": "PLO1", "text": "Apply cloud design."}],
            "clos": [
                {
                    "code": "CLO1",
                    "text": "Design a cloud.",
                    "plos": ["PLO1", "PLO9"],
                }
            ],
            "weeks": [
                {"week": 1, "topic": "Intro", "lo_codes": ["CLO1"]},
                {"week": 13, "topic": "Wrap", "lo_codes": ["LO9"]},
            ],
            "readings": ["Book one."],
            "outcome_measures": [
                {"lo_code": "CLO1", "measures": "A1"},
                {"lo_code": "LO9", "measures": "A9"},
            ],
            "grades": [{"band": "Invented", "range": "0-1", "description": ""}],
            "genai": ["An invented AI rule."],
        },
    )
    db: Any = _DB(row)

    result = asyncio.run(
        outline.generate_outline(
            db, row.organization_id, row.owner_user_id, row.id, "Focus on healthcare cases."
        )
    )

    body = result["outline"]["body"]
    assert body["basics"]["credit_points"] == 6
    assert body["plos"] == [{"code": "PLO1", "text": "Apply cloud design."}]
    assert body["clos"][0]["code"] == "LO1"
    assert body["clos"][0]["plos"] == ["PLO1"]
    assert [week["week"] for week in body["weeks"]] == [1, 2]
    assert body["weeks"][1]["lo_codes"] == []
    assert body["outcome_measures"] == [{"lo_code": "LO1", "measures": "A1"}]
    assert body["readings"] == ["Book one."]

    # The model may not invent the fixed sections.
    assert body["grades"] == GRADES
    assert body["genai"] == GENAI_POINTS
    assert body["late_submission"] == LATE_SUBMISSION

    assert row.instructions == "Focus on healthcare cases."
    assert result["changed_sections"] == [
        "basics",
        "lecture",
        "description",
        "plos",
        "clos",
        "weeks",
        "readings",
        "outcome_measures",
    ]
    assert result["outline"]["status"] == "draft"
    # The trace is response metadata, never part of the outline JSON.
    assert result["trace_url"] == fake_langfuse
    assert "trace_url" not in result["outline"]
    assert "trace_url" not in result["outline"]["body"]

    sent = calls[0]
    assert sent["kwargs"]["max_tokens"] == 6000
    system = _system(sent["messages"])
    assert "Do not invent policies" in system
    assert "11 or 12 weeks" in system
    assert "outcome_measures" in system
    assert "Focus on healthcare cases." in system


def test_generate_body_accepts_gemini_provider_shape() -> None:
    """Gemini returns plos as an object and clos with id/description/supports."""
    drafted = {
        "reply": "Drafted from your notes.",
        "plos": {
            "PLO1": "Apply discipline fundamentals.",
            "PLO2": "Analyse problems.",
            "PLO3": "Design solutions.",
            "PLO4": "Communicate findings.",
            "PLO5": "Evaluate professional risk.",
            "PLO6": "Work in teams.",
        },
        "clos": [
            {
                "id": "CLO1",
                "description": "Build a working system.",
                "supports": ["PLO1", "PLO5"],
            },
            {
                "id": "CLO2",
                "description": "Test the system.",
                "supports": [{"code": "PLO3"}],
            },
        ],
    }

    body, changed, missing = outline._generate_body({}, drafted)

    assert len(body["plos"]) == 6
    assert body["plos"][0] == {"code": "PLO1", "text": "Apply discipline fundamentals."}
    assert body["clos"][0]["plos"] == ["PLO1", "PLO5"]
    assert body["clos"][1]["plos"] == ["PLO3"]
    assert "plos" not in missing
    assert "plos" in changed


def test_generate_outline_requires_a_configured_model(monkeypatch) -> None:
    row = _row()
    _wire(monkeypatch, row)
    _clear_keys(monkeypatch)
    monkeypatch.setattr("app.profassist.llm.key_configured", lambda _provider: False)
    db: Any = _DB(row)

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            outline.generate_outline(
                db, row.organization_id, row.owner_user_id, row.id, "Draft it."
            )
        )
    assert caught.value.status == 503


def test_generate_outline_says_when_no_ready_notes_exist(monkeypatch) -> None:
    row = _row()
    sources = [
        {
            "id": "m1",
            "filename": "draft.pdf",
            "status": "processing",
            "pii_quarantined": False,
        }
    ]
    _wire(monkeypatch, row, sources=sources, chunks=[])
    calls = _fake_model(
        monkeypatch,
        {
            "reply": "Drafted from your instructions.",
            "basics": {"name": "Cloud Systems", "code": "CS 501"},
            "description": "A subject about clouds.",
        },
    )
    db: Any = _DB(row)

    result = asyncio.run(
        outline.generate_outline(db, row.organization_id, row.owner_user_id, row.id, "Draft it.")
    )

    assert "No ready notes are available" in calls[0]["messages"][1]["content"]
    assert "No ready notes are available" in result["reply"]
    assert result["sources"][0]["status"] == "processing"


def test_refine_outline_updates_only_outcomes_and_leaves_schedule_and_52(monkeypatch) -> None:
    weeks = [{"week": 1, "topic": "Keep me", "lo_codes": ["LO1"]}]
    tasks = [{"number": "A1", "title": "Keep 5.2 untouched"}]
    body = empty_outline()
    body["clos"] = [{"code": "LO1", "text": "Old outcome.", "plos": ["PLO1"]}]
    body["plos"] = [{"code": "PLO1", "text": "Old program outcome."}]
    body["weeks"] = weeks
    body["assessment_tasks"] = tasks
    row = _row(body=body, status="published")
    _wire(monkeypatch, row)
    calls = _fake_model(
        monkeypatch,
        {
            "reply": "Updated the outcomes.",
            "changed": True,
            "sections": {
                "outcomes": {
                    "plos": [{"code": "PLO1", "text": "New program outcome."}],
                    "clos": [{"code": "LO1", "text": "New outcome.", "plos": ["PLO1"]}],
                },
                "schedule": [{"week": 1, "topic": "Should not apply"}],
            },
        },
    )
    db: Any = _DB(row)

    result = asyncio.run(
        outline.refine_outline(
            db,
            row.organization_id,
            row.owner_user_id,
            row.id,
            "Make the outcomes sharper.",
            section="outcomes",
        )
    )

    assert result["changed"] is True
    assert result["changed_sections"] == ["outcomes"]
    assert row.body["clos"][0]["text"] == "New outcome."
    assert row.body["plos"][0]["text"] == "New program outcome."
    assert row.body["weeks"] == weeks
    assert row.body["assessment_tasks"] == tasks
    assert row.status == "published"

    sent = calls[0]
    assert sent["kwargs"]["max_tokens"] == 6000
    assert '"sections"' in _system(sent["messages"])


def test_refine_outline_400_keeps_the_previous_body(monkeypatch) -> None:
    weeks = [{"week": 1, "topic": "Keep me", "lo_codes": ["LO1"]}]
    body = empty_outline()
    body["weeks"] = weeks
    row = _row(body=body)
    _wire(monkeypatch, row)
    _fake_model(
        monkeypatch,
        {"reply": "Bad change.", "changed": True, "sections": {"weeks": {"not": "a list"}}},
    )
    db: Any = _DB(row)

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            outline.refine_outline(
                db, row.organization_id, row.owner_user_id, row.id, "Change the schedule."
            )
        )
    assert caught.value.status == 400
    assert row.body["weeks"] == weeks


def test_refine_outline_reports_no_change_for_a_question(monkeypatch) -> None:
    row = _row()
    _wire(monkeypatch, row)
    _fake_model(
        monkeypatch,
        {"reply": "This outline covers cloud design.", "changed": False, "sections": {}},
    )
    db: Any = _DB(row)

    result = asyncio.run(
        outline.refine_outline(
            db, row.organization_id, row.owner_user_id, row.id, "What does this outline cover?"
        )
    )

    assert result["changed"] is False
    assert result["changed_sections"] == []
    assert result["reply"] == "This outline covers cloud design."


def test_refine_outline_maps_schedule_and_assessment_map(monkeypatch) -> None:
    body = empty_outline()
    body["clos"] = [{"code": "LO1", "text": "Design a cloud.", "plos": []}]
    row = _row(body=body)
    _wire(monkeypatch, row)
    _fake_model(
        monkeypatch,
        {
            "reply": "Updated the schedule and map.",
            "changed": True,
            "sections": {
                "schedule": [{"week": 1, "topic": "New intro", "lo_codes": ["LO1"]}],
                "assessment_map": [{"lo_code": "LO1", "measures": "A1 Workshop"}],
            },
        },
    )
    db: Any = _DB(row)

    result = asyncio.run(
        outline.refine_outline(
            db, row.organization_id, row.owner_user_id, row.id, "Update the schedule."
        )
    )

    assert result["changed_sections"] == ["schedule", "assessment_map"]
    assert row.body["weeks"][0]["topic"] == "New intro"
    assert row.body["outcome_measures"] == [{"lo_code": "LO1", "measures": "A1 Workshop"}]
    assert result["outline"]["body"]["weeks"][0]["week"] == 1


def test_outline_ai_routes_are_registered_in_openapi() -> None:
    """The artifact-first generate and refine endpoints must be reachable."""
    from app.core.config import settings
    from app.main import app

    paths = app.openapi()["paths"]
    prefix = f"{settings.API_V1_STR}/profassist/outlines/{{outline_id}}"
    for suffix in ("generate", "refine"):
        operation = paths[f"{prefix}/{suffix}"]
        assert "post" in operation


def test_generate_route_forwards_the_message_to_the_service(monkeypatch) -> None:
    import app.api.routes.v1.outline_ai as outline_ai

    captured: dict[str, Any] = {}

    async def fake_generate(db, org_id, user_id, outline_id, message):
        captured.update(
            db=db,
            org_id=org_id,
            user_id=user_id,
            outline_id=outline_id,
            message=message,
        )
        return {"reply": "ok"}

    monkeypatch.setattr(outline_ai, "generate_outline", fake_generate)

    user = SimpleNamespace(id=uuid.uuid4())
    org = SimpleNamespace(id=uuid.uuid4())
    outline_id = uuid.uuid4()
    db: Any = object()

    result = asyncio.run(
        outline_ai.outlines_generate(
            outline_id,
            outline_ai.OutlineGenerateBody(message="Draft it from my notes."),
            user,
            org,
            db,
        )
    )

    assert result == {"reply": "ok"}
    assert captured["db"] is db
    assert captured["org_id"] == org.id
    assert captured["user_id"] == user.id
    assert captured["outline_id"] == outline_id
    assert captured["message"] == "Draft it from my notes."


def test_refine_route_forwards_the_message_and_section_to_the_service(monkeypatch) -> None:
    import app.api.routes.v1.outline_ai as outline_ai

    captured: dict[str, Any] = {}

    async def fake_refine(db, org_id, user_id, outline_id, message, section=None):
        captured.update(
            db=db,
            org_id=org_id,
            user_id=user_id,
            outline_id=outline_id,
            message=message,
            section=section,
        )
        return {"changed": True}

    monkeypatch.setattr(outline_ai, "refine_outline", fake_refine)

    user = SimpleNamespace(id=uuid.uuid4())
    org = SimpleNamespace(id=uuid.uuid4())
    outline_id = uuid.uuid4()
    db: Any = object()

    result = asyncio.run(
        outline_ai.outlines_refine(
            outline_id,
            outline_ai.OutlineRefineBody(message="Tighten the outcomes.", section="outcomes"),
            user,
            org,
            db,
        )
    )

    assert result == {"changed": True}
    assert captured["db"] is db
    assert captured["org_id"] == org.id
    assert captured["user_id"] == user.id
    assert captured["outline_id"] == outline_id
    assert captured["message"] == "Tighten the outcomes."
    assert captured["section"] == "outcomes"


DOSSIER = {
    "summary": "The course covers cloud systems.",
    "provenance": [{"field": "summary", "value": "cloud systems", "filename": "syllabus.pdf"}],
}


def test_generate_outline_injects_the_course_dossier(monkeypatch) -> None:
    row = _row()
    _wire(monkeypatch, row, dossier=DOSSIER)
    calls = _fake_model(
        monkeypatch,
        {"reply": "Drafted.", "basics": {"name": "Cloud Systems", "code": "CS 501"}},
    )

    asyncio.run(
        outline.generate_outline(
            db=_DB(row),
            org_id=row.organization_id,
            user_id=row.owner_user_id,
            outline_id=row.id,
            message="Draft it.",
        )
    )

    sent = calls[0]["messages"]
    system = _system(sent)
    assert "## Course memory" in system
    assert "syllabus.pdf" in system
    assert "syllabus.pdf" in sent[1]["content"]


def test_refine_outline_injects_the_course_dossier(monkeypatch) -> None:
    row = _row()
    _wire(monkeypatch, row, dossier=DOSSIER)
    calls = _fake_model(
        monkeypatch,
        {"reply": "Updated.", "changed": False, "sections": {}},
    )

    asyncio.run(
        outline.refine_outline(
            db=_DB(row),
            org_id=row.organization_id,
            user_id=row.owner_user_id,
            outline_id=row.id,
            message="What does this cover?",
        )
    )

    sent = calls[0]["messages"]
    assert "## Course memory" in _system(sent)
    assert "syllabus.pdf" in sent[1]["content"]


def test_generate_body_cleans_assessment_tasks_from_the_dossier() -> None:
    body = empty_outline()
    body["clos"] = [
        {"code": "LO1", "text": "Design a cloud.", "plos": []},
        {"code": "LO2", "text": "Analyse risk.", "plos": []},
    ]
    drafted = {
        "assessment_tasks": [
            {
                "name": "Workshops",
                "weight": "20%",
                "due": "Throughout",
                "lo_codes": ["CLO1"],
                "brief": "Weekly practice.",
            },
            {
                "title": "Report",
                "percentage": 50,
                "due_date": "Week 7",
                "clos": ["LO2"],
                "description": "A written report.",
            },
            {
                "name": "Exam",
                "weight": "30%",
                "lo_codes": ["LO1", "LO2"],
                "criteria": [{"name": "Accuracy"}],
            },
        ]
    }

    updated, changed, missing = outline._generate_body(body, drafted)

    tasks = updated["assessment_tasks"]
    assert [task["weight"] for task in tasks] == [20, 50, 30]
    assert [task["name"] for task in tasks] == ["Workshops", "Report", "Exam"]
    assert tasks[0]["lo_codes"] == ["LO1"]
    assert tasks[1]["lo_codes"] == ["LO2"]
    assert tasks[2]["lo_codes"] == ["LO1", "LO2"]
    assert tasks[1]["due"] == "Week 7"
    assert tasks[0]["brief"] == "Weekly practice."
    assert [task["number"] for task in tasks] == ["A1", "A2", "A3"]
    assert [task["title"] for task in tasks] == ["Workshops", "Report", "Exam"]
    assert all(task["type"] == "Individual" for task in tasks)
    assert all(task["total_marks"] == 100 for task in tasks)
    assert tasks[0]["overview"] == ["Weekly practice."]
    assert tasks[1]["overview"] == ["A written report."]
    assert tasks[2]["rubric"] == [{"name": "Accuracy", "weight": 0, "levels": {}}]
    assert tasks[0]["deliverables"] == []
    assert tasks[0]["format"] == []
    assert "assessment_tasks" in changed
    assert "assessment_tasks" not in missing


def test_generate_body_accepts_assessment_tasks_as_a_code_map() -> None:
    body = empty_outline()
    body["clos"] = [{"code": "LO1", "text": "Design.", "plos": []}]

    updated, _, _ = outline._generate_body(
        body,
        {
            "assessment_tasks": {
                "A1": {"title": "Report", "percentage": "40%", "clos": ["CLO1"]},
            }
        },
    )

    tasks = updated["assessment_tasks"]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["number"] == "A1"
    assert task["title"] == "Report"
    assert task["name"] == "Report"
    assert task["type"] == "Individual"
    assert task["weight"] == 40
    assert task["total_marks"] == 100
    assert task["due"] == ""
    assert task["lo_codes"] == ["LO1"]
    assert task["overview"] == []
    assert task["brief"] == ""
    assert task["deliverables"] == []
    assert task["format"] == []
    assert task["rubric"] == []


def test_clean_weight_rounds_instead_of_truncating() -> None:
    assert outline._clean_weight("12.5") == 13
    assert outline._clean_weight("12.4") == 12
    assert outline._clean_weight(12.5) == 13


def test_generate_body_reports_missing_or_blank_assessment_tasks() -> None:
    body = empty_outline()

    missing_body, _, missing = outline._generate_body(body, {"reply": "Drafted."})
    assert missing_body["assessment_tasks"] == []
    assert "assessment_tasks" in missing

    _, _, blank_missing = outline._generate_body(body, {"assessment_tasks": []})
    assert "assessment_tasks" in blank_missing


def test_generate_outline_keeps_the_dossier_assessment_tasks(monkeypatch) -> None:
    row = _row()
    _wire(monkeypatch, row)
    calls = _fake_model(
        monkeypatch,
        {
            "reply": "Drafted.",
            "clos": [{"code": "LO1", "text": "Design a cloud."}],
            "assessment_tasks": [
                {"name": "Workshops", "weight": "20%", "lo_codes": ["LO1"]},
                {"name": "Report", "weight": "50%", "lo_codes": ["LO1"]},
                {"name": "Exam", "weight": "30%", "lo_codes": ["LO1"]},
            ],
        },
    )
    db: Any = _DB(row)

    result = asyncio.run(
        outline.generate_outline(db, row.organization_id, row.owner_user_id, row.id, "Draft it.")
    )

    tasks = result["outline"]["body"]["assessment_tasks"]
    assert [task["weight"] for task in tasks] == [20, 50, 30]
    assert all(task["lo_codes"] == ["LO1"] for task in tasks)
    assert [task["number"] for task in tasks] == ["A1", "A2", "A3"]
    assert [task["title"] for task in tasks] == ["Workshops", "Report", "Exam"]
    assert all(task["type"] == "Individual" for task in tasks)
    assert all(task["total_marks"] == 100 for task in tasks)
    system = _system(calls[0]["messages"])
    assert "assessment_tasks" in system
    assert "never invent a task or a weight" in system


def _capture_complete(monkeypatch, response):
    captured: dict[str, dict[str, Any]] = {}

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured[task] = payload
        return response

    monkeypatch.setattr("app.profassist.llm.complete", fake_complete)
    return captured


def test_generate_outline_payload_carries_learned_preferences(monkeypatch) -> None:
    row = _row()
    _wire(monkeypatch, row, preferences=["Prefers a more concise outline."])
    captured = _capture_complete(
        monkeypatch,
        {"reply": "Drafted.", "basics": {"name": "Cloud Systems", "code": "CS 501"}},
    )

    asyncio.run(
        outline.generate_outline(
            _DB(row), row.organization_id, row.owner_user_id, row.id, "Draft it."
        )
    )

    assert captured["outline_generate"]["preferences"] == ["Prefers a more concise outline."]


def test_assist_step_payload_carries_learned_preferences(monkeypatch) -> None:
    row = _row()
    _wire(monkeypatch, row, preferences=["Prefers fuller detail in outlines."])

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(outline, "capture_movement", noop)
    captured = _capture_complete(
        monkeypatch,
        {"reply": "Drafted.", "suggestion": {"description": "A clearer description."}},
    )

    asyncio.run(
        outline.assist_step(
            _DB(row), row.organization_id, row.owner_user_id, row.id, "description", "Tighten it."
        )
    )

    assert captured["outline_assist"]["preferences"] == ["Prefers fuller detail in outlines."]
    assert captured["outline_assist"]["step"] == "description"


def test_refine_outline_payload_carries_learned_preferences(monkeypatch) -> None:
    row = _row()
    _wire(monkeypatch, row, preferences=["Prefers a more concise outline."])
    captured = _capture_complete(
        monkeypatch,
        {"reply": "No change was needed.", "changed": False, "sections": {}},
    )

    asyncio.run(
        outline.refine_outline(
            _DB(row), row.organization_id, row.owner_user_id, row.id, "What does this cover?"
        )
    )

    assert captured["outline_refine"]["preferences"] == ["Prefers a more concise outline."]
