"""One prompt to a finishable assignment brief and rubric."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import DateTime, Delete
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter, Null

import app.api.routes.v1.assignment_ai as assignment_ai
import app.profassist.llm as llm
from app.profassist.assignment_data import CLASS_DETAILS, REPORT_SECTIONS, fixed_report_sections
from app.profassist.errors import ProfassistError
from app.profassist.models import (
    Assessment,
    Course,
    GroupAssignment,
    RubricCriterion,
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


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None


def _criteria(statement) -> list[tuple[str, object, str]]:
    filters: list[tuple[str, object, str]] = []
    for criterion in getattr(statement, "_where_criteria", ()):
        key = getattr(getattr(criterion, "left", None), "key", None)
        if not key:
            continue
        right = getattr(criterion, "right", None)
        if isinstance(right, Null):
            filters.append((key, None, "is"))
        elif isinstance(right, BindParameter):
            kind = "in" if getattr(criterion, "operator", None) is operators.in_op else "eq"
            filters.append((key, right.value, kind))
    return filters


def _matches(row: object, filters: list[tuple[str, object, str]]) -> bool:
    for key, value, kind in filters:
        actual = getattr(row, key, object())
        if kind == "is":
            if actual is not None:
                return False
        elif actual != value:
            return False
    return True


def _apply_defaults(row: object) -> None:
    for attr in sa_inspect(type(row)).mapper.column_attrs:
        if getattr(row, attr.key, None) is not None:
            continue
        column = attr.columns[0]
        if column.default is not None:
            try:
                value = column.default.arg(None)
            except TypeError:
                value = column.default.arg
        elif column.server_default is not None and isinstance(column.type, DateTime):
            from datetime import UTC, datetime

            value = datetime.now(UTC)
        else:
            continue
        setattr(row, attr.key, value)


class FakeSession:
    """Enough of AsyncSession for the routes to run without a database."""

    def __init__(self) -> None:
        self.rows: list[object] = []

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        for row in self.rows:
            _apply_defaults(row)

    async def get(self, model, ident):
        for row in self.rows:
            if isinstance(row, model) and getattr(row, "id", None) == ident:
                return row
        return None

    async def execute(self, statement):
        if isinstance(statement, Delete):
            table = statement.table.name
            filters = _criteria(statement)
            self.rows = [
                row
                for row in self.rows
                if not (getattr(row, "__tablename__", "") == table and _matches(row, filters))
            ]
            return _Result([])
        entity = statement.column_descriptions[0]["entity"]
        filters = _criteria(statement)
        rows = [row for row in self.rows if isinstance(row, entity) and _matches(row, filters)]
        return _Result(rows)


class Patches:
    """Collects the calls the route makes to the model."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, responses: dict[str, Any]) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

        def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
            self.calls.append((task, payload))
            return responses.get(
                task, {"verdict": "pass", "summary": "No findings.", "strengths": []}
            )

        async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr(llm, "complete", fake_complete)
        monkeypatch.setattr(assignment_ai, "load_runtime", fake_load_runtime)

    def payload(self, task: str) -> dict[str, Any]:
        return next(payload for name, payload in self.calls if name == task)


def _document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "class_details": {
            "institution": "University of Wollongong in Dubai",
            "course": "MAAI903 AI Solutions Design & MLOps",
            "lecturer": "Dr Patrick Mukala",
            "assessment": "Assessment 2: Solutions Architecture Report",
            "weight": "25%",
            "report_length": "Maximum 2,500 words",
            "report_due": "Week 7",
            "presentation": "Week 7, 10 minutes",
            "submission": "Upload to Moodle",
        },
        "overview": ["Design an AI solution architecture."],
        "problem_choices": [
            {"problem": "Bank fraud detection", "description": "Real-time card scoring."}
        ],
        "deliverables": [
            {"title": "Technical report", "description": "At most 2,500 words."},
        ],
        "report_sections": fixed_report_sections(),
    }
    document.update(overrides)
    return document


def _rubric() -> list[dict[str, Any]]:
    levels = {
        "beginning": "Little detail.",
        "developing": "Some detail.",
        "proficient": "Clear detail.",
        "advanced": "Insightful detail.",
    }
    return [
        {"name": "Architecture", "weight": 60, "levels": dict(levels)},
        {"name": "Ethics", "weight": 40, "levels": dict(levels)},
    ]


