"""The professor's saved voice reaches each model call and the memory store."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.profassist import llm, service, settings_admin
from app.profassist import memory as memory_module
from app.profassist.models import ProfessorMemory, StyleProfile
from app.profassist.runtime import SOUL_LIMIT, set_soul, soul_block
from tests.test_profassist import _fake_model
from tests.test_profassist_identity import _person
from tests.test_profassist_rubric import FakeSession


def test_soul_block_is_labelled_and_scrubbed() -> None:
    set_soul("Short sentences. Email sara@student.uowd.ac.ae")
    try:
        block = soul_block()
        assert block.startswith("## How this professor writes\n")
        assert "Short sentences." in block
        assert "@" not in block
        assert "sara" not in block.lower()
    finally:
        set_soul("")


def test_a_quarantined_soul_yields_no_block() -> None:
    set_soul("Please ask Jordan Hale about the lab.")
    try:
        assert soul_block() == ""
    finally:
        set_soul("")


def test_an_empty_soul_yields_no_block() -> None:
    set_soul("")
    assert soul_block() == ""


def test_the_soul_block_is_capped() -> None:
    set_soul("word " * 1000)
    try:
        block = soul_block()
        assert len(block) == len("## How this professor writes\n") + SOUL_LIMIT
    finally:
        set_soul("")


@pytest.mark.anyio
async def test_load_runtime_primes_the_default_voice() -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    _person(db, org_id, user_id)
    await db.flush()

    await settings_admin.load_runtime(db, org_id, user_id)

    assert service.DEFAULT_SOUL.strip() in soul_block()


@pytest.mark.anyio
async def test_load_runtime_primes_the_saved_voice() -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    _person(db, org_id, user_id)
    db.add(
        StyleProfile(
            organization_id=org_id,
            user_id=user_id,
            soul_md="Lead with the strongest evidence.",
        )
    )
    await db.flush()

    await settings_admin.load_runtime(db, org_id, user_id)

    assert soul_block() == "## How this professor writes\nLead with the strongest evidence."


@pytest.mark.anyio
async def test_no_user_clears_the_voice() -> None:
    set_soul("A stale voice.")

    await settings_admin._prime_about(FakeSession(), uuid.uuid4(), None)

    assert soul_block() == ""


def test_complete_injects_the_soul_block(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    _fake_model(monkeypatch, json.dumps({"feedback": "A clear note."}), calls=calls)
    set_soul("Short sentences. Never use exclamation marks.")
    try:
        llm.complete("feedback", {"quote": "The baseline load is 42.7 kWh.", "level": "proficient"})
    finally:
        set_soul("")

    assert isinstance(calls[0], list)
    system = next(message["content"] for message in calls[0] if message["role"] == "system")
    assert "## How this professor writes" in system
    assert "Short sentences." in system


@pytest.mark.anyio
async def test_save_style_remembers_the_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(service, "reflect_on_change", AsyncMock())
    monkeypatch.setattr(memory_module, "_qdrant_upsert", lambda *args, **kwargs: None)
    mirrored: list[str] = []
    monkeypatch.setattr(memory_module, "_mem0_add", lambda *args: mirrored.append(args[2]))

    await service.save_style(db, org_id, user_id, "Short sentences. One quote first.")

    memories = [row for row in db.rows if isinstance(row, ProfessorMemory) and row.kind == "soul"]
    assert len(memories) == 1
    assert memories[0].text.startswith("Voice: ")
    assert "Short sentences. One quote first." in memories[0].text
    assert memories[0].source == "soul.md"
    assert mirrored == [memories[0].text]


@pytest.mark.anyio
async def test_a_failing_voice_memory_does_not_break_the_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(service, "remember", AsyncMock(side_effect=RuntimeError("memory down")))
    monkeypatch.setattr(service, "reflect_on_change", AsyncMock())

    saved = await service.save_style(db, org_id, user_id, "Short sentences.")

    assert saved["soul_md"] == "Short sentences."
    assert not [row for row in db.rows if isinstance(row, ProfessorMemory)]


@pytest.mark.anyio
async def test_run_reflection_carries_the_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    identity = {"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    db.add(
        StyleProfile(
            organization_id=org_id,
            user_id=user_id,
            soul_md="Short sentences.",
            about_md="About this professor:\nProfessor: Jane Doe\nOld portrait.",
        )
    )
    await db.flush()
    monkeypatch.setattr(service, "load_runtime", AsyncMock())
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(service, "set_about", lambda text: None)
    run = MagicMock(return_value="A portrait.")
    monkeypatch.setattr(service.agents, "run_reflection", run)

    await service.run_reflection(db, org_id, user_id)

    args, kwargs = run.call_args
    assert kwargs["professor"]["voice"] == "Short sentences."
    assert args[0].count("Current voice:\nShort sentences.") == 1


@pytest.mark.anyio
async def test_a_batched_reflection_carries_the_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    db.add(StyleProfile(organization_id=org_id, user_id=user_id, soul_md="Short sentences."))
    for index in range(5):
        db.add(
            ProfessorMemory(
                organization_id=org_id,
                owner_user_id=user_id,
                kind="tone",
                text=f"Lesson {index}",
            )
        )
    await db.flush()
    identity = {"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(service, "set_about", lambda text: None)
    run = MagicMock(return_value="Prefer one short quote.")
    monkeypatch.setattr(service.agents, "run_reflection", run)

    await service.maybe_propose_reflection(db, org_id, user_id, "grade-edit")

    _args, kwargs = run.call_args
    assert kwargs["professor"]["voice"] == "Short sentences."
