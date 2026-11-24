"""The outline context layer: focus instructions, attached files, and source notes."""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import app.profassist.outline as outline


class _DB:
    def __init__(self, row):
        self.row = row

    async def get(self, model, ident):
        return self.row if ident == self.row.id else None

    async def flush(self):
        return None


class _Scalars:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items

    def __iter__(self):
        return iter(self.items)


class _Result:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return _Scalars(self.items)


class _QueueDB:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, *args, **kwargs):
        return self.results.pop(0)


def _row(**overrides):
    row = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        code="MAAI 903",
        name="AI Solutions Design & MLOps",
        status="draft",
        course_id=None,
        body={"basics": {"name": "AI Solutions Design & MLOps"}},
        pdf_key="",
        docx_key="",
        instructions="",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def test_ready_chunks_returns_every_ready_chunk_and_skips_blocked_material() -> None:
    ready_one = SimpleNamespace(id=uuid.uuid4(), filename="one.pdf", status="ready")
    ready_two = SimpleNamespace(id=uuid.uuid4(), filename="two.docx", status="ready")
    blocked = SimpleNamespace(id=uuid.uuid4(), filename="three.pdf", status="processing")
    chunks = [
        SimpleNamespace(
            id=uuid.uuid4(), material_id=ready_one.id, text=f"note {index}", ordinal=index
        )
        for index in range(10)
    ]
    chunks.append(
        SimpleNamespace(id=uuid.uuid4(), material_id=blocked.id, text="blocked note", ordinal=11)
    )
    db: Any = _QueueDB(
        [
            _Result([ready_one, ready_two, blocked]),
            _Result(chunks),
        ]
    )
    result = asyncio.run(outline._ready_chunks(db, uuid.uuid4(), uuid.uuid4(), uuid.uuid4()))
    assert len(result) == 10
    assert all(item["material_id"] == str(ready_one.id) for item in result)
    assert all(item["filename"] == "one.pdf" for item in result)


def test_source_note_names_ready_notes_and_flags_blocked_files() -> None:
    sources = [
        {"id": "1", "filename": "ready.pdf", "status": "ready", "pii_quarantined": False},
        {
            "id": "2",
            "filename": "processing.pdf",
            "status": "processing",
            "pii_quarantined": False,
        },
        {
            "id": "3",
            "filename": "private.pdf",
            "status": "quarantined",
            "pii_quarantined": True,
        },
    ]
    note = outline._sources_note(sources, [{"id": "c1"}])
    assert "Ready notes used: ready.pdf" in note
    assert "Not usable yet" in note
    assert "processing.pdf (processing)" in note
    assert "private.pdf (quarantined)" in note
    assert "No ready notes are available" in outline._sources_note(sources, [])


def test_save_instructions_persists_without_a_model_call(monkeypatch) -> None:
    row = _row()
    course = SimpleNamespace(id=uuid.uuid4(), ai_instructions="")
    db: Any = _DB(row)

    async def fake_course_for(db_session, org_id, body):
        return course

    monkeypatch.setattr(outline, "_course_for", fake_course_for)

    result = asyncio.run(
        outline.save_instructions(
            db, row.organization_id, row.owner_user_id, row.id, "Focus on healthcare cases."
        )
    )
    assert row.instructions == "Focus on healthcare cases."
    assert course.ai_instructions == "Focus on healthcare cases."
    assert result["instructions"] == "Focus on healthcare cases."