def _row(db: FakeSession, org_id: uuid.UUID, user_id: uuid.UUID, course: Course) -> GroupAssignment:
    row = GroupAssignment(
        organization_id=org_id,
        owner_user_id=user_id,
        course_id=course.id,
        number="A2",
        title="Assessment 2: Solutions Architecture Report",
        body="",
        document=_document(),
        blind=False,
        group_mode="individual",
        weight=25,
        due="Week 7",
        lo_codes=["Design a pipeline."],
        status="draft",
    )
    db.add(row)
    return row


def _assessment(
    db: FakeSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course: Course,
    *,
    status: str = "draft",
) -> Assessment:
    assessment = Assessment(
        organization_id=org_id,
        course_id=course.id,
        owner_user_id=user_id,
        title="Assessment 2: Solutions Architecture Report",
        brief="",
        clos=["Design a pipeline."],
        status=status,
        external_id="assignment:A2",
        weight=25,
        kind="assignment",
    )
    db.add(assessment)
    return assessment


def _add_rubric(
    db: FakeSession, org_id: uuid.UUID, assessment: Assessment, rubric: list[dict[str, Any]]
) -> None:
    for ordinal, criterion in enumerate(rubric, start=1):
        db.add(
            RubricCriterion(
                organization_id=org_id,
                assessment_id=assessment.id,
                ordinal=ordinal,
                name=criterion["name"],
                weight=criterion["weight"],
                levels=criterion["levels"],
            )
        )


async def _workspace(db: FakeSession) -> tuple[uuid.UUID, uuid.UUID, Course]:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = Course(
        organization_id=org_id,
        code="MAAI903",
        title="AI Solutions Design & MLOps",
        term="2026",
        clos=["Design a pipeline.", "Reason about ethics."],
    )
    db.add(course)
    await db.flush()
    return org_id, user_id, course


def test_template_has_the_eleven_sections_and_the_rendered_labels() -> None:
    from app.profassist.assignment_doc import CLASS_FIELDS

    assert CLASS_DETAILS == CLASS_FIELDS
    assert [item["number"] for item in REPORT_SECTIONS] == [str(i) for i in range(1, 12)]
    assert REPORT_SECTIONS[0]["section"] == "Executive Summary"
    assert REPORT_SECTIONS[-1]["section"] == "References"


def _user(user_id: uuid.UUID) -> Any:
    return SimpleNamespace(id=user_id)


def _org(org_id: uuid.UUID) -> Any:
    return SimpleNamespace(id=org_id)


@pytest.mark.anyio
async def test_create_fills_eleven_sections_and_a_rubric_that_totals_100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    patches = Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "Drafted the brief.",
                "document": {
                    "class_details": {
                        "assessment": "Assessment 2: Solutions Architecture Report",
                        "weight": "25%",
                        "lecturer": "Dr Patrick Mukala",
                        "report_due": "Week 7",
                    },
                    "overview": ["Design an AI solution architecture."],
                    "problem_choices": [
                        {"problem": "Bank fraud detection", "description": "Real-time scoring."}
                    ],
                    "deliverables": [
                        {"title": "Technical report", "description": "At most 2,500 words."}
                    ],
                },
            },
            "rubric": {"criteria": _rubric()},
        },
    )
    user, org = _user(user_id), _org(org_id)

    result = await assignment_ai.create_assignment(
        assignment_ai.AssistCreateBody(course_id=course.id, message="Bank fraud assignment."),
        user,
        org,
        db,
    )

    document = result["document"]
    sections = document["report_sections"]
    assert len(sections) == 11
    assert [item["number"] for item in sections] == [item["number"] for item in REPORT_SECTIONS]
    assert [item["section"] for item in sections] == [item["section"] for item in REPORT_SECTIONS]
    assert document["class_details"]["lecturer"] == "Dr Patrick Mukala"

    rubric = result["rubric"]
    assert rubric == _rubric()
    assert sum(item["weight"] for item in rubric) == 100

    row = next(item for item in db.rows if isinstance(item, GroupAssignment))
    assert row.document == document
    assert row.title == "Assessment 2: Solutions Architecture Report"
    assert row.weight == 25
    assert row.due == "Week 7"
    assert row.status == "draft"
    assert row.assessment_id is not None
    assessment = next(item for item in db.rows if isinstance(item, Assessment))
    assert assessment.id == row.assessment_id
    assert assessment.title == row.title
    assert assessment.weight == 25
    assert len([item for item in db.rows if isinstance(item, RubricCriterion)]) == 2
    assert result["assignment"]["document"] == document
    assert result["assignment"]["group_mode"] == "individual"
    assert result["assignment"]["blind"] is False

    assert [name for name, _payload in patches.calls] == [
        "assignment_text",
        "rubric",
        "council_review",
        "council_review",
        "council_review",
        "assignment_review",
    ]
    assert result["review"]["messages"][-1]["text"].startswith("The council verdict is")
    assert result["document"]["review"] == result["review"]
    first = patches.payload("assignment_text")
    assert set(first) == {
        "prompt",
        "course",
        "outcomes",
        "report_sections",
        "existing",
        "outline",
        "chunks",
        "dossier",
        "preferences",
    }
    assert first["prompt"] == "Bank fraud assignment."
    assert first["course"]["code"] == "MAAI903"
    assert first["outcomes"] == ["Design a pipeline.", "Reason about ethics."]
    assert [item["number"] for item in first["report_sections"]] == [
        item["number"] for item in REPORT_SECTIONS
    ]
    # No outline or ready notes in this workspace: the payload says so by being empty.
    assert first["outline"] == {}
    assert first["chunks"] == []
    second = patches.payload("rubric")
    assert set(second) == {
        "brief",
        "clos",
        "existing",
        "outline",
        "chunks",
        "dossier",
        "preferences",
    }
    assert "eleven sections" in second["brief"]
    assert second["outline"] == {}
    assert second["chunks"] == []
    # With no trace open the key is still present, but never inside the document.
    assert result["trace_url"] == ""
    assert "trace_url" not in result["document"]


