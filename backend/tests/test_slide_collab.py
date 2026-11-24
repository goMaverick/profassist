"""Material Studio collaboration: repair rules, the job registry, the loop, SSE."""

import copy
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

import app.api.routes.v1.studio_collab as studio_collab
import app.profassist.slide_collab as slide_collab
from app.profassist import agents, service
from app.profassist.council_config import default_roles
from app.profassist.errors import ProfassistError

CITED = "Retrieval grounds the answer in the course notes (lecture.pdf)."


def _deck(slides: list[dict[str, Any]], gaps: list[str] | None = None) -> dict[str, Any]:
    return {"title": "Deck", "slides": slides, "gaps": gaps or []}


# --- stable issue codes ---------------------------------------------------


def test_slide_checks_carry_stable_codes() -> None:
    deck = _deck(
        slides=[
            {"title": "", "bullets": []},
            {"title": "Busy", "bullets": ["x" * 260, CITED, CITED, CITED]},
            {"title": "Same", "bullets": [CITED]},
            {"title": "same", "bullets": [CITED]},
        ],
        gaps=["Ethics of deployment."],
    )
    outline = {"weeks": [{"week": 3, "topic": "Deployment ethics"}]}

    codes = {item.get("code") for item in agents.slide_checks(deck, outline)}

    assert codes == {
        "missing_title",
        "no_bullets",
        "missing_citation",
        "too_many_bullets",
        "long_bullet",
        "duplicate_title",
        "gap",
        "uncovered_week",
        "missing_objective",
    }


def test_llm_only_issues_may_have_no_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task != "slide_review":
            return {"issues": []}
        return {
            "verdict": "revise",
            "issues": [
                {
                    "slide": "Deck",
                    "severity": "medium",
                    "issue": "The flow is abrupt.",
                    "fix": "Reorder.",
                }
            ],
        }

    monkeypatch.setattr(agents.llm, "complete", fake_complete)
    roles = default_roles("material")
    next(role for role in roles if role["role_key"] == "design")["kind"] = "deterministic"

    review = agents.run_slide_review(_deck([{"title": "", "bullets": []}]), council_roles=roles)

    llm_issue = next(item for item in review["issues"] if item["issue"] == "The flow is abrupt.")
    assert "code" not in llm_issue
    title_issue = next(
        item for item in review["issues"] if item["issue"] == "The slide has no title."
    )
    assert title_issue["code"] == "missing_title"


# --- structural repair ----------------------------------------------------


def test_repair_titles_bullets_and_duplicates() -> None:
    slides = [
        {"objective": "Explain retrieval", "bullets": [{"text": CITED}]},
        {"title": "Same", "bullets": [CITED, CITED, CITED, CITED]},
        {"title": "same", "bullets": [CITED]},
    ]
    original = copy.deepcopy(slides)

    repaired, count, notes = slide_collab.repair_slides(slides, [], [], [])

    assert repaired[0]["title"] == "Explain retrieval"
    assert repaired[1]["title"] == "Same"
    assert repaired[2]["title"] == "same (2)"
    assert repaired[1]["bullets"] == [CITED, CITED, CITED]
    assert count == 3
    assert len(notes) == 3
    assert slides == original


def test_repair_falls_back_to_the_objective_then_untitled() -> None:
    repaired, count, _notes = slide_collab.repair_slides(
        [{"bullets": [CITED]}], [], [], ["Compare the two models"]
    )
    assert repaired[0]["title"] == "Compare the two models"
    assert count == 1

    blank, blank_count, _notes = slide_collab.repair_slides(
        [{"title": "   ", "bullets": [CITED]}], [], [], []
    )
    assert blank[0]["title"] == "Untitled slide"
    assert blank_count == 1


