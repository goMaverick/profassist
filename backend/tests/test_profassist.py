"""Unit tests for the professor workflows. No database and no model key."""

import pytest

from app.profassist.errors import ProfassistError, require_same_tenant
from app.profassist.grading import (
    assert_can_push,
    is_blind_sample,
    quotes_in_text,
    reconcile,
)
from app.profassist.llm import complete, demo_complete
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


def test_model_gate_refuses_an_email() -> None:
    with pytest.raises(RuntimeError):
        assert_prompt_is_clean("contact ada@university.edu now")


def test_demo_quotes_are_in_the_submission() -> None:
    submission = (
        "We chose this use case because the brief asks for a measurable operational problem. "
        "A limitation is that weekend readings were missing, therefore the trend is only reliable on weekdays."
    )
    vote = demo_complete(
        "grade_persona",
        {"persona": "strict", "submission": submission, "criterion": {"name": "CLO 1"}},
    )
    kept, rejected = quotes_in_text(vote["quotes"], submission)
    assert kept
    assert rejected == []


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


def test_calibrator_and_risk_are_untrained() -> None:
    calibrator = grade_calibrator({"judge_level": "proficient"})
    assert calibrator["trained"] is False
    assert calibrator["level"] is None
    risk = at_risk_snapshot([{"display_name": "Sara Al Maktoum", "external_id": "stu-1"}])
    assert risk["trained"] is False
    assert risk["students"][0]["risk"] is None
    assert risk["students"][0]["display_name"] == "Sara Al Maktoum"


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


def test_connector_factory_defaults_to_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOODLE_MODE", raising=False)
    assert isinstance(get_connector(), FakeMoodleConnector)
    monkeypatch.setenv("MOODLE_MODE", "real")
    real = get_connector()
    assert isinstance(real, RealMoodleConnector)
    with pytest.raises(ProfassistError) as caught:
        real.list_courses()
    assert caught.value.status == 503


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


def test_demo_completion_does_not_call_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = complete(
        "feedback",
        {
            "quote": "The baseline load is 42.7 kWh during the teaching day.",
            "level": "proficient",
            "soul": "",
        },
    )
    assert "42.7" in result["feedback"]
    assert "!" not in result["feedback"]