@pytest.mark.anyio
async def test_create_keeps_the_first_model_trace_across_a_corrective_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.profassist import observe

    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    calls: list[str] = []

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(task)
        observe._step_trace.set(f"http://trace/{len(calls)}")
        if task == "assignment_text" and calls.count("assignment_text") == 1:
            # An empty first answer is hollow, so the route retries once.
            return {"reply": "Hmm.", "document": {}}
        if task == "assignment_text":
            return {"reply": "Drafted.", "document": _document()}
        return {"reply": "Rubric.", "criteria": _rubric()}

    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(assignment_ai, "load_runtime", fake_load_runtime)

    result = await assignment_ai.create_assignment(
        assignment_ai.AssistCreateBody(course_id=course.id, message="Draft it."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert calls[:2] == ["assignment_text", "assignment_text"]
    assert result["trace_url"] == "http://trace/1"
    assert "trace_url" not in result["document"]
    observe.reset_step_trace()


@pytest.mark.anyio
async def test_create_requires_a_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(assignment_ai, "load_runtime", _noop)

    with pytest.raises(ProfassistError) as caught:
        await assignment_ai.create_assignment(
            assignment_ai.AssistCreateBody(course_id=course.id, message="Draft it."),
            _user(user_id),
            _org(org_id),
            db,
        )
    assert caught.value.status == 503


@pytest.mark.anyio
async def test_refine_updates_only_the_requested_field(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()
    row.weight = 30
    await db.flush()
    Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "Tightened the overview.",
                "changed": True,
                "document": {"overview": ["A sharper overview."]},
            }
        },
    )

    result = await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="Tighten the overview."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert result["changed"] is True
    assert result["document"]["overview"] == ["A sharper overview."]
    assert result["document"]["deliverables"] == _document()["deliverables"]
    assert result["document"]["problem_choices"] == _document()["problem_choices"]
    assert [item["section"] for item in result["document"]["report_sections"]] == [
        item["section"] for item in REPORT_SECTIONS
    ]
    assert [item["guidelines"] for item in result["document"]["report_sections"]] == [
        item["guidelines"] for item in REPORT_SECTIONS
    ]
    assert result["rubric"] == _rubric()
    assert row.weight == 30
    assert row.document == result["document"]
    assert len([item for item in db.rows if isinstance(item, RubricCriterion)]) == 2


OUTLINE = {
    "code": "MAAI903",
    "name": "AI Solutions Design & MLOps",
    "clos": [{"code": "LO1", "text": "Design an end-to-end AI solution."}],
    "weeks": [{"week": 7, "topic": "Architecture review", "lo_codes": ["LO1"]}],
    "readings": ["Lecture 6: MLOps pipelines"],
    "outcome_measures": [{"lo_code": "LO1", "measures": "Assessment 2 report"}],
}