def test_repair_truncates_a_long_bullet_and_keeps_the_quote() -> None:
    quote = "A verbatim passage from the notes."
    bullet = {
        "text": "x" * 260,
        "citation": {
            "filename": "lecture.pdf",
            "section": "note",
            "quote": quote,
            "chunk_id": "c1",
        },
    }

    repaired, count, _notes = slide_collab.repair_slides(
        [{"title": "Long", "bullets": [bullet]}], [], [], []
    )

    assert len(repaired[0]["bullets"][0]["text"]) == slide_collab.MAX_BULLET_CHARS
    assert repaired[0]["bullets"][0]["citation"]["quote"] == quote
    assert repaired[0]["bullets"][0]["citation"]["filename"] == "lecture.pdf"
    assert count == 1


def test_repair_attaches_a_citation_from_the_notes() -> None:
    chunks = [
        {
            "id": "c9",
            "text": "Retrieval grounds the answer in the course notes, so the claim is traceable.",
            "filename": "week7.pdf",
        }
    ]
    slides = [{"title": "Retrieval", "bullets": [{"text": "Retrieval grounds the answer"}]}]

    repaired, count, notes = slide_collab.repair_slides(slides, chunks, [], [])

    bullet = repaired[0]["bullets"][0]
    assert bullet["citation"]["filename"] == "week7.pdf"
    assert bullet["citation"]["section"] == "note"
    assert bullet["citation"]["chunk_id"] == "c9"
    assert "Retrieval grounds the answer" in bullet["citation"]["quote"]
    assert count == 1
    assert any("attached a citation" in note for note in notes)


def test_repair_matches_a_paraphrased_bullet_by_keyword_overlap() -> None:
    chunks = [
        {
            "id": "c1",
            "text": "Monitoring catches drift early once a model is deployed.",
            "filename": "ops.md",
        }
    ]
    slides = [{"title": "Ops", "bullets": [{"text": "Monitoring catches drift"}]}]

    repaired, count, _notes = slide_collab.repair_slides(slides, chunks, [], [])

    assert repaired[0]["bullets"][0]["citation"]["filename"] == "ops.md"
    assert count == 1


def test_repair_never_invents_a_source() -> None:
    slides = [{"title": "Ethics", "bullets": [{"text": "Deployment ethics need a review board."}]}]

    repaired, count, notes = slide_collab.repair_slides(slides, [], [], [])

    bullet = repaired[0]["bullets"][0]
    assert "citation" not in bullet
    assert bullet["text"] == "Deployment ethics need a review board."
    assert repaired[0]["gap"] is True
    assert repaired[0]["notes"] == slide_collab.GAP_NOTE
    assert count == 1
    assert any("gap" in note for note in notes)


def test_repair_is_idempotent_for_a_gap() -> None:
    slides = [{"title": "Ethics", "bullets": [{"text": "No note covers this claim."}]}]

    first, first_count, _notes = slide_collab.repair_slides(slides, [], [], [])
    second, second_count, _notes = slide_collab.repair_slides(first, [], [], [])

    assert first_count == 1
    assert second_count == 0
    assert second == first


def test_repair_skips_a_review_with_no_structural_code() -> None:
    slides = [{"title": "", "bullets": [CITED]}]
    issues = [{"slide": "Deck", "severity": "high", "issue": "Gap.", "code": "gap"}]

    repaired, count, _notes = slide_collab.repair_slides(slides, [], issues, [])

    assert count == 0
    assert repaired[0]["title"] == ""


# --- the job registry -----------------------------------------------------


def test_job_registry_is_org_and_user_scoped() -> None:
    org, user = uuid.uuid4(), uuid.uuid4()
    job_id = slide_collab.create_job(org, user, uuid.uuid4(), 3, "Keep it short.")

    job = slide_collab.get_job(job_id, org, user)
    assert job["id"] == job_id
    assert job["week"] == 3
    assert job["instructions"] == "Keep it short."
    assert job["stop"] is False
    assert job["done"] is False
    assert job["deck_id"] == ""
    assert isinstance(job["created"], datetime)

    with pytest.raises(ProfassistError) as caught:
        slide_collab.get_job(job_id, uuid.uuid4(), user)
    assert caught.value.status == 404

    with pytest.raises(ProfassistError) as caught:
        slide_collab.get_job(job_id, org, uuid.uuid4())
    assert caught.value.status == 404