def test_assist_step_sends_focus_instructions_and_all_sources(monkeypatch) -> None:
    row = _row(instructions="Focus on healthcare cases.")
    course = SimpleNamespace(id=uuid.uuid4(), code="MAAI 903", ai_instructions="")
    sources = [
        {"id": "m1", "filename": "lecture.pdf", "status": "ready", "pii_quarantined": False},
        {"id": "m2", "filename": "notes.docx", "status": "ready", "pii_quarantined": False},
        {"id": "m3", "filename": "draft.pdf", "status": "processing", "pii_quarantined": False},
    ]
    chunks = [{"id": "c1", "material_id": "m1", "text": "lecture note", "filename": "lecture.pdf"}]
    captured: dict = {}

    async def fake_get_outline(*args):
        return row

    async def fake_load_runtime(*args):
        return None

    async def fake_course_for(db_session, org_id, body):
        return course

    async def fake_sources(*args):
        return sources

    async def fake_chunks(*args):
        return chunks

    async def fake_save_step(*args, **kwargs):
        return None

    def fake_complete(task, payload):
        captured.update(payload)
        return {"reply": "ok", "suggestion": {}}

    monkeypatch.setattr(outline, "get_outline", fake_get_outline)
    monkeypatch.setattr(outline, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(outline, "_course_for", fake_course_for)
    monkeypatch.setattr(outline, "_source_materials", fake_sources)
    monkeypatch.setattr(outline, "_ready_chunks", fake_chunks)

    async def fake_dossier(*args, **kwargs):
        return {}

    async def fake_preferences(*args, **kwargs):
        return []

    monkeypatch.setattr(outline, "dossier_ai_context", fake_dossier)
    monkeypatch.setattr(outline, "artifact_preferences", fake_preferences)
    monkeypatch.setattr(outline, "save_step", fake_save_step)
    monkeypatch.setattr("app.profassist.llm.complete", fake_complete)

    db: Any = _DB(row)
    result = asyncio.run(
        outline.assist_step(
            db, row.organization_id, row.owner_user_id, row.id, "lecture", "Draft it."
        )
    )

    assert captured["instructions"] == "Focus on healthcare cases."
    assert [item["filename"] for item in captured["sources"]] == [
        "lecture.pdf",
        "notes.docx",
        "draft.pdf",
    ]
    assert len(captured["chunks"]) == 1
    assert "Not usable yet" in captured["sources_note"]
    assert row.body["source_materials"] == sources
    assert result["outline"]["source_materials"] == sources


def test_assist_step_says_when_no_ready_notes_exist(monkeypatch) -> None:
    row = _row(instructions="Focus on ethics.")
    course = SimpleNamespace(id=uuid.uuid4(), code="MAAI 903", ai_instructions="")
    sources = [
        {"id": "m1", "filename": "draft.pdf", "status": "processing", "pii_quarantined": False}
    ]
    captured: dict = {}

    async def fake_get_outline(*args):
        return row

    async def fake_load_runtime(*args):
        return None

    async def fake_course_for(db_session, org_id, body):
        return course

    async def fake_sources(*args):
        return sources

    async def fake_chunks(*args):
        return []

    def fake_complete(task, payload):
        captured.update(payload)
        return {"reply": "No ready notes are available.", "suggestion": {}}

    monkeypatch.setattr(outline, "get_outline", fake_get_outline)
    monkeypatch.setattr(outline, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(outline, "_course_for", fake_course_for)
    monkeypatch.setattr(outline, "_source_materials", fake_sources)
    monkeypatch.setattr(outline, "_ready_chunks", fake_chunks)

    async def fake_dossier(*args, **kwargs):
        return {}

    async def fake_preferences(*args, **kwargs):
        return []

    monkeypatch.setattr(outline, "dossier_ai_context", fake_dossier)
    monkeypatch.setattr(outline, "artifact_preferences", fake_preferences)
    monkeypatch.setattr("app.profassist.llm.complete", fake_complete)

    db: Any = _DB(row)
    result = asyncio.run(
        outline.assist_step(
            db, row.organization_id, row.owner_user_id, row.id, "lecture", "Draft it."
        )
    )
    assert captured["chunks"] == []
    assert "No ready notes are available" in captured["sources_note"]
    assert "No ready notes are available" in result["reply"]


def test_outline_materials_returns_status_and_refreshes_body(monkeypatch) -> None:
    row = _row(course_id=uuid.uuid4())
    items = [
        {
            "id": "m1",
            "filename": "ready.pdf",
            "status": "ready",
            "pii_report": {"quarantined": False},
        },
        {
            "id": "m2",
            "filename": "private.pdf",
            "status": "quarantined",
            "pii_report": {"quarantined": True},
        },
    ]

    async def fake_list_materials(*args):
        return items

    monkeypatch.setattr("app.profassist.service.list_materials", fake_list_materials)

    db: Any = _DB(row)
    result = asyncio.run(
        outline.outline_materials(db, row.organization_id, row.owner_user_id, row.id)
    )
    assert [item["status"] for item in result] == ["ready", "quarantined"]
    assert row.body["source_materials"][0]["pii_quarantined"] is False
    assert row.body["source_materials"][1]["pii_quarantined"] is True


def test_attach_file_updates_source_materials(monkeypatch) -> None:
    row = _row()
    course = SimpleNamespace(id=uuid.uuid4())
    items = [
        {
            "id": "m1",
            "filename": "lecture.pdf",
            "status": "ready",
            "pii_report": {"quarantined": False},
        }
    ]

    async def fake_course_for(db_session, org_id, body):
        return course

    async def fake_add_material(*args):
        return items[0]

    async def fake_list_materials(*args):
        return items

    monkeypatch.setattr(outline, "_course_for", fake_course_for)
    monkeypatch.setattr("app.profassist.service.add_material", fake_add_material)
    monkeypatch.setattr("app.profassist.service.list_materials", fake_list_materials)

    db: Any = _DB(row)
    result = asyncio.run(
        outline.attach_file(
            db, row.organization_id, row.owner_user_id, row.id, "lecture.pdf", b"data"
        )
    )
    assert result["source_materials"] == [
        {"id": "m1", "filename": "lecture.pdf", "status": "ready", "pii_quarantined": False}
    ]
    assert row.body["source_materials"] == result["source_materials"]


def test_remove_outline_material_refreshes_source_materials(monkeypatch) -> None:
    row = _row(course_id=uuid.uuid4())

    async def fake_delete(*args):
        return {"deleted": True}

    async def fake_list_materials(*args):
        return []

    monkeypatch.setattr("app.profassist.service.delete_material", fake_delete)
    monkeypatch.setattr("app.profassist.service.list_materials", fake_list_materials)

    db: Any = _DB(row)
    result = asyncio.run(
        outline.remove_outline_material(
            db,
            row.organization_id,
            row.owner_user_id,
            row.id,
            uuid.uuid4(),
        )
    )
    assert result["source_materials"] == []
    assert row.body["source_materials"] == []


def test_public_payload_lists_two_source_materials_with_statuses() -> None:
    row = _row(
        body={
            "basics": {"name": "AI Solutions Design & MLOps"},
            "source_materials": [
                {
                    "id": "m1",
                    "filename": "lecture.pdf",
                    "status": "ready",
                    "pii_quarantined": False,
                },
                {
                    "id": "m2",
                    "filename": "notes.docx",
                    "status": "processing",
                    "pii_quarantined": False,
                },
            ],
        }
    )
    public = outline._public(row)
    assert len(public["source_materials"]) == 2
    assert [item["status"] for item in public["source_materials"]] == [
        "ready",
        "processing",
    ]
    assert public["sources"] == ["lecture.pdf", "notes.docx"]
