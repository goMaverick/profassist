"""Slide-edit memory: deterministic lessons, scoped recall, and style constraints."""

import copy
import sys
import types
import uuid
from typing import Any

import pytest

from app.profassist import memory, slide_memory
from app.profassist.models import ProfessorMemory
from app.profassist.skills import slide_studio
from tests.test_profassist_rubric import FakeSession


@pytest.fixture(autouse=True)
def _fresh_mem0(monkeypatch: pytest.MonkeyPatch):
    """No cached Mem0 client or inherited embedder settings between cases."""
    for name in (
        "MEM0_ENABLED",
        "MEM0_EMBEDDER_PROVIDER",
        "MEM0_EMBEDDER_MODEL",
        "MEM0_EMBEDDER_DIMS",
        "MEM0_HISTORY_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    memory._reset_mem0_store()
    yield
    memory._reset_mem0_store()
    _FakeMemory.fail = False


def _long(text: str) -> str:
    return text * 20


def test_slide_snapshot_is_deterministic() -> None:
    slides = [
        {"title": "Intro", "bullets": ["One point."], "speaker_notes": "Say one."},
        {"title": "Body", "bullets": [{"text": "Two points.", "citation": {}}]},
    ]

    first = slide_memory.slide_snapshot(slides, "Deck")
    second = slide_memory.slide_snapshot(copy.deepcopy(slides), "Deck")

    assert first == second
    assert "Deck" in first
    assert "One point." in first
    assert "Two points." in first
    assert "Say one." in first


def test_fewer_bullets_is_a_lesson() -> None:
    before = [{"title": "Intro", "bullets": ["Alpha one.", "Beta two.", "Gamma three."]}]
    after = [{"title": "Intro", "bullets": ["Alpha one."]}]

    assert slide_memory.extract_slide_lessons(before, after) == ["Prefers fewer bullets per slide"]


def test_shorter_bullets_is_a_lesson() -> None:
    before = [{"title": "Intro", "bullets": [_long("alpha "), _long("beta "), _long("gamma ")]}]
    after = [{"title": "Intro", "bullets": [_long("alpha ")[:60], _long("beta ")[:60]]}]

    lessons = slide_memory.extract_slide_lessons(before, after)
    assert any(lesson.startswith("Prefers shorter bullets") for lesson in lessons)


def test_shorter_bullets_lesson_records_the_average_length() -> None:
    before = [{"title": "Intro", "bullets": ["x" * 100, "y" * 100]}]
    after = [{"title": "Intro", "bullets": ["x" * 28, "y" * 28]}]

    assert slide_memory.extract_slide_lessons(before, after) == [
        "Prefers shorter bullets (about 28 characters)"
    ]


def test_fuller_bullets_lesson_records_the_average_length() -> None:
    before = [{"title": "Intro", "bullets": ["x" * 40, "y" * 40]}]
    after = [{"title": "Intro", "bullets": ["x" * 100, "y" * 100]}]

    assert slide_memory.extract_slide_lessons(before, after) == [
        "Prefers fuller bullet text (about 100 characters)"
    ]


def test_citation_removed_from_bullets_is_a_lesson() -> None:
    before = [
        {
            "title": "Intro",
            "bullets": [
                {"text": "Alpha one.", "citation": {"filename": "notes.pdf", "quote": "Alpha one."}}
            ],
        }
    ]
    after = [{"title": "Intro", "bullets": [{"text": "Alpha one."}]}]

    assert slide_memory.extract_slide_lessons(before, after) == [
        "Prefers citations in speaker notes, not on the slide"
    ]


def test_citation_added_to_bullets_is_a_lesson() -> None:
    before = [{"title": "Intro", "bullets": [{"text": "Alpha one."}]}]
    after = [
        {
            "title": "Intro",
            "bullets": [
                {"text": "Alpha one.", "citation": {"filename": "notes.pdf", "quote": "Alpha one."}}
            ],
        }
    ]

    assert slide_memory.extract_slide_lessons(before, after) == [
        "Keep the source filename on the slide"
    ]


def test_added_speaker_notes_is_a_lesson() -> None:
    before = [{"title": "Intro", "bullets": ["Alpha one."]}]
    after = [{"title": "Intro", "bullets": ["Alpha one."], "speaker_notes": "Say this."}]

    assert slide_memory.extract_slide_lessons(before, after) == [
        "Adds speaker notes to explain the slide"
    ]


def test_title_case_to_sentence_case_is_a_lesson() -> None:
    before = [{"title": "Design The Pipeline", "bullets": ["Alpha one."]}]
    after = [{"title": "Design the pipeline", "bullets": ["Alpha one."]}]

    assert slide_memory.extract_slide_lessons(before, after) == [
        "Prefers sentence-case slide titles"
    ]


def test_removed_exclamation_mark_is_a_lesson() -> None:
    before = [{"title": "Intro", "bullets": ["Alpha one!"]}]
    after = [{"title": "Intro", "bullets": ["Alpha one."]}]

    assert slide_memory.extract_slide_lessons(before, after) == [
        "Avoid exclamation marks on slides"
    ]


def test_no_op_edit_yields_no_lessons() -> None:
    slides = [
        {
            "title": "Intro",
            "bullets": [{"text": "Alpha one.", "citation": {"filename": "notes.pdf"}}],
            "speaker_notes": "Say this.",
        }
    ]

    assert slide_memory.extract_slide_lessons(slides, copy.deepcopy(slides)) == []


@pytest.mark.anyio
async def test_slide_preferences_scopes_ranks_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEM0_ENABLED", raising=False)
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    other_user, other_org = uuid.uuid4(), uuid.uuid4()
    rows = [
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="slides",
            text="Prefers shorter bullets",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="slides",
            text="Prefers shorter bullets",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="tone",
            text="Avoid exclamation marks on slides",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="preference",
            text="Keep source filenames on the slide",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="grade",
            text="Prefers shorter bullets",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=other_user,
            kind="slides",
            text="Prefers shorter bullets",
        ),
        ProfessorMemory(
            organization_id=other_org,
            owner_user_id=user_id,
            kind="slides",
            text="Prefers shorter bullets",
        ),
    ]
    for row in rows:
        db.add(row)
    await db.flush()

    preferences = await slide_memory.slide_preferences(
        db, org_id, user_id, "shorter bullets slide", limit=5
    )

    assert preferences[0] == "Prefers shorter bullets"
    assert preferences.count("Prefers shorter bullets") == 1
    assert "Avoid exclamation marks on slides" in preferences
    assert "Keep source filenames on the slide" in preferences
    assert len(preferences) == 3


