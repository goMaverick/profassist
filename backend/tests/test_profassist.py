"""Unit tests for the professor workflows. No database and no model key."""

from collections.abc import Iterator

import pytest

from app.profassist.errors import ProfassistError, require_same_tenant
from app.profassist.grading import (
    assert_can_push,
    is_blind_sample,
    quotes_in_text,
    reconcile,
)
from app.profassist.llm import complete
from app.profassist.moodle import (
    SUBMISSIONS,
    FakeMoodleConnector,
    RealMoodleConnector,
    get_connector,
    parse_lti_launch,
)
from app.profassist.pii import assert_prompt_is_clean, scrub
from app.profassist.similarity import compare_submissions, hash_embed
from app.profassist.slides import build_pptx
from app.profassist.stubs import at_risk_snapshot, grade_calibrator
from tests.integrity_fixture import DEMO_COURSES, install, remove


@pytest.fixture
def demo_board() -> Iterator[None]:
    install()
    try:
        yield
    finally:
        remove()


def test_scrub_removes_roster_email_and_id() -> None:
    text = (
        "Student: Sara Al Maktoum\n"
        "Student ID: 8881001\n"
        "Email: sara.almaktoum@student.uowd.ac.ae\n"
        "The baseline load is 42.7 kWh because the brief asks for evidence."
    )
    result = scrub(text, ["Sara Al Maktoum"])
    assert "Sara" not in result.text
    assert "8881001" not in result.text
    assert "@" not in result.text
    assert "42.7" in result.text
    assert result.quarantined is False
    assert result.replacements


def test_scrub_quarantines_an_unknown_name() -> None:
    result = scrub("Please ask Jordan Hale about the lab report.", [])
    assert result.quarantined is True
    assert any("Jordan Hale" in item for item in result.uncertain)


def test_presidio_leaves_a_url_and_filename_unchanged() -> None:
    from app.profassist.pii import _presidio_extra

    assert _presidio_extra("See https://example.com/PIPE903-notes for details.") == []
    assert _presidio_extra("PIPE903-notes-v2.txt") == []


def test_heading_pairs_do_not_quarantine_but_a_body_name_does() -> None:
    for heading in ("Practice Term", "Policies Late", "Course Schedule: Teaching Week"):
        assert scrub(heading).quarantined is False

    body = scrub("This report was written by Ahmed Al Mansoori for the final assessment.")
    assert body.quarantined is True
    assert any("Ahmed Al Mansoori" in item for item in body.uncertain)


def test_model_gate_refuses_an_email() -> None:
    with pytest.raises(RuntimeError):
        assert_prompt_is_clean("contact ada@university.edu now")


def test_grade_reply_must_name_a_band() -> None:
    from app.profassist.llm import parse_grade_content

    vote = parse_grade_content(
        '{"level": "Proficient", "quotes": ["The meter reads 42.7."], "why": "A number is shown."}',
        "evidence",
    )
    assert vote is not None
    assert vote["level"] == "proficient"
    assert vote["persona"] == "evidence"
    assert parse_grade_content("not json", "strict") is None


def test_missing_course_pdf_still_opens() -> None:
    from app.profassist.integrity_docs import file_bytes

    data, media, name = file_bytes("AAS910", "1", "A", "pdf")
    assert data.startswith(b"%PDF")
    assert media == "application/pdf"
    assert name.endswith(".pdf")


def test_grade_reply_quotes_are_in_the_submission() -> None:
    import json

    from app.profassist.llm import parse_grade_content

    submission = (
        "We chose this use case because the brief asks for a measurable operational problem. "
        "A limitation is that weekend readings were missing, therefore the trend is only reliable on weekdays."
    )
    vote = parse_grade_content(
        json.dumps(
            {
                "level": "proficient",
                "quotes": ["A limitation is that weekend readings were missing"],
                "why": "The limitation is explicit.",
            }
        ),
        "strict",
    )
    assert vote is not None
    kept, rejected = quotes_in_text(vote["quotes"], submission)
    assert kept
    assert rejected == []


def test_judge_keeps_a_quote_when_only_the_spacing_differs() -> None:
    submission = "The meter on level two reads 42.7 during the Thursday class change."
    verdict = reconcile(
        [
            {"level": "proficient", "quotes": ["The meter on level two reads 42.7"], "checks": []},
            {"level": None, "quotes": ["The meter on level two reads 42.7"], "checks": []},
            {"level": "proficient", "quotes": ["not in the text"], "checks": []},
        ],
        submission,
    )
    assert verdict["level"] == "proficient"
    assert verdict["evidence_status"] == "ok"


def test_judge_rejects_invented_quotes() -> None:
    submission = "The student wrote one careful paragraph about the meter."
    verdict = reconcile(
        [
            {"level": "advanced", "quotes": ["this sentence was invented"], "checks": []},
            {"level": "advanced", "quotes": ["also invented"], "checks": []},
            {"level": "proficient", "quotes": ["still invented"], "checks": []},
        ],
        submission,
    )
    assert verdict["evidence_status"] == "no_reliable_evidence"
    assert verdict["skip_calibrator"] is True
    assert verdict["level"] is None


def test_judge_keeps_a_real_quote() -> None:
    submission = (
        "We chose this use case because the brief asks for a measurable operational problem."
    )
    quote = submission
    verdict = reconcile(
        [
            {
                "level": "proficient",
                "quotes": [quote],
                "checks": [{"quote": quote, "answer": True}],
            },
            {
                "level": "developing",
                "quotes": [quote],
                "checks": [{"quote": quote, "answer": True}],
            },
            {
                "level": "proficient",
                "quotes": [quote],
                "checks": [{"quote": quote, "answer": True}],
            },
        ],
        submission,
    )
    assert verdict["evidence_status"] == "ok"
    assert verdict["level"] == "proficient"
    assert "Why this level" in verdict["why"]


def test_push_requires_approval() -> None:
    with pytest.raises(PermissionError):
        assert_can_push("draft")
    assert_can_push("approved")


def test_group_b_is_the_blind_sample() -> None:
    assert is_blind_sample("Group B") is True
    assert is_blind_sample("Group B18") is True
    assert is_blind_sample("Group A") is False


def test_similarity_flags_the_copied_method_only() -> None:
    rows = []
    for row in SUBMISSIONS:
        cleaned = scrub(
            row["text"],
            ["Sara Al Maktoum", "Omar Haddad", "Noor Rahman"],
        )
        rows.append(
            {
                "id": row["id"],
                "group_name": row["group_name"],
                "topic": row["topic"],
                "text": cleaned.text,
            }
        )
    flags = compare_submissions(rows)
    pairs = {tuple(sorted((flag["left_id"], flag["right_id"]))) for flag in flags}
    assert ("sub-a", "sub-b") in pairs
    assert ("sub-a", "sub-c") not in pairs
    copied = next(
        flag for flag in flags if {flag["left_id"], flag["right_id"]} == {"sub-a", "sub-b"}
    )
    assert copied["viva"] if False else copied["section"] == "method"
    assert "sustanability" in copied["rare_details"] or copied["kind"] == "fingerprint"


def test_outline_assist_scrubs_a_contact_email_before_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from app.profassist.llm import complete

    calls: list[object] = []
    _fake_model(monkeypatch, json.dumps({"reply": "ok", "suggestion": {}}), calls=calls)
    drafted = complete(
        "outline_assist",
        {
            "step": "lecture",
            "body": {"lecture": {"email": "ada@university.edu"}},
            "instructions": "",
        },
    )
    assert isinstance(drafted, dict)
    assert "ada@university.edu" not in json.dumps(calls)


def test_assignment_catalog_keeps_the_outline_number_and_due_date() -> None:
    from app.profassist.groupwork import merge_catalog

    rows = merge_catalog(
        [{"number": "A2", "name": "Architecture report", "due": "Week 7", "weight": 25}],
        [
            {
                "id": "saved",
                "number": "A2",
                "title": "Architecture report",
                "due": "15 Dec",
                "weight": 25,
                "status": "draft",
            }
        ],
    )
    assert rows[0]["id"] == "saved"
    assert rows[0]["due"] == "15 Dec"
    assert rows[0]["title"] == "Architecture report"
    assert rows[0]["status"] == "draft"


