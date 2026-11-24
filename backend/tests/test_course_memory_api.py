"""Course-memory endpoints and the upload hook that keeps the dossier current."""

import io
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import BackgroundTasks, UploadFile

import app.api.routes.v1.profassist as routes
import app.worker.tasks.profassist_tasks as tasks
from app.profassist import slide_memory
from app.profassist.errors import ProfassistError
from app.profassist.models import Course, ProfessorMemory
from tests.test_profassist_rubric import FakeSession


def _user(user_id: uuid.UUID | None = None) -> Any:
    return SimpleNamespace(id=user_id or uuid.uuid4())


def _org(org_id: uuid.UUID | None = None) -> Any:
    return SimpleNamespace(id=org_id or uuid.uuid4())


@pytest.mark.anyio
async def test_memory_view_returns_the_dossier_and_materials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": "m1"}]

    async def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"summary": "The course memory."}

    monkeypatch.setattr(routes, "list_materials", fake_list)
    monkeypatch.setattr(routes, "load_dossier", fake_load)

    result = await routes.course_memory(uuid.uuid4(), _user(), _org(), FakeSession())

    assert result == {
        "dossier": {"summary": "The course memory."},
        "materials": [{"id": "m1"}],
        "slide_preferences": [],
        "artifact_preferences": [],
    }


@pytest.mark.anyio
async def test_memory_view_returns_the_signed_in_users_slide_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, user, other_user, other_org = _org(), _user(), _user(), _org()
    course = Course(organization_id=org.id, code="MAAI903", title="AI Studio")
    db = FakeSession()
    db.add(course)
    db.add(
        ProfessorMemory(
            organization_id=org.id,
            owner_user_id=user.id,
            kind="slides",
            text="Prefers shorter bullets",
        )
    )
    db.add(
        ProfessorMemory(
            organization_id=org.id,
            owner_user_id=other_user.id,
            kind="slides",
            text="Prefers 40pt titles",
        )
    )
    db.add(
        ProfessorMemory(
            organization_id=other_org.id,
            owner_user_id=user.id,
            kind="slides",
            text="Prefers full-bleed images",
        )
    )
    await db.flush()

    async def fake_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"summary": "The course memory."}

    monkeypatch.setattr(routes, "list_materials", fake_list)
    monkeypatch.setattr(routes, "load_dossier", fake_load)

    result = await routes.course_memory(course.id, user, org, db)

    assert result["dossier"] == {"summary": "The course memory."}
    assert result["materials"] == []
    assert result["slide_preferences"] == ["Prefers shorter bullets"]


@pytest.mark.anyio
async def test_memory_view_does_not_leak_another_users_slide_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, user, other_user = _org(), _user(), _user()
    course = Course(organization_id=org.id, code="MAAI903", title="AI Studio")
    db = FakeSession()
    db.add(course)
    db.add(
        ProfessorMemory(
            organization_id=org.id,
            owner_user_id=other_user.id,
            kind="slides",
            text="Prefers 40pt titles",
        )
    )
    await db.flush()

    async def fake_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return None

    monkeypatch.setattr(routes, "list_materials", fake_list)
    monkeypatch.setattr(routes, "load_dossier", fake_load)

    result = await routes.course_memory(course.id, user, org, db)

    assert result["slide_preferences"] == []


@pytest.mark.anyio
async def test_memory_view_returns_empty_slide_preferences_when_none_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, user = _org(), _user()
    course = Course(organization_id=org.id, code="MAAI903", title="AI Studio")
    db = FakeSession()
    db.add(course)
    await db.flush()

    async def fake_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return None

    monkeypatch.setattr(routes, "list_materials", fake_list)
    monkeypatch.setattr(routes, "load_dossier", fake_load)

    result = await routes.course_memory(course.id, user, org, db)

    assert result["slide_preferences"] == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "expected"),
    [("MAAI903", "MAAI903 slides"), ("", "slides")],
)
async def test_memory_view_queries_slide_memory_with_the_course_code(
    monkeypatch: pytest.MonkeyPatch, code: str, expected: str
) -> None:
    captured: dict[str, Any] = {}

    async def fake_preferences(
        db: Any, org_id: Any, user_id: Any, query: str, limit: int = 5
    ) -> list[str]:
        captured.update({"org_id": org_id, "user_id": user_id, "query": query, "limit": limit})
        return ["Prefers shorter bullets"]

    async def fake_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return None

    monkeypatch.setattr(slide_memory, "slide_preferences", fake_preferences)
    monkeypatch.setattr(routes, "list_materials", fake_list)
    monkeypatch.setattr(routes, "load_dossier", fake_load)

    org, user = _org(), _user()
    course = Course(organization_id=org.id, code=code, title="AI Studio")
    db = FakeSession()
    db.add(course)
    await db.flush()

    result = await routes.course_memory(course.id, user, org, db)

    assert result["slide_preferences"] == ["Prefers shorter bullets"]
    assert captured == {
        "org_id": org.id,
        "user_id": user.id,
        "query": expected,
        "limit": 5,
    }


