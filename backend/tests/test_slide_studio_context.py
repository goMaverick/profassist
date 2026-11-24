"""Slide studio receives the official outline and every ready course chunk."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.profassist import service
from app.profassist.models import Course, SlideDeck, SubjectOutline
from app.profassist.skills import slide_studio

DOSSIER = {
    "summary": "The course covers AI solution design.",
    "provenance": [{"field": "summary", "value": "AI solution design", "filename": "syllabus.pdf"}],
}

OUTLINE_BODY = {
    "basics": {"code": "MAAI903", "name": "AI Solutions Design & MLOps"},
    "description": "Design AI solutions and the MLOps pipeline around them.",
    "clos": [
        {"code": "LO1", "text": "Design an end-to-end AI solution."},
        {"code": "LO2", "text": "Reason about the ethics of a deployment."},
    ],
    "weeks": [
        {"week": 7, "topic": "Architecture review", "lo_codes": ["LO1", "LO2"]},
    ],
    "readings": ["Lecture 6: MLOps pipelines"],
}


def _outline(org_id: uuid.UUID, user_id: uuid.UUID, course: Course) -> SubjectOutline:
    return SubjectOutline(
        id=uuid.uuid4(),
        organization_id=org_id,
        owner_user_id=user_id,
        course_id=course.id,
        code=course.code,
        name=course.title,
        status="published",
        body=dict(OUTLINE_BODY),
    )


def _chunks(org_id: uuid.UUID, course: Course, user_id: uuid.UUID) -> list[dict[str, Any]]:
    return [
        {
            "id": f"c{index}",
            "material_id": "m1",
            "text": f"Ready note passage {index}.",
            "filename": "lecture.pdf",
            "ordinal": index,
        }
        for index in range(10)
    ]


class _Empty:
    def scalars(self) -> "_Empty":
        return self

    def all(self) -> list[Any]:
        return []


class _DB:
    def __init__(self) -> None:
        self.added: list[Any] = []

    async def execute(self, statement: Any) -> _Empty:
        return _Empty()

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid.uuid4()


def test_slide_studio_graph_state_carries_the_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    chunks = [{"id": "c1", "text": "A cited passage.", "filename": "note.pdf"}]

    def fake_invoke(graph: Any, state: dict[str, Any], **kwargs: Any) -> tuple[Any, None]:
        captured.update(state)
        return {"slides": []}, None

    monkeypatch.setattr(slide_studio, "invoke_graph", fake_invoke)

    deck = slide_studio.run_slide_studio(
        ["Design an end-to-end AI solution."],
        chunks,
        outline=dict(OUTLINE_BODY),
        dossier=DOSSIER,
        preferences=["Prefers fewer bullets per slide"],
    )

    assert captured["outline"] == OUTLINE_BODY
    assert captured["chunks"] == chunks
    assert captured["objectives"] == ["Design an end-to-end AI solution."]
    assert captured["dossier"] == DOSSIER
    assert captured["preferences"] == ["Prefers fewer bullets per slide"]
    assert deck["preferences"] == ["Prefers fewer bullets per slide"]


@pytest.mark.anyio
async def test_build_cited_deck_sends_outline_and_all_ready_chunks(
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
        ai_instructions="",
    )
    outline = _outline(org_id, user_id, course)
    chunks = _chunks(org_id, course, user_id)
    calls: list[dict[str, Any]] = []

    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_course(*args: Any, **kwargs: Any) -> Course:
        return course

    async def fake_outline(*args: Any, **kwargs: Any) -> SubjectOutline:
        return outline

    async def fake_objectives(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"text": "Default approved objective.", "status": "approved"}]

    async def fake_chunks(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [dict(item) for item in chunks]

    async def fake_style(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_dossier(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return dict(DOSSIER)

    async def fake_preferences(*args: Any, **kwargs: Any) -> list[str]:
        return ["Prefers shorter bullets"]

    def fake_studio(
        objectives: list[str], payload: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        calls.append({"objectives": objectives, "chunks": payload, **kwargs})
        return {"slides": [], "gaps": [], "skill": "slide-studio", "pptx": b""}

    monkeypatch.setattr(service, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(service, "_course", fake_course)
    monkeypatch.setattr(service, "load_outline", fake_outline)
    monkeypatch.setattr(service, "list_objectives", fake_objectives)
    monkeypatch.setattr(service, "ready_chunks", fake_chunks)
    monkeypatch.setattr(service, "_style_row", fake_style)
    monkeypatch.setattr(service, "dossier_ai_context", fake_dossier)
    monkeypatch.setattr(service, "slide_preferences", fake_preferences)
    monkeypatch.setattr("app.profassist.skills.slide_studio.run_slide_studio", fake_studio)

    db = _DB()
    result = await service.build_cited_deck(db, org_id, course.id, user_id, week=7)

    assert len(calls) == 1
    call = calls[0]
    assert call["preferences"] == ["Prefers shorter bullets"]
    assert result["preferences"] == ["Prefers shorter bullets"]
    assert call["outline"]["description"] == OUTLINE_BODY["description"]
    assert call["outline"]["clos"] == OUTLINE_BODY["clos"]
    assert call["outline"]["readings"] == OUTLINE_BODY["readings"]
    assert call["outline"]["weeks"][0]["topic"] == "Architecture review"
    assert len(call["chunks"]) == len(chunks) == 10
    assert {item["id"] for item in call["chunks"]} == {item["id"] for item in chunks}
    assert call["title"] == "Week 7: Architecture review"
    assert call["dossier"] == DOSSIER
    assert call["objectives"] == [
        "Design an end-to-end AI solution.",
        "Reason about the ethics of a deployment.",
    ]
    assert any(isinstance(row, SlideDeck) for row in db.added)


@pytest.mark.anyio
async def test_draft_slides_sends_the_course_dossier(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = Course(
        id=uuid.uuid4(),
        organization_id=org_id,
        code="MAAI903",
        title="AI Solutions Design & MLOps",
        term="2026",
        clos=[],
        ai_instructions="",
    )
    calls: list[dict[str, Any]] = []
    chunk_text = "Design an end-to-end AI solution with a clear architecture."

    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_course(*args: Any, **kwargs: Any) -> Course:
        return course

    async def fake_objectives(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"text": "Design an end-to-end AI solution.", "status": "approved"}]

    async def fake_chunks(*args: Any, **kwargs: Any) -> list[Any]:
        return [SimpleNamespace(id=uuid.uuid4(), text=chunk_text)]

    async def fake_soul(*args: Any, **kwargs: Any) -> str:
        return "Short sentences."

    async def fake_dossier(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return dict(DOSSIER)

    async def fake_preferences(*args: Any, **kwargs: Any) -> list[str]:
        return ["Prefers shorter bullets"]

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append({"task": task, **payload})
        return {"title": "Deck", "slides": [{"title": "Slide", "bullets": [chunk_text]}]}

    monkeypatch.setattr(service, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(service, "_course", fake_course)
    monkeypatch.setattr(service, "list_objectives", fake_objectives)
    monkeypatch.setattr(service, "_chunks", fake_chunks)
    monkeypatch.setattr(service, "_soul", fake_soul)
    monkeypatch.setattr(service, "dossier_ai_context", fake_dossier)
    monkeypatch.setattr(service, "slide_preferences", fake_preferences)
    monkeypatch.setattr(service, "llm_complete", fake_complete)
    monkeypatch.setattr(service, "build_pptx", lambda *args, **kwargs: b"")
    monkeypatch.setattr(service, "save_bytes", lambda *args, **kwargs: "storage-key")
    monkeypatch.setattr(service, "_deck_dict", lambda row: {"id": str(row.id)})

    db = _DB()
    await service.draft_slides(db, org_id, course.id, user_id)

    assert calls[0]["task"] == "slides"
    assert calls[0]["dossier"] == DOSSIER
    assert calls[0]["preferences"] == ["Prefers shorter bullets"]


def _wire_deck(
    monkeypatch: pytest.MonkeyPatch,
    course: Any,
    outline: Any,
    objectives: Any,
    dossier: Any,
    chunks: Any,
    calls: list[dict[str, Any]],
) -> None:
    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_course(*args: Any, **kwargs: Any) -> Any:
        return course

    async def fake_outline(*args: Any, **kwargs: Any) -> Any:
        return outline

    async def fake_objectives(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return objectives

    async def fake_dossier(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return dossier

    async def fake_chunks(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [dict(item) for item in chunks]

    async def fake_style(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_preferences(*args: Any, **kwargs: Any) -> list[str]:
        return ["Prefers fewer bullets per slide"]

    def fake_studio(
        objectives: list[str], payload: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        calls.append({"objectives": objectives, "chunks": payload, **kwargs})
        return {"slides": [], "gaps": [], "skill": "slide-studio", "pptx": b""}

    monkeypatch.setattr(service, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(service, "_course", fake_course)
    monkeypatch.setattr(service, "load_outline", fake_outline)
    monkeypatch.setattr(service, "list_objectives", fake_objectives)
    monkeypatch.setattr(service, "dossier_ai_context", fake_dossier)
    monkeypatch.setattr(service, "ready_chunks", fake_chunks)
    monkeypatch.setattr(service, "_style_row", fake_style)
    monkeypatch.setattr(service, "slide_preferences", fake_preferences)
    monkeypatch.setattr("app.profassist.skills.slide_studio.run_slide_studio", fake_studio)


def _deck_course(org_id: uuid.UUID) -> Course:
    return Course(
        id=uuid.uuid4(),
        organization_id=org_id,
        code="MAAI903",
        title="AI Solutions Design & MLOps",
        term="2026",
        clos=[],
        ai_instructions="",
    )


@pytest.mark.anyio
async def test_build_cited_deck_falls_back_to_outline_clos_without_approved_objectives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = _deck_course(org_id)
    outline = _outline(org_id, user_id, course)
    chunks = _chunks(org_id, course, user_id)
    calls: list[dict[str, Any]] = []
    _wire_deck(
        monkeypatch,
        course,
        outline,
        [{"text": "Draft objective.", "status": "draft"}],
        dict(DOSSIER),
        chunks,
        calls,
    )

    db = _DB()
    await service.build_cited_deck(db, org_id, course.id, user_id)

    assert calls[0]["objectives"] == [
        "Design an end-to-end AI solution.",
        "Reason about the ethics of a deployment.",
    ]
    assert "Drafted from the official outline CLOs." in calls[0]["instructions"]
    deck = next(row for row in db.added if isinstance(row, SlideDeck))
    assert "Drafted from the official outline CLOs." in deck.instructions


@pytest.mark.anyio
async def test_build_cited_deck_falls_back_to_dossier_clos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = _deck_course(org_id)
    chunks = _chunks(org_id, course, user_id)
    calls: list[dict[str, Any]] = []
    dossier = {"outcomes": {"clos": [{"code": "LO1", "text": "From the dossier."}]}}
    _wire_deck(monkeypatch, course, None, [], dossier, chunks, calls)

    db = _DB()
    await service.build_cited_deck(db, org_id, course.id, user_id)

    assert calls[0]["objectives"] == ["From the dossier."]


@pytest.mark.anyio
async def test_build_cited_deck_still_requires_objectives_without_an_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.profassist.errors import ProfassistError

    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = _deck_course(org_id)
    calls: list[dict[str, Any]] = []
    _wire_deck(monkeypatch, course, None, [], {}, [], calls)

    db = _DB()
    with pytest.raises(ProfassistError) as caught:
        await service.build_cited_deck(db, org_id, course.id, user_id)

    assert caught.value.status == 400
    assert calls == []


@pytest.mark.anyio
async def test_build_cited_deck_returns_the_learned_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = _deck_course(org_id)
    outline = _outline(org_id, user_id, course)
    chunks = _chunks(org_id, course, user_id)
    calls: list[dict[str, Any]] = []
    _wire_deck(
        monkeypatch,
        course,
        outline,
        [{"text": "Design an end-to-end AI solution.", "status": "approved"}],
        dict(DOSSIER),
        chunks,
        calls,
    )

    db = _DB()
    result = await service.build_cited_deck(db, org_id, course.id, user_id, week=7)

    assert calls[0]["preferences"] == ["Prefers fewer bullets per slide"]
    assert result["preferences"] == ["Prefers fewer bullets per slide"]
