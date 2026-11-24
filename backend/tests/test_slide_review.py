"""Slide review: deterministic checks, the reviewer graph, the store, and the route."""

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import app.api.routes.v1.deck_ai as deck_ai
import app.profassist.agents as agents
import app.profassist.course_context as course_context
import app.profassist.course_memory.service as course_memory_service
import app.profassist.llm as llm
import app.profassist.slide_memory as slide_memory
from app.profassist import service
from app.profassist.errors import ProfassistError
from app.profassist.providers import AGENTS
from app.profassist.runtime import DEFAULT_PROMPTS

CITED = "Design an end-to-end AI solution (lecture.pdf)."
REVIEW = {
    "verdict": "pass",
    "score": 100,
    "issues": [],
    "strengths": ["Every bullet cites a file."],
    "checks": [],
    "trace_url": "http://trace/1",
    "degraded": False,
}


def _deck(slides: Any = None, **overrides: Any) -> dict[str, Any]:
    deck: dict[str, Any] = {
        "title": "Week 7: Architecture review",
        "slides": (
            [
                {
                    "title": "Architecture",
                    "objective": "Design an end-to-end AI solution.",
                    "bullets": [CITED],
                }
            ]
            if slides is None
            else slides
        ),
        "gaps": [],
    }
    deck.update(overrides)
    return deck


def _wire_llm(monkeypatch: pytest.MonkeyPatch, reply: Any) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_complete(task: str, payload: dict[str, Any]) -> Any:
        calls.append((task, payload))
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(agents.llm, "complete", fake_complete)
    return calls


def test_slide_review_migration_adds_and_drops_the_columns() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0040_slide_review.py"
    ).read_text(encoding="utf-8")

    assert 'revision = "0040_slide_review"' in source
    assert 'down_revision = "0039_course_dossier"' in source
    assert '"review"' in source
    assert '"review_trace_url"' in source
    dropped_url = source.index('op.drop_column("pa_slide_decks", "review_trace_url")')
    dropped_review = source.index('op.drop_column("pa_slide_decks", "review")')
    assert dropped_url < dropped_review


def test_slide_deck_model_carries_the_review() -> None:
    from app.profassist.models import SlideDeck

    assert "review" in SlideDeck.__table__.columns
    assert "review_trace_url" in SlideDeck.__table__.columns


# --- deterministic checks -------------------------------------------------


def test_slide_checks_find_missing_titles_bullets_and_citations() -> None:
    deck = _deck(
        slides=[
            {"title": "", "bullets": []},
            {"title": "Key idea", "bullets": ["An uncited claim."]},
        ]
    )
    checks = agents.slide_checks(deck)
    by_issue = {item["issue"]: item for item in checks}

    assert by_issue["The slide has no title."]["slide"] == "Slide 1"
    assert by_issue["The slide has no title."]["severity"] == "high"
    assert by_issue["The slide has no bullets."]["severity"] == "high"

    uncited = [item for item in checks if "no citation" in item["issue"]]
    assert len(uncited) == 1
    assert uncited[0]["severity"] == "medium"
    assert uncited[0]["slide"] == "Key idea"
    assert uncited[0]["fix"]


def test_slide_checks_flag_long_and_numerous_bullets() -> None:
    long_bullet = "x" * 260
    deck = _deck(slides=[{"title": "Busy", "bullets": [CITED, CITED, CITED, long_bullet]}])

    checks = agents.slide_checks(deck)
    low = [item for item in checks if item["severity"] == "low"]

    assert len(low) == 2
    assert any("4 bullets" in item["issue"] for item in low)
    assert any("260 characters" in item["issue"] for item in low)


def test_slide_checks_flag_gaps_and_duplicate_titles() -> None:
    deck = _deck(
        slides=[
            {"title": "Same", "bullets": [CITED]},
            {"title": "same", "bullets": [CITED]},
        ],
        gaps=["Ethics of deployment."],
    )

    checks = agents.slide_checks(deck)
    gap = next(item for item in checks if "No source passage" in item["issue"])
    duplicate = next(item for item in checks if "share the title" in item["issue"])

    assert gap["severity"] == "high"
    assert "Ethics of deployment." in gap["issue"]
    assert duplicate["severity"] == "medium"
    assert '"Same"' in duplicate["issue"]


def test_slide_checks_take_gaps_from_the_slides_too() -> None:
    deck = _deck(
        slides=[
            {
                "title": "Ethics",
                "objective": "Reason about the ethics of a deployment.",
                "bullets": [],
                "gap": True,
            }
        ]
    )

    checks = agents.slide_checks(deck)
    gap = next(item for item in checks if "No source passage" in item["issue"])

    assert gap["slide"] == "Ethics"
    assert "Reason about the ethics" in gap["issue"]


