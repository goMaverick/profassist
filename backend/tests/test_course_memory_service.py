"""Course-memory persistence: idempotent rebuilds, stale dossiers, bounded context.

Every test uses a fake session and a fake model. No database, no network.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.profassist import llm, observe
from app.profassist.course_memory import graph, service
from app.profassist.course_memory.cleaners import content_hash
from app.profassist.course_memory.schemas import MergedDossier
from app.profassist.errors import ProfassistError
from app.profassist.models import Chunk, CourseDossier, Material


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _Nested:
    """Minimal savepoint stand-in: tracks depth and propagates errors."""

    def __init__(self, db: _DB) -> None:
        self._db = db

    async def __aenter__(self) -> _DB:
        self._db.nested_depth += 1
        return self._db

    async def __aexit__(self, *exc: object) -> bool:
        self._db.nested_depth -= 1
        return False


class _DB:
    """Serves queued rows by table name. Records ``add`` and ``flush``."""

    def __init__(
        self,
        materials: list[Material],
        chunks: list[Chunk],
        dossiers: list[CourseDossier],
    ) -> None:
        self.materials = list(materials)
        self.chunks = list(chunks)
        self.dossiers = list(dossiers)
        self.added: list[Any] = []
        self.flushes = 0
        self.nested_depth = 0

    def begin_nested(self) -> _Nested:
        return _Nested(self)

    async def execute(self, statement: Any) -> _Result:
        text = str(statement)
        if "pa_chunks" in text:
            return _Result(self.chunks)
        if "pa_materials" in text:
            return _Result(self.materials)
        if "pa_course_dossiers" in text:
            return _Result(self.dossiers)
        return _Result([])

    async def get(self, model: Any, ident: uuid.UUID) -> Any | None:
        if model is Material:
            for row in self.materials:
                if row.id == ident:
                    return row
        return None

    def add(self, row: Any) -> None:
        self.added.append(row)
        if isinstance(row, CourseDossier):
            self.dossiers.append(row)

    async def flush(self) -> None:
        self.flushes += 1


class _ConflictDB(_DB):
    """Simulates a concurrent rebuild that inserts the dossier first."""

    def __init__(
        self,
        materials: list[Material],
        chunks: list[Chunk],
        winner: CourseDossier,
    ) -> None:
        super().__init__(materials, chunks, [])
        self.winner = winner
        self.conflicted = False

    async def flush(self) -> None:
        self.flushes += 1
        if self.nested_depth and not self.conflicted:
            self.conflicted = True
            # The nested insert loses; the other transaction's row is visible.
            self.added = [row for row in self.added if not isinstance(row, CourseDossier)]
            self.dossiers = [self.winner]
            raise IntegrityError("uq_pa_dossier_owner", None, Exception("duplicate key"))


def _material(
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    *,
    scrubbed: str = "Week 1 Foundations",
    status: str = "ready",
    pii_report: dict[str, Any] | None = None,
) -> Material:
    return Material(
        id=uuid.uuid4(),
        organization_id=org_id,
        course_id=course_id,
        owner_user_id=user_id,
        filename=filename,
        text_content="",
        scrubbed_text=scrubbed,
        status=status,
        pii_report=pii_report or {},
        storage_key="",
        insight={},
        insight_status="pending",
        trace_url="",
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


def _dossier(
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    body: dict[str, Any] | None = None,
    status: str = "ready",
    version: int = 1,
) -> CourseDossier:
    return CourseDossier(
        id=uuid.uuid4(),
        organization_id=org_id,
        course_id=course_id,
        owner_user_id=user_id,
        version=version,
        body=body or MergedDossier().model_dump(),
        status=status,
        trace_url="",
        history=[],
    )


async def _no_outline_row(*_args: Any) -> None:
    return None


def _install_llm(monkeypatch, *, extract=None, merge=None) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append({"task": task, "payload": payload})
        if task == "dossier_extract":
            value = extract(payload) if callable(extract) else extract
        else:
            if isinstance(merge, Exception):
                raise merge
            value = merge(payload) if callable(merge) else merge
        return value if value is not None else {}

    monkeypatch.setattr(llm, "complete", fake_complete)
    return calls


def _extract(topic: str = "Foundations") -> dict[str, Any]:
    return {
        "document_kind": "syllabus",
        "summary": "A course document.",
        "topics": [{"name": topic, "week": 1}],
        "claims": [{"field": "topics", "chunk_ordinal": 0, "quote": topic}],
    }


def _disable_langfuse(monkeypatch) -> None:
    monkeypatch.setattr(observe, "_client", lambda: None)


@pytest.mark.anyio
async def test_inputs_skip_processing_and_quarantined_materials(monkeypatch) -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ready = _material(org_id, course_id, user_id, "ready.pdf")
    processing = _material(org_id, course_id, user_id, "processing.pdf", status="processing")
    quarantined = _material(
        org_id,
        course_id,
        user_id,
        "quarantined.pdf",
        pii_report={"quarantined": True},
    )
    chunk = _chunk(org_id, course_id, user_id, ready, ordinal=0, text="Week 1 Foundations")
    db = _DB([ready, processing, quarantined], [chunk], [])
    monkeypatch.setattr(service, "_load_outline_row", _no_outline_row)

    inputs = await service.load_memory_inputs(db, org_id, user_id, course_id)

    assert [item["filename"] for item in inputs["materials"]] == ["ready.pdf"]
    assert inputs["materials"][0]["chunks"] == [{"ordinal": 0, "text": "Week 1 Foundations"}]


@pytest.mark.anyio
async def test_rebuild_persists_material_insight_and_dossier(monkeypatch) -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    material = _material(org_id, course_id, user_id, "syllabus.pdf")
    chunk = _chunk(org_id, course_id, user_id, material, ordinal=0, text="Week 1 Foundations")
    db = _DB([material], [chunk], [])
    monkeypatch.setattr(service, "_load_outline_row", _no_outline_row)
    _disable_langfuse(monkeypatch)
    _install_llm(monkeypatch, extract=_extract(), merge={})

    result = await service.rebuild_course_memory(db, org_id, user_id, course_id)

    assert material.insight_status == "ready"
    assert material.insight["content_hash"] == content_hash(material.scrubbed_text)
    assert material.insight["topics"][0]["name"] == "Foundations"
    assert len(db.dossiers) == 1
    dossier = db.dossiers[0]
    assert dossier.version == 1
    assert dossier.status == "ready"
    assert result["dossier"]["version"] == 1
    assert result["materials"][0]["insight_status"] == "ready"
    assert db.flushes >= 1


@pytest.mark.anyio
async def test_unchanged_hash_skips_extraction_and_keeps_the_version(monkeypatch) -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    material = _material(org_id, course_id, user_id, "syllabus.pdf")
    chunk = _chunk(org_id, course_id, user_id, material, ordinal=0, text="Week 1 Foundations")
    db = _DB([material], [chunk], [])
    monkeypatch.setattr(service, "_load_outline_row", _no_outline_row)
    _disable_langfuse(monkeypatch)
    calls = _install_llm(monkeypatch, extract=_extract(), merge={})

    await service.rebuild_course_memory(db, org_id, user_id, course_id)
    first_extracts = len([call for call in calls if call["task"] == "dossier_extract"])
    await service.rebuild_course_memory(db, org_id, user_id, course_id)
    second_extracts = len([call for call in calls if call["task"] == "dossier_extract"])

    assert first_extracts == 1
    assert second_extracts == 1
    assert db.dossiers[0].version == 1
    assert material.insight_status == "ready"


@pytest.mark.anyio
async def test_forced_rebuild_runs_again_and_increments_the_version(monkeypatch) -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    material = _material(org_id, course_id, user_id, "syllabus.pdf")
    chunk = _chunk(org_id, course_id, user_id, material, ordinal=0, text="Week 1 Foundations")
    db = _DB([material], [chunk], [])
    monkeypatch.setattr(service, "_load_outline_row", _no_outline_row)
    _disable_langfuse(monkeypatch)
    calls = _install_llm(monkeypatch, extract=_extract(), merge={})

    await service.rebuild_course_memory(db, org_id, user_id, course_id)
    result = await service.rebuild_course_memory(db, org_id, user_id, course_id, force=True)

    extracts = [call for call in calls if call["task"] == "dossier_extract"]
    dossier = db.dossiers[0]
    assert len(extracts) == 2
    assert dossier.version == 2
    assert result["dossier"]["version"] == 2
    assert len(dossier.history) == 1
    assert dossier.history[0]["version"] == 1


@pytest.mark.anyio
async def test_forced_rebuild_stamps_the_body_version_to_match_the_row(monkeypatch) -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    material = _material(org_id, course_id, user_id, "syllabus.pdf")
    chunk = _chunk(org_id, course_id, user_id, material, ordinal=0, text="Week 1 Foundations")
    db = _DB([material], [chunk], [])
    monkeypatch.setattr(service, "_load_outline_row", _no_outline_row)
    _disable_langfuse(monkeypatch)
    _install_llm(monkeypatch, extract=_extract(), merge={})

    first = await service.rebuild_course_memory(db, org_id, user_id, course_id)
    dossier = db.dossiers[0]
    assert dossier.version == 1
    assert dossier.body["version"] == 1
    assert first["dossier"]["body"]["version"] == 1

    second = await service.rebuild_course_memory(db, org_id, user_id, course_id, force=True)
    assert dossier.version == 2
    assert dossier.body["version"] == 2
    assert second["dossier"]["body"]["version"] == 2

    loaded = await service.load_dossier(db, org_id, user_id, course_id)
    assert loaded is not None
    assert loaded["version"] == dossier.version


@pytest.mark.anyio
async def test_rebuild_returns_the_trace_url_from_invoke_graph(monkeypatch) -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    material = _material(org_id, course_id, user_id, "syllabus.pdf")
    chunk = _chunk(org_id, course_id, user_id, material, ordinal=0, text="Week 1 Foundations")
    db = _DB([material], [chunk], [])
    monkeypatch.setattr(service, "_load_outline_row", _no_outline_row)

    def fake_invoke(
        compiled: Any,
        state: dict[str, Any],
        *,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        return {"merged": MergedDossier().model_dump(), "dossiers": [], "errors": []}, (
            "http://trace"
        )

    monkeypatch.setattr(graph, "invoke_graph", fake_invoke)

    result = await service.rebuild_course_memory(db, org_id, user_id, course_id)

    assert result["trace_url"] == "http://trace"
    assert db.dossiers[0].trace_url == "http://trace"


@pytest.mark.anyio
async def test_concurrent_rebuild_updates_the_winning_dossier(monkeypatch) -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    material = _material(org_id, course_id, user_id, "syllabus.pdf")
    chunk = _chunk(org_id, course_id, user_id, material, ordinal=0, text="Week 1 Foundations")
    winner = _dossier(org_id, course_id, user_id, version=1)
    db = _ConflictDB([material], [chunk], winner)
    monkeypatch.setattr(service, "_load_outline_row", _no_outline_row)
    _disable_langfuse(monkeypatch)
    _install_llm(monkeypatch, extract=_extract(), merge={})

    result = await service.rebuild_course_memory(db, org_id, user_id, course_id)

    assert db.conflicted is True
    assert db.dossiers == [winner]
    assert winner.version == 2
    assert winner.status == "ready"
    assert [item["version"] for item in winner.history] == [1]
    assert result["dossier"]["version"] == 2


@pytest.mark.anyio
async def test_rebuild_material_marks_the_course_dossier_stale(monkeypatch) -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    material = _material(org_id, course_id, user_id, "syllabus.pdf")
    chunk = _chunk(org_id, course_id, user_id, material, ordinal=0, text="Week 1 Foundations")
    dossier = _dossier(org_id, course_id, user_id, version=3)
    db = _DB([material], [chunk], [dossier])
    _install_llm(monkeypatch, extract=_extract(), merge={})

    result = await service.rebuild_material(db, org_id, user_id, material.id)

    assert material.insight_status == "ready"
    assert material.insight["content_hash"] == content_hash(material.scrubbed_text)
    assert dossier.status == "stale"
    assert dossier.version == 3
    assert result["dossier"]["status"] == "stale"


@pytest.mark.anyio
async def test_rebuild_material_clears_a_trace_url_from_an_older_full_rebuild(
    monkeypatch,
) -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    material = _material(org_id, course_id, user_id, "syllabus.pdf")
    material.trace_url = "http://trace/full-rebuild"
    chunk = _chunk(org_id, course_id, user_id, material, ordinal=0, text="Week 1 Foundations")
    dossier = _dossier(org_id, course_id, user_id)
    db = _DB([material], [chunk], [dossier])
    _install_llm(monkeypatch, extract=_extract(), merge={})

    await service.rebuild_material(db, org_id, user_id, material.id)

    assert material.trace_url == ""
    assert material.insight_status == "ready"


@pytest.mark.anyio
async def test_rebuild_material_rejects_another_professor() -> None:
    org_id, course_id = uuid.uuid4(), uuid.uuid4()
    material = _material(org_id, course_id, uuid.uuid4(), "syllabus.pdf")
    db = _DB([material], [], [])

    with pytest.raises(ProfassistError):
        await service.rebuild_material(db, org_id, uuid.uuid4(), material.id)


@pytest.mark.anyio
async def test_dossier_ai_context_is_empty_when_missing_or_stale() -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    stale = _dossier(org_id, course_id, user_id, status="stale")

    assert await service.dossier_ai_context(_DB([], [], []), org_id, user_id, course_id) == {}
    assert await service.dossier_ai_context(_DB([], [], [stale]), org_id, user_id, course_id) == {}


@pytest.mark.anyio
async def test_dossier_ai_context_fits_the_budget() -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    body = MergedDossier().model_dump()
    body["topics"] = [{"name": "Topic " + "x" * 600} for _ in range(30)]
    body["summary"] = "summary " * 1000
    dossier = _dossier(org_id, course_id, user_id, body=body)

    context = await service.dossier_ai_context(
        _DB([], [], [dossier]), org_id, user_id, course_id, budget=1000
    )

    assert context
    assert len(json.dumps(context, ensure_ascii=False)) <= 1000


@pytest.mark.anyio
async def test_ai_context_trims_a_copy_not_the_stored_body() -> None:
    org_id, course_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    body = MergedDossier().model_dump()
    body["topics"] = [{"name": "Topic " + "x" * 600} for _ in range(30)]
    body["summary"] = "summary " * 1000
    dossier = _dossier(org_id, course_id, user_id, body=body)
    original = copy.deepcopy(body)

    await service.dossier_ai_context(
        _DB([], [], [dossier]), org_id, user_id, course_id, budget=1000
    )

    assert dossier.body == original