CHUNKS = [
    {
        "id": "c1",
        "text": "The architecture must name the audience and the artefact.",
        "filename": "lecture-6.pdf",
    }
]


def _context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_context(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"outline": dict(OUTLINE), "chunks": [dict(item) for item in CHUNKS]}

    monkeypatch.setattr(assignment_ai, "course_ai_context", fake_context)


@pytest.mark.anyio
async def test_create_sends_the_outline_and_chunks_to_both_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    patches = Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "Drafted the brief.",
                "document": {"overview": ["Design an AI solution architecture."]},
            },
            "rubric": {"criteria": _rubric()},
        },
    )
    _context(monkeypatch)

    await assignment_ai.create_assignment(
        assignment_ai.AssistCreateBody(course_id=course.id, message="Bank fraud assignment."),
        _user(user_id),
        _org(org_id),
        db,
    )

    for task in ("assignment_text", "rubric"):
        payload = patches.payload(task)
        assert payload["outline"]["clos"][0]["code"] == "LO1"
        assert payload["outline"]["weeks"][0]["topic"] == "Architecture review"
        assert payload["outline"]["readings"] == ["Lecture 6: MLOps pipelines"]
        assert payload["chunks"] == CHUNKS


@pytest.mark.anyio
async def test_refine_sends_the_outline_and_chunks_and_is_honest_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()
    patches = Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "Tightened the overview.",
                "changed": True,
                "document": {"overview": ["A sharper overview."]},
            }
        },
    )
    _context(monkeypatch)

    await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="Tighten the overview."),
        _user(user_id),
        _org(org_id),
        db,
    )
    payload = patches.payload("assignment_text")
    assert payload["outline"]["clos"][0]["text"] == "Design an end-to-end AI solution."
    assert payload["chunks"] == CHUNKS

    # Without an outline or ready notes, the next call says so with empty values.
    async def empty_context(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"outline": {}, "chunks": []}

    monkeypatch.setattr(assignment_ai, "course_ai_context", empty_context)
    patches.calls.clear()
    await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="Tighten the overview again."),
        _user(user_id),
        _org(org_id),
        db,
    )
    payload = patches.payload("assignment_text")
    assert payload["outline"] == {}
    assert payload["chunks"] == []


@pytest.mark.anyio
async def test_refine_answers_a_question_without_touching_the_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    before = dict(row.document)
    Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "The brief asks for an AI architecture report.",
                "document": {},
            }
        },
    )

    result = await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="What does this brief ask for?"),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert result["changed"] is False
    assert result["reply"] == "The brief asks for an AI architecture report."
    assert row.document == before
    assert result["document"] == before


@pytest.mark.anyio
async def test_refine_applies_a_complete_document_without_a_changed_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()

    Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "Updated the brief.",
                "document": _document(overview=["A sharper overview."]),
            }
        },
    )

    result = await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="Tighten the overview."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert result["changed"] is True
    assert result["document"]["overview"] == ["A sharper overview."]
    assert row.document["overview"] == ["A sharper overview."]


@pytest.mark.anyio
async def test_refine_returns_changed_false_for_an_identical_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    before = dict(row.document)
    Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "No change was needed.",
                "document": _document(),
            }
        },
    )

    result = await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="Leave it as it is."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert result["changed"] is False
    assert result["document"] == before
    assert row.document == before


@pytest.mark.anyio
async def test_refine_refuses_an_approved_rubric(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course, status="approved")
    await db.flush()
    row.assessment_id = assessment.id
    Patches(monkeypatch, {"assignment_text": {"reply": "Should not run.", "changed": False}})

    with pytest.raises(ProfassistError) as caught:
        await assignment_ai.refine_assignment(
            row.id,
            assignment_ai.AssistRefineBody(message="Change the rubric."),
            _user(user_id),
            _org(org_id),
            db,
        )
    assert caught.value.status == 409


@pytest.mark.anyio
async def test_finish_blocks_missing_sections_and_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()

    row.document = {**row.document, "report_sections": []}
    with pytest.raises(ProfassistError) as missing:
        await assignment_ai.finish_assignment(row.id, _user(user_id), _org(org_id), db)
    assert missing.value.status == 400
    assert "eleven" in missing.value.detail

    row.document = _document()
    for criterion in [item for item in db.rows if isinstance(item, RubricCriterion)]:
        criterion.weight = 45
    with pytest.raises(ProfassistError) as weights:
        await assignment_ai.finish_assignment(row.id, _user(user_id), _org(org_id), db)
    assert weights.value.status == 400
    assert "100" in weights.value.detail
    assert row.status == "draft"


