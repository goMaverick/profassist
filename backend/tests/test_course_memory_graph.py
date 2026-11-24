"""The dossier graph: one span per file, a deterministic merge, bounded input.

No model and no network: ``llm.complete`` is replaced by a fake.
"""

from __future__ import annotations

import json
from typing import Any

from app.profassist import llm
from app.profassist.course_memory import graph
from app.profassist.course_memory.merge import MAX_CHARS
from app.profassist.course_memory.schemas import MergedDossier


def _material(
    filename: str,
    *,
    material_id: str = "",
    chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "material_id": material_id or filename,
        "filename": filename,
        "ordinal": 0,
        "chunks": chunks or [{"ordinal": 0, "text": f"{filename} week 1 foundations"}],
    }


def _extract_payload(topic: str) -> dict[str, Any]:
    return {
        "document_kind": "syllabus",
        "summary": "A course document.",
        "topics": [{"name": topic, "week": 1}],
        "claims": [{"field": "topics", "chunk_ordinal": 0, "quote": topic}],
    }


def _install(monkeypatch, *, extract=None, merge=None):
    calls: list[dict[str, Any]] = []

    def fake_complete(task: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append({"task": task, "payload": payload})
        if task == "dossier_extract":
            value = extract(payload) if callable(extract) else extract
        else:
            if isinstance(merge, Exception):
                raise merge
            value = merge(payload) if callable(merge) else merge
        return value if value is not None else {}

    monkeypatch.setattr(llm, "complete", fake_complete)
    return calls


def _run(
    materials: list[dict[str, Any]],
    official: dict[str, Any] | None = None,
    course_code: str = "MAAI903",
) -> dict[str, Any]:
    return graph.build_memory_graph().invoke(
        {
            "course_code": course_code,
            "materials": materials,
            "official": official or {},
            "dossiers": [],
            "errors": [],
        }
    )


def test_one_file_becomes_a_dossier(monkeypatch) -> None:
    _install(monkeypatch, extract=_extract_payload("Foundations"), merge={})

    state = _run([_material("syllabus.pdf")])

    assert state["errors"] == []
    assert len(state["dossiers"]) == 1
    assert state["dossiers"][0]["topics"][0]["name"] == "Foundations"
    assert state["merged"]["topics"][0]["name"] == "Foundations"
    assert state["merged"]["provenance"][0]["filename"] == "syllabus.pdf"


def test_two_files_are_each_extracted(monkeypatch) -> None:
    def extract(payload: dict[str, Any]) -> dict[str, Any]:
        topic = "Foundations" if payload["filename"] == "a.pdf" else "Pipelines"
        return _extract_payload(topic)

    calls = _install(monkeypatch, extract=extract, merge={})

    state = _run([_material("a.pdf"), _material("b.pdf")])

    extracts = [call for call in calls if call["task"] == "dossier_extract"]
    merges = [call for call in calls if call["task"] == "dossier_merge"]
    assert len(extracts) == 2
    assert len(merges) == 1
    assert len(state["dossiers"]) == 2
    assert {item["topics"][0]["name"] for item in state["dossiers"]} == {
        "Foundations",
        "Pipelines",
    }


def test_one_file_failure_does_not_lose_the_other(monkeypatch) -> None:
    def extract(payload: dict[str, Any]) -> dict[str, Any]:
        if payload["filename"] == "bad.pdf":
            raise RuntimeError("model down")
        return _extract_payload("Pipelines")

    _install(monkeypatch, extract=extract, merge={})

    state = _run([_material("bad.pdf"), _material("good.pdf")])

    assert len(state["dossiers"]) == 1
    assert state["errors"]
    assert state["errors"][0]["filename"] == "bad.pdf"
    assert state["merged"]["topics"][0]["name"] == "Pipelines"


def test_per_file_input_is_capped_at_24k(monkeypatch) -> None:
    calls = _install(monkeypatch, extract={}, merge={})
    chunks = [{"ordinal": index, "text": "topic " * 2000} for index in range(60)]

    _run([_material("lecture.pdf", chunks=chunks)])

    extracts = [call for call in calls if call["task"] == "dossier_extract"]
    sent = extracts[0]["payload"]["chunks"]
    assert sum(len(item["text"]) for item in sent) <= graph.MAX_FILE_CHARS
    assert len(sent) <= graph.MAX_CHUNKS


def test_merge_failure_keeps_the_deterministic_dossier(monkeypatch) -> None:
    _install(
        monkeypatch,
        extract=_extract_payload("Foundations"),
        merge=RuntimeError("merge model down"),
    )

    state = _run([_material("syllabus.pdf")])

    assert state["merged"]["topics"][0]["name"] == "Foundations"
    assert state["merged"]["provenance"]


def test_junk_merge_reply_falls_back_to_the_deterministic_dossier(monkeypatch) -> None:
    _install(monkeypatch, extract=_extract_payload("Foundations"), merge={"ok": True})

    state = _run([_material("syllabus.pdf")])

    assert state["merged"]["topics"][0]["name"] == "Foundations"


def test_merged_body_fits_the_budget(monkeypatch) -> None:
    def extract(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "document_kind": "lecture",
            "topics": [{"name": f"Topic {index} " + "detail " * 80} for index in range(30)],
            "policies_dates": [
                {"key": f"policy-{index}", "title": "Policy", "body": "rule " * 1000}
                for index in range(20)
            ],
        }

    _install(monkeypatch, extract=extract, merge={})
    materials = [_material(f"lecture-{index}.pdf") for index in range(4)]

    state = _run(materials)

    body = json.dumps(state["merged"], ensure_ascii=False, sort_keys=True)
    assert len(body) <= MAX_CHARS


def test_pii_gate_drops_a_name_bearing_field() -> None:
    clean, dropped = graph.pii_gate_dossier(
        {"summary": "Sara Maktoum", "topics": [{"name": "Week 1"}]}
    )

    assert "summary" not in clean
    assert dropped == 1
    assert clean["topics"] == [{"name": "Week 1"}]


def test_trace_url_comes_from_invoke_graph(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake_invoke(
        compiled: Any,
        state: dict[str, Any],
        *,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        seen["name"] = name
        seen["metadata"] = metadata
        return {"merged": MergedDossier().model_dump(), "dossiers": [], "errors": []}, (
            "http://trace"
        )

    monkeypatch.setattr(graph, "invoke_graph", fake_invoke)

    _merged, url = graph.run_course_memory([], {}, course_code="MAAI903")

    assert url == "http://trace"
    assert seen["name"] == "course-memory: MAAI903"
    assert seen["metadata"] == {"kind": "course_memory"}


def test_no_materials_still_returns_an_empty_dossier(monkeypatch) -> None:
    _install(monkeypatch, extract={}, merge={})

    state = _run([])

    assert state["dossiers"] == []
    assert state["errors"] == []
    assert state["merged"]["topics"] == []
    assert state["merged"]["assessments"] == []


def test_extract_prompt_carries_the_file_dossier_contract(monkeypatch) -> None:
    calls = _install(monkeypatch, extract=_extract_payload("Foundations"), merge={})

    _run([_material("PIPE903-notes-v2.txt")])

    extract = next(call for call in calls if call["task"] == "dossier_extract")
    contract = extract["payload"]["contract"]
    assert "FileDossier" in contract
    assert "one sentence" in contract
    assert "{name, week}" in contract
    assert "weight" in contract
    assert "chunk_ordinal" in contract
    assert extract["payload"]["filename"] == "PIPE903-notes-v2.txt"


def _partial(topic: str = "Foundations") -> dict[str, Any]:
    """The live failure: summary and topics only, no CLOs and no assessments."""
    return {
        "document_kind": "syllabus",
        "summary": "A course document.",
        "topics": [{"name": topic, "week": 1}],
    }


def _richer() -> dict[str, Any]:
    return {
        "document_kind": "syllabus",
        "summary": "A course syllabus.",
        "topics": [{"name": "Foundations", "week": 1}],
        "outcomes": {"clos": [{"code": "CLO1", "text": "Explain the pipeline."}]},
        "assessments": [{"name": "Report", "weight": 40, "due": "Week 6", "lo_codes": ["CLO1"]}],
    }


def _signal_chunks() -> list[dict[str, Any]]:
    return [
        {
            "ordinal": 0,
            "text": "CLO1 Explain the pipeline. Assessment: report, weight 40 percent.",
        }
    ]


def test_a_partial_extraction_retries_once_when_the_excerpts_name_clos(monkeypatch) -> None:
    replies = iter([_partial(), _richer()])
    calls = _install(monkeypatch, extract=lambda payload: next(replies), merge={})

    state = _run([_material("syllabus.pdf", chunks=_signal_chunks())])

    extracts = [call for call in calls if call["task"] == "dossier_extract"]
    assert len(extracts) == 2
    assert "Return every field" in extracts[1]["payload"]["retry_note"]
    assert "retry_note" not in extracts[0]["payload"]

    dossier = state["dossiers"][0]
    assert dossier["outcomes"]["clos"][0]["code"] == "CLO1"
    assert dossier["assessments"][0]["name"] == "Report"
    assert dossier["topics"][0]["name"] == "Foundations"


def test_a_partial_extraction_without_signals_does_not_retry(monkeypatch) -> None:
    calls = _install(monkeypatch, extract=_partial(), merge={})

    state = _run([_material("lecture.pdf")])

    extracts = [call for call in calls if call["task"] == "dossier_extract"]
    assert len(extracts) == 1
    assert state["dossiers"][0]["assessments"] == []
    assert state["dossiers"][0]["summary"] == "A course document."


def test_a_failed_retry_keeps_the_first_dossier(monkeypatch) -> None:
    def extract(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("retry_note"):
            raise RuntimeError("model down")
        return _partial()

    _install(monkeypatch, extract=extract, merge={})

    state = _run([_material("syllabus.pdf", chunks=_signal_chunks())])

    assert state["errors"] == []
    assert state["dossiers"][0]["summary"] == "A course document."


def test_merge_prompt_carries_the_merged_dossier_contract(monkeypatch) -> None:
    calls = _install(monkeypatch, extract=_extract_payload("Foundations"), merge={})

    _run([_material("syllabus.pdf")])

    merge = next(call for call in calls if call["task"] == "dossier_merge")
    contract = merge["payload"]["contract"]
    assert "MergedDossier" in contract
    assert "one sentence" in contract
    assert "chunk_ordinal" in contract


def test_pii_gate_keeps_identifiers_and_drops_a_name_bearing_field() -> None:
    clean, dropped = graph.pii_gate_dossier(
        {
            "filename": "PIPE903-notes-v2.txt",
            "document_kind": "syllabus",
            "material_id": "m1",
            "chunk_ordinal": 4,
            "outcomes": {"clos": [{"code": "CLO1", "text": "Sara Maktoum"}]},
            "assessments": [{"name": "Report", "lo_codes": ["CLO1"]}],
            "provenance": [
                {
                    "field": "topics",
                    "value": "Sara Maktoum",
                    "filename": "PIPE903-notes-v2.txt",
                    "chunk_ordinal": 2,
                    "kind": "syllabus",
                }
            ],
        }
    )

    assert clean["filename"] == "PIPE903-notes-v2.txt"
    assert clean["document_kind"] == "syllabus"
    assert clean["material_id"] == "m1"
    assert clean["chunk_ordinal"] == 4
    assert clean["outcomes"]["clos"] == [{"code": "CLO1"}]
    assert clean["assessments"][0]["lo_codes"] == ["CLO1"]
    assert clean["provenance"][0]["filename"] == "PIPE903-notes-v2.txt"
    assert "value" not in clean["provenance"][0]
    assert dropped == 2