@pytest.mark.anyio
async def test_memory_view_hides_a_foreign_course(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = False

    async def fake_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise ProfassistError(404, "That course is not in this workspace.")

    async def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal loaded
        loaded = True
        return {}

    monkeypatch.setattr(routes, "list_materials", fake_list)
    monkeypatch.setattr(routes, "load_dossier", fake_load)

    with pytest.raises(ProfassistError) as caught:
        await routes.course_memory(uuid.uuid4(), _user(), _org(), object())

    assert caught.value.status == 404
    assert loaded is False


@pytest.mark.anyio
async def test_rebuild_returns_status_trace_and_materials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []

    async def fake_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fake_rebuild(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(args)
        return {
            "dossier": {"status": "ready"},
            "trace_url": "https://trace",
            "materials": [{"material_id": "m1", "insight_status": "ready"}],
        }

    monkeypatch.setattr(routes, "list_materials", fake_list)
    monkeypatch.setattr(routes, "rebuild_course_memory", fake_rebuild)

    result = await routes.course_memory_rebuild(uuid.uuid4(), _user(), _org(), object())

    assert result == {
        "status": "ready",
        "trace_url": "https://trace",
        "materials": [{"material_id": "m1", "insight_status": "ready"}],
    }
    assert len(calls) == 1


@pytest.mark.anyio
async def test_rebuild_hides_a_foreign_course(monkeypatch: pytest.MonkeyPatch) -> None:
    rebuilt = False

    async def fake_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise ProfassistError(404, "That course is not in this workspace.")

    async def fake_rebuild(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal rebuilt
        rebuilt = True
        return {}

    monkeypatch.setattr(routes, "list_materials", fake_list)
    monkeypatch.setattr(routes, "rebuild_course_memory", fake_rebuild)

    with pytest.raises(ProfassistError) as caught:
        await routes.course_memory_rebuild(uuid.uuid4(), _user(), _org(), object())

    assert caught.value.status == 404
    assert rebuilt is False


@pytest.mark.anyio
async def test_extract_rebuilds_one_material(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_rebuild(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"material": {"material_id": "m1", "insight_status": "ready"}}

    monkeypatch.setattr(routes, "rebuild_material", fake_rebuild)

    result = await routes.material_extract(uuid.uuid4(), _user(), _org(), object())

    assert result == {"material": {"material_id": "m1", "insight_status": "ready"}}


@pytest.mark.anyio
async def test_extract_hides_a_foreign_material(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_rebuild(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ProfassistError(404, "That file is not in this course.")

    monkeypatch.setattr(routes, "rebuild_material", fake_rebuild)

    with pytest.raises(ProfassistError) as caught:
        await routes.material_extract(uuid.uuid4(), _user(), _org(), object())

    assert caught.value.status == 404


@pytest.mark.anyio
async def test_upload_schedules_the_course_memory_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[tuple[Any, ...]] = []

    async def fake_flow(*args: Any, **kwargs: Any) -> dict[str, Any]:
        scheduled.append(args)
        return {"ok": True}

    async def fake_add(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"status": "ready", "pii_report": {"quarantined": False}}

    monkeypatch.setattr(tasks, "course_memory_flow", fake_flow)
    monkeypatch.setattr(routes, "add_material", fake_add)

    org, user = _org(), _user()
    course_id = uuid.uuid4()
    background = BackgroundTasks()
    upload = UploadFile(file=io.BytesIO(b"hello"), filename="notes.txt")

    result = await routes.upload_material(course_id, user, org, object(), background, upload)

    assert result["status"] == "ready"
    assert len(background.tasks) == 1
    task = background.tasks[0]
    assert task.func is fake_flow
    assert task.args == (str(org.id), str(course_id), str(user.id))
    assert scheduled == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "material",
    [
        {"status": "processing", "pii_report": {"quarantined": False}},
        {"status": "ready", "pii_report": {"quarantined": True}},
    ],
)
async def test_upload_does_not_schedule_an_unready_file(
    monkeypatch: pytest.MonkeyPatch, material: dict[str, Any]
) -> None:
    async def fake_add(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return dict(material)

    monkeypatch.setattr(routes, "add_material", fake_add)

    background = BackgroundTasks()
    upload = UploadFile(file=io.BytesIO(b"hello"), filename="notes.txt")

    await routes.upload_material(uuid.uuid4(), _user(), _org(), object(), background, upload)

    assert background.tasks == []


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _DB:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.flushed = False

    async def execute(self, statement: Any) -> _Result:
        return _Result(self.rows)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.anyio
async def test_course_memory_flow_marks_materials_failed_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = SimpleNamespace(insight_status="pending")
    db = _DB([material])

    @asynccontextmanager
    async def fake_db():
        yield db

    async def boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("model down")

    monkeypatch.setattr(tasks, "get_db_context", fake_db)
    monkeypatch.setattr(tasks, "rebuild_course_memory", boom)

    result = await tasks.course_memory_flow.fn(
        str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    )

    assert result["ok"] is False
    assert "model down" in result["error"]
    assert material.insight_status == "failed"
    assert db.flushed is True


@pytest.mark.anyio
async def test_memory_view_returns_artifact_preferences_without_leaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, user, other_user = _org(), _user(), _user()
    course = Course(organization_id=org.id, code="MAAI903", title="AI Studio")
    db = FakeSession()
    db.add(course)
    db.add(
        ProfessorMemory(
            organization_id=org.id,
            owner_user_id=user.id,
            kind="slides",
            text="Prefers shorter bullets",
        )
    )
    db.add(
        ProfessorMemory(
            organization_id=org.id,
            owner_user_id=user.id,
            kind="objective",
            text="Prefers a more concise outline.",
        )
    )
    db.add(
        ProfessorMemory(
            organization_id=org.id,
            owner_user_id=other_user.id,
            kind="objective",
            text="Prefers fuller detail in outlines.",
        )
    )
    await db.flush()

    async def fake_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fake_load(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return None

    monkeypatch.setattr(routes, "list_materials", fake_list)
    monkeypatch.setattr(routes, "load_dossier", fake_load)

    result = await routes.course_memory(course.id, user, org, db)

    assert result["slide_preferences"] == ["Prefers shorter bullets"]
    assert set(result["artifact_preferences"]) == {
        "Prefers shorter bullets",
        "Prefers a more concise outline.",
    }
    assert "Prefers fuller detail in outlines." not in result["artifact_preferences"]