@pytest.mark.anyio
async def test_finish_rejects_a_hollow_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    row.document = _document(overview=[], problem_choices=[], deliverables=[])
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()

    with pytest.raises(ProfassistError) as hollow:
        await assignment_ai.finish_assignment(row.id, _user(user_id), _org(org_id), db)

    assert hollow.value.status == 400
    assert "overview" in hollow.value.detail
    assert "problem choices" in hollow.value.detail
    assert "deliverables" in hollow.value.detail
    assert row.status == "draft"


@pytest.mark.anyio
async def test_finish_publishes_a_complete_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()
    monkeypatch.setattr(assignment_ai, "_index_assignment", lambda *args, **kwargs: None)

    result = await assignment_ai.finish_assignment(row.id, _user(user_id), _org(org_id), db)

    assert row.status == "published"
    assert result["assignment"]["status"] == "published"
    assert len(result["document"]["report_sections"]) == 11
    assert sum(item["weight"] for item in result["rubric"]) == 100


@pytest.mark.anyio
async def test_a_foreign_course_and_assignment_are_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    foreign = GroupAssignment(
        organization_id=uuid.uuid4(),
        owner_user_id=user_id,
        course_id=course.id,
        number="9",
        title="Foreign",
        document={},
    )
    db.add(foreign)
    await db.flush()
    Patches(monkeypatch, {"assignment_text": {"reply": "Draft.", "changed": False}})

    with pytest.raises(ProfassistError) as missing_course:
        await assignment_ai.create_assignment(
            assignment_ai.AssistCreateBody(course_id=uuid.uuid4(), message="Draft it."),
            _user(user_id),
            _org(org_id),
            db,
        )
    assert missing_course.value.status == 404

    with pytest.raises(ProfassistError) as missing_assignment:
        await assignment_ai.refine_assignment(
            foreign.id,
            assignment_ai.AssistRefineBody(message="Change it."),
            _user(user_id),
            _org(org_id),
            db,
        )
    assert missing_assignment.value.status == 404

    with pytest.raises(ProfassistError) as no_artifact:
        await assignment_ai.assignment_artifact(foreign.id, _user(user_id), _org(org_id), db)
    assert no_artifact.value.status == 404


@pytest.mark.anyio
async def test_document_downloads_pdf_and_docx_bytes() -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    await db.flush()

    pdf = await assignment_ai.assignment_document(
        row.id, _user(user_id), _org(org_id), db, kind="pdf"
    )
    docx = await assignment_ai.assignment_document(
        row.id, _user(user_id), _org(org_id), db, kind="docx"
    )

    assert pdf.body.startswith(b"%PDF")
    assert len(pdf.body) > 1000
    assert docx.body.startswith(b"PK")
    assert len(docx.body) > 1000
    assert pdf.media_type == "application/pdf"
    assert "Assessment-2-Solutions-Architecture-Report.pdf" in pdf.headers["Content-Disposition"]
    with pytest.raises(ProfassistError) as bad_kind:
        await assignment_ai.assignment_document(
            row.id, _user(user_id), _org(org_id), db, kind="txt"
        )
    assert bad_kind.value.status == 400


async def _noop(*args: Any, **kwargs: Any) -> None:
    return None