def test_pause_and_finish_update_only_the_owners_job() -> None:
    org, user = uuid.uuid4(), uuid.uuid4()
    job_id = slide_collab.create_job(
        SimpleNamespace(id=org), SimpleNamespace(id=user), uuid.uuid4()
    )

    slide_collab.pause_job(job_id, org, user)
    assert slide_collab.get_job(job_id, org, user)["stop"] is True

    deck_id = uuid.uuid4()
    slide_collab.finish_job(job_id, org, user, deck_id)
    job = slide_collab.get_job(job_id, org, user)
    assert job["done"] is True
    assert job["deck_id"] == str(deck_id)

    with pytest.raises(ProfassistError) as caught:
        slide_collab.pause_job(job_id, org, uuid.uuid4())
    assert caught.value.status == 404


def test_jobs_older_than_thirty_minutes_are_removed() -> None:
    org, user = uuid.uuid4(), uuid.uuid4()
    job_id = slide_collab.create_job(org, user, uuid.uuid4())
    slide_collab.get_job(job_id, org, user)["created"] = datetime.now(UTC) - timedelta(minutes=31)

    assert slide_collab.cleanup_jobs() >= 1

    with pytest.raises(ProfassistError) as caught:
        slide_collab.get_job(job_id, org, user)
    assert caught.value.status == 404


# --- the collaboration loop ------------------------------------------------


class _DB:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = {row.id: row for row in rows or []}
        self.flushed = 0
        self.committed = 0
        self.log: list[str] = []

    async def get(self, model: object, ident: uuid.UUID) -> Any:
        return self.rows.get(ident)

    async def flush(self) -> None:
        self.flushed += 1
        self.log.append("flush")

    async def commit(self) -> None:
        self.committed += 1
        self.log.append("commit")


def _row(slides: list[Any], **overrides: Any) -> SimpleNamespace:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        title="Week 3: Retrieval",
        slides=slides,
        status="draft",
        storage_key="org/course/deck.pptx",
        week=3,
        instructions="",
        review={},
        review_trace_url="",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    row: SimpleNamespace,
    reviews: list[dict[str, Any]],
    chunks: list[dict[str, Any]] | None = None,
) -> tuple[_DB, dict[str, int]]:
    db = _DB([row])
    row.review = dict(reviews[0])
    calls = {"build": 0, "review": 0}

    async def fake_build(
        db_: Any, org: Any, course: Any, user: Any, week: int, instructions: str
    ) -> dict[str, Any]:
        calls["build"] += 1
        db.log.append("build")
        return {"id": str(row.id), "slides": list(row.slides), "review": dict(row.review)}

    async def fake_review(db_: Any, org: Any, user: Any, deck_id: uuid.UUID) -> dict[str, Any]:
        calls["review"] += 1
        db.log.append("review")
        review = dict(reviews[min(calls["review"], len(reviews) - 1)])
        row.review = review
        row.review_trace_url = str(review.get("trace_url") or "")
        return {"review": review, "trace_url": row.review_trace_url}

    async def fake_chunks(db_: Any, org: Any, user: Any, course: Any) -> list[dict[str, Any]]:
        return list(chunks or [])

    monkeypatch.setattr(service, "build_cited_deck", fake_build)
    monkeypatch.setattr(service, "review_deck", fake_review)
    monkeypatch.setattr(slide_collab, "ready_chunks", fake_chunks)
    monkeypatch.setattr(slide_collab, "MESSAGE_PAUSE", 0)
    monkeypatch.setattr(
        service, "_deck_dict", lambda row: {"id": str(row.id), "slides": list(row.slides)}
    )
    return db, calls


