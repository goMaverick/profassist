"""Reflection hooks: cheap movement capture, batched proposals, and deck ownership."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.v1 import assignment_ai, deck_ai
from app.api.routes.v1 import profassist as profassist_route
from app.core.config import settings
from app.profassist import memory as memory_module
from app.profassist import outline, service
from app.profassist.errors import ProfassistError
from app.profassist.models import (
    Course,
    ProfessorMemory,
    Reflection,
    StyleProfile,
    SubjectOutline,
)
from app.profassist.outline_data import empty_outline
from tests.test_assignment_ai import FakeSession as AssignmentSession
from tests.test_assignment_ai import _document, _org, _user, _workspace
from tests.test_assignment_ai import _row as assignment_row
from tests.test_deck_ai import _row as deck_row
from tests.test_profassist_rubric import FakeSession, _criteria
from tests.test_profassist_rubric import _workspace as rubric_workspace


def _quiet_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_module, "_qdrant_upsert", lambda *args, **kwargs: None)
    monkeypatch.setattr(memory_module, "_mem0_add", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "set_about", lambda text: None)


@pytest.mark.anyio
async def test_remember_movement_writes_a_lesson_and_portrait_without_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    _quiet_memory(monkeypatch)
    run = MagicMock(side_effect=AssertionError("remember_movement must not call the model"))
    monkeypatch.setattr(service.agents, "run_reflection", run)

    lessons = await service.remember_movement(
        db,
        org_id,
        user_id,
        "grade",
        "Draft feedback with an exclamation!",
        "Clean final feedback with evidence from the report.",
        "grade-edit",
    )

    assert lessons
    memories = [row for row in db.rows if isinstance(row, ProfessorMemory)]
    assert memories and memories[0].kind == "tone"
    profile = next(row for row in db.rows if isinstance(row, StyleProfile))
    assert "tone:" in profile.about_md
    run.assert_not_called()


@pytest.mark.anyio
async def test_maybe_propose_waits_for_five_memories_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    for index in range(4):
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
    run = MagicMock(return_value="Use shorter feedback with one evidence quote.")
    monkeypatch.setattr(service.agents, "run_reflection", run)

    assert await service.maybe_propose_reflection(db, org_id, user_id, "grade-edit") is None
    assert not [row for row in db.rows if isinstance(row, Reflection)]

    db.add(
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="tone",
            text="Lesson 4",
        )
    )
    await db.flush()
    created = await service.maybe_propose_reflection(db, org_id, user_id, "grade-edit")

    assert created is not None
    assert created.status == "applied"
    profile = next(row for row in db.rows if isinstance(row, StyleProfile))
    assert "Use shorter feedback with one evidence quote." in profile.about_md
    run.assert_called_once()
    _args, kwargs = run.call_args
    assert kwargs["professor"]["name"] == identity["name"]
    assert kwargs["professor"]["voice"] == service.DEFAULT_SOUL

    for index in range(5):
        db.add(
            ProfessorMemory(
                organization_id=org_id,
                owner_user_id=user_id,
                kind="rubric",
                text=f"More lesson {index}",
            )
        )
    await db.flush()
    assert await service.maybe_propose_reflection(db, org_id, user_id, "rubric-edit") is None
    assert len([row for row in db.rows if isinstance(row, Reflection)]) == 1
    assert run.call_count == 2


@pytest.mark.anyio
async def test_run_reflection_auto_applies_to_about_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    identity = {"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    old = "About this professor:\nProfessor: Jane Doe \u2014 owner\nTeaches: AAS910\nOld portrait."
    db.add(
        StyleProfile(
            organization_id=org_id,
            user_id=user_id,
            soul_md=service.DEFAULT_SOUL,
            about_md=old,
        )
    )
    await db.flush()
    monkeypatch.setattr(service, "load_runtime", AsyncMock())
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(
        service.agents, "run_reflection", MagicMock(return_value="Use one evidence quote.")
    )
    seen: dict[str, str] = {}
    monkeypatch.setattr(service, "set_about", lambda text: seen.setdefault("text", text))

    result = await service.run_reflection(db, org_id, user_id)

    profile = next(row for row in db.rows if isinstance(row, StyleProfile))
    assert result["status"] == "applied"
    assert "Use one evidence quote." in profile.about_md
    assert "Professor: Jane Doe \u2014 owner" in profile.about_md
    assert profile.about_history[-1] == {
        "version": 1,
        "text": old,
        "source": "reflection-auto",
    }
    assert seen["text"] == profile.about_md


@pytest.mark.anyio
async def test_batch_reflection_auto_applies_to_the_portrait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    old = "About this professor:\nProfessor: Jane Doe \u2014 owner\nTeaches: AAS910\nOld."
    db.add(
        StyleProfile(
            organization_id=org_id,
            user_id=user_id,
            soul_md=service.DEFAULT_SOUL,
            about_md=old,
        )
    )
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
    monkeypatch.setattr(
        service.agents, "run_reflection", MagicMock(return_value="Prefer one short quote.")
    )
    monkeypatch.setattr(service, "set_about", lambda text: None)

    created = await service.maybe_propose_reflection(db, org_id, user_id, "grade-edit")

    profile = next(row for row in db.rows if isinstance(row, StyleProfile))
    assert created is not None
    assert created.status == "applied"
    assert "Prefer one short quote." in profile.about_md
    assert profile.about_history[-1]["source"] == "reflection-auto"
    assert profile.about_history[-1]["text"] == old


@pytest.mark.anyio
async def test_quarantined_reflection_is_not_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    identity = {"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    old = "About this professor:\nProfessor: Jane Doe \u2014 owner\nTeaches: AAS910\nKeep this."
    db.add(
        StyleProfile(
            organization_id=org_id,
            user_id=user_id,
            soul_md=service.DEFAULT_SOUL,
            about_md=old,
        )
    )
    await db.flush()
    monkeypatch.setattr(service, "load_runtime", AsyncMock())
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(
        service.agents,
        "run_reflection",
        MagicMock(return_value="Student: Sara Maktoum needs a shorter note."),
    )
    applied: list[str] = []
    monkeypatch.setattr(service, "set_about", lambda text: applied.append(text))

    result = await service.run_reflection(db, org_id, user_id)

    profile = next(row for row in db.rows if isinstance(row, StyleProfile))
    assert result["status"] == "applied"
    assert profile.about_md == old
    assert profile.about_history == []
    assert applied == []


@pytest.mark.anyio
async def test_empty_reflection_is_applied_without_changing_the_portrait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    identity = {"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    old = "About this professor:\nProfessor: Jane Doe \u2014 owner\nTeaches: AAS910\nKeep this."
    db.add(
        StyleProfile(
            organization_id=org_id,
            user_id=user_id,
            soul_md=service.DEFAULT_SOUL,
            about_md=old,
        )
    )
    await db.flush()
    monkeypatch.setattr(service, "load_runtime", AsyncMock())
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(service.agents, "run_reflection", MagicMock(return_value=""))
    monkeypatch.setattr(service, "set_about", lambda text: None)

    result = await service.run_reflection(db, org_id, user_id)

    profile = next(row for row in db.rows if isinstance(row, StyleProfile))
    assert result["status"] == "applied"
    assert result["proposal"] == ""
    assert profile.about_md == old
    assert profile.about_history == []


@pytest.mark.anyio
async def test_identical_reflection_does_not_churn_the_portrait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    identity = {"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    current = "About this professor:\nProfessor: Jane Doe \u2014 owner\nTeaches: AAS910\nSame body."
    db.add(
        StyleProfile(
            organization_id=org_id,
            user_id=user_id,
            soul_md=service.DEFAULT_SOUL,
            about_md=current,
        )
    )
    await db.flush()
    monkeypatch.setattr(service, "load_runtime", AsyncMock())
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(service.agents, "run_reflection", MagicMock(return_value="Same body."))
    monkeypatch.setattr(service, "set_about", lambda text: None)

    result = await service.run_reflection(db, org_id, user_id)

    profile = next(row for row in db.rows if isinstance(row, StyleProfile))
    assert result["status"] == "applied"
    assert profile.about_md == current
    assert profile.about_history == []


@pytest.mark.anyio
async def test_duplicate_applied_proposal_does_not_churn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
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
    monkeypatch.setattr(service.agents, "run_reflection", MagicMock(return_value="Keep one quote."))
    monkeypatch.setattr(service, "set_about", lambda text: None)

    first = await service.maybe_propose_reflection(db, org_id, user_id, "grade-edit")
    profile = next(row for row in db.rows if isinstance(row, StyleProfile))
    history = list(profile.about_history)

    for index in range(5):
        db.add(
            ProfessorMemory(
                organization_id=org_id,
                owner_user_id=user_id,
                kind="tone",
                text=f"More lesson {index}",
            )
        )
    await db.flush()
    second = await service.maybe_propose_reflection(db, org_id, user_id, "grade-edit")

    assert first is not None and first.status == "applied"
    assert second is None
    assert len([row for row in db.rows if isinstance(row, Reflection)]) == 1
    assert profile.about_history == history


@pytest.mark.anyio
async def test_approve_reflection_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    identity = {"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(service, "set_about", lambda text: None)
    row = Reflection(
        organization_id=org_id,
        owner_user_id=user_id,
        proposal="Keep one quote.",
        status="applied",
    )
    db.add(row)
    db.add(
        StyleProfile(
            organization_id=org_id,
            user_id=user_id,
            soul_md=service.DEFAULT_SOUL,
            about_md="About this professor:\nProfessor: Jane Doe \u2014 owner\nKeep one quote.",
        )
    )
    await db.flush()

    first = await service.approve_reflection(db, org_id, user_id, row.id)
    second = await service.approve_reflection(db, org_id, user_id, row.id)

    profile = next(item for item in db.rows if isinstance(item, StyleProfile))
    assert (
        first == second == {"id": str(row.id), "proposal": "Keep one quote.", "status": "applied"}
    )
    assert row.status == "applied"
    assert len([item for item in db.rows if isinstance(item, Reflection)]) == 1
    assert profile.about_history == []


@pytest.mark.anyio
async def test_applied_reflection_reaches_labelled_about(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.runtime import labelled_about, set_about

    set_about("")
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    identity = {"name": "Jane Doe", "role": "owner", "courses": ["AAS910"]}
    monkeypatch.setattr(service, "load_runtime", AsyncMock())
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(
        service.agents, "run_reflection", MagicMock(return_value="Lead with one quote.")
    )

    await service.run_reflection(db, org_id, user_id)

    block = labelled_about()
    assert "Lead with one quote." in block
    assert "Professor: Jane Doe" in block
    set_about("")


@pytest.mark.anyio
async def test_a_failing_reflection_does_not_break_the_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    _quiet_memory(monkeypatch)
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
    monkeypatch.setattr(service, "professor_identity", AsyncMock(return_value={}))
    monkeypatch.setattr(
        service.agents, "run_reflection", MagicMock(side_effect=RuntimeError("model down"))
    )

    assert await service.maybe_propose_reflection(db, org_id, user_id, "grade-edit") is None
    await service.capture_movement(
        db,
        org_id,
        user_id,
        "grade",
        "Draft with an exclamation!",
        "Clean final feedback with evidence.",
        "grade-edit",
    )
    assert any(isinstance(row, ProfessorMemory) for row in db.rows)


@pytest.mark.anyio
async def test_outline_save_step_captures_the_section(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    row = SubjectOutline(
        organization_id=org_id,
        owner_user_id=user_id,
        code="TST101",
        name="Test subject",
        body=empty_outline(),
        status="draft",
    )
    db.add(row)
    await db.flush()
    hook = AsyncMock()
    monkeypatch.setattr(outline, "capture_movement", hook)

    await outline.save_step(
        db, org_id, user_id, row.id, "description", {"description": "A clearer description."}
    )

    hook.assert_awaited_once()
    args = hook.await_args.args
    assert args[3] == "objective"
    assert args[6] == "outline-edit"
    assert "A clearer description." in args[5]


@pytest.mark.anyio
async def test_assignment_save_captures_brief_and_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    db = AssignmentSession()
    org_id, user_id, course = await _workspace(db)
    row = assignment_row(db, org_id, user_id, course)
    await db.flush()
    hook = AsyncMock()
    monkeypatch.setattr(assignment_ai, "capture_movement", hook)

    document = _document(overview=["Edited overview."])
    await assignment_ai.save_assignment(
        row.id,
        assignment_ai.ManualAssignmentBody(document=document, title="Edited title"),
        _user(user_id),
        _org(org_id),
        db,
    )

    kinds = [call.args[3] for call in hook.await_args_list]
    sources = {call.args[6] for call in hook.await_args_list}
    assert "objective" in kinds
    assert "rubric" in kinds
    assert sources == {"assignment-edit"}


@pytest.mark.anyio
async def test_rubric_save_and_approve_capture_criteria(monkeypatch: pytest.MonkeyPatch) -> None:
    db, org_id, user_id, course = await rubric_workspace()
    created = await service.create_rubric(db, org_id, course.id, user_id, "Blank rubric")
    assessment_id = uuid.UUID(created["id"])
    capture = AsyncMock()
    monkeypatch.setattr(service, "capture_movement", capture)

    await service.save_rubric(db, org_id, user_id, assessment_id, _criteria(), "Groups report.")

    rubric_calls = [call for call in capture.await_args_list if call.args[3] == "rubric"]
    assert rubric_calls
    args = rubric_calls[0].args
    assert args[6] == "rubric-edit"
    assert "Evidence" in args[5] and "40%" in args[5]

    reflect = AsyncMock()
    monkeypatch.setattr(service, "reflect_on_change", reflect)
    await service.approve_assessment(db, org_id, user_id, assessment_id)

    args = reflect.await_args.args
    assert args[3] == "rubric"
    assert args[6] == "rubric-approve"
    assert "Evidence" in args[5]
    assert "proficient" in args[5]
    assert reflect.await_args.kwargs["propose"] is True


@pytest.mark.anyio
async def test_deck_save_and_approve_capture_full_content(monkeypatch: pytest.MonkeyPatch) -> None:
    row = deck_row(status="draft")
    db = _DeckStore(row)
    user = SimpleNamespace(id=row.owner_user_id)
    org = SimpleNamespace(id=row.organization_id)
    hook = AsyncMock()
    monkeypatch.setattr(deck_ai, "capture_movement", hook)

    await deck_ai.deck_save(
        row.id,
        deck_ai.DeckSaveBody(
            slides=[{"title": "Intro", "bullets": ["Changed bullet"], "speaker_notes": "New note."}]
        ),
        user,
        org,
        db,
    )

    args = hook.await_args.args
    assert args[3] == "slides"
    assert args[6] == "deck-save"
    assert "Intro" in args[5]
    assert "Changed bullet" in args[5]
    assert "New note." in args[5]

    reflect = AsyncMock()
    monkeypatch.setattr(service, "reflect_on_change", reflect)
    await service.approve_deck(db, org.id, user.id, row.id)

    args = reflect.await_args.args
    assert args[3] == "slides"
    assert args[6] == "deck-approve"
    assert "Intro" in args[5]
    assert "Changed bullet" in args[5]
    assert "New note." in args[5]


@pytest.mark.anyio
async def test_grade_feedback_save_captures_feedback(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr("app.profassist.integrity_docs.document_side", lambda *args: {})
    hook = AsyncMock()
    monkeypatch.setattr(profassist_route, "capture_movement", hook)

    class _DB:
        def add(self, row: object) -> None:
            return None

        async def flush(self) -> None:
            return None

    body = profassist_route.FeedbackBody(
        group="Group A",
        course="MAAI903",
        comments=[{"text": "Name who would use the count."}],
        overall="A clearer draft.",
    )
    await profassist_route.grade_feedback_save(
        body,
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(id=uuid.uuid4()),
        _DB(),
    )

    args = hook.await_args.args
    assert args[3] == "feedback"
    assert args[6] == "grade-feedback"
    assert "A clearer draft." in args[5]


@pytest.mark.anyio
async def test_upload_remembers_the_source_file(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    course = Course(organization_id=org_id, code="TST101", title="Test subject")
    db.add(course)
    await db.flush()
    monkeypatch.setattr(service, "extract_text", lambda *args: "Some course notes.")
    monkeypatch.setattr(service, "save_bytes", lambda *args: "stored/key")
    monkeypatch.setattr(service, "_remember_pii", AsyncMock())
    monkeypatch.setattr(service, "_index_material", AsyncMock())
    remember = AsyncMock()
    monkeypatch.setattr(service, "remember", remember)
    monkeypatch.setattr(service, "maybe_propose_reflection", AsyncMock())

    await service.add_material(db, org_id, course.id, user_id, "notes.txt", b"hello")

    args = remember.await_args.args
    kwargs = remember.await_args.kwargs
    assert "notes.txt" in args[3]
    assert kwargs["kind"] == "materials"
    assert kwargs["source"].startswith("material:")


class _DeckStore:
    def __init__(self, row: object) -> None:
        self.row = row
        self.added: list[object] = []

    async def get(self, model: object, ident: uuid.UUID) -> object | None:
        return self.row if ident == self.row.id else None

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None


@pytest.mark.anyio
async def test_deck_approval_and_download_belong_to_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = deck_row(storage_key="")
    db = _DeckStore(row)
    monkeypatch.setattr(service, "reflect_on_change", AsyncMock())
    other = uuid.uuid4()

    with pytest.raises(ProfassistError) as caught:
        await service.approve_deck(db, row.organization_id, other, row.id)
    assert caught.value.status == 404

    with pytest.raises(ProfassistError) as caught:
        await service.deck_bytes(db, row.organization_id, other, row.id)
    assert caught.value.status == 404

    approved = await service.approve_deck(db, row.organization_id, row.owner_user_id, row.id)
    assert approved["status"] == "approved"
    filename, data = await service.deck_bytes(db, row.organization_id, row.owner_user_id, row.id)
    assert filename.endswith(".pptx")
    assert data[:2] == b"PK"