@pytest.mark.anyio
async def test_manual_save_persists_the_document_and_artifact_returns_it() -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    await db.flush()

    document = _document(overview=["Manually edited overview."])
    document["extra"] = {"keep": True}
    document["class_details"]["extra_note"] = "Harmless."
    sections = [dict(item) for item in document["report_sections"]]
    sections[0]["guidelines"] = "Edited executive summary guidelines."
    document["report_sections"] = sections

    result = await assignment_ai.save_assignment(
        row.id,
        assignment_ai.ManualAssignmentBody(document=document),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert result["document"]["overview"] == ["Manually edited overview."]
    assert result["document"]["report_sections"][0]["guidelines"] == (
        "Edited executive summary guidelines."
    )
    assert [item["number"] for item in result["document"]["report_sections"]] == [
        str(i) for i in range(1, 12)
    ]
    assert result["document"]["extra"] == {"keep": True}
    assert result["document"]["class_details"]["extra_note"] == "Harmless."
    assert row.document["overview"] == ["Manually edited overview."]

    artifact = await assignment_ai.assignment_artifact(row.id, _user(user_id), _org(org_id), db)
    assert artifact["document"] == result["document"]


@pytest.mark.anyio
async def test_manual_save_rejects_missing_duplicate_and_renumbered_sections() -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    await db.flush()
    before = dict(row.document)
    body = assignment_ai.ManualAssignmentBody

    missing = _document()
    missing["report_sections"] = missing["report_sections"][:-1]
    with pytest.raises(ProfassistError) as caught:
        await assignment_ai.save_assignment(
            row.id, body(document=missing), _user(user_id), _org(org_id), db
        )
    assert caught.value.status == 400

    duplicate = _document()
    duplicate["report_sections"][1] = {**duplicate["report_sections"][1], "number": "1"}
    with pytest.raises(ProfassistError) as caught:
        await assignment_ai.save_assignment(
            row.id, body(document=duplicate), _user(user_id), _org(org_id), db
        )
    assert caught.value.status == 400

    renumbered = _document()
    renumbered["report_sections"][0] = {**renumbered["report_sections"][0], "number": "0"}
    with pytest.raises(ProfassistError) as caught:
        await assignment_ai.save_assignment(
            row.id, body(document=renumbered), _user(user_id), _org(org_id), db
        )
    assert caught.value.status == 400
    assert row.document == before


@pytest.mark.anyio
async def test_manual_save_updates_title_weight_and_due_without_the_rubric() -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()
    document = dict(row.document)

    result = await assignment_ai.save_assignment(
        row.id,
        assignment_ai.ManualAssignmentBody(title="Manual title", weight=40, due="Week 9"),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert row.title == "Manual title"
    assert row.weight == 40
    assert row.due == "Week 9"
    assert row.document == document
    assert result["assignment"]["title"] == "Manual title"
    assert result["assignment"]["weight"] == 40
    assert result["assignment"]["due"] == "Week 9"
    assert result["document"] == document
    assert result["rubric"] == _rubric()
    assert len([item for item in db.rows if isinstance(item, RubricCriterion)]) == 2


@pytest.mark.anyio
async def test_manual_save_hides_a_foreign_assignment() -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    foreign = GroupAssignment(
        organization_id=uuid.uuid4(),
        owner_user_id=user_id,
        course_id=course.id,
        number="9",
        title="Foreign",
        document={},
    )
    db.add(foreign)
    await db.flush()

    with pytest.raises(ProfassistError) as caught:
        await assignment_ai.save_assignment(
            foreign.id,
            assignment_ai.ManualAssignmentBody(title="Changed"),
            _user(user_id),
            _org(org_id),
            db,
        )
    assert caught.value.status == 404


def test_manual_save_route_is_registered_in_openapi() -> None:
    from app.core.config import settings
    from app.main import app

    paths = app.openapi()["paths"]
    operation = paths[f"{settings.API_V1_STR}/profassist/assignments/{{assignment_id}}"]
    assert "put" in operation


DOSSIER = {
    "summary": "The course covers AI solution design and MLOps.",
    "provenance": [{"field": "summary", "value": "AI solution design", "filename": "syllabus.pdf"}],
}


def _mock_dossier(monkeypatch: pytest.MonkeyPatch, dossier: dict[str, Any]) -> None:
    async def fake_dossier(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return dict(dossier)

    monkeypatch.setattr("app.profassist.course_memory.service.dossier_ai_context", fake_dossier)


@pytest.mark.anyio
async def test_create_sends_the_course_dossier_to_both_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    patches = Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "Drafted the brief.",
                "document": {"overview": ["Design an AI solution architecture."]},
            },
            "rubric": {"criteria": _rubric()},
        },
    )
    _mock_dossier(monkeypatch, DOSSIER)

    await assignment_ai.create_assignment(
        assignment_ai.AssistCreateBody(course_id=course.id, message="Bank fraud assignment."),
        _user(user_id),
        _org(org_id),
        db,
    )

    for task in ("assignment_text", "rubric"):
        assert patches.payload(task)["dossier"] == DOSSIER


@pytest.mark.anyio
async def test_refine_sends_the_course_dossier(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()
    patches = Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "Tightened the overview.",
                "changed": True,
                "document": {"overview": ["A sharper overview."]},
            }
        },
    )
    _mock_dossier(monkeypatch, DOSSIER)

    await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="Tighten the overview."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert patches.payload("assignment_text")["dossier"] == DOSSIER