@pytest.mark.anyio
async def test_slide_preferences_merges_mem0_after_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    db.add(
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="slides",
            text="Prefers shorter bullets",
        )
    )
    await db.flush()
    calls: list[tuple[Any, Any, str, int]] = []

    def fake_search(organization_id: Any, user_id_: Any, query: str, limit: int = 5) -> list[str]:
        calls.append((organization_id, user_id_, query, limit))
        return ["Mem0 lesson"]

    monkeypatch.setattr(memory, "mem0_enabled", lambda: True)
    monkeypatch.setattr(memory, "mem0_search", fake_search)
    monkeypatch.setitem(sys.modules, "mem0", types.ModuleType("mem0"))

    preferences = await slide_memory.slide_preferences(db, org_id, user_id, "shorter bullets")

    assert preferences == ["Prefers shorter bullets", "Mem0 lesson"]
    assert calls == [(org_id, user_id, "shorter bullets", 5)]


@pytest.mark.anyio
async def test_slide_preferences_swallows_a_mem0_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    db.add(
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="slides",
            text="Prefers shorter bullets",
        )
    )
    await db.flush()

    def explode(*args: Any, **kwargs: Any) -> list[str]:
        raise RuntimeError("mem0 down")

    monkeypatch.setattr(memory, "mem0_enabled", lambda: True)
    monkeypatch.setattr(memory, "mem0_search", explode)
    monkeypatch.setitem(sys.modules, "mem0", types.ModuleType("mem0"))

    preferences = await slide_memory.slide_preferences(db, org_id, user_id, "shorter bullets")

    assert preferences == ["Prefers shorter bullets"]


class _FakeMemory:
    results: Any = []
    fail: bool = False

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "_FakeMemory":
        return cls()

    def search(self, query: str, *, filters: dict[str, Any] | None = None, top_k: int = 20) -> Any:
        if self.fail:
            raise RuntimeError("search failed")
        return self.results