def test_integrity_board_is_empty_until_submissions_are_registered() -> None:
    from app.profassist.integrity_board import (
        assignment_matrix,
        concerns,
        overview,
        pair_detail,
    )

    board = overview("all")
    assert board["courses"] == []
    assert board["items"] == []
    assert board["summary"] == {
        "courses": 0,
        "assignments": 0,
        "groups": 0,
        "review": 0,
        "concern": 0,
    }
    assert assignment_matrix("MAAI903", "1") == {"error": "That course is not in this workspace."}
    assert pair_detail("MAAI903", "1", "A", "B") == {"error": "That pair is not in this workspace."}
    empty = concerns("AAS910")
    assert empty["items"] == []
    assert empty["cases"] == []
    assert empty["matches"] == []
    assert empty["message"] == "AAS 910 has no copying cases yet."


def test_integrity_board_has_a_concern_and_a_clear_assignment(demo_board) -> None:
    from app.profassist.integrity_board import overview
    from app.profassist.platform_tools import choose_tool

    board = overview("all")
    assert board["summary"]["courses"] == 2
    statuses = {item["status"] for item in board["items"]}
    assert {"Clear", "Review", "Concern"} <= statuses
    name, args = choose_tool("show integrity concerns for MAAI 903 assignment 1")
    assert name == "integrity_concerns"
    assert args["code"] == "MAAI903"
    assert args["assignment"] == "1"
    from app.profassist.integrity_board import concerns as board_concerns

    answered = board_concerns("MAAI903", "1")
    assert "Concern" in answered["message"]
    assert "86" in answered["message"]
    assert "page" in answered["message"]
    assert answered["matches"][0]["page"] >= 1
    assert "1 pairs" not in answered["message"]
    assert answered["href"].startswith("/integrity?course=MAAI903")
    from app.profassist.integrity_board import concerns, pair_detail

    architecture = concerns("MAAI903", "2")
    assert "1 pair to read" in architecture["message"]
    from app.profassist.integrity_board import assignment_matrix

    page = overview("all")
    expected = page["summary"]["review"] + page["summary"]["concern"]
    assert expected == 4
    listed = concerns("AAS910")
    assert "Nothing needs a look" not in listed["message"]
    assert "no copying cases yet" in listed["message"]
    assert "in other courses" in listed["message"]
    assert "integrity board" not in listed["message"]
    seen = {
        (item["slug"], str(item["number"]), pair["left"], pair["right"], pair["percent"])
        for item in page["items"]
        if item["status"] != "Clear"
        for pair in assignment_matrix(item["slug"], str(item["number"]))["pairs"]
        if pair["status"] != "Clear"
    }
    got = {
        (case["slug"], case["assignment"], case["groups"][0], case["groups"][1], case["percent"])
        for case in listed["cases"]
    }
    assert got == seen
    for case in listed["cases"]:
        assert case["href"] in listed["message"]
        assert f"Group {case['groups'][0]} and Group {case['groups'][1]}" in listed["message"]
        assert f"{case['percent']}%" in listed["message"]
    detail = pair_detail("MAAI903", "1", "A", "B")
    assert len(detail["left_text"]) >= 3
    assert detail["left_meta"]["members"].startswith("Sara")
    assert any(item["common"] for item in detail["passages"])
    assert len(detail["matches"]) >= 7
    assert detail["documents"]["left"]["origin"] == "pdf"
    assert detail["documents"]["right"]["origin"] == "docx"
    assert detail["documents"]["right"]["converter"] in {"libreoffice", "builtin"}
    assert {"shared", "brief", "readings"} <= {item["source"] for item in detail["matches"]}
    assert len({item["page_left"] for item in detail["matches"]}) >= 2
    assert detail["matches"][0]["left_box"]["w"] > 0
    assert "1 pair to read" in next(
        item["line"] for item in overview("MAAI903")["items"] if item["number"] == "2"
    )
    assert "1 writing flag" in next(
        item["line"] for item in overview("MAAI903")["items"] if item["number"] == "3"
    )


def test_integrity_gate_and_match_decisions(
    monkeypatch: pytest.MonkeyPatch, tmp_path, demo_board
) -> None:
    from app.core.config import settings
    from app.profassist.integrity_board import _pair_id, assignment_card
    from app.profassist.integrity_docs import gate_for_model, pair_matches, save_decision

    cleaned = gate_for_model("Write to ada@university.edu about the typo sustanability.")
    assert "ada@university.edu" not in cleaned
    assert "sustanability" in cleaned
    with pytest.raises(RuntimeError):
        from app.profassist.pii import assert_prompt_is_clean

        assert_prompt_is_clean("ada@university.edu")

    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    course = DEMO_COURSES[0]
    item = course["assignments"][0]
    before = assignment_card(course, item)["flagged_pairs"]
    shared = [row for row in pair_matches("MAAI903", "1", "A", "B") if row["source"] == "shared"]
    for row in shared:
        save_decision(_pair_id("MAAI903", "1", "A", "B"), row["id"], "ok")
    after = assignment_card(course, item)["flagged_pairs"]
    assert after < before


def test_grading_council_drafts_from_the_rubric() -> None:
    from app.profassist.grade_notes import draft_mark, letter_for

    mark = draft_mark("Group B")
    assert mark["rubric"] == "Workshops rubric"
    assert mark["total"] == 78
    assert mark["letter"] == "B"
    assert letter_for(70) == "C"
    assert mark["confidence"] == "Medium"
    names = [row["name"] for row in mark["criteria"]]
    assert names == ["Problem definition", "Solution design", "Ethical risk"]
    design = next(row for row in mark["criteria"] if row["id"] == "design")
    assert design["agreed"] is False
    assert {item["band"] for item in design["graders"]} == {"Good", "Fair"}
    ethics = next(row for row in mark["criteria"] if row["id"] == "ethics")
    assert "brief asks" not in ethics["evidence"].lower()
    for row in mark["criteria"]:
        assert len(str(row["short"]).split()) <= 12
    assert len(mark["council"]) == 4