def test_model_document_maps_aliases_and_keeps_unknown_keys() -> None:
    mapped = assignment_ai._model_document(
        {
            "brief": "A short brief.",
            "problems": [{"problem": "Fraud", "description": "Detect fraud."}],
            "outputs": [{"title": "Report", "description": "Write it."}],
            "course_details": {"course": "MAAI903"},
            "extra": {"keep": True},
        }
    )

    assert mapped["overview"] == ["A short brief."]
    assert mapped["problem_choices"] == [{"problem": "Fraud", "description": "Detect fraud."}]
    assert mapped["deliverables"] == [{"title": "Report", "description": "Write it."}]
    assert mapped["class_details"] == {"course": "MAAI903"}
    assert mapped["extra"] == {"keep": True}
    for alias in ("brief", "problems", "outputs", "course_details"):
        assert alias not in mapped


def test_model_document_maps_aliases_inside_the_document_object() -> None:
    mapped = assignment_ai._model_document(
        {"document": {"summary": ["One.", "Two."], "tasks": [], "details": {"course": "C"}}}
    )

    assert mapped["overview"] == ["One.", "Two."]
    assert mapped["problem_choices"] == []
    assert mapped["class_details"] == {"course": "C"}
    assert "summary" not in mapped
    assert "tasks" not in mapped
    assert "details" not in mapped