def _install_mem0(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("mem0")
    module.Memory = _FakeMemory
    monkeypatch.setitem(sys.modules, "mem0", module)


def test_mem0_search_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mem0(monkeypatch)
    monkeypatch.delenv("MEM0_ENABLED", raising=False)

    assert memory.mem0_enabled() is False
    assert memory.mem0_search(uuid.uuid4(), uuid.uuid4(), "shorter bullets") == []


def test_mem0_search_reads_dict_and_string_results(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mem0(monkeypatch)
    _FakeMemory.fail = False
    _FakeMemory.results = [
        {"memory": "Prefers shorter bullets"},
        "Keep source filenames on the slide",
        {"text": "Avoid exclamation marks on slides"},
    ]
    monkeypatch.setenv("MEM0_ENABLED", "true")
    monkeypatch.setattr(memory, "llm_api_key", lambda: "test-key")

    found = memory.mem0_search(uuid.uuid4(), uuid.uuid4(), "shorter bullets")

    assert found == [
        "Prefers shorter bullets",
        "Keep source filenames on the slide",
        "Avoid exclamation marks on slides",
    ]


def test_mem0_search_swallows_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mem0(monkeypatch)
    _FakeMemory.fail = True
    monkeypatch.setenv("MEM0_ENABLED", "true")
    monkeypatch.setattr(memory, "llm_api_key", lambda: "test-key")

    assert memory.mem0_search(uuid.uuid4(), uuid.uuid4(), "shorter bullets") == []


@pytest.mark.anyio
async def test_slide_preferences_keep_postgres_rows_when_the_mem0_store_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mem0 is a mirror: a broken store never removes the Postgres answer."""
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    db.add(
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="slides",
            text="Prefers shorter bullets",
        )
    )
    await db.flush()
    _install_mem0(monkeypatch)
    _FakeMemory.fail = True
    monkeypatch.setenv("MEM0_ENABLED", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    preferences = await slide_memory.slide_preferences(db, org_id, user_id, "shorter bullets")

    assert preferences == ["Prefers shorter bullets"]


def test_style_constraints_keep_citations_and_cap_bullets() -> None:
    quote = "A" * 200
    slides = [
        {
            "title": "Design The Pipeline",
            "bullets": [
                {"text": quote, "citation": {"filename": "notes.pdf", "quote": quote}},
                {
                    "text": "Second point.",
                    "citation": {"filename": "notes.pdf", "quote": "Second point."},
                },
            ],
            "notes": "",
        }
    ]

    styled = slide_studio.apply_style_preferences(
        slides,
        [
            "Prefers fewer bullets per slide",
            "Prefers shorter bullets",
            "Adds speaker notes to explain the slide",
            "Prefers sentence-case slide titles",
        ],
    )

    assert len(styled[0]["bullets"]) == 1
    assert len(styled[0]["bullets"][0]["text"]) == 100
    assert styled[0]["bullets"][0]["citation"]["quote"] == quote
    assert styled[0]["notes"].startswith("From the notes")
    assert "notes.pdf" in styled[0]["notes"]
    assert styled[0]["title"] == "Design the pipeline"


def test_style_constraints_apply_the_learned_bullet_length() -> None:
    quote = "a" * 47
    slides = [
        {
            "title": "Short",
            "bullets": [
                {"text": quote, "citation": {"filename": "notes.pdf", "quote": quote}},
                "b" * 47,
            ],
        }
    ]

    styled = slide_studio.apply_style_preferences(
        slides, ["Prefers shorter bullets (about 28 characters)"]
    )

    # 28 is below the 40-character floor; no space means cut at the limit.
    assert styled[0]["bullets"][0]["text"] == "a" * 40
    assert styled[0]["bullets"][0]["citation"]["quote"] == quote
    assert styled[0]["bullets"][1] == "b" * 40


def test_shorter_bullets_floor_ceiling_and_word_boundary() -> None:
    quote = "A verbatim passage from the notes."
    text = "Alpha beta gamma delta epsilon zeta eta theta iota kappa"
    slides = [
        {
            "title": "Trim",
            "bullets": [{"text": text, "citation": {"filename": "notes.pdf", "quote": quote}}],
        }
    ]

    styled = slide_studio.apply_style_preferences(
        slides, ["Prefers shorter bullets (about 30 characters)"]
    )

    trimmed = styled[0]["bullets"][0]["text"]
    assert slide_studio._shorter_limit(["shorter bullets (about 10 characters)"]) == 40
    assert slide_studio._shorter_limit(["shorter bullets (about 500 characters)"]) == 220
    assert trimmed == "Alpha beta gamma delta epsilon zeta eta"
    assert text.startswith(trimmed + " ")
    assert styled[0]["bullets"][0]["citation"]["quote"] == quote


@pytest.mark.anyio
async def test_artifact_preferences_scopes_ranks_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEM0_ENABLED", raising=False)
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    other_user, other_org = uuid.uuid4(), uuid.uuid4()
    rows = [
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="objective",
            text="Prefers a more concise outline.",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="objective",
            text="Prefers a more concise outline.",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="rubric",
            text="Rubric levels stay four bands.",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="feedback",
            text="Keep feedback short.",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="materials",
            text="Cite the uploaded notes.",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="grade",
            text="Prefers a more concise outline.",
        ),
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=other_user,
            kind="objective",
            text="Prefers a more concise outline.",
        ),
        ProfessorMemory(
            organization_id=other_org,
            owner_user_id=user_id,
            kind="rubric",
            text="Rubric levels stay four bands.",
        ),
    ]
    for row in rows:
        db.add(row)
    await db.flush()

    preferences = await slide_memory.artifact_preferences(
        db, org_id, user_id, "concise outline rubric", limit=6
    )

    assert preferences[0] == "Prefers a more concise outline."
    assert preferences.count("Prefers a more concise outline.") == 1
    assert "Rubric levels stay four bands." in preferences
    assert "Keep feedback short." in preferences
    assert "Cite the uploaded notes." in preferences
    assert len(preferences) == 4


@pytest.mark.anyio
async def test_artifact_preferences_accepts_an_explicit_kind_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEM0_ENABLED", raising=False)
    db = FakeSession()
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    db.add(
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="objective",
            text="Prefers a more concise outline.",
        )
    )
    db.add(
        ProfessorMemory(
            organization_id=org_id,
            owner_user_id=user_id,
            kind="rubric",
            text="Rubric levels stay four bands.",
        )
    )
    await db.flush()

    preferences = await slide_memory.artifact_preferences(
        db, org_id, user_id, "outline", kinds=("objective",), limit=6
    )

    assert preferences == ["Prefers a more concise outline."]