def test_grade_feedback_approval_never_pushes(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.core.config import settings
    from app.profassist.grade_notes import load_feedback, release_feedback, save_feedback

    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    monkeypatch.setenv("MOODLE_MODE", "fake")
    monkeypatch.delenv("MOODLE_PUSH_ENABLED", raising=False)
    saved = save_feedback(
        "professor",
        "Group A",
        {
            "comments": [
                {"id": "c1", "page": 1, "text": "Fix the spelling.", "quote": "sustanability"}
            ],
            "rubric": [{"criterion": "Problem definition", "comment": "Name the user."}],
            "overall": "A solid draft.",
            "bank": ["Add the missing citation."],
        },
    )
    assert saved["release"] == "draft"
    held = release_feedback("professor", "Group A")
    assert held["pushed"] is False
    assert "Nothing sent until push" in held["message"]
    monkeypatch.setenv("MOODLE_PUSH_ENABLED", "true")
    still_held = release_feedback("professor", "Group A")
    assert still_held["pushed"] is False
    assert "Nothing sent until push" in still_held["message"]
    assert load_feedback("professor", "Group A")["release"] == "held"


def test_create_assignment_phrase_picks_the_course_tool() -> None:
    from app.profassist.platform_tools import choose_tool

    name, args = choose_tool("Create assignment 2 for MAAI 903 due 15 Dec")
    assert name == "create_assignment"
    assert args["number"] == "A2"
    assert args["code"] == "MAAI903"
    assert args["due"] == "15 Dec"


def test_chat_stream_asks_before_a_moodle_push() -> None:
    from app.profassist.platform_tools import chat_stream_events

    events = chat_stream_events(
        {
            "reply": "I can record the grade.",
            "tool": "moodle_push",
            "needs_confirm": True,
            "result": {"preview": "push"},
        }
    )
    tool = next(item for item in events if item["event"] == "tool")
    assert tool["data"]["name"] == "moodle_push"
    assert tool["data"]["state"] == "approval-requested"
    assert tool["data"]["output"] is None
    assert "".join(item["data"]["delta"] for item in events if item["event"] == "text").startswith(
        "I can record"
    )


def test_shared_idea_brief_is_not_treated_as_copying(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from app.profassist.groupwork import pairwise_similarity
    from app.profassist.llm import complete

    _fake_model(
        monkeypatch,
        json.dumps(
            {
                "ideas": [
                    {"title": f"Idea {index}", "brief": "b", "deliverables": "", "evidence": ""}
                    for index in range(1, 6)
                ]
            }
        ),
    )
    ideas = complete("ideas", {"title": "Report", "lo_codes": ["LO1"]})["ideas"]
    assert len(ideas) == 5
    brief = "Shared clinic triage use case."
    flags = pairwise_similarity(
        [
            {
                "id": "a",
                "group": "A",
                "idea_id": "1",
                "text": brief + " Our pipeline logs every prediction.",
                "brief": brief,
            },
            {
                "id": "b",
                "group": "B",
                "idea_id": "1",
                "text": brief + " We interviewed nurses and kept paper notes.",
                "brief": brief,
            },
        ]
    )
    assert flags == []


def test_moodle_schedule_respects_pause_interval_and_nightly_hour() -> None:
    from datetime import UTC, datetime

    from app.profassist.moodle_schedule import (
        incremental_due,
        next_incremental,
        next_nightly,
        nightly_due,
    )

    now = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
    last = datetime(2026, 11, 22, 9, 40, tzinfo=UTC)
    assert incremental_due(last, 30, False, now) is False
    assert incremental_due(last, 15, False, now) is True
    assert incremental_due(last, 30, True, now) is False
    assert next_incremental(last, 30, True, now) is None
    assert next_nightly(2, False, now) is None
    assert next_nightly(2, True, now).hour == 2
    assert nightly_due(None, 10, True, now) is True
    assert nightly_due(now, 10, True, now) is False


def test_dropout_adapter_does_not_invent_scores() -> None:
    from app.profassist.ml.dropout import FEATURE_COLUMNS, predict

    payload = predict(
        [{"display_name": "Sara Al Maktoum", "external_id": "stu-1"}],
        course_code="MAAI903",
    )
    assert payload["trained"] is False
    assert payload["automatic_actions"] is False
    assert payload["status"] == "not_trained"
    assert payload["synthetic"] is True
    assert "active_days_14d" in FEATURE_COLUMNS
    assert "mean_score_pct_to_date" in FEATURE_COLUMNS
    assert len(FEATURE_COLUMNS) == 14
    assert payload["students"][0]["score"] is None
    assert payload["students"][0]["band"] is None
    assert payload["students"][0]["factors"] == []
    assert payload["students"][0]["note"].startswith("Not enough data")
    assert payload["course_code"] == "MAAI903"
    assert payload["message"] in {
        "The course-withdrawal model is not trained. Connect Moodle activity data to enable it.",
        "A model is present but there is not enough activity data to score.",
    }


def test_calibrator_and_dropout_stay_untrained() -> None:
    calibrator = grade_calibrator({"judge_level": "proficient"})
    assert calibrator["trained"] is False
    assert calibrator["level"] is None
    risk = at_risk_snapshot([{"display_name": "Sara Al Maktoum", "external_id": "stu-1"}])
    assert risk["trained"] is False
    assert risk["status"] == "not_trained"
    assert risk["synthetic"] is True
    assert risk["automatic_actions"] is False
    assert risk["students"][0]["score"] is None
    assert risk["students"][0]["display_name"] == "Sara Al Maktoum"


@pytest.mark.anyio
async def test_fake_grade_send_does_not_complete_assignments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid
    from types import SimpleNamespace

    from app.profassist.journey import send_grade
    from app.profassist.models import Course, GradeDraft, GroupAssignment, Submission

    monkeypatch.setenv("MOODLE_MODE", "fake")
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    course = SimpleNamespace(id=uuid.uuid4(), organization_id=org_id, code="AAS 910", term="2026")
    submission = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=org_id,
        course_id=course.id,
        group_name="Group A",
    )
    draft = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=org_id,
        owner_user_id=user_id,
        submission_id=submission.id,
        status="pushed",
    )
    assignments = [
        SimpleNamespace(
            organization_id=org_id,
            owner_user_id=user_id,
            course_id=course.id,
            status="open",
        )
    ]

    class _Result:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def scalars(self) -> "_Result":
            return self

        def all(self) -> list[object]:
            return self._rows

        def first(self) -> object | None:
            return self._rows[0] if self._rows else None

        def scalar_one_or_none(self) -> object | None:
            return self.first()

    class _FakeDb:
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is Course:
                return _Result([course])
            if entity is Submission:
                return _Result([submission])
            if entity is GradeDraft:
                return _Result([draft])
            if entity is GroupAssignment:
                return _Result(assignments)
            return _Result([])

        async def flush(self) -> None:
            return None

        def add(self, row: object) -> None:
            return None

    result = await send_grade(_FakeDb(), org_id, user_id, "AAS 910", "Group A")
    assert result["message"] == "Recorded in ProfAssist"
    assert "Sent to Moodle" not in result["message"]
    assert result["note"] == "Recorded in ProfAssist. Moodle was not contacted."
    assert result["assignment_status"] == "unchanged"
    assert [item.status for item in assignments] == ["open"]


def test_fake_moodle_push_does_not_claim_a_live_write() -> None:
    receipt = FakeMoodleConnector().push({"type": "grade", "id": "1"})
    assert receipt["mode"] == "fake"
    assert "not contacted" in receipt["moodle_response"]
    launch = FakeMoodleConnector().lti_launch({"iss": "https://moodle.example", "sub": "9"})
    assert launch["course_external_id"] == "mdl-maai903"
    parsed = parse_lti_launch(
        {
            "iss": "https://moodle.example",
            "https://purl.imsglobal.org/spec/lti/claim/context": {
                "id": "mdl-maai903",
                "title": "AI",
            },
        }
    )
    assert parsed["course_external_id"] == "mdl-maai903"


def test_connector_factory_uses_real_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOODLE_MODE", raising=False)
    monkeypatch.delenv("MOODLE_BASE_URL", raising=False)
    monkeypatch.delenv("MOODLE_WS_TOKEN", raising=False)
    assert isinstance(get_connector(), RealMoodleConnector)
    with pytest.raises(ProfassistError) as caught:
        get_connector().list_courses()
    assert caught.value.status == 503
    assert "Moodle is not configured" in caught.value.detail
    monkeypatch.setenv("MOODLE_MODE", "fake")
    assert isinstance(get_connector(), FakeMoodleConnector)
    monkeypatch.setenv("MOODLE_MODE", "real")
    assert isinstance(get_connector(), RealMoodleConnector)


def test_tenant_guard() -> None:
    require_same_tenant("org", "org")
    with pytest.raises(ProfassistError):
        require_same_tenant("org-a", "org-b")


def test_hash_embed_is_stable() -> None:
    assert hash_embed("campus energy") == hash_embed("campus energy")
    assert len(hash_embed("campus energy")) == 64


def test_slide_studio_cites_and_flags_a_gap() -> None:
    from app.profassist.skills.slide_studio import run_slide_studio

    note = (
        "Explain how an LLM agent differs from a trained machine learning model. "
        "An assessment brief should name the audience and the artefact."
    )
    deck = run_slide_studio(
        [
            "Explain how an LLM agent differs from a trained machine learning model.",
            "Describe the campus telescope that is not in the notes.",
        ],
        [{"id": "c1", "text": note, "filename": "lecture-note.txt", "section": "note"}],
    )
    covered = next(slide for slide in deck["slides"] if not slide["gap"])
    bullet = covered["bullets"][0]
    assert bullet["citation"]["filename"] == "lecture-note.txt"
    assert bullet["text"] in note
    assert deck["gaps"]
    assert deck["pptx"][:2] == b"PK"