@pytest.mark.anyio
async def test_loop_repairs_then_stops_on_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    slides = [
        {"objective": "Explain retrieval", "bullets": [{"text": "Retrieval grounds the answer"}]},
        {"title": "Retrieval", "bullets": [{"text": "Retrieval grounds the answer"}]},
    ]
    row = _row(copy.deepcopy(slides))
    revise = {
        "verdict": "revise",
        "score": 60,
        "issues": [
            {"code": "missing_title", "severity": "high", "issue": "No title.", "fix": "Name it."},
            {"code": "missing_citation", "severity": "medium", "issue": "No cite.", "fix": "Cite."},
        ],
        "trace_url": "",
    }
    passed = {"verdict": "pass", "score": 100, "issues": [], "trace_url": "http://trace/2"}
    db, calls = _wire(
        monkeypatch,
        row,
        [revise, passed],
        chunks=[
            {
                "id": "c1",
                "text": "Retrieval grounds the answer in the notes.",
                "filename": "week3.pdf",
            }
        ],
    )
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id, 3, "")
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)

    events = [event async for event in slide_collab.collaboration_events(job, db)]

    assert events[0]["type"] == "start"
    assert events[0]["creator"] == "Creator"
    assert events[0]["reviewer"] == "Reviewer"
    assert events[1] == {"type": "typing", "role": "creator"}
    assert events[2]["role"] == "creator"
    assert events[2]["text"].startswith("I drafted 2 slides")
    messages = [event for event in events if event["type"] == "message"]
    council = [
        event
        for event in messages
        if event["role"] in {"curriculum", "evidence", "design", "chair"}
    ]
    assert [event["role"] for event in council[:4]] == [
        "curriculum",
        "evidence",
        "design",
        "chair",
    ]
    assert "No title." in council[2]["text"]
    assert "revise" in council[3]["text"] and "60" in council[3]["text"]
    fixed = next(event for event in messages if event["text"].startswith("I fixed"))
    assert fixed["text"].startswith("I fixed 3 issues")
    assert [event["role"] for event in council[4:8]] == [
        "curriculum",
        "evidence",
        "design",
        "chair",
    ]
    assert "pass" in council[7]["text"]
    final = events[-1]
    assert final["job_id"] == job_id
    assert final["paused"] is False
    assert final["deck"]["id"] == str(row.id)
    assert final["deck"]["status"] == "draft"
    assert "slides" not in final["deck"]
    assert "previews" not in final["deck"]
    assert final["review"]["verdict"] == "pass"
    assert final["trace_url"] == "http://trace/2"
    assert row.slides[0]["title"] == "Explain retrieval"
    assert row.slides[1]["bullets"][0]["citation"]["filename"] == "week3.pdf"
    assert db.flushed == 1
    # One commit for the build, one for the repaired slides, one for the review.
    assert db.committed == 3
    assert calls == {"build": 1, "review": 1}
    assert slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)["done"] is True


@pytest.mark.anyio
async def test_repair_clears_the_stale_review_before_re_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slides = [{"bullets": [{"text": "Retrieval grounds the answer"}]}]
    row = _row(
        copy.deepcopy(slides),
        review={"verdict": "pass", "score": 100},
        review_trace_url="http://trace/old",
    )
    db = _DB([row])
    revise = {
        "verdict": "revise",
        "score": 40,
        "issues": [
            {"code": "missing_title", "severity": "high", "issue": "No title.", "fix": "Name it."}
        ],
        "trace_url": "http://trace/old",
    }
    seen_entry: list[dict[str, Any]] = []

    async def fake_build(
        db_: Any, org: Any, course: Any, user: Any, week: int, instructions: str
    ) -> dict[str, Any]:
        row.review = dict(revise)
        return {"id": str(row.id), "slides": list(row.slides), "review": dict(revise)}

    async def fake_review(db_: Any, org: Any, user: Any, deck_id: uuid.UUID) -> dict[str, Any]:
        seen_entry.append({"review": dict(row.review), "trace": str(row.review_trace_url)})
        fresh = {"verdict": "pass", "score": 100, "issues": [], "trace_url": "http://trace/new"}
        row.review = fresh
        row.review_trace_url = "http://trace/new"
        return {"review": fresh, "trace_url": "http://trace/new"}

    async def fake_chunks(db_: Any, org: Any, user: Any, course: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "c1",
                "text": "Retrieval grounds the answer in the notes.",
                "filename": "week3.pdf",
            }
        ]

    monkeypatch.setattr(service, "build_cited_deck", fake_build)
    monkeypatch.setattr(service, "review_deck", fake_review)
    monkeypatch.setattr(slide_collab, "ready_chunks", fake_chunks)
    monkeypatch.setattr(slide_collab, "MESSAGE_PAUSE", 0)

    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id, 3, "")
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)
    events = [event async for event in slide_collab.collaboration_events(job, db)]

    assert len(seen_entry) == 1
    assert seen_entry[0]["review"] == {}
    assert seen_entry[0]["trace"] == ""
    assert row.review_trace_url == "http://trace/new"
    assert events[-1]["trace_url"] == "http://trace/new"