def test_missing_outline_weeks_are_info_and_capped() -> None:
    outline = {
        "weeks": [
            {"week": 1, "topic": "Architecture review"},
            {"week": 2, "topic": "Deployment ethics"},
            {"week": 3, "topic": "Model monitoring"},
            {"week": 4, "topic": "Data pipelines"},
        ]
    }
    deck = _deck(
        slides=[{"title": "Course overview", "objective": "Survey the course.", "bullets": [CITED]}]
    )

    checks = agents.slide_checks(deck, outline)
    info = [item for item in checks if item["severity"] == "info"]

    assert len(info) == agents.WEEK_GAP_CAP == 2
    assert all(item["slide"] == "Outline" for item in info)
    assert agents.review_score(checks) == 100


def test_a_covered_week_raises_no_info_issue() -> None:
    outline = {"weeks": [{"week": 7, "topic": "Architecture review"}]}
    deck = _deck(
        slides=[
            {
                "title": "Week 7: Architecture",
                "objective": "Review the architecture.",
                "bullets": [CITED],
            }
        ]
    )

    checks = agents.slide_checks(deck, outline)

    assert [item for item in checks if item["severity"] == "info"] == []


def test_review_score_uses_the_severity_weights() -> None:
    issues = [
        {"severity": "high"},
        {"severity": "medium"},
        {"severity": "low"},
        {"severity": "info"},
    ]

    assert agents.review_score(issues) == 67
    assert agents.review_score([{"severity": "high"}] * 6) == 0


# --- the reviewer graph ---------------------------------------------------