def test_memory_scope_is_professor_and_tenant() -> None:
    import uuid

    from app.profassist.memory import scope_id
    from app.profassist.pii import scrub

    org = uuid.uuid4()
    professor = uuid.uuid4()
    other = uuid.uuid4()
    assert scope_id(org, professor) != scope_id(org, other)
    blocked = scrub("Email sara.almaktoum@student.uowd.ac.ae stays out of memory.", [])
    assert "@" not in blocked.text


def test_mlflow_empty_state_when_server_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.tracking import list_registered_models

    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:9")
    payload = list_registered_models()
    assert payload["reachable"] is False
    assert payload["models"][0]["status"] == "not_trained"


def test_objectives_accept_a_bare_string_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model that answers ["..."] instead of [{"text": ...}] must not 500."""
    from app.profassist import agents

    note = "Explain how an LLM agent differs from a trained machine learning model."
    chunks = [{"id": "c1", "text": note}]
    monkeypatch.setattr(
        agents.llm,
        "complete",
        lambda task, payload: {"objectives": [note, "  ", {"text": note}]},
    )

    drafted = agents.run_course(
        "objectives", title="Agents", query="course learning outcome", chunks=chunks
    )

    assert drafted["objectives"] == [{"text": note}, {"text": note}]

    monkeypatch.setattr(agents.llm, "complete", lambda task, payload: {"objectives": note})
    single = agents.run_course(
        "objectives", title="Agents", query="course learning outcome", chunks=chunks
    )

    assert single["objectives"] == [{"text": note}]


def test_objectives_accept_a_bare_list_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist import agents

    note = "Explain how an LLM agent differs from a trained machine learning model."
    monkeypatch.setattr(agents.llm, "complete", lambda task, payload: [note])

    drafted = agents.run_course(
        "objectives", title="Agents", query="course learning outcome", chunks=[{"text": note}]
    )

    assert drafted["objectives"] == [{"text": note}]


@pytest.mark.anyio
async def test_legacy_admin_models_awaits_the_async_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old route called the sync wrapper and always reported unreachable."""
    from app.api.routes.v1 import profassist as routes

    async def fake_registry() -> dict:
        return {"tracking_uri": "http://mlflow:5000", "reachable": True, "models": []}

    monkeypatch.setattr(routes, "list_registered_models_async", fake_registry)

    payload = await routes.models_admin(user=None, org=None)

    assert payload["reachable"] is True
    assert payload["tracking_uri"] == "http://mlflow:5000"


def test_debate_starts_only_past_the_threshold() -> None:
    from app.profassist.grading import level_spread, needs_debate

    close = [{"level": "proficient"}, {"level": "developing"}]
    far = [{"level": "advanced"}, {"level": "beginning"}]
    assert level_spread(close) == 1
    assert needs_debate(close, threshold=0) is True
    assert needs_debate(close, threshold=1) is False
    assert needs_debate(far, threshold=1) is True


def test_a_short_rate_limit_is_retried_and_a_daily_cap_is_not() -> None:
    from app.profassist.providers import retry_wait

    assert retry_wait("Please retry in 12.5s") == 13.0
    assert retry_wait("Please retry in 40s") == 40.5
    assert retry_wait("retry in 400s. Quota exceeded per day") is None
    assert retry_wait("RESOURCE_EXHAUSTED limit: 0") is None
    assert retry_wait("429 rate limit") == 5.0


