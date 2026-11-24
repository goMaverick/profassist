"""Deck editing, one-slide assistance, and the PPTX speaker notes."""

import asyncio
import copy
import io
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

import app.api.routes.v1.deck_ai as deck_ai
import app.profassist.llm as llm
from app.profassist.errors import ProfassistError
from app.profassist.slides import build_pptx

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

CONTRACT_KEYS = {
    "id",
    "course_id",
    "title",
    "status",
    "week",
    "slides",
    "instructions",
    "review",
    "review_trace_url",
}


class _DB:
    def __init__(self, row: Any = None) -> None:
        self.row = row
        self.flushed = 0

    async def get(self, model: object, ident: uuid.UUID) -> Any:
        if self.row is not None and ident == self.row.id:
            return self.row
        return None

    async def flush(self) -> None:
        self.flushed += 1


def _slides() -> list[dict[str, Any]]:
    return [
        {"title": "Intro", "bullets": ["One"], "speaker_notes": "Say one."},
        {"title": "Body", "bullets": ["Two"], "speaker_notes": "Say two."},
        {"title": "Close", "bullets": ["Three"], "speaker_notes": "Say three."},
    ]


def _row(**overrides: Any) -> SimpleNamespace:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        title="Draft deck",
        slides=_slides(),
        status="draft",
        storage_key="org/course/slides.pptx",
        week=4,
        instructions="Keep it short.",
        review={},
        review_trace_url="",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _ids(row: SimpleNamespace) -> tuple[SimpleNamespace, SimpleNamespace]:
    return SimpleNamespace(id=row.owner_user_id), SimpleNamespace(id=row.organization_id)


