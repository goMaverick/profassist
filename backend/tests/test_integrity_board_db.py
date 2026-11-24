"""DB-backed integrity board. Fake rows, no database and no model key."""

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routes.v1 import profassist as route
from app.core.config import settings
from app.profassist.integrity_board import (
    _group_labels,
    _norm,
    _pair_id,
    assignment_matrix_db,
    overview_db,
    pair_detail_db,
)

ORG = uuid.uuid4()
USER = uuid.uuid4()
OTHER = uuid.uuid4()

SHARED_TEXT = (
    "The group counted entries at the east stair every afternoon for four weeks "
    "and kept the tally in the same notebook."
)


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Session:
    """Five result batches in _db_catalog order."""

    def __init__(self, courses=(), assessments=(), assignments=(), submissions=(), flags=()):
        self._batches = [
            list(courses),
            list(assessments),
            list(assignments),
            list(submissions),
            list(flags),
        ]

    async def execute(self, _statement):
        return _Result(self._batches.pop(0))


def _course(code="MAAI 903", title="AI Solutions", org=ORG, course_id="course-1"):
    return SimpleNamespace(
        id=course_id,
        organization_id=org,
        code=code,
        title=title,
        external_id="moodle-course-1",
    )


def _assessment(
    assessment_id="assessment-1",
    course_id="course-1",
    owner=USER,
    title="Workshops",
    external_id="1",
    org=ORG,
):
    return SimpleNamespace(
        id=assessment_id,
        organization_id=org,
        course_id=course_id,
        owner_user_id=owner,
        title=title,
        external_id=external_id,
        created_at="2026-11-01",
    )


def _submission(
    submission_id,
    group_name,
    text=SHARED_TEXT,
    assessment_id="assessment-1",
    topic="workshops",
    org=ORG,
):
    return SimpleNamespace(
        id=submission_id,
        organization_id=org,
        assessment_id=assessment_id,
        group_name=group_name,
        topic=topic,
        scrubbed_text=text,
        raw_text=text,
        created_at=datetime(2026, 11, 4, tzinfo=UTC),
    )


def _flag(left, right, score, section="body", kind="fingerprint", owner=USER, org=ORG):
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        organization_id=org,
        owner_user_id=owner,
        left_submission_id=left,
        right_submission_id=right,
        section=section,
        passage_a=SHARED_TEXT,
        passage_b=SHARED_TEXT,
        score=score,
        kind=kind,
    )


def _assignment(number="1", title="Workshops", assessment_id="assessment-1"):
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        organization_id=ORG,
        owner_user_id=USER,
        course_id="course-1",
        assessment_id=assessment_id,
        number=number,
        title=title,
    )


@pytest.mark.anyio
async def test_overview_db_is_empty_without_submissions() -> None:
    session = _Session(courses=[_course()], assessments=[_assessment()])

    board = await overview_db(session, ORG, USER, "all")

    assert board == {
        "courses": [],
        "summary": {"courses": 0, "assignments": 0, "groups": 0, "review": 0, "concern": 0},
        "items": [],
    }


@pytest.mark.anyio
async def test_overview_db_groups_real_submissions_and_scores_them() -> None:
    rows = [
        _submission("s-a", "Group A"),
        _submission("s-b", "B"),
        _submission("s-c", "Group C"),
    ]
    session = _Session(
        courses=[_course()],
        assessments=[_assessment()],
        submissions=rows,
    )

    board = await overview_db(session, ORG, USER, "all")

    assert board["courses"] == [{"code": "MAAI 903", "slug": "MAAI903", "title": "AI Solutions"}]
    assert board["summary"] == {
        "courses": 1,
        "assignments": 1,
        "groups": 3,
        "review": 0,
        "concern": 1,
    }
    card = board["items"][0]
    assert card["number"] == "1"
    assert card["name"] == "Workshops"
    assert card["groups"] == 3
    assert card["flagged_pairs"] == 3
    assert card["highest"] == 100
    assert card["status"] == "Concern"
    assert card["line"] == "3 groups · 3 pairs to read · 0 writing flags"
    assert card["course_id"] == "course-1"
    assert card["assessment_id"] == "assessment-1"
    # No fixture roster leaked into a durable board.
    assert "Sara" not in json.dumps(board)