def test_a_busy_model_becomes_a_clean_503(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    from unittest.mock import patch

    import app.profassist.providers as providers

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret-do-not-leak")
    monkeypatch.setattr(providers.time, "sleep", lambda _seconds: None)
    calls: list[int] = []

    # litellm loads backend/.env on import; keep those keys out of the rest of the suite.
    with patch.dict(os.environ):
        import litellm
        from litellm import ServiceUnavailableError

        def busy(*_args: object, **_kwargs: object) -> object:
            calls.append(1)
            raise ServiceUnavailableError(
                message="The provider is at high demand. raw payload super-secret",
                llm_provider="anthropic",
                model="claude-3-5-haiku-latest",
            )

        monkeypatch.setattr(litellm, "completion", busy)

        with pytest.raises(ProfassistError) as caught:
            providers.generate(
                "anthropic",
                "claude-3-5-haiku-latest",
                [{"role": "user", "content": "hello"}],
            )

    assert caught.value.status == 503
    assert caught.value.detail
    assert "sk-test-secret-do-not-leak" not in caught.value.detail
    assert "raw payload" not in caught.value.detail
    assert len(calls) == 4


def test_a_busy_debate_keeps_the_votes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist import agents
    from app.profassist.errors import ProfassistError

    def boom(*_args: object, **_kwargs: object) -> dict:
        raise ProfassistError(429, "busy")

    monkeypatch.setattr(agents.llm, "complete", boom)
    monkeypatch.setattr(
        agents,
        "debate_settings",
        lambda: {"enabled": True, "threshold": 0, "max_rounds": 1},
    )
    votes = [
        {"persona": "evidence", "level": "proficient"},
        {"persona": "strict", "level": "beginning"},
        {"persona": "supportive", "level": "proficient"},
    ]
    result = agents._debate({"votes": votes})
    assert result["votes"] == votes
    assert result["debate_rounds"] == []


def test_provider_keys_are_detected_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.providers import key_configured, litellm_model

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert key_configured("anthropic") is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert key_configured("anthropic") is True
    assert (
        litellm_model("anthropic", "claude-3-5-haiku-latest") == "anthropic/claude-3-5-haiku-latest"
    )
    assert litellm_model("openai", "openai/gpt-4o-mini") == "openai/gpt-4o-mini"


def test_trace_link_uses_the_public_langfuse_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_BASE_URL", "http://localhost:3100")
    monkeypatch.setenv("LANGFUSE_PROJECT_ID", "profassist-project")
    from app.profassist.observe import opaque, prompt_status, trace_url

    assert opaque("same") == opaque("same")
    assert opaque("a") != opaque("b")
    assert trace_url("abc") == "http://localhost:3100/project/profassist-project/traces/abc"
    status = prompt_status("grading_council", None)
    assert status["source"] == "code"
    assert "Quote the submission" in status["text"]


def test_skill_file_lists_tools() -> None:
    from app.profassist.skills.loader import load_skill

    skill = load_skill("slide-studio")
    assert "plan" in skill["tools"]
    assert "pptx" in skill["tools"]


def test_pptx_is_a_zip() -> None:
    data = build_pptx("Draft", [{"title": "One idea", "bullets": ["Cite the note."], "notes": "n"}])
    assert data[:2] == b"PK"


def test_lessons_rewrite_the_portrait_instead_of_stacking() -> None:
    from app.profassist.lessons import condense_about, extract_lessons, same_lesson

    changed = extract_lessons("grade", "Great work! " * 12, "You can tighten the claim. beginning")
    assert any(item["kind"] == "tone" for item in changed)
    assert extract_lessons("grade", "same words", "same words") == []
    portrait = condense_about(
        "Short sentences.",
        [{"kind": "tone", "text": "Write feedback without exclamation marks."}],
        ["MAAI903"],
    )
    assert portrait == condense_about(
        "Short sentences.",
        [{"kind": "tone", "text": "Write feedback without exclamation marks."}],
        ["MAAI903"],
    )
    assert "MAAI903" in portrait
    assert len(portrait) <= 900
    assert same_lesson(portrait, portrait)


def test_lessons_note_concise_and_fuller_outline_and_assignment() -> None:
    from app.profassist.lessons import extract_lessons

    long_text = "word " * 100
    short_text = "word " * 40

    concise = extract_lessons("outline", long_text, short_text)
    assert {"kind": "objective", "text": "Prefers a more concise outline."} in concise

    fuller = extract_lessons("outline", short_text, long_text)
    assert {"kind": "objective", "text": "Prefers fuller detail in outlines."} in fuller

    concise_brief = extract_lessons("assignment", long_text, short_text)
    assert {
        "kind": "objective",
        "text": "Prefers a more concise assignment brief.",
    } in concise_brief

    fuller_brief = extract_lessons("assignment", short_text, long_text)
    assert {
        "kind": "objective",
        "text": "Prefers fuller detail in assignment briefs.",
    } in fuller_brief


def test_about_section_is_labelled_and_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from app.profassist.llm import complete
    from app.profassist.runtime import labelled_about, set_about

    set_about("She prefers short feedback.\nEmail sara@student.uowd.ac.ae")
    block = labelled_about()
    assert block.startswith("\n\n## About this professor\n")
    assert "@" not in block
    assert "sara" not in block.lower()
    _fake_model(
        monkeypatch,
        json.dumps(
            {"feedback": "You showed 42.7 in your own words. One improvement: name the limit."}
        ),
    )
    drafted = complete(
        "feedback",
        {
            "quote": "The baseline load is 42.7 kWh during the teaching day.",
            "level": "proficient",
            "soul": "",
        },
    )
    assert "42.7" in drafted["feedback"]
    set_about("Please ask Jordan Hale about the lab.")
    assert labelled_about() == ""
    set_about("")


def test_trace_about_drops_identity_and_still_scrubs() -> None:
    from app.profassist.observe import trace_about
    from app.profassist.runtime import set_about

    set_about(
        "About this professor:\nProfessor: Jane Doe \u2014 owner\nTeaches: AAS910\n"
        "She prefers short feedback.\nEmail sara@student.uowd.ac.ae"
    )

    text = trace_about()

    assert "Jane Doe" not in text
    assert "Professor:" not in text
    assert "Teaches:" not in text
    assert "AAS910" not in text
    assert "@" not in text
    assert "sara" not in text.lower()
    assert "She prefers short feedback." in text
    assert len(text) <= 900
    set_about("")


def test_deck_fits_and_cites_every_slide() -> None:
    import io

    from pptx import Presentation

    from app.profassist.slides import build_pptx, text_fits

    data = build_pptx(
        "MAAI903",
        [
            {
                "title": "Explain the difference",
                "bullets": [
                    {
                        "text": "An agent differs from a trained model. The load is 42.7 kWh.",
                        "citation": {"filename": "lecture-note.txt"},
                    },
                    "The brief names the audience and the artefact.",
                ],
                "notes": "Say this slowly.",
            }
        ],
    )
    deck = Presentation(io.BytesIO(data))
    assert len(deck.slides) >= 6
    saw_image = False
    for slide in deck.slides:
        notes = slide.notes_slide.notes_text_frame.text
        assert notes.strip()
        assert "lecture-note.txt" in notes
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            text = "\n".join(paragraph.text for paragraph in shape.text_frame.paragraphs)
            if text.strip() == "Image":
                saw_image = True
            size = 14
            for paragraph in shape.text_frame.paragraphs:
                if paragraph.font.size is not None:
                    size = int(paragraph.font.size.pt)
                    break
            assert text_fits(text, int(shape.width), int(shape.height), size)
    assert saw_image


def test_course_design_parses_a_model_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from app.profassist.llm import complete

    _fake_model(
        monkeypatch,
        json.dumps(
            {
                "reply": "Drafted from your notes and the About this professor section.",
                "clos": [
                    {
                        "code": "CLO1",
                        "text": "Explain how an LLM agent differs from a trained machine learning model.",
                    }
                ],
                "weeks": [{"week": 1, "topic": "Agents", "clos": ["CLO1"], "notes": "Draft."}],
                "plan": [
                    {
                        "title": "Group report 1",
                        "weight": 40,
                        "clos": ["CLO1"],
                        "brief": "A short report that quotes the evidence.",
                        "kind": "assignment",
                    }
                ],
            }
        ),
    )
    drafted = complete(
        "course_design",
        {
            "message": "Draft the course",
            "chunks": [
                {
                    "id": "c1",
                    "text": "Explain how an LLM agent differs from a trained machine learning model.",
                }
            ],
            "soul": "Short sentences.",
        },
    )
    assert drafted["weeks"]
    assert drafted["clos"][0]["code"] == "CLO1"
    assert drafted["plan"][0]["weight"] == 40


def test_rubric_import_flags_vague_wording() -> None:
    from app.profassist.rubric_build import alignment, parse_rubric_text

    text = """
Criterion: Evidence
Weight: 2
Beginning: Names the task
Developing: Partly shows the outcome
Proficient: Quotes an example
Advanced: States a limitation

Criterion: Style
Weight: 1
Beginning: A good try
Developing: Appropriate detail
Proficient: Various points
Advanced: Nice work
"""
    criteria = parse_rubric_text(text)
    assert criteria[0]["name"] == "Evidence"
    assert criteria[0]["levels"]["advanced"].startswith("States")
    report = alignment(criteria, ["Explain how an LLM agent differs from a trained model."])
    assert any("vague" in flag for flag in report["flags"])


def test_sample_attachments_keep_the_evidence() -> None:
    from app.profassist.moodle import FakeMoodleConnector
    from app.profassist.storage import extract_text

    rows = FakeMoodleConnector().list_submissions("asg-901")
    group_a = next(row for row in rows if row["group_name"] == "Group A")
    names = {item["filename"] for item in group_a["files"]}
    assert "group-a-report.docx" in names
    assert "group-a-code.zip" in names
    docx = next(item for item in group_a["files"] if item["filename"].endswith(".docx"))
    assert "42.7" in extract_text(docx["filename"], docx["data"])
    pdf_row = next(row for row in rows if row["id"] == "sub-b")
    pdf = pdf_row["files"][0]
    assert "42.7" in extract_text(pdf["filename"], pdf["data"])
    workshop = FakeMoodleConnector().list_workshop_submissions("ws-901")
    assert workshop[0]["peer_reviews"]
    assert workshop[0]["files"]


def test_real_grade_push_stays_off_until_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.moodle import RealMoodleConnector

    monkeypatch.setenv("MOODLE_BASE_URL", "https://moodle.example.edu")
    monkeypatch.setenv("MOODLE_WS_TOKEN", "token")
    monkeypatch.delenv("MOODLE_PUSH_ENABLED", raising=False)
    with pytest.raises(ProfassistError) as caught:
        RealMoodleConnector().push({"type": "grade", "feedback": "You quoted the meter."})
    assert caught.value.status == 501
    assert "MOODLE_PUSH_ENABLED" in caught.value.detail


def test_subject_outline_document_and_catalogue() -> None:
    from app.profassist.outline_data import demo_outline
    from app.profassist.outline_doc import render_docx, render_pdf

    body = demo_outline()
    assert len(body["clos"]) == 6
    assert len(body["plos"]) == 6
    assert len(body["weeks"]) == 11
    assert len(body["readings"]) == 5
    assert len(body["outcome_measures"]) == 6
    assert len(body["assessment_tasks"]) == 4
    assert len(body["genai"]) == 6
    assert len(body["grades"]) == 7
    assert len(body["policy_documents"]) == 18
    assert "tasks" not in body
    assert "criteria" not in body
    assert body["clos"][0]["plos"]
    assert render_pdf(body)[:4] == b"%PDF"
    assert render_docx(body)[:2] == b"PK"


def test_chat_tools_require_a_professor_and_a_confirm() -> None:
    import asyncio
    import uuid

    from app.profassist.platform_tools import choose_tool, invoke_tool, set_tool_actor

    assert choose_tool("Please sync Moodle")[0] == "moodle_sync"
    assert choose_tool("Suggest an assessment for LO1")[0] == "suggest_assessments"

    async def run() -> None:
        set_tool_actor(uuid.uuid4(), uuid.uuid4(), is_admin=False)
        pending = await invoke_tool(None, "moodle_push", {"draft_id": "x"}, confirmed=False)
        assert pending["needs_confirm"] is True
        with pytest.raises(ProfassistError):
            await invoke_tool(None, "admin_ai_settings", {}, confirmed=False)

    asyncio.run(run())


def test_choose_tool_routes_outline_review_and_opinion_by_context() -> None:
    from app.profassist.platform_tools import choose_tool

    oid = "11111111-1111-1111-1111-111111111111"
    name, args = choose_tool("review this outline", {"outline_id": oid})
    assert name == "review_outline"
    assert args["outline_id"] == oid
    assert args["mode"] == "council"
    assert args["reviewer"] == "curriculum"

    name, args = choose_tool("what do you think?", {"outline_id": oid})
    assert name == "review_outline"
    assert args["outline_id"] == oid
    assert args["mode"] == "single"
    assert args["reviewer"] == "curriculum"


def test_choose_tool_falls_back_to_assistant_chat_not_list_courses() -> None:
    from app.profassist.platform_tools import choose_tool

    name, args = choose_tool("hello", {})
    assert name == "assistant_chat"
    assert args["message"] == "hello"
    assert args["context"] == {}


def test_assistant_chat_is_honest_without_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.profassist.providers as providers
    from app.profassist.platform_tools import _assistant_chat

    monkeypatch.setattr(providers, "key_configured", lambda _provider: False)

    current = {"org_id": "org", "user_id": "user", "is_admin": False}
    answer = asyncio.run(
        _assistant_chat(
            None,
            current,
            {"message": "what is on this page?", "context": {"page": "dashboard"}},
        )
    )
    assert "No AI model is configured" in answer["answer"]
    assert "LLM_API_KEY" in answer["answer"]


def test_review_outline_handler_returns_findings_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import uuid

    import app.profassist.outline_review as outline_review
    from app.profassist.platform_tools import _reply, _review_outline

    outline_id = uuid.uuid4()
    seen: dict = {}

    async def fake_run_review(db, org_id, user_id, oid, *, mode, reviewer):
        seen.update(
            {
                "db": db,
                "org_id": org_id,
                "user_id": user_id,
                "oid": oid,
                "mode": mode,
                "reviewer": reviewer,
            }
        )
        return {
            "score": 82,
            "summary": "Two outcomes need a clearer program link.",
            "findings": [
                {"section": "outcomes", "message": "CLO1 does not map to a program outcome."},
                {"section": "assessments", "message": "CLO1 is not assessed by any task."},
            ],
        }

    monkeypatch.setattr(outline_review, "run_review", fake_run_review)

    current = {"org_id": "org", "user_id": "user", "is_admin": False}
    args = {"outline_id": str(outline_id), "mode": "council", "reviewer": "curriculum"}
    snapshot = dict(args)
    result = asyncio.run(_review_outline(None, current, args))

    assert result["score"] == 82
    assert len(result["findings"]) == 2
    assert seen["oid"] == outline_id
    assert seen["mode"] == "council"
    assert seen["reviewer"] == "curriculum"
    # The handler only reads its arguments; the outline snapshot is untouched.
    assert args == snapshot

    reply = _reply("review_outline", result)
    assert "This is a review, not a verdict. Nothing was changed." in reply
    assert "CLO1 does not map" in reply


def test_choose_tool_routes_rubric_review_by_context() -> None:
    from app.profassist.platform_tools import choose_tool

    rid = "22222222-2222-2222-2222-222222222222"
    oid = "11111111-1111-1111-1111-111111111111"
    name, args = choose_tool("Review this rubric", {"rubric_id": rid, "page": "/rubric"})
    assert name == "review_rubric"
    assert args["rubric_id"] == rid

    # Both ids are set: the page decides which review tool wins.
    name, _ = choose_tool(
        "Review this rubric", {"rubric_id": rid, "outline_id": oid, "page": "/rubric"}
    )
    assert name == "review_rubric"
    name, _ = choose_tool(
        "Review this outline", {"rubric_id": rid, "outline_id": oid, "page": "/outline"}
    )
    assert name == "review_outline"


def _fake_rubric_loader(monkeypatch: pytest.MonkeyPatch, data: dict) -> None:
    import app.profassist.service as service

    async def fake_owned(db, model, org_id, row_id, user_id=None):
        return object()

    async def fake_dict(db, row):
        return data

    monkeypatch.setattr(service, "_owned", fake_owned)
    monkeypatch.setattr(service, "_assessment_dict", fake_dict)


def test_review_rubric_reports_findings_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import copy
    import uuid

    from app.profassist.platform_tools import _reply, _review_rubric

    fake = {
        "title": "Workshops rubric",
        "status": "draft",
        "criteria": [
            {
                "name": "Evidence",
                "weight": 60,
                "levels": {
                    "beginning": "Little evidence",
                    "developing": "",
                    "proficient": "Clear evidence",
                    "advanced": "Strong evidence",
                },
            },
            {
                "name": "Reflection",
                "weight": 30,
                "levels": {
                    "beginning": "Describes",
                    "developing": "Explains",
                    "proficient": "Analyses",
                    "advanced": "Evaluates",
                },
            },
        ],
        "alignment": {"flags": ["No criterion mentions this outcome: Design a study."]},
    }
    snapshot = copy.deepcopy(fake)
    _fake_rubric_loader(monkeypatch, fake)

    current = {"org_id": "org", "user_id": "user", "is_admin": False}
    result = asyncio.run(_review_rubric(None, current, {"rubric_id": str(uuid.uuid4())}))

    assert result["title"] == "Workshops rubric"
    assert result["status"] == "draft"
    assert result["criteria_count"] == 2
    assert result["weight_total"] == 90
    assert result["changed"] is False
    messages = [item["message"] for item in result["findings"]]
    assert any("90%" in message for message in messages)
    assert any("blank developing" in message for message in messages)
    assert any("No criterion mentions this outcome" in message for message in messages)
    # The handler reads the rubric; the fake payload is untouched.
    assert fake == snapshot

    reply = _reply("review_rubric", result)
    assert "Workshops rubric" in reply
    assert "weighting 90%" in reply
    assert "This is a review, not a verdict. Nothing was changed." in reply


def test_review_rubric_with_no_criteria_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import uuid

    from app.profassist.platform_tools import _review_rubric

    _fake_rubric_loader(
        monkeypatch,
        {"title": "Empty rubric", "status": "draft", "criteria": [], "alignment": {}},
    )
    current = {"org_id": "org", "user_id": "user", "is_admin": False}
    result = asyncio.run(_review_rubric(None, current, {"rubric_id": str(uuid.uuid4())}))

    assert result["criteria_count"] == 0
    assert result["weight_total"] == 0
    assert result["findings"] == [{"severity": "high", "message": "No criteria yet."}]


def test_review_rubric_returns_404_for_a_foreign_rubric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import uuid

    import app.profassist.service as service
    from app.profassist.errors import ProfassistError
    from app.profassist.platform_tools import _review_rubric

    async def foreign(db, model, org_id, row_id, user_id=None):
        raise ProfassistError(404, "Not found in this workspace")

    monkeypatch.setattr(service, "_owned", foreign)

    current = {"org_id": "org", "user_id": "user", "is_admin": False}
    with pytest.raises(ProfassistError) as caught:
        asyncio.run(_review_rubric(None, current, {"rubric_id": str(uuid.uuid4())}))
    assert caught.value.status == 404


def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "LLM_API_KEY",
        "OLLAMA_API_BASE",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "MISTRAL_API_KEY",
        "AZURE_API_KEY",
        "AZURE_API_BASE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _fake_model(
    monkeypatch: pytest.MonkeyPatch, content: str, calls: list[object] | None = None
) -> None:
    from types import SimpleNamespace

    from app.profassist.runtime import bind_runtime

    bind_runtime({}, {}, {"provider": "openai", "model": "gpt-4o-mini", "agents": {}})
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class Response:
        choices = [SimpleNamespace(message=SimpleNamespace(content=content))]

    def fake_generate(provider_id: str, model: str, messages: object, **kwargs: object) -> Response:
        if calls is not None:
            calls.append(messages)
        return Response()

    monkeypatch.setattr("app.profassist.providers.generate", fake_generate)


