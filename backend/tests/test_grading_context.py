"""The grading council sees the official outline and the assessment CLOs."""

import uuid
from typing import Any

import pytest

from app.profassist import agents, llm, service
from app.profassist.models import (
    Assessment,
    Course,
    RubricCriterion,
    SubjectOutline,
    Submission,
)

OUTLINE = {
    "code": "MAAI903",
    "name": "AI Solutions Design & MLOps",
    "clos": [{"code": "LO1", "text": "Design an end-to-end AI solution."}],
    "weeks": [{"week": 7, "topic": "Architecture review", "lo_codes": ["LO1"]}],
    "outcome_measures": [{"lo_code": "LO1", "measures": "Assessment 2 report"}],
}

CLOS = ["Design an end-to-end AI solution."]

DOSSIER = {
    "summary": "The official course covers architecture review.",
    "provenance": [
        {"field": "summary", "value": "architecture review", "filename": "syllabus.pdf"}
    ],
}

SUBMISSION_TEXT = "The report names the audience. The architecture covers the pipeline."


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, results: list[list[Any]], mapping: dict[Any, Any]) -> None:
        self.results = list(results)
        self.mapping = mapping
        self.added: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        return _Result(self.results.pop(0))

    async def get(self, model: Any, ident: uuid.UUID) -> Any | None:
        return self.mapping.get((model, ident))

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid.uuid4()


def _outline(org_id: uuid.UUID, user_id: uuid.UUID, course: Course) -> SubjectOutline:
    body = {
        "basics": {"code": course.code, "name": course.title},
        "clos": [dict(item) for item in OUTLINE["clos"]],
        "weeks": [dict(item) for item in OUTLINE["weeks"]],
        "outcome_measures": [dict(item) for item in OUTLINE["outcome_measures"]],
        "readings": ["Lecture 6: MLOps pipelines"],
    }
    return SubjectOutline(
        id=uuid.uuid4(),
        organization_id=org_id,
        owner_user_id=user_id,
        course_id=course.id,
        code=course.code,
        name=course.title,
        status="published",
        body=body,
    )


@pytest.mark.anyio
async def test_run_grade_passes_the_outline_and_clos_to_the_council(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = Course(
        id=uuid.uuid4(),
        organization_id=org_id,
        code="MAAI903",
        title="AI Solutions Design & MLOps",
        term="2026",
        clos=[],
    )
    assessment = Assessment(
        id=uuid.uuid4(),
        organization_id=org_id,
        course_id=course.id,
        owner_user_id=user_id,
        title="Assessment 2: Architecture report",
        brief="",
        clos=list(CLOS),
        status="approved",
        external_id="assignment:A2",
        weight=25,
        kind="assignment",
    )
    criterion = RubricCriterion(
        id=uuid.uuid4(),
        organization_id=org_id,
        assessment_id=assessment.id,
        ordinal=1,
        name="Architecture",
        weight=100,
        levels={"proficient": "Clear architecture."},
    )
    submission = Submission(
        id=uuid.uuid4(),
        organization_id=org_id,
        course_id=course.id,
        assessment_id=assessment.id,
        external_id="sub-1",
        group_name="Group A",
        topic="",
        raw_text=SUBMISSION_TEXT,
        scrubbed_text=SUBMISSION_TEXT,
        pii_report={},
        peer_reviews=[],
        origin="moodle",
    )
    outline = _outline(org_id, user_id, course)
    db = _DB(
        [[criterion], [], [outline]],
        {
            (Course, course.id): course,
            (Submission, submission.id): submission,
            (Assessment, assessment.id): assessment,
        },
    )

    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_council_roles(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        from app.profassist.council_config import default_roles

        roles = default_roles("grading")
        for role in roles:
            if role["role_key"] == "strict":
                role["enabled"] = False
            if role["role_key"] == "evidence":
                role["persona_prompt"] = "Evidence voice."
                role["model"] = "evidence-model"
        return roles

    async def fake_recall(*args: Any, **kwargs: Any) -> list[str]:
        return []

    async def fake_soul(*args: Any, **kwargs: Any) -> str:
        return "Short sentences."

    calls: list[dict[str, Any]] = []

    def fake_council(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return {
            "votes": [],
            "debate_rounds": [],
            "judge": {
                "level": "proficient",
                "quotes": [],
                "vote_split": [],
                "evidence_status": "ok",
            },
            "feedback": "Good.",
            "trace_url": "",
        }

    monkeypatch.setattr(service, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(service, "load_council_roles", fake_council_roles)
    monkeypatch.setattr(service, "recall", fake_recall)
    monkeypatch.setattr(service, "_soul", fake_soul)
    monkeypatch.setattr(service.agents, "run_grading_council", fake_council)

    async def fake_dossier(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return dict(DOSSIER)

    monkeypatch.setattr(service, "dossier_ai_context", fake_dossier)

    await service.run_grade(db, org_id, user_id, submission.id)

    assert len(calls) == 1
    assert calls[0]["clos"] == CLOS
    assert calls[0]["outline"]["clos"] == OUTLINE["clos"]
    assert calls[0]["outline"]["weeks"][0]["topic"] == "Architecture review"
    assert "readings" not in calls[0]["outline"]
    assert calls[0]["dossier"] == DOSSIER
    # Only enabled llm personas reach the graph, each with its own prompt and model.
    assert calls[0]["personas"] == ["evidence", "supportive"]
    assert calls[0]["persona_config"]["evidence"] == {
        "prompt_override": "Evidence voice.",
        "model": "evidence-model",
    }
    assert "strict" not in calls[0]["persona_config"]


def test_grade_persona_payload_includes_the_outline_and_clos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_invoke(graph: Any, state: dict[str, Any], **kwargs: Any) -> tuple[Any, None]:
        captured.update(state)
        return graph.invoke(state), None

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((task, payload))
        if task == "feedback":
            return {"feedback": "Good."}
        return {
            "level": "proficient",
            "quotes": ["The report names the audience."],
            "why": "It names the audience.",
        }

    monkeypatch.setattr(agents, "invoke_graph", fake_invoke)
    monkeypatch.setattr(llm, "complete", fake_complete)

    agents.run_grading_council(
        SUBMISSION_TEXT,
        {"name": "Architecture", "levels": {"proficient": "Clear."}},
        "Short sentences.",
        outline=OUTLINE,
        clos=CLOS,
        dossier=DOSSIER,
    )

    assert captured["outline"] == OUTLINE
    assert captured["clos"] == CLOS
    assert captured["dossier"] == DOSSIER
    persona_payloads = [payload for task, payload in calls if task == "grade_persona"]
    assert len(persona_payloads) == 3
    for payload in persona_payloads:
        assert payload["outline"] == OUTLINE
        assert payload["clos"] == CLOS
        assert payload["dossier"] == DOSSIER