def _wire_model(
    monkeypatch: pytest.MonkeyPatch, drafted: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_load_runtime(*args: object) -> None:
        return None

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((task, payload))
        return dict(drafted)

    monkeypatch.setattr(deck_ai, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(deck_ai.llm, "complete", fake_complete)
    return calls


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in KEY_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_deck_routes_are_registered_and_get_returns_contract_keys() -> None:
    from app.core.config import settings
    from app.main import app

    paths = app.openapi()["paths"]
    base = f"{settings.API_V1_STR}/profassist/slides/{{deck_id}}"
    assert "get" in paths[base]
    assert "put" in paths[base]
    assert "post" in paths[f"{base}/assist"]

    row = _row()
    user, org = _ids(row)
    result = asyncio.run(deck_ai.deck_get(row.id, user, org, _DB(row)))

    assert set(result) == CONTRACT_KEYS
    assert result["id"] == str(row.id)
    assert result["course_id"] == str(row.course_id)
    assert result["title"] == "Draft deck"
    assert result["status"] == "draft"
    assert result["week"] == 4
    assert result["slides"] == row.slides
    assert result["instructions"] == "Keep it short."
    assert result["review"] == {}
    assert result["review_trace_url"] == ""


def test_deck_get_hides_a_foreign_deck() -> None:
    row = _row()
    user = SimpleNamespace(id=uuid.uuid4())
    org = SimpleNamespace(id=row.organization_id)

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(deck_ai.deck_get(row.id, user, org, _DB(row)))
    assert caught.value.status == 404

    org = SimpleNamespace(id=uuid.uuid4())
    user = SimpleNamespace(id=row.owner_user_id)
    with pytest.raises(ProfassistError) as caught:
        asyncio.run(deck_ai.deck_get(row.id, user, org, _DB(row)))
    assert caught.value.status == 404


def test_deck_save_updates_the_deck_and_clears_the_pptx_cache() -> None:
    row = _row()
    user, org = _ids(row)
    db = _DB(row)
    body = deck_ai.DeckSaveBody(
        title="Saved deck",
        slides=[{"title": "Intro", "bullets": ["One"], "speaker_notes": "Say one."}],
    )

    result = asyncio.run(deck_ai.deck_save(row.id, body, user, org, db))

    assert row.title == "Saved deck"
    assert row.slides == [{"title": "Intro", "bullets": ["One"], "speaker_notes": "Say one."}]
    assert row.storage_key == ""
    assert db.flushed == 1
    assert result["slides"] == row.slides


def test_deck_save_round_trips_cited_bullets() -> None:
    cited = [
        {
            "title": "Cited",
            "bullets": [
                {
                    "text": "Claim",
                    "citation": {
                        "filename": "notes.pdf",
                        "section": "S1",
                        "quote": "Claim",
                        "chunk_id": "c-1",
                        "extra": "dropped",
                    },
                },
                "Plain bullet",
            ],
            "speaker_notes": "Say it.",
        }
    ]
    row = _row(slides=copy.deepcopy(cited))
    user, org = _ids(row)
    db = _DB(row)

    got = asyncio.run(deck_ai.deck_get(row.id, user, org, db))
    result = asyncio.run(
        deck_ai.deck_save(
            row.id,
            deck_ai.DeckSaveBody(title=got["title"], slides=got["slides"]),
            user,
            org,
            db,
        )
    )

    assert result["slides"] == [
        {
            "title": "Cited",
            "bullets": [
                {
                    "text": "Claim",
                    "citation": {
                        "filename": "notes.pdf",
                        "section": "S1",
                        "quote": "Claim",
                        "chunk_id": "c-1",
                    },
                },
                "Plain bullet",
            ],
            "speaker_notes": "Say it.",
        }
    ]


def test_deck_save_accepts_notes_as_a_speaker_notes_alias() -> None:
    row = _row()
    user, org = _ids(row)
    db = _DB(row)
    body = deck_ai.DeckSaveBody(
        slides=[{"title": "Intro", "bullets": ["One"], "notes": "Alias note."}]
    )

    result = asyncio.run(deck_ai.deck_save(row.id, body, user, org, db))

    assert row.slides == [{"title": "Intro", "bullets": ["One"], "speaker_notes": "Alias note."}]
    assert result["slides"] == row.slides


def test_deck_save_drops_empty_bullets_and_rejects_other_types() -> None:
    row = _row()
    user, org = _ids(row)
    db = _DB(row)
    body = deck_ai.DeckSaveBody(
        slides=[{"title": "Intro", "bullets": ["", "  ", {"text": "   "}, "Keep"]}]
    )

    result = asyncio.run(deck_ai.deck_save(row.id, body, user, org, db))
    assert result["slides"] == [{"title": "Intro", "bullets": ["Keep"]}]

    other = _row()
    user, org = _ids(other)
    db = _DB(other)
    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            deck_ai.deck_save(
                other.id,
                deck_ai.DeckSaveBody(slides=[{"title": "Bad", "bullets": [1]}]),
                user,
                org,
                db,
            )
        )
    assert caught.value.status == 400


def test_slides_text_reads_object_bullets_and_notes_alias() -> None:
    text = deck_ai._slides_text(
        "Deck",
        [
            {
                "title": "Cited",
                "bullets": [
                    {"text": "Cited claim", "citation": {"filename": "n.pdf"}},
                    "Plain",
                ],
                "notes": "Alias note.",
            }
        ],
    )

    assert "Bullets: Cited claim | Plain" in text
    assert "Notes: Alias note." in text
    assert "citation" not in text


def test_deck_save_clears_a_stale_review_when_the_content_changes() -> None:
    row = _row(review={"verdict": "pass", "score": 100}, review_trace_url="http://trace/1")
    user, org = _ids(row)
    db = _DB(row)
    body = deck_ai.DeckSaveBody(
        slides=[{"title": "Intro", "bullets": ["One"], "speaker_notes": "Say one."}]
    )

    result = asyncio.run(deck_ai.deck_save(row.id, body, user, org, db))

    assert row.review == {}
    assert row.review_trace_url == ""
    assert result["review"] == {}
    assert result["review_trace_url"] == ""


def test_deck_save_keeps_the_review_when_nothing_changes() -> None:
    review = {"verdict": "pass", "score": 100}
    row = _row(review=review, review_trace_url="http://trace/1")
    user, org = _ids(row)
    db = _DB(row)
    body = deck_ai.DeckSaveBody(title="Draft deck", slides=_slides())

    result = asyncio.run(deck_ai.deck_save(row.id, body, user, org, db))

    assert row.review == review
    assert row.review_trace_url == "http://trace/1"
    assert result["review"] == review


def test_assist_returns_the_trace_url_without_polluting_the_deck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    user, org = _ids(row)
    db = _DB(row)
    _wire_model(
        monkeypatch,
        {"reply": "Tightened it.", "slides": [{"title": "New intro", "bullets": ["Fresh"]}]},
    )
    monkeypatch.setattr(deck_ai, "step_trace_url", lambda: "http://trace/deck")

    result = asyncio.run(
        deck_ai.deck_assist(
            row.id, deck_ai.DeckAssistBody(message="Make the opening clearer."), user, org, db
        )
    )

    assert result["trace_url"] == "http://trace/deck"
    assert "trace_url" not in result["deck"]
    assert all("trace_url" not in slide for slide in result["deck"]["slides"])


def test_assist_clears_a_stale_review_when_the_content_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(review={"verdict": "pass", "score": 100}, review_trace_url="http://trace/1")
    user, org = _ids(row)
    db = _DB(row)
    _wire_model(
        monkeypatch,
        {"reply": "Tightened it.", "slides": [{"title": "New intro", "bullets": ["Fresh"]}]},
    )

    result = asyncio.run(
        deck_ai.deck_assist(
            row.id, deck_ai.DeckAssistBody(message="Make the opening clearer."), user, org, db
        )
    )

    assert result["changed_slides"] == [0]
    assert row.review == {}
    assert row.review_trace_url == ""
    assert result["deck"]["review"] == {}
    assert result["deck"]["review_trace_url"] == ""


def test_get_then_put_keeps_citations_and_layout() -> None:
    citation = {"filename": "lecture.pdf", "section": "note", "quote": "A verbatim line."}
    row = _row(
        slides=[
            {
                "title": "Intro",
                "bullets": [{"text": "One", "citation": citation}],
                "speaker_notes": "Say one.",
                "citations": [citation],
                "layout": "two-column",
            }
        ]
    )
    user, org = _ids(row)
    db = _DB(row)

    loaded = asyncio.run(deck_ai.deck_get(row.id, user, org, db))
    asyncio.run(
        deck_ai.deck_save(row.id, deck_ai.DeckSaveBody(slides=loaded["slides"]), user, org, db)
    )

    saved = row.slides[0]
    assert saved["citations"] == [citation]
    assert saved["layout"] == "two-column"
    assert saved["bullets"][0]["citation"] == citation
    assert saved["speaker_notes"] == "Say one."


def test_deck_save_rejects_invalid_slides_and_keeps_the_deck() -> None:
    row = _row()
    before = copy.deepcopy(row.slides)
    user, org = _ids(row)
    db = _DB(row)

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            deck_ai.deck_save(
                row.id,
                deck_ai.DeckSaveBody(slides=[{"title": "Bad", "bullets": "not a list"}]),
                user,
                org,
                db,
            )
        )
    assert caught.value.status == 400
    assert row.slides == before
    assert row.storage_key == "org/course/slides.pptx"
    assert db.flushed == 0


