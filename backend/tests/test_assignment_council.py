"""Assignment council: deterministic checks, chair merge, and no invented findings."""

from typing import Any

import pytest

import app.profassist.assignment_council as assignment_council
from app.profassist.assignment_data import fixed_report_sections

LEVELS = {
    "beginning": "Little detail.",
    "developing": "Some detail.",
    "proficient": "Clear detail.",
    "advanced": "Insightful detail.",
}


def _document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "class_details": {
            "assessment": "Assessment 2: Solutions Architecture Report",
            "weight": "25%",
            "report_due": "Week 7",
        },
        "overview": ["Design an AI solution architecture."],
        "problem_choices": [
            {"problem": "Bank fraud detection", "description": "Real-time scoring."}
        ],
        "deliverables": [{"title": "Technical report", "description": "At most 2,500 words."}],
        "report_sections": fixed_report_sections(),
    }
    document.update(overrides)
    return document


def _rubric() -> list[dict[str, Any]]:
    return [
        {"name": "Architecture", "weight": 60, "levels": dict(LEVELS)},
        {"name": "Ethics", "weight": 40, "levels": dict(LEVELS)},
    ]


def _outline() -> dict[str, Any]:
    return {
        "clos": [{"code": "LO1", "text": "Design an end-to-end AI solution."}],
        "outcome_measures": [{"lo_code": "LO1", "measures": "Assessment 2 report"}],
    }


def _wire(monkeypatch: pytest.MonkeyPatch, reply: Any) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_complete(task: str, payload: dict[str, Any]) -> Any:
        calls.append((task, payload))
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(task, payload)
        return reply

    monkeypatch.setattr(assignment_council.llm, "complete", fake_complete)
    return calls


def test_assignment_checks_are_tagged_by_reviewer() -> None:
    checks = assignment_council.assignment_checks({}, [], [], {})

    reviewers = {item["code"]: item["reviewer"] for item in checks}
    assert reviewers["no_outcomes"] == "alignment"
    assert reviewers["missing_outline"] == "alignment"
    assert reviewers["empty_overview"] == "brief"
    assert reviewers["missing_report_sections"] == "brief"
    assert reviewers["unnamed_assessment"] == "brief"
    assert reviewers["no_criteria"] == "rubric"


def test_alignment_skips_the_per_clo_check_without_an_assessment_map() -> None:
    checks = assignment_council.assignment_checks(
        _document(),
        _rubric(),
        ["Design an end-to-end AI solution."],
        {
            "clos": [
                {"code": "LO1", "text": "Design an AI solution."},
                {"code": "LO2", "text": "Reason about ethics."},
            ]
        },
    )

    alignment = [item for item in checks if item["reviewer"] == "alignment"]
    assert [item["code"] for item in alignment] == ["missing_assessment_map"]


def test_an_unassessed_clo_is_a_high_alignment_issue() -> None:
    checks = assignment_council.assignment_checks(
        _document(),
        _rubric(),
        ["Design an AI solution.", "Reason about ethics."],
        {
            "clos": [
                {"code": "LO1", "text": "Design an AI solution."},
                {"code": "LO2", "text": "Reason about ethics."},
            ],
            "outcome_measures": [{"lo_code": "LO1", "measures": "Assessment 2"}],
        },
    )

    unassessed = [item for item in checks if item["code"] == "unassessed_outcome"]
    assert len(unassessed) == 1
    assert unassessed[0]["severity"] == "high"
    assert "LO2" in unassessed[0]["issue"]


def test_brief_checks_report_missing_sections_and_unnamed_assessment() -> None:
    document = _document(
        class_details={"assessment": "new assignment", "weight": "", "report_due": ""},
        report_sections=[],
    )

    checks = assignment_council.assignment_checks(document, _rubric(), [], {})
    codes = {item["code"] for item in checks if item["reviewer"] == "brief"}

    assert "missing_report_sections" in codes
    assert "unnamed_assessment" in codes
    assert "missing_weight" in codes
    assert "missing_due" in codes