def test_outline_assist_suggests_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from app.profassist.llm import complete

    _fake_model(
        monkeypatch,
        json.dumps(
            {
                "reply": "Suggested outcomes.",
                "suggestion": {
                    "clos": [{"code": "CLO1", "text": "Explain the idea."}],
                    "plos": [{"code": "PLO1", "text": "Apply the idea."}],
                },
            }
        ),
    )
    drafted = complete("outline_assist", {"step": "outcomes", "message": "Suggest outcomes"})
    assert drafted["suggestion"]["clos"]
    assert drafted["suggestion"]["plos"]


def test_outline_assist_prompt_interviews_for_the_next_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from app.profassist.llm import complete

    calls: list[object] = []
    _fake_model(monkeypatch, json.dumps({"reply": "ok", "suggestion": {}}), calls=calls)

    complete("outline_assist", {"step": "outcomes", "message": "Explain the idea."})
    complete("outline_assist", {"step": "policies", "message": "Late work loses marks."})

    def system_of(messages: object) -> str:
        assert isinstance(messages, list)
        return next(message["content"] for message in messages if message["role"] == "system")

    first = system_of(calls[0])
    assert "current section is outcomes" in first
    assert "next section: schedule" in first
    assert "exactly ONE natural question" in first

    last = system_of(calls[1])
    assert "current section is policies" in last
    assert "ready to review" in last
    assert "ONE natural question" not in last


