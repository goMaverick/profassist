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


def test_debate_starts_only_past_the_threshold() -> None:
    from app.profassist.grading import level_spread, needs_debate

    close = [{"level": "proficient"}, {"level": "developing"}]
    far = [{"level": "advanced"}, {"level": "beginning"}]
    assert level_spread(close) == 1
    assert needs_debate(close, threshold=0) is True
    assert needs_debate(close, threshold=1) is False
    assert needs_debate(far, threshold=1) is True


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


def test_about_section_is_labelled_and_scrubbed() -> None:
    from app.profassist.llm import complete
    from app.profassist.runtime import labelled_about, set_about

    set_about("She prefers short feedback.\nEmail sara@student.uowd.ac.ae")
    block = labelled_about()
    assert block.startswith("\n\n## About this professor\n")
    assert "@" not in block
    assert "sara" not in block.lower()
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


def test_course_design_uses_notes_and_a_shorter_reply() -> None:
    from app.profassist.llm import complete

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
    shorter = complete("course_design", {"message": "Make the weeks shorter", "chunks": []})
    assert "shortened" in shorter["reply"].lower()


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