@pytest.mark.anyio
async def test_create_retries_once_with_a_corrective_prompt_when_hollow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    responses = [
        {"reply": "Drafted.", "document": {"class_details": {"assessment": "Assessment 2"}}},
        {
            "reply": "Drafted fully.",
            "document": {
                "class_details": {"assessment": "Assessment 2"},
                "overview": ["A complete overview."],
                "problem_choices": [{"problem": "Fraud", "description": "Detect fraud."}],
                "deliverables": [{"title": "Report", "description": "Write it."}],
            },
        },
    ]
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((task, payload))
        if task == "assignment_text":
            return responses[len(calls) - 1]
        return {"criteria": _rubric()}

    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(assignment_ai, "load_runtime", fake_load_runtime)

    result = await assignment_ai.create_assignment(
        assignment_ai.AssistCreateBody(course_id=course.id, message="Bank fraud assignment."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assignment_calls = [payload for task, payload in calls if task == "assignment_text"]
    assert len(assignment_calls) == 2
    assert assignment_calls[1]["prompt"].endswith(
        "Return the document object with non-empty overview, problem_choices, and deliverables."
    )
    assert result["reply"] == "Drafted fully."
    assert result["document"]["overview"] == ["A complete overview."]
    assert result["document"]["problem_choices"][0]["problem"] == "Fraud"
    assert result["document"]["deliverables"][0]["title"] == "Report"


@pytest.mark.anyio
async def test_create_does_not_retry_when_the_document_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    calls: list[str] = []

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(task)
        if task == "assignment_text":
            return {"reply": "Drafted.", "document": _document()}
        return {"criteria": _rubric()}

    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(assignment_ai, "load_runtime", fake_load_runtime)

    result = await assignment_ai.create_assignment(
        assignment_ai.AssistCreateBody(course_id=course.id, message="Draft it."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert calls == [
        "assignment_text",
        "rubric",
        "council_review",
        "council_review",
        "council_review",
        "assignment_review",
    ]
    assert result["document"]["overview"] == ["Design an AI solution architecture."]


@pytest.mark.anyio
async def test_refine_retries_once_when_the_stored_brief_is_hollow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    row.document = {
        "class_details": {"assessment": "Assessment 2"},
        "overview": [],
        "problem_choices": [],
        "deliverables": [],
        "report_sections": fixed_report_sections(),
    }
    await db.flush()
    responses = [
        {"reply": "No change was needed.", "changed": False, "document": {}},
        {
            "reply": "Filled the brief.",
            "changed": True,
            "document": {
                "overview": ["A full overview."],
                "problem_choices": [{"problem": "Fraud", "description": "Detect it."}],
                "deliverables": [{"title": "Report", "description": "Write it."}],
            },
        },
    ]
    calls: list[str] = []

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task == "assignment_review":
            return {"verdict": "pass", "summary": "No findings.", "strengths": []}
        if task == "council_review":
            return {"issues": []}
        calls.append(str(payload.get("prompt") or ""))
        return responses[len(calls) - 1]

    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(assignment_ai, "load_runtime", fake_load_runtime)

    result = await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="Fill in the brief."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert len(calls) == 2
    assert calls[1].endswith(
        "Return the document object with non-empty overview, problem_choices, and deliverables."
    )
    assert result["changed"] is True
    assert result["document"]["overview"] == ["A full overview."]


@pytest.mark.anyio
async def test_create_sends_learned_preferences_to_both_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    patches = Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "Drafted the brief.",
                "document": {"overview": ["Design an AI solution architecture."]},
            },
            "rubric": {"criteria": _rubric()},
        },
    )

    async def fake_preferences(*args: Any, **kwargs: Any) -> list[str]:
        return ["Prefers a more concise assignment brief."]

    monkeypatch.setattr(assignment_ai, "artifact_preferences", fake_preferences)

    await assignment_ai.create_assignment(
        assignment_ai.AssistCreateBody(course_id=course.id, message="Bank fraud assignment."),
        _user(user_id),
        _org(org_id),
        db,
    )

    for task in ("assignment_text", "rubric"):
        assert patches.payload(task)["preferences"] == ["Prefers a more concise assignment brief."]


@pytest.mark.anyio
async def test_refine_sends_learned_preferences(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()
    patches = Patches(
        monkeypatch,
        {
            "assignment_text": {
                "reply": "Tightened the overview.",
                "changed": True,
                "document": {"overview": ["A sharper overview."]},
            }
        },
    )

    async def fake_preferences(*args: Any, **kwargs: Any) -> list[str]:
        return ["Prefers fuller detail in assignment briefs."]

    monkeypatch.setattr(assignment_ai, "artifact_preferences", fake_preferences)

    await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="Tighten the overview."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert patches.payload("assignment_text")["preferences"] == [
        "Prefers fuller detail in assignment briefs."
    ]


@pytest.mark.anyio
async def test_refine_no_op_returns_the_stored_review_without_rerunning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    existing = {
        "verdict": "pass",
        "score": 90,
        "issues": [],
        "summary": "Already reviewed.",
        "messages": [],
        "trace_url": "http://trace/old",
    }
    row = _row(db, org_id, user_id, course)
    row.document = {**_document(), "review": dict(existing)}
    await db.flush()
    patches = Patches(
        monkeypatch,
        {"assignment_text": {"reply": "No change was needed.", "document": _document()}},
    )

    result = await assignment_ai.refine_assignment(
        row.id,
        assignment_ai.AssistRefineBody(message="Leave it as it is."),
        _user(user_id),
        _org(org_id),
        db,
    )

    assert result["changed"] is False
    assert result["review"] == existing
    assert [name for name, _payload in patches.calls] == ["assignment_text"]


@pytest.mark.anyio
async def test_review_route_stores_the_council_review(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    row = _row(db, org_id, user_id, course)
    assessment = _assessment(db, org_id, user_id, course)
    await db.flush()
    row.assessment_id = assessment.id
    _add_rubric(db, org_id, assessment, _rubric())
    await db.flush()
    Patches(
        monkeypatch,
        {
            "assignment_review": {
                "verdict": "pass",
                "summary": "Looks complete.",
                "strengths": ["Clear brief."],
            }
        },
    )

    async def empty_context(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"outline": {}, "chunks": []}

    monkeypatch.setattr(assignment_ai, "course_ai_context", empty_context)

    result = await assignment_ai.review_assignment(row.id, _user(user_id), _org(org_id), db)

    assert result["review"]["summary"] == "Looks complete."
    assert result["review"]["messages"][-1]["text"].startswith("The council verdict is")
    assert row.document["review"] == result["review"]
    assert result["trace_url"] == ""


@pytest.mark.anyio
async def test_review_route_is_owner_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id, course = await _workspace(db)
    foreign = GroupAssignment(
        organization_id=uuid.uuid4(),
        owner_user_id=user_id,
        course_id=course.id,
        number="9",
        title="Foreign",
        document=_document(),
    )
    db.add(foreign)
    await db.flush()
    patches = Patches(monkeypatch, {})

    with pytest.raises(ProfassistError) as caught:
        await assignment_ai.review_assignment(foreign.id, _user(user_id), _org(org_id), db)

    assert caught.value.status == 404
    assert patches.calls == []