@pytest.mark.anyio
async def test_loop_stops_when_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    slides = [{"title": "Retrieval", "bullets": [{"text": "Retrieval grounds the answer"}]}]
    row = _row(copy.deepcopy(slides))
    revise = {
        "verdict": "revise",
        "score": 40,
        "issues": [
            {"code": "missing_citation", "severity": "medium", "issue": "No cite.", "fix": "Cite."}
        ],
        "trace_url": "",
    }
    db, calls = _wire(monkeypatch, row, [revise], chunks=[])
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    slide_collab.pause_job(job_id, row.organization_id, row.owner_user_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)

    events = [event async for event in slide_collab.collaboration_events(job, db)]

    texts = [event.get("text", "") for event in events if event["type"] == "message"]
    assert "Paused. I am keeping the current draft as-is." in texts
    assert not any(text.startswith("I fixed") for text in texts)
    assert events[-1]["paused"] is True
    assert row.slides == slides
    assert row.storage_key == "org/course/deck.pptx"
    assert calls == {"build": 1, "review": 0}
    assert db.flushed == 0
    # The draft is committed before the pause is noticed.
    assert db.committed == 1


@pytest.mark.anyio
async def test_loop_stops_right_after_the_build_when_paused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slides = [{"title": "Retrieval", "bullets": [{"text": "Retrieval grounds the answer"}]}]
    row = _row(copy.deepcopy(slides))
    revise = {
        "verdict": "revise",
        "score": 40,
        "issues": [
            {"code": "missing_citation", "severity": "medium", "issue": "No cite.", "fix": "Cite."}
        ],
        "trace_url": "",
    }
    db, calls = _wire(monkeypatch, row, [revise], chunks=[])
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)
    build = service.build_cited_deck

    async def pause_during_build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = await build(*args, **kwargs)
        slide_collab.pause_job(job_id, row.organization_id, row.owner_user_id)
        return result

    monkeypatch.setattr(service, "build_cited_deck", pause_during_build)

    events = [event async for event in slide_collab.collaboration_events(job, db)]

    messages = [
        (event.get("role"), event.get("text")) for event in events if event["type"] == "message"
    ]
    assert messages[0][0] == "creator"
    assert messages[0][1].startswith("I drafted 1 slides")
    assert messages[1] == ("creator", "Paused. I am keeping the current draft as-is.")
    assert not any(role == "reviewer" for role, _text in messages)
    assert not any(str(text).startswith("I fixed") for _role, text in messages)
    assert events[-1]["type"] == "final"
    assert events[-1]["paused"] is True
    assert events[-1]["deck"]["id"] == str(row.id)
    assert calls == {"build": 1, "review": 0}
    assert db.flushed == 0
    # Only the draft is committed; no repair commits happen after a pause.
    assert db.committed == 1
    assert row.slides == slides


@pytest.mark.anyio
async def test_loop_runs_at_most_two_repair_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row([{"title": "Retrieval", "bullets": [{"text": "Retrieval grounds the answer"}]}])
    revise = {
        "verdict": "revise",
        "score": 40,
        "issues": [
            {"code": "missing_citation", "severity": "medium", "issue": "No cite.", "fix": "Cite."}
        ],
        "trace_url": "",
    }
    db, calls = _wire(monkeypatch, row, [revise, revise, revise, revise], chunks=[])

    def fake_repair(
        slides: list[Any],
        chunks: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        objectives: list[str],
    ) -> tuple[list[Any], int, list[str]]:
        return [dict(slide) for slide in slides], 1, ["Tightened a bullet."]

    monkeypatch.setattr(slide_collab, "repair_slides", fake_repair)
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)

    events = [event async for event in slide_collab.collaboration_events(job, db)]

    fixed = [
        event
        for event in events
        if event["type"] == "message" and event.get("text", "").startswith("I fixed")
    ]
    assert len(fixed) == 2
    assert calls == {"build": 1, "review": 2}
    assert events[-1]["paused"] is False


