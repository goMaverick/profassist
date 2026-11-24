"""Merge is deterministic: authority wins, provenance is unioned, output fits.

No model, no network, no database. Every case must produce a dossier that the
``MergedDossier`` contract accepts.
"""

from __future__ import annotations

import json

from app.profassist.course_memory.cleaners import READING_CAP, WEEK_CAP
from app.profassist.course_memory.merge import MAX_CHARS, merge_dossiers, shrink_dossier
from app.profassist.course_memory.schemas import MergedDossier


def dossier(filename: str, kind: str, **fields: object) -> dict:
    return {"filename": filename, "document_kind": kind, **fields}


def _valid(merged: dict) -> dict:
    MergedDossier.model_validate(merged)
    return merged


def test_empty_input_is_a_valid_dossier() -> None:
    merged = _valid(merge_dossiers())
    assert merged["version"] == 1
    assert merged["topics"] == []
    assert merged["assessments"] == []
    assert merged["conflicts"] == []
    assert merged["provenance"] == []


def test_duplicate_topics_collapse_and_provenance_is_unioned() -> None:
    merged = _valid(
        merge_dossiers(
            [
                dossier(
                    "week1.pdf", "lecture", topics=[{"name": "Introduction to  Machine Learning"}]
                ),
                dossier(
                    "syllabus.pdf",
                    "syllabus",
                    topics=[{"name": "introduction to machine learning"}],
                ),
            ]
        )
    )
    assert len(merged["topics"]) == 1
    assert {entry["filename"] for entry in merged["provenance"]} == {"week1.pdf", "syllabus.pdf"}


def test_near_duplicate_topics_collapse_by_jaccard() -> None:
    merged = _valid(
        merge_dossiers(
            [
                dossier(
                    "a.pdf",
                    "lecture",
                    topics=[{"name": "data pipeline design monitoring and evaluation"}],
                ),
                dossier(
                    "b.pdf",
                    "lecture",
                    topics=[{"name": "data pipeline design monitoring and evaluation review"}],
                ),
            ]
        )
    )
    assert len(merged["topics"]) == 1
    assert merged["topics"][0]["name"] == "data pipeline design monitoring and evaluation"


def test_official_outline_weight_wins_and_conflict_is_recorded() -> None:
    official = {
        "filename": "outline",
        "assessments": [{"name": "Solution Architecture Report", "weight": 25}],
    }
    merged = _valid(
        merge_dossiers(
            [
                dossier(
                    "slides.pdf",
                    "lecture",
                    assessments=[{"name": "Solution Architecture Report", "weight": 20}],
                )
            ],
            official,
        )
    )
    assert merged["assessments"][0]["weight"] == 25.0
    conflict = merged["conflicts"][0]
    assert conflict["field"] == "assessment weight: Solution Architecture Report"
    assert conflict["winner"] == "25%"
    assert conflict["loser"] == "20%"
    assert "outline" in conflict["reason"]
    assert "slides.pdf" in conflict["reason"]


def test_same_weight_is_not_a_conflict() -> None:
    merged = _valid(
        merge_dossiers(
            [
                dossier("a.pdf", "syllabus", assessments=[{"name": "Report", "weight": 25}]),
                dossier("b.pdf", "lecture", assessments=[{"name": "Report", "weight": 25}]),
            ]
        )
    )
    assert merged["conflicts"] == []
    assert len(merged["assessments"]) == 1


def test_syllabus_outranks_lecture_for_policy_text() -> None:
    merged = _valid(
        merge_dossiers(
            [
                dossier(
                    "lecture.pdf",
                    "lecture",
                    policies_dates=[
                        {"key": "attendance", "title": "Attendance", "body": "Recorded."}
                    ],
                ),
                dossier(
                    "syllabus.pdf",
                    "syllabus",
                    policies_dates=[
                        {"key": "attendance", "title": "Attendance", "body": "Compulsory."}
                    ],
                ),
            ]
        )
    )
    assert merged["policies_dates"][0]["body"] == "Compulsory."
    assert len(merged["provenance"]) == 2


def test_readings_and_weeks_are_capped() -> None:
    merged = _valid(
        merge_dossiers(
            [
                dossier(
                    "a.pdf",
                    "syllabus",
                    readings=[f"Book {index}" for index in range(50)],
                    week_links=[
                        {"week": index, "topic": f"Topic {index}"} for index in range(1, 30)
                    ],
                )
            ]
        )
    )
    assert len(merged["readings"]) == READING_CAP
    assert len(merged["weeks"]) == WEEK_CAP