def test_deck_save_locks_an_approved_deck() -> None:
    row = _row(status="approved")
    user, org = _ids(row)
    db = _DB(row)

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            deck_ai.deck_save(row.id, deck_ai.DeckSaveBody(title="Too late"), user, org, db)
        )
    assert caught.value.status == 409
    assert row.title == "Draft deck"
    assert db.flushed == 0


def test_assist_changes_only_the_named_slide(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row()
    before = copy.deepcopy(row.slides)
    user, org = _ids(row)
    db = _DB(row)
    calls = _wire_model(
        monkeypatch,
        {
            "reply": "Rewrote the body.",
            "title": "Ignored title",
            "slides": [
                {"title": "Changed 0", "bullets": ["Zero"]},
                {"title": "Changed 1", "bullets": ["One"]},
                {"title": "Changed 2", "bullets": ["Two"]},
            ],
        },
    )

    result = asyncio.run(
        deck_ai.deck_assist(
            row.id,
            deck_ai.DeckAssistBody(message="Rewrite this slide.", slide_index=1),
            user,
            org,
            db,
        )
    )

    assert row.slides[0] == before[0]
    assert row.slides[1] == {"title": "Changed 1", "bullets": ["One"]}
    assert row.slides[2] == before[2]
    assert row.title == "Draft deck"
    assert result["changed_slides"] == [1]
    assert result["deck"]["slides"] == row.slides
    assert calls[0][0] == "slides"
    assert calls[0][1]["slide_index"] == 1
    assert calls[0][1]["existing_deck"]["slides"] == before


def test_assist_keeps_the_slide_count_without_an_explicit_resize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    before = copy.deepcopy(row.slides)
    user, org = _ids(row)
    db = _DB(row)
    _wire_model(
        monkeypatch,
        {
            "reply": "Tightened the opening.",
            "slides": [{"title": "New intro", "bullets": ["Fresh"]}],
        },
    )

    result = asyncio.run(
        deck_ai.deck_assist(
            row.id, deck_ai.DeckAssistBody(message="Make the opening clearer."), user, org, db
        )
    )

    assert len(row.slides) == len(before)
    assert row.slides[0] == {"title": "New intro", "bullets": ["Fresh"]}
    assert row.slides[1] == before[1]
    assert row.slides[2] == before[2]
    assert result["changed_slides"] == [0]


def test_assist_resizes_when_the_message_asks_to_add_slides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    before = copy.deepcopy(row.slides)
    user, org = _ids(row)
    db = _DB(row)
    _wire_model(
        monkeypatch,
        {
            "reply": "Added a slide.",
            "slides": [
                *copy.deepcopy(before),
                {"title": "Assessment", "bullets": ["How marks work."]},
            ],
        },
    )

    result = asyncio.run(
        deck_ai.deck_assist(
            row.id,
            deck_ai.DeckAssistBody(message="Add a slide about assessment."),
            user,
            org,
            db,
        )
    )

    assert len(row.slides) == 4
    assert row.slides[:3] == before
    assert row.slides[3]["title"] == "Assessment"
    assert result["changed_slides"] == [3]


def test_assist_rejects_invalid_model_slides_and_leaves_the_deck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    before = copy.deepcopy(row.slides)
    user, org = _ids(row)
    db = _DB(row)
    _wire_model(
        monkeypatch,
        {"reply": "Bad result.", "slides": [{"title": "Broken", "bullets": [1, 2]}]},
    )

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            deck_ai.deck_assist(
                row.id, deck_ai.DeckAssistBody(message="Rewrite the deck."), user, org, db
            )
        )
    assert caught.value.status == 422
    assert row.slides == before
    assert row.storage_key == "org/course/slides.pptx"
    assert db.flushed == 0


