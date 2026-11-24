"""The shared course context: official outline plus bounded ready-note chunks."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.profassist import course_context
from app.profassist.models import Chunk, Course, Material, SubjectOutline


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
    """Consumes queued query results; `get` only knows the course."""

    def __init__(self, results: list[list[Any]], course: Course | None = None) -> None:
        self.results = list(results)
        self.course = course

    async def execute(self, statement: Any) -> _Result:
        return _Result(self.results.pop(0))

    async def get(self, model: Any, ident: uuid.UUID) -> Any | None:
        if self.course is not None and model is Course and ident == self.course.id:
            return self.course
        return None


def _course(org_id: uuid.UUID, code: str = "MAAI903") -> Course:
    return Course(
        id=uuid.uuid4(),
        organization_id=org_id,
        code=code,
        title="AI Solutions Design & MLOps",
        term="2026",
        clos=[],
    )


def _outline(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    code: str = "MAAI903",
    course_id: uuid.UUID | None = None,
    status: str = "draft",
    updated: datetime | None = None,
    name: str = "AI Solutions Design & MLOps",
) -> SubjectOutline:
    body = {
        "basics": {"code": code, "name": name, "session": "Autumn", "year": "2026"},
        "lecture": {"educator_name": "Dr Patrick Mukala", "email": "patrick@example.edu"},
        "description": "Design AI solutions and the MLOps pipeline around them.",
        "program": "Master of Artificial Intelligence",
        "plos": [{"code": "PLO1", "text": "Design solutions."}],
        "clos": [
            {"code": "LO1", "text": "Design an end-to-end AI solution."},
            {"code": "LO2", "text": "Reason about the ethics of a deployment."},
        ],
        "weeks": [
            {
                "week": 1,
                "topic": "Architecture foundations",
                "lo_codes": ["LO1"],
                "session_type": "lecture",
                "delivery": "on campus",
                "assessment_note": "",
            },
            {
                "week": 7,
                "topic": "Architecture review",
                "lo_codes": ["LO1", "LO2"],
                "session_type": "workshop",
                "delivery": "on campus",
                "assessment_note": "A2 due",
            },
        ],
        "readings": ["Lecture 1: AI solution design", "Lecture 6: MLOps pipelines"],
        "outcome_measures": [
            {"lo_code": "LO1", "measures": "Assessment 2 architecture report"},
        ],
        "policies": [{"key": "late", "title": "Late submission", "body": "Ten percent a day."}],
        # An outline body must never carry student rows; the trim drops unknown keys.
        "students": [{"name": "Sara Al Maktoum", "student_number": "8881001"}],
    }
    return SubjectOutline(
        id=uuid.uuid4(),
        organization_id=org_id,
        owner_user_id=user_id,
        course_id=course_id,
        code=code,
        name=name,
        status=status,
        body=body,
        updated_at=updated or datetime(2026, 1, 1, tzinfo=UTC),
    )


def _material(
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    filename: str,
    status: str = "ready",
) -> Material:
    return Material(
        id=uuid.uuid4(),
        organization_id=org_id,
        course_id=course_id,
        owner_user_id=user_id,
        filename=filename,
        text_content="",
        scrubbed_text="",
        status=status,
        pii_report={},
        storage_key="",
    )


def _chunk(
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    material: Material,
    *,
    ordinal: int,
    text: str,
) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        organization_id=org_id,
        course_id=course_id,
        material_id=material.id,
        owner_user_id=user_id,
        ordinal=ordinal,
        text=text,
    )


@pytest.mark.anyio
async def test_latest_published_outline_is_trimmed_and_has_no_student_data() -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = _course(org_id)
    newer_draft = _outline(
        org_id,
        user_id,
        status="draft",
        updated=datetime(2026, 3, 1, tzinfo=UTC),
        name="Newer draft",
    )
    published = _outline(
        org_id,
        user_id,
        status="published",
        updated=datetime(2026, 1, 1, tzinfo=UTC),
        name="Published outline",
    )
    db = _DB([[newer_draft, published], [], []], course=course)

    row = await course_context.load_outline(db, org_id, user_id, course.id)
    assert row is published

    outline = course_context.trim_outline(row)
    assert outline["name"] == "Published outline"
    assert outline["clos"][0] == {"code": "LO1", "text": "Design an end-to-end AI solution."}
    assert outline["weeks"][1]["topic"] == "Architecture review"
    assert outline["readings"] == [
        "Lecture 1: AI solution design",
        "Lecture 6: MLOps pipelines",
    ]
    assert outline["outcome_measures"][0]["lo_code"] == "LO1"
    assert outline["policies"][0]["title"] == "Late submission"
    assert set(outline) == {
        "code",
        "name",
        "status",
        "basics",
        "lecture",
        "description",
        "program",
        "plos",
        "clos",
        "weeks",
        "readings",
        "outcome_measures",
        "policies",
    }
    assert "students" not in outline
    assert "Sara" not in str(outline)


@pytest.mark.anyio
async def test_outline_matches_a_course_code_when_course_id_is_empty() -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = _course(org_id, code="MAAI903")
    outline = _outline(org_id, user_id, code="MAAI 903", course_id=None)
    db = _DB([[outline], [], []], course=course)

    row = await course_context.load_outline(db, org_id, user_id, course.id)
    assert row is outline


@pytest.mark.anyio
async def test_no_outline_and_no_ready_material_returns_empty_context() -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = _course(org_id)
    db = _DB([[], [], []], course=course)

    context = await course_context.course_ai_context(db, org_id, user_id, course.id)
    assert context == {"outline": {}, "chunks": [], "dossier": {}}


@pytest.mark.anyio
async def test_ready_chunks_skip_processing_material_and_are_capped() -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = _course(org_id)
    ready = _material(org_id, course.id, user_id, filename="lecture.pdf")
    processing = _material(org_id, course.id, user_id, filename="upload.pdf", status="processing")
    chunks = [
        _chunk(org_id, course.id, user_id, ready, ordinal=index, text=f"{index}:" + "x" * 2000)
        for index in range(12)
    ]
    chunks.append(_chunk(org_id, course.id, user_id, processing, ordinal=99, text="blocked note"))
    db = _DB([[], [ready, processing], chunks, []], course=course)

    context = await course_context.course_ai_context(db, org_id, user_id, course.id)
    picked = context["chunks"]
    assert context["outline"] == {}
    assert context["dossier"] == {}
    assert 0 < len(picked) <= 8
    assert all(len(item["text"]) <= 1200 for item in picked)
    assert sum(len(item["text"]) for item in picked) <= 6000
    assert all(item["text"] != "blocked note" for item in picked)
    assert all(item["filename"] == "lecture.pdf" for item in picked)
    assert all(item["id"] for item in picked)


def test_chunk_caps_are_eight_rows_1200_chars_and_6000_total() -> None:
    wide = [{"id": f"c{index}", "text": "x" * 2000, "filename": "note.pdf"} for index in range(12)]
    capped = course_context.cap_chunks(wide)
    assert len(capped) <= 8
    assert max(len(item["text"]) for item in capped) <= 1200
    assert sum(len(item["text"]) for item in capped) <= 6000

    # 8 x 1200 would be 9600, so the total budget binds before the row cap.
    assert len(capped) == 5
    assert sum(len(item["text"]) for item in capped) == 6000

    narrow = [{"id": f"c{index}", "text": "y" * 500, "filename": "note.pdf"} for index in range(12)]
    assert len(course_context.cap_chunks(narrow)) == 8


def test_a_query_ranks_the_matching_chunk_first() -> None:
    chunks = [
        {"id": "mlops", "text": "The MLOps pipeline monitors drift in production."},
        {"id": "telescope", "text": "The campus telescope tracks the night sky."},
    ]
    ranked = course_context.rank_chunks(chunks, "telescope night sky")
    assert ranked[0]["id"] == "telescope"