@pytest.mark.anyio
async def test_loop_leaves_gaps_when_nothing_can_be_repaired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slides = [{"title": "Ethics", "bullets": [{"text": "Ethics needs a review board."}]}]
    row = _row(copy.deepcopy(slides))
    revise = {
        "verdict": "revise",
        "score": 80,
        "issues": [
            {
                "code": "gap",
                "severity": "high",
                "issue": "No source passage covers ethics.",
                "fix": "Upload a note.",
            }
        ],
        "trace_url": "",
    }
    db, calls = _wire(monkeypatch, row, [revise], chunks=[])
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)

    events = [event async for event in slide_collab.collaboration_events(job, db)]

    texts = [event.get("text", "") for event in events]
    assert "I cannot fix these without inventing content; I am leaving them as gaps." in texts
    assert calls == {"build": 1, "review": 0}
    assert row.slides == slides
    assert events[-1]["deck"]["id"] == str(row.id)
    assert "slides" not in events[-1]["deck"]


@pytest.mark.anyio
async def test_loop_reports_a_builder_error_without_a_deck(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row([{"title": "Retrieval", "bullets": [CITED]}])
    db = _DB([row])

    async def explode(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ProfassistError(400, "Approve an objective before building a cited deck.")

    monkeypatch.setattr(service, "build_cited_deck", explode)
    monkeypatch.setattr(slide_collab, "MESSAGE_PAUSE", 0)
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)

    events = [event async for event in slide_collab.collaboration_events(job, db)]

    assert [event["type"] for event in events] == ["start", "typing", "error", "final"]
    assert events[2]["text"] == "Approve an objective before building a cited deck."
    final = events[-1]
    assert final["deck"] is None
    assert final["review"] == {}
    assert final["trace_url"] == ""
    assert final["paused"] is False
    assert slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)["done"] is True


@pytest.mark.anyio
async def test_loop_reports_an_unexpected_builder_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row([{"title": "Retrieval", "bullets": [CITED]}])
    db = _DB([row])

    async def explode(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("the vector store is offline")

    monkeypatch.setattr(service, "build_cited_deck", explode)
    monkeypatch.setattr(slide_collab, "MESSAGE_PAUSE", 0)
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)

    events = [event async for event in slide_collab.collaboration_events(job, db)]

    assert [event["type"] for event in events] == ["start", "typing", "error", "final"]
    assert "the vector store is offline" in events[2]["text"]
    assert len(events[2]["text"]) <= 300
    assert events[-1]["deck"] is None
    assert events[-1]["review"] == {}
    assert slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)["done"] is True


@pytest.mark.anyio
async def test_loop_reports_an_unexpected_reviewer_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row([{"title": "Retrieval", "bullets": [{"text": "Retrieval grounds the answer"}]}])
    revise = {
        "verdict": "revise",
        "score": 40,
        "issues": [
            {"code": "missing_citation", "severity": "medium", "issue": "No cite.", "fix": "Cite."}
        ],
        "trace_url": "",
    }
    db, calls = _wire(monkeypatch, row, [revise], chunks=[])

    async def explode(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("the reviewer model crashed")

    monkeypatch.setattr(service, "review_deck", explode)
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)

    events = [event async for event in slide_collab.collaboration_events(job, db)]

    types = [event["type"] for event in events]
    assert types[-2:] == ["error", "final"]
    error = next(event for event in events if event["type"] == "error")
    assert "the reviewer model crashed" in error["text"]
    final = events[-1]
    assert final["deck"] is not None
    assert final["deck"]["id"] == str(row.id)
    assert calls["build"] == 1
    assert slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)["done"] is True