def test_outcome_answer_follows_the_requested_count(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from app.profassist.llm import complete
    from app.profassist.outline import asked_count, shape_outcomes

    message = "Draft 3 learning outcomes for AAS 910"
    assert asked_count(message) == 3
    assert asked_count("Suggest outcomes") is None
    _fake_model(
        monkeypatch,
        json.dumps(
            {
                "suggestion": {
                    "clos": [
                        {"code": f"CLO{index}", "text": f"Outcome {index}"} for index in range(1, 5)
                    ]
                }
            }
        ),
    )
    drafted = complete("outline_assist", {"step": "outcomes", "message": message})
    shaped, reply = shape_outcomes(drafted["suggestion"], message)
    assert len(shaped["clos"]) == 3
    assert reply is not None
    assert "1. " in reply
    assert "2. " in reply
    assert "3. " in reply
    assert "\n4. " not in reply


def test_outline_review_names_a_missing_policy_and_a_weight_gap() -> None:
    from app.profassist.outline_data import demo_outline
    from app.profassist.outline_review import apply_fix, review_outline, score_of

    body = demo_outline()
    body["attendance"] = ""
    # Legacy review input: outlines no longer own tasks, but the reviewer still
    # weighs any that are present so old drafts keep the same checks.
    body["tasks"] = [
        {
            "number": "A1",
            "name": "Workshops",
            "weight": 10,
            "lo_codes": ["LO1", "LO2", "LO3", "LO4", "LO5", "LO6"],
        }
    ]
    findings = review_outline(body, "focus on healthcare cases")
    assert any(
        item["object_id"] == "attendance" and item["severity"] == "high" for item in findings
    )
    assert any(item["object_id"] == "weights" for item in findings)
    fixed = apply_fix(body, next(item for item in findings if item["object_id"] == "attendance"))
    assert fixed["attendance"]
    assert score_of(findings) < 100


def test_council_script_walks_marking_debate_judge_and_verdict() -> None:
    from app.profassist.council_script import script_for

    events = script_for("grade")
    kinds = [event["type"] for event in events]
    assert kinds[0] == "step"
    assert "debate" in [event.get("step") for event in events]
    assert events[-1]["type"] == "verdict"
    assert any(event["type"] == "arrow" for event in events)


def test_a_missing_model_raises_an_explicit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _offline(monkeypatch)
    with pytest.raises(ProfassistError) as caught:
        complete(
            "feedback",
            {
                "quote": "The baseline load is 42.7 kWh during the teaching day.",
                "level": "proficient",
                "soul": "",
            },
        )
    assert caught.value.status == 503
    assert "No AI model is configured" in caught.value.detail


def test_local_ollama_is_used_only_when_the_chosen_provider_has_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.profassist.runtime import agent_route, bind_runtime

    bind_runtime({}, {}, {"provider": "openai", "model": "gpt-4o-mini", "agents": {}})
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert agent_route("chat")["provider"] == "openai"
    monkeypatch.setenv("OLLAMA_API_BASE", "http://127.0.0.1:11434")
    monkeypatch.setenv("LLM_MODEL", "llama3.2:1b")
    routed = agent_route("persona_evidence")
    assert routed["provider"] == "ollama"
    assert routed["model"] == "llama3.2:1b"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert agent_route("chat")["provider"] == "openai"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("LLM_MODEL", "gemini/gemini-3.5-flash")
    routed = agent_route("chat")
    assert routed["provider"] == "gemini"
    assert routed["model"] == "gemini-3.5-flash"
    assert "test-gemini-key" not in str(routed)
    monkeypatch.setenv("LLM_MODEL", "llama3.2:1b")
    assert agent_route("chat")["model"] == "gemini-3.5-flash-lite"


def test_an_explicit_provider_prefix_in_llm_model_selects_that_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Gemini base URL must not be spent on the OpenAI key just because both are set."""
    from app.profassist.runtime import agent_route, bind_runtime

    bind_runtime({}, {}, {"provider": "openai", "model": "gpt-4o-mini", "agents": {}})
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("LLM_MODEL", "gemini/gemini-3.1-flash-lite")

    routed = agent_route("course_designer")
    assert routed == {"provider": "gemini", "model": "gemini-3.1-flash-lite"}
    assert "test-gemini-key" not in str(routed)

    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    assert agent_route("course_designer") == {"provider": "openai", "model": "gpt-4o-mini"}

    bind_runtime({}, {}, {"provider": "openai", "model": "gpt-4o-mini", "agents": {}})


def test_the_database_model_choice_still_wins_without_a_provider_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.profassist.runtime import agent_route, bind_runtime

    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    bind_runtime(
        {}, {}, {"provider": "anthropic", "model": "claude-3-5-haiku-latest", "agents": {}}
    )

    assert agent_route("chat") == {"provider": "anthropic", "model": "claude-3-5-haiku-latest"}

    # A bare model name does not say which key it belongs to, so it changes nothing.
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    assert agent_route("chat") == {"provider": "anthropic", "model": "claude-3-5-haiku-latest"}

    # An admin route for one agent still wins over the app-wide choice.
    bind_runtime(
        {},
        {},
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "agents": {"chat": {"provider": "anthropic", "model": "claude-3-5-haiku-latest"}},
        },
    )
    assert agent_route("chat") == {"provider": "anthropic", "model": "claude-3-5-haiku-latest"}
    assert agent_route("feedback_writer") == {"provider": "openai", "model": "gpt-4o-mini"}

    bind_runtime({}, {}, {"provider": "openai", "model": "gpt-4o-mini", "agents": {}})


def test_connection_errors_hide_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.providers import _safe_detail

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key-do-not-show")
    text = _safe_detail("rejected test-gemini-key-do-not-show")
    assert "test-gemini-key" not in text
    assert "hidden" in text


def test_ai_settings_never_return_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from app.profassist.settings_admin import connection_status

    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret-do-not-show")
    monkeypatch.setenv("MOODLE_WS_TOKEN", "moodle-token-do-not-show")
    monkeypatch.setenv("MOODLE_MODE", "fake")
    monkeypatch.delenv("MOODLE_PUSH_ENABLED", raising=False)
    payload = connection_status()
    text = json.dumps(payload)
    assert "sk-live-secret-do-not-show" not in text
    assert "moodle-token-do-not-show" not in text
    assert payload["moodle_mode"] == "fake"
    assert payload["moodle_push_enabled"] is False
    states = {row["name"]: row["state"] for row in payload["secrets"]}
    assert states["OPENAI_API_KEY"] == "set, hidden"
    assert states["MOODLE_WS_TOKEN"] == "set, hidden"


def test_fresh_course_appears_on_the_integrity_board() -> None:
    from app.profassist.integrity_board import overview, register_course, unregister_course
    from app.profassist.journey import fresh_board

    course = fresh_board("AAS 910", "Assurance Studio", "A3", "Group project")
    register_course(course)
    try:
        board = overview(course["slug"])
        assert board["summary"]["courses"] == 1
        every_course = overview("all")
        assert [row["slug"] for row in every_course["courses"]] == [course["slug"]]
        card = board["items"][0]
        assert card["number"] == "A3"
        assert card["groups"] == 4
        assert card["status"] == "Concern"
    finally:
        unregister_course(course["slug"])


def test_fake_moodle_stages_pdf_and_docx_without_a_network_call() -> None:
    from app.profassist.moodle import CATALOG, STUDENTS, SUBMISSIONS, FakeMoodleConnector

    client = FakeMoodleConnector()
    course_id = "mdl-journey-test"
    assignment_id = "asg-journey-test"
    student_id = "j-journey-test-1"
    submission_id = "sub-journey-test-a"
    client.stage_course_work(
        course={
            "id": course_id,
            "code": "AAS910TEST",
            "title": "Assurance Studio",
            "term": "2026",
        },
        students=[
            {
                "id": student_id,
                "course_id": course_id,
                "display_name": "Sara Al Maktoum",
                "email": "",
                "student_number": "8889101",
            }
        ],
        assignment={
            "id": assignment_id,
            "course_id": course_id,
            "name": "Group project",
            "kind": "assignment",
            "rubric": [],
        },
        submissions=[
            {
                "id": submission_id,
                "assignment_id": assignment_id,
                "group_name": "Group A",
                "text": "Group A submitted a file.",
                "files": [
                    {
                        "filename": "group-a.pdf",
                        "content_type": "application/pdf",
                        "data": b"%PDF-1.4",
                    }
                ],
            },
            {
                "id": submission_id + "-b",
                "assignment_id": assignment_id,
                "group_name": "Group B",
                "text": "Group B submitted a file.",
                "files": [
                    {
                        "filename": "group-b.docx",
                        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "data": b"PK",
                    }
                ],
            },
            {
                "id": submission_id + "-c",
                "assignment_id": assignment_id,
                "group_name": "Group C",
                "text": "Group C submitted a file.",
                "files": [
                    {"filename": "group-c.pdf", "content_type": "application/pdf", "data": b"%PDF"}
                ],
            },
        ],
    )
    try:
        assert any(row["id"] == course_id for row in client.list_courses())
        rows = client.list_submissions(assignment_id)
        names = {row["files"][0]["filename"] for row in rows}
        assert {"group-a.pdf", "group-b.docx", "group-c.pdf"} <= names
        client.stage_course_work(
            course={
                "id": course_id,
                "code": "AAS910TEST",
                "title": "Assurance Studio",
                "term": "2026",
            },
            students=[],
            assignment={
                "id": assignment_id,
                "course_id": course_id,
                "name": "Group project",
                "kind": "assignment",
                "rubric": [],
            },
            submissions=[],
        )
        assert sum(1 for row in client.list_courses() if row["id"] == course_id) == 1
    finally:
        CATALOG["courses"][:] = [row for row in CATALOG["courses"] if row.get("id") != course_id]
        CATALOG["assignments"][:] = [
            row for row in CATALOG["assignments"] if row.get("id") != assignment_id
        ]
        STUDENTS[:] = [row for row in STUDENTS if row.get("id") != student_id]
        SUBMISSIONS[:] = [
            row for row in SUBMISSIONS if not str(row.get("id", "")).startswith("sub-journey-test")
        ]


def test_dossier_model_payload_keeps_filenames_and_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from app.profassist.llm import complete

    calls: list[object] = []
    _fake_model(monkeypatch, json.dumps({"summary": "ok"}), calls=calls)

    complete(
        "dossier_extract",
        {
            "material_id": "m1",
            "filename": "PIPE903-notes-v2.txt",
            "chunks": [{"ordinal": 0, "text": "CLO1 maps to the report."}],
        },
    )

    messages = calls[0]
    assert isinstance(messages, list)
    user = next(message["content"] for message in messages if message["role"] == "user")
    assert "PIPE903-notes-v2.txt" in user
    assert "CLO1" in user


def test_dossier_calls_ask_gemini_for_the_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from types import SimpleNamespace

    from app.profassist import runtime
    from app.profassist.llm import complete
    from app.profassist.runtime import bind_runtime

    previous = (runtime._prompts.get(), runtime._tools.get(), runtime._model.get())
    try:
        bind_runtime({}, {}, {"provider": "gemini", "model": "gemini-3.5-flash-lite", "agents": {}})
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        calls: list[dict[str, object]] = []

        class Response:
            choices = [
                SimpleNamespace(message=SimpleNamespace(content=json.dumps({"summary": "ok"})))
            ]

        def fake_generate(
            provider_id: str, model: str, messages: object, **kwargs: object
        ) -> Response:
            calls.append({"provider": provider_id, "messages": messages, "kwargs": kwargs})
            return Response()

        monkeypatch.setattr("app.profassist.providers.generate", fake_generate)

        complete("dossier_extract", {"filename": "notes.txt", "chunks": []})
    finally:
        runtime._prompts.set(previous[0])
        runtime._tools.set(previous[1])
        runtime._model.set(previous[2])

    assert calls[0]["provider"] == "gemini"
    response_format = calls[0]["kwargs"]["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_object"
    assert response_format["response_schema"]["title"] == "FileDossier"


def test_dossier_schemas_require_the_content_fields() -> None:
    """The schema sent to Gemini demands what a partial reply used to skip."""
    from app.profassist.course_memory.schemas import FileDossier
    from app.profassist.llm import DOSSIER_SCHEMAS

    extract = DOSSIER_SCHEMAS["dossier_extract"]
    assert {"document_kind", "summary", "topics", "outcomes", "assessments"} <= set(
        extract["required"]
    )
    merge = DOSSIER_SCHEMAS["dossier_merge"]
    assert {"summary", "topics", "outcomes", "assessments"} <= set(merge["required"])

    # The Pydantic model itself stays tolerant, so a partial reply still validates.
    assert FileDossier.model_validate({"summary": "ok"}).summary == "ok"


def test_complete_parses_json_with_trailing_prose(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist.llm import complete

    _fake_model(monkeypatch, '{"reply": "ok"} then some trailing prose')
    drafted = complete("ideas", {"title": "Report"})

    assert drafted == {"reply": "ok"}


def test_complete_retries_once_when_the_reply_is_not_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from types import SimpleNamespace

    from app.profassist.llm import complete
    from app.profassist.runtime import bind_runtime

    bind_runtime({}, {}, {"provider": "openai", "model": "gpt-4o-mini", "agents": {}})
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    replies = ["not json at all", json.dumps({"reply": "ok"})]
    calls: list[object] = []

    class Response:
        def __init__(self, content: str) -> None:
            self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]

    def fake_generate(provider_id: str, model: str, messages: object, **kwargs: object) -> Response:
        calls.append(messages)
        return Response(replies[len(calls) - 1])

    monkeypatch.setattr("app.profassist.providers.generate", fake_generate)

    drafted = complete("ideas", {"title": "Report"})

    assert drafted == {"reply": "ok"}
    assert len(calls) == 2
    second = calls[1]
    assert isinstance(second, list)
    user = next(message["content"] for message in second if message["role"] == "user")
    assert "Return valid JSON only, no prose" in user