@pytest.mark.anyio
async def test_overview_db_scopes_courses_and_owners() -> None:
    session = _Session(
        courses=[_course(), _course(code="FOREIGN 101", org=OTHER, course_id="course-x")],
        assessments=[
            _assessment(),
            _assessment(
                assessment_id="assessment-x",
                course_id="course-1",
                owner=OTHER,
                external_id="2",
            ),
        ],
        submissions=[
            _submission("s-a", "Group A"),
            _submission("s-b", "Group B"),
            _submission("s-x", "Group A", assessment_id="assessment-x"),
            _submission("s-y", "Group B", assessment_id="assessment-x"),
        ],
        flags=[_flag("s-a", "s-b", 0.9, owner=OTHER)],
    )

    board = await overview_db(session, ORG, USER, "all")

    assert [item["number"] for item in board["items"]] == ["1"]
    assert board["items"][0]["assessment_id"] == "assessment-1"
    assert board["items"][0]["groups"] == 2
    # The other owner's high flag is not counted.
    assert board["items"][0]["highest"] == 100


def test_group_labels_accept_group_prefixes_and_bare_letters() -> None:
    labels = _group_labels(
        [
            SimpleNamespace(group_name="Group A"),
            SimpleNamespace(group_name="A"),
            SimpleNamespace(group_name="B"),
            SimpleNamespace(group_name="Group C"),
            SimpleNamespace(group_name=""),
        ]
    )

    assert labels["Group A"] == "A"
    assert labels["A"] == "A"
    assert labels["B"] == "B"
    assert labels["Group C"] == "C"
    assert labels[""] in {"D", "E"}


@pytest.mark.anyio
async def test_matrix_uses_the_stored_flag_score_over_the_computed_one() -> None:
    session = _Session(
        courses=[_course()],
        assessments=[_assessment()],
        assignments=[_assignment()],
        submissions=[_submission("s-a", "Group A"), _submission("s-b", "Group B")],
        flags=[_flag("s-a", "s-b", 0.42, section="introduction")],
    )

    page = await assignment_matrix_db(session, ORG, USER, "MAAI903", "1")

    assert page["course"] == "MAAI 903"
    assert page["slug"] == "MAAI903"
    assert page["assignment"] == "1"
    assert page["groups"] == ["A", "B"]
    assert page["matrix"] == [[100, 42], [42, 100]]
    assert page["pairs"] == [
        {
            "left": "A",
            "right": "B",
            "percent": 42,
            "shared": 1,
            "writing": False,
            "status": "Review",
        }
    ]
    assert page["card"]["status"] == "Review"
    assert page["card"]["highest"] == 42


@pytest.mark.anyio
async def test_overview_uses_the_published_assignment_number_and_title() -> None:
    session = _Session(
        courses=[_course()],
        assessments=[_assessment(external_id="42")],
        assignments=[_assignment(number="A1", title="Workshops report")],
        submissions=[_submission("s-a", "Group A"), _submission("s-b", "Group B")],
    )

    board = await overview_db(session, ORG, USER, "all")

    assert board["items"][0]["number"] == "A1"
    assert board["items"][0]["name"] == "Workshops report"

    session = _Session(
        courses=[_course()],
        assessments=[_assessment(external_id="42")],
        assignments=[_assignment(number="A1", title="Workshops report")],
        submissions=[_submission("s-a", "Group A"), _submission("s-b", "Group B")],
    )
    page = await assignment_matrix_db(session, ORG, USER, "MAAI903", "A1")
    assert page["assignment"] == "A1"
    assert page["name"] == "Workshops report"


@pytest.mark.anyio
async def test_matrix_falls_back_to_computed_similarity() -> None:
    session = _Session(
        courses=[_course()],
        assessments=[_assessment()],
        submissions=[_submission("s-a", "Group A"), _submission("s-b", "Group B")],
    )

    page = await assignment_matrix_db(session, ORG, USER, "MAAI903", "1")

    assert page["pairs"][0]["percent"] == 100
    assert page["pairs"][0]["shared"] == 1
    assert page["pairs"][0]["status"] == "Concern"
    assert page["matrix"][0][1] == 100