@pytest.mark.anyio
async def test_loop_commits_after_build_and_after_each_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slides = [{"objective": "Explain retrieval", "bullets": [{"text": "Retrieval grounds it"}]}]
    row = _row(copy.deepcopy(slides))
    revise = {
        "verdict": "revise",
        "score": 60,
        "issues": [
            {"code": "missing_title", "severity": "high", "issue": "No title.", "fix": "Name it."}
        ],
        "trace_url": "",
    }
    passed = {"verdict": "pass", "score": 100, "issues": [], "trace_url": ""}
    db, calls = _wire(monkeypatch, row, [revise, passed], chunks=[])

    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)

    _events = [event async for event in slide_collab.collaboration_events(job, db)]

    # The build is committed before anything else, and every repair round
    # commits the flushed slides and the fresh review.
    assert db.log[:2] == ["build", "commit"]
    assert db.log[2:5] == ["flush", "commit", "review"]
    assert db.log[5] == "commit"
    assert db.committed == 3
    assert calls == {"build": 1, "review": 1}


@pytest.mark.anyio
async def test_a_second_stream_does_not_rebuild_the_deck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row([{"title": "Retrieval", "bullets": [CITED]}])
    passed = {"verdict": "pass", "score": 100, "issues": [], "trace_url": ""}
    db, calls = _wire(monkeypatch, row, [passed])
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)

    first = [event async for event in slide_collab.collaboration_events(job, db)]
    second = [event async for event in slide_collab.collaboration_events(job, db)]

    assert first[-1]["type"] == "final"
    assert calls["build"] == 1
    assert [event["type"] for event in second] == ["final"]
    assert second[-1]["deck"]["id"] == str(row.id)


@pytest.mark.anyio
async def test_a_second_stream_without_a_deck_reports_already_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row([{"title": "Retrieval", "bullets": [CITED]}])
    passed = {"verdict": "pass", "score": 100, "issues": [], "trace_url": ""}
    db, calls = _wire(monkeypatch, row, [passed])
    job_id = slide_collab.create_job(row.organization_id, row.owner_user_id, row.course_id)
    job = slide_collab.get_job(job_id, row.organization_id, row.owner_user_id)
    assert slide_collab._claim_job(job) is True

    events = [event async for event in slide_collab.collaboration_events(job, db)]

    assert [event["type"] for event in events] == ["error", "final"]
    assert events[0]["text"] == "This collaboration is already running."
    assert events[-1]["deck"] is None
    assert calls["build"] == 0


# --- routes ---------------------------------------------------------------


def test_collaborate_routes_are_registered() -> None:
    from app.core.config import settings
    from app.main import app

    paths = app.openapi()["paths"]
    base = f"{settings.API_V1_STR}/profassist"
    assert "post" in paths[f"{base}/courses/{{course_id}}/slides/collaborate"]
    assert "get" in paths[f"{base}/slides/collaborate/{{job_id}}/stream"]
    assert "post" in paths[f"{base}/slides/collaborate/{{job_id}}/pause"]
    assert "get" in paths[f"{base}/slides/collaborate/{{job_id}}"]


@pytest.mark.anyio
async def test_collaborate_routes_require_authentication(client) -> None:
    from app.core.config import settings

    base = f"{settings.API_V1_STR}/profassist"
    course_id, job_id = uuid.uuid4(), uuid.uuid4()

    start = await client.post(f"{base}/courses/{course_id}/slides/collaborate", json={})
    stream = await client.get(f"{base}/slides/collaborate/{job_id}/stream")
    pause = await client.post(f"{base}/slides/collaborate/{job_id}/pause")

    assert start.status_code == 401, start.text
    assert stream.status_code == 401, stream.text
    assert pause.status_code == 401, pause.text


