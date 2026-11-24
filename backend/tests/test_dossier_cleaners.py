"""Provider drift must not reach the dossier pipeline.

Gemini and OpenAI disagree on casing, key names, and how a weight is written.
These tests pin the deterministic repair: no model, no network, no database.
"""

from __future__ import annotations

from app.profassist.course_memory.cleaners import (
    ASSESSMENT_CAP,
    CLAIM_CAP,
    KEY_TERM_CAP,
    PROVENANCE_CAP,
    TOPIC_CAP,
    WEEK_CAP,
    clean_file_dossier,
    clean_merged_dossier,
    content_hash,
    parse_json_object,
)
from app.profassist.course_memory.schemas import FileDossier, MergedDossier

GEMINI_REPLY = """{
  "documentKind": "Syllabus",
  "summary": "MAAI 903 subject outline",
  "topics": [
    {"topic": "AI systems design", "week_number": "Week 1"},
    {"topic": "ML lifecycle", "weekNo": 2},
    "Wrap up"
  ],
  "outcomes": {
    "CLO": [{"code": "CLO2", "text": "Apply MLOps practices"}],
    "PLOs": [{"code": "PLO1", "text": "Evaluate challenges"}]
  },
  "assessments": [
    {"title": "Workshops", "percentage": "25%", "due_date": "Throughout"},
    {"title": "Report", "percent": 25, "due": "Week 7"}
  ],
  "readings": ["Burkov, Machine Learning Engineering"],
  "key_terms": [{"term": "MLOps", "definition": "Machine learning operations"}]
}"""

OPENAI_REPLY = """Here is the dossier:
```json
{
  "document_kind": "Lecture",
  "summary": "Week 3 notes",
  "assessments": [
    {"name": "Quiz", "weight": null, "due_date": "Week 2"},
  ],
}
```
Let me know if you need anything else."""


def _valid(cleaned: dict) -> dict:
    FileDossier.model_validate(cleaned)
    return cleaned


def test_gemini_camel_case_is_repaired() -> None:
    cleaned = _valid(clean_file_dossier(GEMINI_REPLY))
    assert cleaned["document_kind"] == "syllabus"
    assert cleaned["summary"] == "MAAI 903 subject outline"
    assert cleaned["topics"][0] == {"name": "AI systems design", "week": 1}
    assert cleaned["topics"][1] == {"name": "ML lifecycle", "week": 2}
    assert cleaned["topics"][2] == {"name": "Wrap up"}
    assert cleaned["outcomes"]["clos"] == [{"code": "CLO2", "text": "Apply MLOps practices"}]
    assert cleaned["outcomes"]["plos"] == [{"code": "PLO1", "text": "Evaluate challenges"}]
    assert cleaned["assessments"][0]["weight"] == 25.0
    assert cleaned["assessments"][0]["due"] == "Throughout"


def test_lo_alias_and_week_number_are_repaired() -> None:
    cleaned = _valid(
        clean_file_dossier(
            {
                "type": "lecture",
                "learning_outcomes": [{"LO": "LO1", "text": "Design architectures"}],
                "topics": [{"name": "Scoping", "weekNo": "3"}],
            }
        )
    )
    assert cleaned["document_kind"] == "lecture"
    assert cleaned["outcomes"]["clos"] == [{"code": "LO1", "text": "Design architectures"}]
    assert cleaned["topics"] == [{"name": "Scoping", "week": 3}]


def test_fenced_json_with_trailing_junk_is_repaired() -> None:
    cleaned = _valid(clean_file_dossier(OPENAI_REPLY))
    assert cleaned["document_kind"] == "lecture"
    assert cleaned["summary"] == "Week 3 notes"
    assert cleaned["assessments"][0]["name"] == "Quiz"
    assert cleaned["assessments"][0]["due"] == "Week 2"
    assert cleaned["assessments"][0].get("weight") is None


def test_trailing_commas_and_surrounding_prose_are_repaired() -> None:
    raw = (
        'Sure, here it is: {"document_kind": "policy", '
        '"assessments": [{"name": "Late penalty", "percentage": 20},],} Hope that helps!'
    )
    cleaned = _valid(clean_file_dossier(raw))
    assert cleaned["document_kind"] == "policy"
    assert cleaned["assessments"][0]["weight"] == 20.0


def test_provider_wrappers_are_unwrapped() -> None:
    assert parse_json_object({"response": {"summary": "wrapped"}}) == {"summary": "wrapped"}
    arguments = '{"arguments": "{\\"summary\\": \\"nested\\"}"}'
    assert parse_json_object(arguments) == {"summary": "nested"}


def test_partial_object_still_validates() -> None:
    cleaned = _valid(clean_file_dossier({"summary": "only a summary"}))
    assert cleaned["summary"] == "only a summary"
    assert cleaned["topics"] == []
    assert cleaned["outcomes"] == {"clos": [], "plos": [], "mappings": []}


def test_unknown_keys_are_dropped_and_bad_kind_falls_back() -> None:
    cleaned = _valid(clean_file_dossier({"document_kind": "Podcast", "unexpected": {"x": 1}}))
    assert cleaned["document_kind"] == "other"
    assert "unexpected" not in cleaned
    assert clean_file_dossier({"documentKind": "SYLLABUS"})["document_kind"] == "syllabus"