def test_rubric_checks_cover_total_levels_and_duplicates() -> None:
    rubric = [
        {"name": "Architecture", "weight": 50, "levels": {"advanced": "Strong."}},
        {"name": "Architecture", "weight": 40, "levels": dict(LEVELS)},
    ]

    checks = assignment_council.assignment_checks(_document(), rubric, [], {})
    rubric_codes = [item["code"] for item in checks if item["reviewer"] == "rubric"]

    assert "rubric_total" in rubric_codes
    assert rubric_codes.count("missing_level") == 3
    assert "duplicate_criterion" in rubric_codes


def test_zero_numeric_weight_is_high() -> None:
    document = _document(class_details={"assessment": "Assessment 2", "weight": "0%"})

    checks = assignment_council.assignment_checks(document, _rubric(), [], {})

    zero = next(item for item in checks if item["code"] == "zero_weight")
    assert zero["reviewer"] == "alignment"
    assert zero["severity"] == "high"


def test_a_clean_assignment_has_no_findings_and_four_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _wire(
        monkeypatch,
        {"verdict": "pass", "summary": "The brief is complete.", "strengths": ["Clear outcomes."]},
    )

    review = assignment_council.run_assignment_council(
        _document(),
        _rubric(),
        ["Design an end-to-end AI solution."],
        _outline(),
        {"summary": "Course memory."},
    )

    assert review["issues"] == []
    assert review["verdict"] == "pass"
    assert review["score"] == 100
    assert [item["role"] for item in review["messages"]] == [
        "alignment",
        "brief",
        "rubric",
        "chair",
    ]
    assert review["messages"][1]["text"] == "No issues from my pass."
    assert "The brief is complete." in review["messages"][-1]["text"]
    assert [task for task, _payload in calls] == [
        "council_review",
        "council_review",
        "council_review",
        "assignment_review",
    ]
    chair_call = next(payload for task, payload in calls if task == "assignment_review")
    assert chair_call["dossier"] == {"summary": "Course memory."}


def test_the_chair_cannot_invent_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    chair_reply = {
        "verdict": "revise",
        "summary": "The rubric is perfect.",
        "strengths": [],
        "issues": [
            {
                "reviewer": "rubric",
                "severity": "high",
                "issue": "The rubric is perfect, which is suspicious.",
            }
        ],
    }
    _wire(
        monkeypatch,
        lambda task, _payload: chair_reply if task == "assignment_review" else {"issues": []},
    )

    review = assignment_council.run_assignment_council(
        _document(),
        _rubric(),
        ["Design an end-to-end AI solution."],
        _outline(),
    )

    assert review["issues"] == []
    assert review["verdict"] == "pass"


def test_role_issues_are_capped_and_merged(monkeypatch: pytest.MonkeyPatch) -> None:
    model_issues = [
        {"severity": "medium", "issue": f"Model finding {index}", "fix": "Tighten."}
        for index in range(20)
    ]

    def reply(task: str, payload: dict[str, Any]) -> Any:
        if task == "council_review" and payload.get("reviewer") == "rubric":
            return {"issues": model_issues}
        if task == "assignment_review":
            return {"verdict": "revise", "summary": "", "strengths": []}
        return {"issues": []}

    _wire(monkeypatch, reply)

    review = assignment_council.run_assignment_council(
        _document(),
        _rubric(),
        ["Design an end-to-end AI solution."],
        _outline(),
    )

    assert len(review["issues"]) == assignment_council.MAX_COUNCIL_ISSUES == 12
    assert review["score"] < 70
    assert review["verdict"] == "revise"
    assert all(item["reviewer"] == "rubric" for item in review["issues"])


def test_a_failed_chair_degrades_to_the_deterministic_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, RuntimeError("the model is down"))

    review = assignment_council.run_assignment_council(
        _document(),
        _rubric(),
        ["Design an end-to-end AI solution."],
        _outline(),
    )

    assert review["degraded"] is True
    assert review["issues"] == []
    assert review["verdict"] == "pass"
    assert [item["role"] for item in review["messages"]] == [
        "alignment",
        "brief",
        "rubric",
        "chair",
    ]
    assert review["messages"][-1]["text"].startswith("The council verdict is pass")