@pytest.mark.anyio
async def test_collaborate_hides_a_foreign_course(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(*args: Any, **kwargs: Any) -> None:
        raise ProfassistError(404, "Course not found in this workspace")

    monkeypatch.setattr(service, "_course", missing)

    with pytest.raises(ProfassistError) as caught:
        await studio_collab.slides_collaborate(
            uuid.uuid4(),
            studio_collab.CollaborateBody(),
            SimpleNamespace(id=uuid.uuid4()),
            SimpleNamespace(id=uuid.uuid4()),
            object(),
        )
    assert caught.value.status == 404


@pytest.mark.anyio
async def test_collaborate_creates_a_job_for_an_owned_course(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def owned(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace()

    def fake_create(org: Any, user: Any, course: Any, week: int, instructions: str) -> str:
        captured.update(
            {"org": org, "user": user, "course": course, "week": week, "instructions": instructions}
        )
        return "job-1"

    monkeypatch.setattr(service, "_course", owned)
    monkeypatch.setattr(studio_collab, "create_job", fake_create)
    user, org, course = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    result = await studio_collab.slides_collaborate(
        course,
        studio_collab.CollaborateBody(week=4, instructions="Keep it short."),
        SimpleNamespace(id=user),
        SimpleNamespace(id=org),
        object(),
    )

    assert result == {"job_id": "job-1"}
    assert captured == {
        "org": org,
        "user": user,
        "course": course,
        "week": 4,
        "instructions": "Keep it short.",
    }


@pytest.mark.anyio
async def test_collaborate_rejects_an_out_of_range_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def owned(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace()

    monkeypatch.setattr(service, "_course", owned)

    for week in (-1, 53):
        with pytest.raises(ProfassistError) as caught:
            await studio_collab.slides_collaborate(
                uuid.uuid4(),
                studio_collab.CollaborateBody(week=week),
                SimpleNamespace(id=uuid.uuid4()),
                SimpleNamespace(id=uuid.uuid4()),
                object(),
            )
        assert caught.value.status == 400


@pytest.mark.anyio
async def test_pause_route_hides_a_foreign_job() -> None:
    org, user = uuid.uuid4(), uuid.uuid4()
    job_id = slide_collab.create_job(org, user, uuid.uuid4())

    result = await studio_collab.slides_collaborate_pause(
        job_id, SimpleNamespace(id=user), SimpleNamespace(id=org)
    )

    assert result == {"paused": True}
    assert slide_collab.get_job(job_id, org, user)["stop"] is True

    with pytest.raises(ProfassistError) as caught:
        await studio_collab.slides_collaborate_pause(
            job_id, SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=org)
        )
    assert caught.value.status == 404


@pytest.mark.anyio
async def test_status_route_reports_the_job() -> None:
    org, user = uuid.uuid4(), uuid.uuid4()
    job_id = slide_collab.create_job(org, user, uuid.uuid4())

    result = await studio_collab.slides_collaborate_status(
        job_id, SimpleNamespace(id=user), SimpleNamespace(id=org)
    )

    assert result == {"job_id": job_id, "done": False, "paused": False, "deck_id": ""}


@pytest.mark.anyio
async def test_stream_route_encodes_the_events(monkeypatch: pytest.MonkeyPatch) -> None:
    org, user = uuid.uuid4(), uuid.uuid4()
    job_id = slide_collab.create_job(org, user, uuid.uuid4())

    async def fake_events(job, db):
        yield {"type": "start", "job_id": job["id"]}
        yield {"type": "final", "deck": None}

    monkeypatch.setattr(studio_collab, "collaboration_events", fake_events)

    response = await studio_collab.slides_collaborate_stream(
        job_id, SimpleNamespace(id=user), SimpleNamespace(id=org), object()
    )
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert response.media_type == "text/event-stream"
    assert body == (
        b'data: {"type": "start", "job_id": "'
        + job_id.encode()
        + b'"}\n\ndata: {"type": "final", "deck": null}\n\n'
    )


@pytest.mark.anyio
async def test_stream_route_hides_a_foreign_job() -> None:
    org, user = uuid.uuid4(), uuid.uuid4()
    job_id = slide_collab.create_job(org, user, uuid.uuid4())

    with pytest.raises(ProfassistError) as caught:
        await studio_collab.slides_collaborate_stream(
            job_id, SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=org), object()
        )
    assert caught.value.status == 404