def test_run_slide_review_passes_a_clean_cited_deck(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _wire_llm(
        monkeypatch,
        {"verdict": "pass", "issues": [], "strengths": ["Every bullet cites a file."]},
    )

    review = agents.run_slide_review(_deck(), outline={}, dossier={"summary": "AI design."})

    assert review["verdict"] == "pass"
    assert review["score"] == 100
    assert review["issues"] == []
    assert review["strengths"] == ["Every bullet cites a file."]
    assert review["degraded"] is False
    assert review["trace_url"] == ""
    assert calls[-1][0] == "slide_review"
    chair_call = calls[-1][1]
    assert chair_call["dossier"] == {"summary": "AI design."}
    assert chair_call["checks"] == review["checks"]


def test_run_slide_review_merges_dedupes_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    deck = _deck(slides=[{"title": "", "bullets": []}])
    extra = [
        {
            "slide": "Slide 1",
            "severity": "high",
            "issue": "The slide has no title.",
            "fix": "Name the idea.",
        },
        *[
            {
                "slide": index,
                "severity": "medium",
                "issue": f"Model finding {index}",
                "fix": "Tighten.",
            }
            for index in range(1, 20)
        ],
    ]
    calls = _wire_llm(
        monkeypatch, {"verdict": "revise", "issues": extra, "strengths": ["One", "Two"]}
    )

    review = agents.run_slide_review(deck, preferences=["Prefers shorter bullets"])

    assert calls[0][1]["preferences"] == ["Prefers shorter bullets"]
    assert len(review["issues"]) == agents.MAX_REVIEW_ISSUES == 12
    titles = [item for item in review["issues"] if item["issue"] == "The slide has no title."]
    assert len(titles) == 1
    assert review["verdict"] == "revise"
    assert review["strengths"] == ["One", "Two"]
    assert review["degraded"] is False


def test_run_slide_review_degrades_without_any_code_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deck = _deck(slides=[{"title": "", "bullets": []}])
    _wire_llm(monkeypatch, ProfassistError(503, "No AI model is configured."))

    review = agents.run_slide_review(deck)

    assert review["degraded"] is True
    assert review["issues"] == []
    assert review["checks"] == []
    assert review["strengths"] == []
    assert review["verdict"] == "pass"
    assert review["score"] == 100


def test_run_slide_review_treats_a_non_dict_reply_as_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire_llm(monkeypatch, ["not", "an", "object"])

    review = agents.run_slide_review(_deck())

    assert review["degraded"] is True
    assert review["verdict"] == "pass"


def test_slide_review_prompt_and_agent_are_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.runtime import bind_runtime

    assert "slide_reviewer" in AGENTS
    assert "independent reviewer" in DEFAULT_PROMPTS["slide_review"]

    bind_runtime({}, {}, {"provider": "openai", "model": "gpt-4o-mini", "agents": {}})
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sent: list[list[dict[str, str]]] = []

    class Response:
        choices = [SimpleNamespace(message=SimpleNamespace(content='{"verdict": "pass"}'))]

    def fake_generate(
        provider: str, model: str, messages: list[dict[str, str]], **kwargs: Any
    ) -> Response:
        sent.append(messages)
        return Response()

    monkeypatch.setattr("app.profassist.providers.generate", fake_generate)

    llm.complete(
        "slide_review",
        {
            "deck": {"title": "Deck", "slides": []},
            "checks": [],
            "outline": {},
            "dossier": {},
            "preferences": [],
        },
    )

    system = sent[0][0]["content"]
    assert "independent reviewer" in system
    assert "never invent a source or a student name" in system.lower()


def test_slide_checks_tag_design_evidence_and_curriculum() -> None:
    deck = _deck(
        slides=[
            {"title": "", "bullets": []},
            {"title": "Uncited", "bullets": ["An uncited claim."]},
        ],
        gaps=["Ethics of deployment."],
    )
    outline = {
        "weeks": [{"week": 9, "topic": "Deployment ethics"}],
        "clos": [{"code": "LO9", "text": "Reason about deployment ethics."}],
    }

    checks = agents.slide_checks(deck, outline)
    reviewers = {item.get("code"): item.get("reviewer") for item in checks}

    assert reviewers["missing_title"] == "design"
    assert reviewers["no_bullets"] == "design"
    assert reviewers["missing_citation"] == "evidence"
    assert reviewers["gap"] == "evidence"
    assert reviewers["uncovered_week"] == "curriculum"
    assert reviewers["uncovered_outcome"] == "curriculum"
    assert reviewers["missing_objective"] == "curriculum"


def test_quote_check_runs_only_when_chunks_are_supplied() -> None:
    deck = _deck(
        slides=[
            {
                "title": "Architecture",
                "objective": "Design an end-to-end AI solution.",
                "bullets": [
                    {
                        "text": "The architecture names the audience.",
                        "citation": {
                            "filename": "lecture.pdf",
                            "quote": "A quote that is not in the note.",
                        },
                    }
                ],
            }
        ]
    )

    without_chunks = agents.slide_checks(deck)
    assert not any(item.get("code") == "unverified_quote" for item in without_chunks)

    chunks = [{"text": "The architecture must name the audience and the artefact."}]
    with_chunks = agents.slide_checks(deck, chunks=chunks)
    quote_issue = next(item for item in with_chunks if item.get("code") == "unverified_quote")

    assert quote_issue["reviewer"] == "evidence"
    assert quote_issue["severity"] == "medium"


def test_quote_check_ignores_whitespace_differences() -> None:
    deck = _deck(
        slides=[
            {
                "title": "Architecture",
                "objective": "Design an end-to-end AI solution.",
                "bullets": [
                    {
                        "text": "The architecture names the audience.",
                        "citation": {
                            "filename": "lecture.pdf",
                            "quote": "The  architecture must name\n the audience",
                        },
                    }
                ],
            }
        ]
    )
    chunks = [{"text": "The architecture must name the audience and the artefact."}]

    checks = agents.slide_checks(deck, chunks=chunks)

    assert not any(item.get("code") == "unverified_quote" for item in checks)


def test_run_slide_review_returns_four_council_messages_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire_llm(monkeypatch, {"verdict": "pass", "issues": [], "strengths": []})

    review = agents.run_slide_review(_deck())

    assert [item["role"] for item in review["messages"]] == [
        "curriculum",
        "evidence",
        "design",
        "chair",
    ]
    assert review["messages"][0]["text"] == "No issues from my pass."
    assert review["messages"][-1]["text"].startswith("The council verdict is pass")
    assert "100" in review["messages"][-1]["text"]


def test_the_chair_message_falls_back_when_the_model_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire_llm(monkeypatch, ProfassistError(503, "No AI model is configured."))

    review = agents.run_slide_review(_deck(slides=[{"title": "", "bullets": []}]))

    assert review["degraded"] is True
    assert [item["role"] for item in review["messages"]] == [
        "curriculum",
        "evidence",
        "design",
        "chair",
    ]
    chair = review["messages"][-1]["text"]
    assert review["verdict"] in chair
    assert str(review["score"]) in chair


def test_review_messages_synthesise_an_old_review() -> None:
    old = {
        "verdict": "revise",
        "score": 60,
        "issues": [
            {
                "slide": "Deck",
                "severity": "high",
                "issue": "No title.",
                "code": "missing_title",
            }
        ],
    }

    messages = agents.review_messages(old)

    assert [item["role"] for item in messages] == ["curriculum", "evidence", "design", "chair"]
    assert "No title." in messages[2]["text"]
    assert "revise" in messages[3]["text"]


# --- the store ------------------------------------------------------------


class _Empty:
    def scalars(self) -> "_Empty":
        return self

    def all(self) -> list[Any]:
        return []


class _DB:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = {row.id: row for row in rows or []}
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, statement: Any) -> _Empty:
        return _Empty()

    async def get(self, model: object, ident: uuid.UUID) -> Any:
        return self.rows.get(ident)

    def add(self, row: Any) -> None:
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        self.added.append(row)
        self.rows[row.id] = row

    async def flush(self) -> None:
        self.flushed += 1
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid.uuid4()