def test_string_lists_become_objects() -> None:
    cleaned = _valid(
        clean_file_dossier(
            {
                "readings": ["Book A", "Book B"],
                "week_links": ["Week 2: Pipelines", "Wrap up"],
                "open_questions": ["Who owns the lab?"],
            }
        )
    )
    assert cleaned["readings"] == [{"citation": "Book A"}, {"citation": "Book B"}]
    assert cleaned["week_links"][0] == {"week": 2, "topic": "Pipelines"}
    assert cleaned["week_links"][1] == {"week": 0, "topic": "Wrap up"}
    assert cleaned["open_questions"] == ["Who owns the lab?"]


def test_section_caps_are_enforced() -> None:
    cleaned = _valid(
        clean_file_dossier(
            {
                "topics": [f"Topic {index}" for index in range(60)],
                "key_terms": [{"term": f"t{index}", "definition": "d"} for index in range(60)],
                "assessments": [{"name": f"A{index}"} for index in range(40)],
                "claims": [{"quote": f"q{index}", "chunk": index} for index in range(250)],
            }
        )
    )
    assert len(cleaned["topics"]) == TOPIC_CAP
    assert len(cleaned["key_terms"]) == KEY_TERM_CAP
    assert len(cleaned["assessments"]) == ASSESSMENT_CAP
    assert len(cleaned["claims"]) == CLAIM_CAP
    assert cleaned["claims"][10]["chunk_ordinal"] == 10


def test_file_provenance_is_validated_not_copied_verbatim() -> None:
    cleaned = clean_file_dossier(
        {
            "topics": ["AI systems design"],
            "provenance": [
                {
                    "field": "topics",
                    "value": "AI systems design",
                    "filename": "syllabus.pdf",
                    "chunk_ordinal": 4,
                    "kind": "syllabus",
                    "injected": "<script>alert(1)</script>",
                },
                {"unexpected": "no field, so dropped"},
                {"field": "assessment weight", "value": "25%", "extra": "dropped"},
            ],
        }
    )

    assert cleaned["provenance"] == [
        {
            "field": "topics",
            "value": "AI systems design",
            "filename": "syllabus.pdf",
            "chunk_ordinal": 4,
            "kind": "syllabus",
        },
        {
            "field": "assessment weight",
            "value": "25%",
            "filename": "",
            "chunk_ordinal": 0,
            "kind": "other",
        },
    ]
    assert all("injected" not in item and "extra" not in item for item in cleaned["provenance"])


def test_file_provenance_is_capped() -> None:
    cleaned = clean_file_dossier(
        {
            "provenance": [
                {"field": f"field-{index}", "value": f"value-{index}"}
                for index in range(PROVENANCE_CAP + 50)
            ]
        }
    )
    assert len(cleaned["provenance"]) == PROVENANCE_CAP


def test_never_raises_on_junk() -> None:
    junk = [None, "", "no json here", "{broken", b"bytes", 42, [None, 1], 3.5]
    for raw in junk:
        assert isinstance(parse_json_object(raw), dict)
        cleaned = clean_file_dossier(raw)
        assert isinstance(cleaned["topics"], list)
        FileDossier.model_validate(cleaned)


def test_null_and_missing_weights_are_tolerated() -> None:
    cleaned = _valid(
        clean_file_dossier(
            {"assessments": [{"name": "Quiz", "weight": None}, {"name": "Report", "percent": "0%"}]}
        )
    )
    assert cleaned["assessments"][0].get("weight") is None
    assert cleaned["assessments"][1]["weight"] == 0.0


def test_word_percent_weight_becomes_a_number() -> None:
    cleaned = _valid(
        clean_file_dossier(
            {
                "assessments": [
                    {"name": "Report", "weight": "20 percent"},
                    {"name": "Exam", "weight": "50 percent"},
                ]
            }
        )
    )
    assert cleaned["assessments"][0]["weight"] == 20.0
    assert cleaned["assessments"][1]["weight"] == 50.0


def test_merged_cleaner_caps_weeks_and_conflicts() -> None:
    cleaned = clean_merged_dossier(
        {
            "weeks": [{"weekNo": index, "topic": f"Topic {index}"} for index in range(1, 30)],
            "conflicts": [
                {"field": "assessment weight", "winner": "25%", "loser": "20%", "reason": "why"}
                for _ in range(30)
            ],
            "provenance": [
                {
                    "field": "topics",
                    "value": "AI",
                    "filename": "outline",
                    "chunk_ordinal": 1,
                    "kind": "official",
                }
            ],
        }
    )
    MergedDossier.model_validate(cleaned)
    assert len(cleaned["weeks"]) == WEEK_CAP
    assert len(cleaned["conflicts"]) == 20
    assert cleaned["provenance"][0]["kind"] == "official"


def test_content_hash_ignores_whitespace_and_case() -> None:
    assert content_hash("A  b\nc") == content_hash("a b c")
    assert content_hash("one") != content_hash("two")
    assert len(content_hash("x")) == 64