def test_assist_reports_503_without_a_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row()
    before = copy.deepcopy(row.slides)
    user, org = _ids(row)
    db = _DB(row)

    async def fake_load_runtime(*args: object) -> None:
        return None

    monkeypatch.setattr(deck_ai, "load_runtime", fake_load_runtime)
    _clear_keys(monkeypatch)
    monkeypatch.setattr(llm, "key_configured", lambda _provider: False)

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            deck_ai.deck_assist(
                row.id, deck_ai.DeckAssistBody(message="Rewrite the deck."), user, org, db
            )
        )
    assert caught.value.status == 503
    assert row.slides == before
    assert db.flushed == 0


def test_assist_rejects_an_out_of_range_slide_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    user, org = _ids(row)
    db = _DB(row)

    def explode(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("The model must not be called for an out-of-range index.")

    monkeypatch.setattr(deck_ai.llm, "complete", explode)

    with pytest.raises(ProfassistError) as caught:
        asyncio.run(
            deck_ai.deck_assist(
                row.id, deck_ai.DeckAssistBody(message="Rewrite it.", slide_index=3), user, org, db
            )
        )
    assert caught.value.status == 400
    assert db.flushed == 0


def test_assist_applies_a_title_and_reports_changed_slides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    user, org = _ids(row)
    db = _DB(row)
    calls = _wire_model(
        monkeypatch,
        {
            "reply": "Sharpened the deck.",
            "title": "Sharper deck",
            "slides": [{"title": "New intro", "bullets": ["Fresh"]}],
        },
    )

    result = asyncio.run(
        deck_ai.deck_assist(
            row.id, deck_ai.DeckAssistBody(message="Make the deck sharper."), user, org, db
        )
    )

    assert result["reply"] == "Sharpened the deck."
    assert row.title == "Sharper deck"
    assert len(row.slides) == 3
    assert result["changed_slides"] == [0]
    assert result["deck"]["title"] == "Sharper deck"
    assert row.storage_key == ""
    payload = calls[0][1]
    assert payload["sources_note"] == "No new sources supplied. Do not invent sources."
    assert payload["message"] == "Make the deck sharper."
    assert payload["existing_deck"]["id"] == str(row.id)


def test_pptx_notes_prefer_speaker_notes() -> None:
    from pptx import Presentation

    data = build_pptx(
        "Deck",
        [
            {
                "title": "One idea",
                "bullets": ["Cite the note."],
                "speaker_notes": "Say this out loud.",
                "notes": "Old note.",
            }
        ],
    )
    presentation = Presentation(io.BytesIO(data))
    notes = [slide.notes_slide.notes_text_frame.text for slide in presentation.slides]

    assert "Say this out loud." in notes
    assert all("Old note." not in note for note in notes)


def test_slides_prompt_only_applies_to_an_existing_deck(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.runtime import bind_runtime

    bind_runtime({}, {}, {"provider": "openai", "model": "gpt-4o-mini", "agents": {}})
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls: list[dict[str, Any]] = []

    class Response:
        choices = [SimpleNamespace(message=SimpleNamespace(content=json.dumps({"reply": "ok"})))]

    def fake_generate(provider: str, model: str, messages: list[dict[str, str]], **kwargs: Any):
        calls.append({"messages": messages, "kwargs": kwargs})
        return Response()

    monkeypatch.setattr("app.profassist.providers.generate", fake_generate)

    llm.complete(
        "slides",
        {
            "title": "Deck",
            "slides": [],
            "existing_deck": {"title": "Deck", "slides": []},
            "message": "Tighten it.",
            "slide_index": 2,
            "sources_note": "No new sources supplied. Do not invent sources.",
            "preferences": ["Prefers shorter bullets"],
        },
    )
    system = calls[0]["messages"][0]["content"]
    assert '"slides"' in system
    assert '"reply"' in system
    assert "same number of slides" in system
    assert "slide index 2" in system
    assert "Do not invent sources" in system
    assert "slide preferences" in system
    assert "Prefers shorter bullets" in system

    llm.complete("slides", {"title": "Deck", "slides": []})
    plain = calls[1]["messages"][0]["content"]
    assert "## Deck edit" not in plain
    assert "slide preferences" not in plain


def test_deck_save_remembers_the_structured_slide_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row()
    before = copy.deepcopy(row.slides)
    user, org = _ids(row)
    db = _DB(row)
    calls: dict[str, Any] = {}

    async def fake_capture(*args: Any, **kwargs: Any) -> None:
        calls["capture"] = args

    async def fake_remember(
        db_: Any,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        old: Any,
        new: Any,
        source: str,
    ) -> list[str]:
        calls["remember"] = {
            "org_id": org_id,
            "user_id": user_id,
            "before": old,
            "after": new,
            "source": source,
        }
        return []

    monkeypatch.setattr(deck_ai, "capture_movement", fake_capture)
    monkeypatch.setattr(deck_ai, "remember_slide_edits", fake_remember)

    saved = [{"title": "Intro", "bullets": ["One"], "speaker_notes": "Say one."}]
    asyncio.run(deck_ai.deck_save(row.id, deck_ai.DeckSaveBody(slides=saved), user, org, db))

    assert calls["remember"]["before"] == before
    assert calls["remember"]["after"] == saved
    assert calls["remember"]["org_id"] == org.id
    assert calls["remember"]["user_id"] == user.id
    assert calls["remember"]["source"] == "deck-save"


def test_deck_save_survives_a_slide_memory_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row()
    user, org = _ids(row)
    db = _DB(row)

    async def explode(*args: Any, **kwargs: Any) -> list[str]:
        raise RuntimeError("memory down")

    monkeypatch.setattr(deck_ai, "remember_slide_edits", explode)

    result = asyncio.run(
        deck_ai.deck_save(
            row.id,
            deck_ai.DeckSaveBody(slides=[{"title": "Intro", "bullets": ["One"]}]),
            user,
            org,
            db,
        )
    )

    assert row.slides == [{"title": "Intro", "bullets": ["One"]}]
    assert result["slides"] == row.slides