def test_conflicts_are_capped_at_twenty() -> None:
    official = {
        "assessments": [{"name": f"Task {index}", "weight": index + 10} for index in range(20)]
    }
    merged = _valid(
        merge_dossiers(
            [
                dossier(
                    "slides.pdf",
                    "lecture",
                    assessments=[
                        {"name": f"Task {index}", "weight": index + 5} for index in range(20)
                    ],
                )
            ],
            official,
        )
    )
    assert len(merged["conflicts"]) == 20


def test_malformed_dossier_is_tolerated() -> None:
    merged = _valid(
        merge_dossiers(
            [
                "not a dossier",
                {"filename": "broken.pdf", "topics": "nope", "document_kind": 7},
                dossier("ok.pdf", "syllabus", summary="Fine summary"),
            ]
        )
    )
    assert merged["summary"] == "Fine summary"
    assert merged["topics"] == []


def test_official_outline_body_is_understood() -> None:
    official = {
        "filename": "MAAI903-outline",
        "basics": {"name": "AI Solutions Design", "code": "MAAI 903"},
        "description": "Building AI systems.",
        "clos": [{"code": "LO1", "text": "Design architectures.", "plos": ["PLO1", "PLO2"]}],
        "plos": [{"code": "PLO1", "text": "Evaluate challenges."}],
        "weeks": [{"week": 1, "topic": "AI systems design"}],
        "assessment_tasks": [
            {
                "number": "A2",
                "title": "Solution Architecture Report",
                "weight": 25,
                "due": "Week 7",
                "lo_codes": ["LO1"],
            }
        ],
        "readings": ["Burkov, Machine Learning Engineering."],
        "policies": [{"key": "attendance", "title": "Attendance", "body": "Compulsory."}],
    }
    merged = _valid(merge_dossiers([], official))
    assert merged["summary"] == "Building AI systems."
    assert merged["topics"][0]["name"] == "AI systems design"
    assert merged["weeks"][0]["week"] == 1
    assert merged["assessments"][0]["name"] == "Solution Architecture Report"
    assert merged["outcomes"]["clos"][0]["code"] == "LO1"
    assert merged["outcomes"]["mappings"][0]["plos"] == ["PLO1", "PLO2"]
    assert merged["policies_dates"][0]["key"] == "attendance"
    assert merged["readings"][0]["citation"] == "Burkov, Machine Learning Engineering."
    assert merged["provenance"][0]["kind"] == "official"


def test_big_input_shrinks_but_keeps_conflicts_and_provenance() -> None:
    big = {
        "filename": "lecture-notes.pdf",
        "document_kind": "lecture",
        "assessments": [{"name": "Report", "weight": 30}],
        "topics": [{"name": f"Topic {index} " + "detail " * 40} for index in range(30)],
        "readings": [{"citation": f"Reading {index} " + "body " * 60} for index in range(30)],
        "key_terms": [
            {"term": f"Term {index}", "definition": "definition " * 30} for index in range(40)
        ],
        "formulas_examples": [
            {"name": f"Formula {index}", "body": "x = y " * 40} for index in range(40)
        ],
        "grading_criteria": [
            {"name": f"Criterion {index}", "levels": {"a": "level " * 20}} for index in range(20)
        ],
    }
    official = {"filename": "outline", "assessments": [{"name": "Report", "weight": 40}]}
    merged = _valid(merge_dossiers([big], official))
    assert len(json.dumps(merged, ensure_ascii=False, sort_keys=True)) <= MAX_CHARS
    assert merged["conflicts"]
    assert merged["provenance"]
    assert len(merged["formulas_examples"]) < 40


def test_shrink_dossier_preserves_conflicts() -> None:
    merged = MergedDossier().model_dump()
    merged["topics"] = [{"name": "Long topic " + "x" * 1000} for _ in range(30)]
    merged["conflicts"] = [{"field": "f", "winner": "a", "loser": "b", "reason": "r" * 100}]
    shrunk = shrink_dossier(merged)
    assert len(json.dumps(shrunk, ensure_ascii=False, sort_keys=True)) <= MAX_CHARS
    assert shrunk["conflicts"] == merged["conflicts"]