@pytest.mark.anyio
async def test_matrix_names_the_missing_course_and_assignment() -> None:
    session = _Session(courses=[_course()], assessments=[_assessment()])

    missing_course = await assignment_matrix_db(session, ORG, USER, "NOPE101", "1")
    assert missing_course == {"error": "That course is not in this workspace."}

    session = _Session(courses=[_course()], assessments=[_assessment()])
    missing_assignment = await assignment_matrix_db(session, ORG, USER, "MAAI903", "99")
    assert missing_assignment == {"error": "That assignment is not in this course."}


@pytest.mark.anyio
async def test_pair_detail_reads_the_stored_flag_and_decisions(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.profassist.integrity_docs import save_decision

    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    pair_id = _pair_id("MAAI903", "1", "A", "B")
    save_decision(pair_id, "body-1", "ok")
    session = _Session(
        courses=[_course()],
        assessments=[_assessment()],
        submissions=[_submission("s-a", "Group A"), _submission("s-b", "Group B")],
        flags=[_flag("s-a", "s-b", 0.66, section="body")],
    )

    detail = await pair_detail_db(session, ORG, USER, "MAAI903", "1", "A", "B")

    assert detail["left"] == "A"
    assert detail["right"] == "B"
    assert detail["percent"] == 66
    assert detail["status"] == "Review"
    assert detail["left_meta"] == {"members": "", "submitted": "04 Nov 2026"}
    assert detail["right_meta"] == {"members": "", "submitted": "04 Nov 2026"}
    assert detail["documents"]["left"]["view"] == ""
    assert detail["documents"]["right"]["view"] == ""
    assert detail["matches"][0]["id"] == "body-1"
    assert detail["matches"][0]["decision"] == "ok"
    assert detail["matches"][0]["source"] == "shared"
    assert detail["decisions"] == {"flagged": 0, "ok": 1, "pending": 0}
    assert any(run.get("id") == "body-1" for block in detail["left_text"] for run in block["runs"])
    assert "Sara" not in json.dumps(detail)


@pytest.mark.anyio
async def test_pair_detail_falls_back_to_computed_similarity(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    session = _Session(
        courses=[_course()],
        assessments=[_assessment()],
        submissions=[_submission("s-a", "Group A"), _submission("s-b", "Group B")],
    )

    detail = await pair_detail_db(session, ORG, USER, "MAAI903", "1", "A", "B")

    assert detail["percent"] == 100
    assert detail["status"] == "Concern"
    assert detail["matches"][0]["decision"] == "pending"
    assert detail["decisions"] == {"flagged": 0, "ok": 0, "pending": 1}


@pytest.mark.anyio
async def test_pair_detail_rejects_a_pair_outside_the_assignment() -> None:
    session = _Session(
        courses=[_course()],
        assessments=[_assessment()],
        submissions=[_submission("s-a", "Group A"), _submission("s-b", "Group B")],
    )

    detail = await pair_detail_db(session, ORG, USER, "MAAI903", "1", "A", "Z")

    assert detail == {"error": "That pair is not in this workspace."}


@pytest.mark.anyio
async def test_integrity_routes_delegate_to_the_db_functions(monkeypatch) -> None:
    user = SimpleNamespace(id=USER)
    org = SimpleNamespace(id=ORG)
    db = object()

    overview = AsyncMock(return_value={"items": []})
    matrix = AsyncMock(return_value={"pairs": []})
    pair = AsyncMock(return_value={"matches": []})
    monkeypatch.setattr("app.profassist.integrity_board.overview_db", overview)
    monkeypatch.setattr("app.profassist.integrity_board.assignment_matrix_db", matrix)
    monkeypatch.setattr("app.profassist.integrity_board.pair_detail_db", pair)

    assert await route.integrity_overview(user, org, db, "MAAI903") == {"items": []}
    overview.assert_awaited_once_with(db, ORG, USER, "MAAI903")

    assert await route.integrity_matrix(user, org, db, "MAAI903", "1") == {"pairs": []}
    matrix.assert_awaited_once_with(db, ORG, USER, "MAAI903", "1")

    assert await route.integrity_pair(user, org, db, "MAAI903", "1", "A", "B") == {"matches": []}
    pair.assert_awaited_once_with(db, ORG, USER, "MAAI903", "1", "A", "B")


def test_integrity_routes_are_registered() -> None:
    paths = {item.path for item in route.router.routes}

    assert "/integrity/overview" in paths
    assert "/integrity/matrix" in paths
    assert "/integrity/pair" in paths
    assert _norm("MAAI 903") == "MAAI903"