def _row(**overrides: Any) -> SimpleNamespace:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        title="Week 7: Architecture review",
        week=7,
        instructions="Keep it short.",
        slides=[{"title": "Architecture", "bullets": [CITED]}],
        status="draft",
        storage_key="",
        review={},
        review_trace_url="",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _wire_review_service(monkeypatch: pytest.MonkeyPatch, review: Any = REVIEW) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_outline(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_dossier(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"summary": "The course covers AI design."}

    async def fake_preferences(*args: Any, **kwargs: Any) -> list[str]:
        return ["Prefers shorter bullets"]

    async def fake_chunks(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": "c1", "text": CITED, "filename": "lecture.pdf"}]

    def fake_review(
        deck: dict[str, Any],
        outline: dict[str, Any] | None = None,
        dossier: dict[str, Any] | None = None,
        preferences: list[str] | None = None,
        chunks: list[dict[str, Any]] | None = None,
        council_roles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        captured.update(
            {
                "deck": deck,
                "outline": outline,
                "dossier": dossier,
                "preferences": preferences,
                "chunks": chunks,
                "council_roles": council_roles,
            }
        )
        if isinstance(review, Exception):
            raise review
        return dict(review)

    monkeypatch.setattr(service, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(course_context, "load_outline", fake_outline)
    monkeypatch.setattr(course_memory_service, "dossier_ai_context", fake_dossier)
    monkeypatch.setattr(slide_memory, "slide_preferences", fake_preferences)
    monkeypatch.setattr(service, "ready_chunks", fake_chunks)
    monkeypatch.setattr(service.agents, "run_slide_review", fake_review)
    return captured


@pytest.mark.anyio
async def test_review_deck_persists_the_review_for_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    captured = _wire_review_service(monkeypatch)
    db = _DB([row])
    org = SimpleNamespace(id=row.organization_id)
    user = SimpleNamespace(id=row.owner_user_id)

    result = await service.review_deck(db, org, user, row.id)

    assert result["review"]["verdict"] == "pass"
    assert result["trace_url"] == "http://trace/1"
    assert row.review["verdict"] == "pass"
    assert row.review_trace_url == "http://trace/1"
    assert db.flushed == 1
    assert captured["deck"]["title"] == row.title
    assert captured["deck"]["gaps"] == []
    assert captured["outline"] == {}
    assert captured["dossier"] == {"summary": "The course covers AI design."}
    assert captured["preferences"] == ["Prefers shorter bullets"]
    assert captured["chunks"] == [
        {"id": "c1", "text": CITED, "filename": "lecture.pdf", "section": "note"}
    ]


@pytest.mark.anyio
async def test_review_deck_hides_a_foreign_deck(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row()
    db = _DB([row])

    def explode(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("The reviewer must not run on a foreign deck.")

    monkeypatch.setattr(service.agents, "run_slide_review", explode)

    with pytest.raises(ProfassistError) as caught:
        await service.review_deck(
            db,
            SimpleNamespace(id=uuid.uuid4()),
            SimpleNamespace(id=row.owner_user_id),
            row.id,
        )
    assert caught.value.status == 404

    with pytest.raises(ProfassistError) as caught:
        await service.review_deck(
            db,
            SimpleNamespace(id=row.organization_id),
            SimpleNamespace(id=uuid.uuid4()),
            row.id,
        )
    assert caught.value.status == 404


# --- deck generation ------------------------------------------------------


def _wire_build(monkeypatch: pytest.MonkeyPatch, review: Any) -> tuple[Any, dict[str, Any]]:
    course = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        code="MAAI903",
        title="AI Solutions Design & MLOps",
        ai_instructions="",
        clos=[],
    )
    captured: dict[str, Any] = {}

    async def fake_load_runtime(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_course(*args: Any, **kwargs: Any) -> Any:
        return course

    async def fake_outline(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_objectives(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"text": "Design an end-to-end AI solution.", "status": "approved"}]

    async def fake_chunks(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": "c1", "text": CITED, "filename": "lecture.pdf"}]

    async def fake_style(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_dossier(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    async def fake_preferences(*args: Any, **kwargs: Any) -> list[str]:
        return ["Prefers shorter bullets"]

    def fake_studio(
        objectives: list[str], payload: list[dict[str, Any]], **kwargs: Any
    ) -> dict[str, Any]:
        return {
            "slides": [{"title": "Architecture", "bullets": [CITED]}],
            "gaps": ["Ethics of deployment."],
            "skill": "slide-studio",
            "pptx": b"",
        }

    def fake_review(
        deck: dict[str, Any],
        outline: dict[str, Any] | None = None,
        dossier: dict[str, Any] | None = None,
        preferences: list[str] | None = None,
        chunks: list[dict[str, Any]] | None = None,
        council_roles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        captured.update(
            {
                "deck": deck,
                "outline": outline,
                "dossier": dossier,
                "preferences": preferences,
                "chunks": chunks,
                "council_roles": council_roles,
            }
        )
        if isinstance(review, Exception):
            raise review
        return dict(review)

    monkeypatch.setattr(service, "load_runtime", fake_load_runtime)
    monkeypatch.setattr(service, "_course", fake_course)
    monkeypatch.setattr(service, "load_outline", fake_outline)
    monkeypatch.setattr(service, "list_objectives", fake_objectives)
    monkeypatch.setattr(service, "ready_chunks", fake_chunks)
    monkeypatch.setattr(service, "_style_row", fake_style)
    monkeypatch.setattr(service, "dossier_ai_context", fake_dossier)
    monkeypatch.setattr(service, "slide_preferences", fake_preferences)
    monkeypatch.setattr(service, "render_thumbnails", lambda plan: [])
    monkeypatch.setattr("app.profassist.skills.slide_studio.run_slide_studio", fake_studio)
    monkeypatch.setattr(service.agents, "run_slide_review", fake_review)
    return course, captured


@pytest.mark.anyio
async def test_build_cited_deck_reviews_the_new_deck(monkeypatch: pytest.MonkeyPatch) -> None:
    course, captured = _wire_build(monkeypatch, REVIEW)
    db = _DB()

    result = await service.build_cited_deck(db, course.organization_id, course.id, uuid.uuid4())

    assert result["review"]["verdict"] == "pass"
    assert result["review_trace_url"] == "http://trace/1"
    assert result["gaps"] == ["Ethics of deployment."]
    deck = next(row for row in db.added if row.__class__.__name__ == "SlideDeck")
    assert deck.review["score"] == 100
    assert deck.review_trace_url == "http://trace/1"
    assert captured["deck"]["gaps"] == ["Ethics of deployment."]
    assert captured["preferences"] == ["Prefers shorter bullets"]
    assert captured["chunks"] == [
        {"id": "c1", "text": CITED, "filename": "lecture.pdf", "section": "note"}
    ]
    assert db.flushed == 2


@pytest.mark.anyio
async def test_build_cited_deck_survives_a_failed_review(monkeypatch: pytest.MonkeyPatch) -> None:
    course, _captured = _wire_build(monkeypatch, RuntimeError("review down"))
    db = _DB()

    result = await service.build_cited_deck(db, course.organization_id, course.id, uuid.uuid4())

    assert result["review"] == {}
    assert result["review_trace_url"] == ""
    deck = next(row for row in db.added if row.__class__.__name__ == "SlideDeck")
    assert not deck.review
    assert not deck.review_trace_url
    assert db.flushed == 1


# --- the route ------------------------------------------------------------


def test_slide_review_route_is_registered() -> None:
    from app.core.config import settings
    from app.main import app

    paths = app.openapi()["paths"]
    base = f"{settings.API_V1_STR}/profassist/slides/{{deck_id}}"
    assert "post" in paths[f"{base}/review"]


def test_review_route_delegates_to_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, Any, Any, uuid.UUID]] = []

    async def fake_review(db: Any, org: Any, user: Any, deck_id: uuid.UUID) -> dict[str, Any]:
        calls.append((db, org, user, deck_id))
        return {"review": {"verdict": "pass"}, "trace_url": ""}

    monkeypatch.setattr(deck_ai, "review_deck", fake_review)
    deck_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4())
    org = SimpleNamespace(id=uuid.uuid4())
    db = object()

    result = asyncio.run(deck_ai.deck_review(deck_id, user, org, db))

    assert result["review"]["verdict"] == "pass"
    assert calls == [(db, org, user, deck_id)]
