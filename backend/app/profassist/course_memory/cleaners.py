"""Deterministic repair of model output. No model, no network, never raises.

Providers drift: Gemini emits camelCase and ``LO``; OpenAI wraps JSON in prose
or a Markdown fence; weights arrive as ``"25%"`` or ``null``. These helpers turn
any of that into the same bounded shape before validation. Provenance is
bounded before it is stored, so a claim can still be traced to its chunk.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.profassist.course_memory.schemas import DOCUMENT_KINDS, FileDossier, MergedDossier

TOPIC_CAP = 30
ASSESSMENT_CAP = 20
READING_CAP = 30
POLICY_CAP = 40
KEY_TERM_CAP = 40
FORMULA_CAP = 40
CRITERION_CAP = 20
OPEN_QUESTION_CAP = 10
CLAIM_CAP = 200
PROVENANCE_CAP = 100
WEEK_CAP = 16
CONFLICT_CAP = 20

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_WRAPPER_KEYS = frozenset(
    {
        "response",
        "result",
        "output",
        "data",
        "dossier",
        "file_dossier",
        "merged_dossier",
        "content",
        "text",
        "arguments",
    }
)
_WEEK_RE = re.compile(r"(?:week\s*)?(\d{1,2})\s*[:\-\u2013\u2014.]\s*(.*)", re.I)
_CODE_RE = re.compile(r"^([A-Za-z]{1,6}\s?\d{1,3})\s*[:.\-\u2013]\s*(.+)$")


def _loads(text: str) -> Any:
    """``json.loads`` with one tolerant retry for trailing commas."""
    for candidate in (text, _TRAILING_COMMA_RE.sub(r"\1", text)):
        try:
            return json.loads(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _candidates(raw: str) -> list[str]:
    """The whole string, every fenced block, and every brace span between."""
    found = [raw]
    found.extend(match.group(1).strip() for match in _FENCE_RE.finditer(raw))
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        found.append(raw[start : end + 1])
    for candidate in list(found):
        inner_start, inner_end = candidate.find("{"), candidate.rfind("}")
        if 0 <= inner_start < inner_end:
            span = candidate[inner_start : inner_end + 1]
            if span != candidate:
                found.append(span)
    return list(dict.fromkeys(found))


def _from_string(value: str) -> dict[str, Any] | None:
    for candidate in _candidates(value.strip()):
        loaded = _loads(candidate)
        if isinstance(loaded, dict):
            return loaded
    return None


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip ``{"response": ...}``, ``{"arguments": "<json>"}`` and friends."""
    current: Any = payload
    for _ in range(4):
        if not isinstance(current, dict):
            return {}
        lowered = {str(key).lower(): value for key, value in current.items()}
        if len(current) == 1:
            key = next(iter(lowered))
            value = lowered[key]
            if key in _WRAPPER_KEYS:
                if isinstance(value, dict):
                    current = value
                    continue
                if isinstance(value, str):
                    nested = _from_string(value)
                    if nested is not None:
                        current = nested
                        continue
        arguments = current.get("arguments")
        if isinstance(arguments, str):
            nested = _from_string(arguments)
            if nested is not None:
                current = nested
                continue
        break
    return current if isinstance(current, dict) else {}


def parse_json_object(text: Any) -> dict[str, Any]:
    """Best-effort JSON object from model output. Returns ``{}`` on failure."""
    if isinstance(text, dict):
        return _unwrap(text)
    if isinstance(text, (list, tuple)):
        for item in text:
            parsed = parse_json_object(item)
            if parsed:
                return parsed
        return {}
    raw = str(text or "").strip()
    if not raw:
        return {}
    for candidate in _candidates(raw):
        loaded = _loads(candidate)
        if isinstance(loaded, dict):
            return _unwrap(loaded)
        if isinstance(loaded, list):
            for item in loaded:
                if isinstance(item, dict):
                    return _unwrap(item)
    return {}


def _get(payload: Any, *names: str, default: Any = None) -> Any:
    """First non-empty value under any alias, case-insensitive."""
    if not isinstance(payload, dict):
        return default
    lowered = {str(key).lower(): value for key, value in payload.items()}
    for name in names:
        value = payload.get(name)
        if value is None:
            value = lowered.get(name.lower())
        if value is not None and value != "":
            return value
    return default


def _items(value: Any) -> list[Any]:
    """A single object, a list, or nothing -- always a list of candidates."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if item is not None and item != ""]
    return []


def _text(value: Any, limit: int = 4000) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()[:limit]
    if isinstance(value, (int, float)):
        return str(value)[:limit]
    if isinstance(value, (list, tuple)):
        joined = "; ".join(part for part in (_text(item, limit) for item in value) if part)
        return joined[:limit]
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:limit]
    return str(value).strip()[:limit]


def _to_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else default


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _codes(value: Any) -> list[str]:
    """``"LO1, LO2"``, ``["LO1"]``, and ``[{"code": "LO1"}]`` all become codes."""
    codes: list[str] = []
    seen: set[str] = set()
    for item in _items(value):
        if isinstance(item, dict):
            raw = _text(_get(item, "code", "lo", "clo", "plo", "id", "name", "value"), 64)
        else:
            raw = _text(item, 64)
        for part in re.split(r"[,;/|]", raw):
            code = part.strip()[:32]
            key = code.upper()
            if code and key not in seen:
                seen.add(key)
                codes.append(code)
    return codes


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:64]


def _scalar(value: Any, limit: int = 500) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:limit]
    return _text(value, limit)


def _clean_topics(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, dict):
            name = _text(_get(item, "name", "topic", "title"), 300)
            week = _to_int(_get(item, "week", "week_number", "weekNumber", "weekNo"), 0)
        else:
            name, week = _text(item, 300), 0
        if not name:
            continue
        entry: dict[str, Any] = {"name": name}
        if week > 0:
            entry["week"] = week
        rows.append(entry)
    return rows[:TOPIC_CAP]


def _clean_weeks(value: Any, cap: int = WEEK_CAP) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, dict):
            week = _to_int(_get(item, "week", "week_number", "weekNumber", "weekNo", "number"), 0)
            topic = _text(_get(item, "topic", "name", "title", "summary"), 300)
        else:
            topic = _text(item, 300)
            week = 0
            match = _WEEK_RE.match(topic)
            if match:
                week, topic = int(match.group(1)), match.group(2).strip()
            else:
                match = re.match(r"^week\s*(\d{1,2})\b", topic, re.I)
                if match:
                    week, topic = int(match.group(1)), ""
        if not week and not topic:
            continue
        rows.append({"week": week, "topic": topic})
    return rows[:cap]


def _clean_outcome_codes(value: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in _items(value):
        if isinstance(item, dict):
            code = _text(_get(item, "code", "id", "clo", "lo", "plo", "label"), 32)
            text = _text(_get(item, "text", "description", "statement", "outcome", "title"), 1000)
        else:
            raw = _text(item, 1000)
            match = _CODE_RE.match(raw)
            if match:
                code, text = _text(match.group(1), 32), _text(match.group(2), 1000)
            else:
                code, text = raw[:32], ""
        if code:
            rows.append({"code": code, "text": text})
    return rows


def _clean_mappings(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, dict):
            clo = _text(_get(item, "clo", "lo", "code", "source"), 32)
            plos = _codes(_get(item, "plos", "plo", "targets", "codes", "maps_to"))
        else:
            clo, plos = _text(item, 32), []
        if clo:
            rows.append({"clo": clo, "plos": plos})
    return rows


def _clean_outcomes(payload: dict[str, Any]) -> dict[str, Any]:
    source = _get(payload, "outcomes", "learning_outcomes", "course_outcomes", default={})
    if not isinstance(source, dict):
        source = {}
    clos = _get(source, "clos", "clo", "LO", "course_outcomes", "learning_outcomes", "los")
    plos = _get(source, "plos", "plo", "PLO", "program_outcomes")
    if not clos and not plos:
        clos = _get(payload, "clos", "clo", "LO", "learning_outcomes", "learningOutcomes")
        plos = _get(payload, "plos", "plo", "PLO", "program_outcomes")
    mappings = _get(source, "mappings", "map", "clo_plo", "cloPlos")
    if mappings is None:
        mappings = _get(payload, "mappings", "outcome_mappings")
    return {
        "clos": _clean_outcome_codes(clos),
        "plos": _clean_outcome_codes(plos),
        "mappings": _clean_mappings(mappings),
    }


def _clean_assessments(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, dict):
            name = _text(_get(item, "name", "title", "assessment", "task", "component"), 300)
            weight = _to_float(_get(item, "weight", "percentage", "percent", "marks", "mark"))
            due = _text(_get(item, "due", "due_date", "dueDate", "deadline", "when"), 64)
            codes = _codes(
                _get(item, "lo_codes", "loCodes", "los", "clo", "clos", "learning_outcomes")
            )
        else:
            name, weight, due, codes = _text(item, 300), None, "", []
        if not name:
            continue
        entry: dict[str, Any] = {"name": name, "due": due, "lo_codes": codes}
        if weight is not None:
            entry["weight"] = weight
        rows.append(entry)
    return rows[:ASSESSMENT_CAP]


def _clean_readings(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, dict):
            citation = _text(_get(item, "citation", "reference", "text", "title", "source"), 1000)
            week = _to_int(_get(item, "week", "week_number", "weekNo"), 0)
        else:
            citation, week = _text(item, 1000), 0
        if not citation:
            continue
        entry: dict[str, Any] = {"citation": citation}
        if week > 0:
            entry["week"] = week
        rows.append(entry)
    return rows[:READING_CAP]


def _clean_policies(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, dict):
            title = _text(_get(item, "title", "name", "heading"), 255)
            key = _text(_get(item, "key", "policy", "id", "slug"), 64)
            body = _text(_get(item, "body", "text", "detail", "summary", "description"), 4000)
            date = _text(_get(item, "date", "due", "due_date", "deadline", "when"), 64)
        else:
            title, key, body, date = _text(item, 255), "", "", ""
        if not title and not body:
            continue
        key = key or _slug(title or body[:64])
        entry: dict[str, Any] = {"key": key, "title": title or key, "body": body}
        if date:
            entry["date"] = date
        rows.append(entry)
    return rows[:POLICY_CAP]


def _clean_terms(value: Any) -> list[dict[str, str]]:
    if isinstance(value, dict) and not any(
        str(key).lower() in {"term", "name", "word", "key"} for key in value
    ):
        return [
            {"term": _text(term, 128), "definition": _text(definition, 1000)}
            for term, definition in value.items()
            if _text(term, 128)
        ][:KEY_TERM_CAP]
    rows: list[dict[str, str]] = []
    for item in _items(value):
        if isinstance(item, dict):
            term = _text(_get(item, "term", "name", "word"), 128)
            definition = _text(_get(item, "definition", "meaning", "description", "text"), 1000)
        else:
            term, definition = _text(item, 128), ""
        if term:
            rows.append({"term": term, "definition": definition})
    return rows[:KEY_TERM_CAP]


def _clean_formulas(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, dict):
            name = _text(_get(item, "name", "title", "formula", "expression"), 255)
            body = _text(_get(item, "body", "text", "example", "detail", "value"), 2000)
        else:
            name, body = _text(item, 255), ""
        if name or body:
            rows.append({"name": name or body[:64], "body": body})
    return rows[:FORMULA_CAP]


def _clean_levels(value: Any) -> dict[str, str] | list[str]:
    if isinstance(value, dict):
        return {
            _text(key, 64): _text(level, 1000) for key, level in value.items() if _text(key, 64)
        }
    rows: list[str] = []
    for item in _items(value):
        if isinstance(item, dict):
            label = _text(_get(item, "level", "name", "band", "grade"), 64)
            detail = _text(_get(item, "text", "description", "descriptor"), 1000)
            if label and detail:
                rows.append(f"{label}: {detail}")
            elif label or detail:
                rows.append(label or detail)
        else:
            text = _text(item, 1000)
            if text:
                rows.append(text)
    return rows


def _clean_criteria(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, dict):
            name = _text(_get(item, "name", "criterion", "title", "component"), 255)
            levels = _clean_levels(_get(item, "levels", "bands", "descriptors", "scale"))
        else:
            name, levels = _text(item, 255), {}
        if name:
            rows.append({"name": name, "levels": levels})
    return rows[:CRITERION_CAP]


def _clean_open_questions(value: Any) -> list[str]:
    rows: list[str] = []
    for item in _items(value):
        if isinstance(item, dict):
            text = _text(_get(item, "question", "text", "title", "name", "summary"), 500)
        else:
            text = _text(item, 500)
        if text:
            rows.append(text)
    return rows[:OPEN_QUESTION_CAP]


def _clean_claims(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, dict):
            quote = _text(_get(item, "quote", "text", "snippet", "evidence", "excerpt"), 1000)
            if not quote:
                continue
            rows.append(
                {
                    "field": _text(_get(item, "field", "name", "key", "section"), 128),
                    "chunk_ordinal": _to_int(
                        _get(item, "chunk_ordinal", "chunkOrdinal", "chunk", "ordinal"), 0
                    ),
                    "quote": quote,
                }
            )
        else:
            quote = _text(item, 1000)
            if quote:
                rows.append({"field": "", "chunk_ordinal": 0, "quote": quote})
    return rows[:CLAIM_CAP]


def _clean_provenance(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if not isinstance(item, dict):
            continue
        field = _text(_get(item, "field", "section", "name"), 128)
        if not field:
            continue
        rows.append(
            {
                "field": field,
                "value": _scalar(_get(item, "value", "text", "source_value")),
                "filename": _text(_get(item, "filename", "file", "source"), 255),
                "chunk_ordinal": _to_int(
                    _get(item, "chunk_ordinal", "chunkOrdinal", "chunk", "ordinal"), 0
                ),
                "kind": _text(_get(item, "kind", "document_kind", "documentKind", "type"), 32)
                or "other",
            }
        )
    return rows[:PROVENANCE_CAP]


def _clean_conflicts(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _items(value):
        if not isinstance(item, dict):
            continue
        field = _text(_get(item, "field", "section", "name"), 128)
        if not field:
            continue
        rows.append(
            {
                "field": field,
                "winner": _text(_get(item, "winner", "winner_value", "kept"), 128),
                "loser": _text(_get(item, "loser", "loser_value", "dropped"), 128),
                "reason": _text(_get(item, "reason", "why", "because"), 300),
            }
        )
    return rows[:CONFLICT_CAP]


def _empty_file() -> dict[str, Any]:
    return FileDossier().model_dump()


def _empty_merged() -> dict[str, Any]:
    return MergedDossier().model_dump()


def clean_file_dossier(raw: Any) -> dict[str, Any]:
    """Repair one model reply into the ``FileDossier`` shape."""
    payload = parse_json_object(raw)
    cleaned = _empty_file()
    if not payload:
        return cleaned
    kind = _text(_get(payload, "document_kind", "documentKind", "kind", "type", "doc_type"), 32)
    cleaned["document_kind"] = kind.lower() if kind.lower() in DOCUMENT_KINDS else "other"
    cleaned["summary"] = _text(
        _get(payload, "summary", "overview", "abstract", "description"), 2000
    )
    cleaned["topics"] = _clean_topics(_get(payload, "topics", "topic_list", "syllabus_topics"))
    cleaned["week_links"] = _clean_weeks(
        _get(payload, "week_links", "weekLinks", "weeks", "schedule")
    )
    cleaned["outcomes"] = _clean_outcomes(payload)
    cleaned["assessments"] = _clean_assessments(
        _get(payload, "assessments", "assessment", "tasks", "assessment_tasks")
    )
    cleaned["readings"] = _clean_readings(_get(payload, "readings", "references", "reading_list"))
    cleaned["policies_dates"] = _clean_policies(
        _get(payload, "policies_dates", "policiesDates", "policies", "policies_and_dates")
    )
    cleaned["key_terms"] = _clean_terms(_get(payload, "key_terms", "keyTerms", "terms", "glossary"))
    cleaned["formulas_examples"] = _clean_formulas(
        _get(payload, "formulas_examples", "formulasExamples", "formulas", "examples")
    )
    cleaned["grading_criteria"] = _clean_criteria(
        _get(payload, "grading_criteria", "gradingCriteria", "criteria", "rubric")
    )
    cleaned["open_questions"] = _clean_open_questions(
        _get(payload, "open_questions", "openQuestions", "questions", "gaps")
    )
    cleaned["claims"] = _clean_claims(_get(payload, "claims", "evidence", "quotes"))
    provenance = _clean_provenance(_get(payload, "provenance", "sources"))
    if provenance:
        cleaned["provenance"] = provenance
    return cleaned


def clean_merged_dossier(raw: Any) -> dict[str, Any]:
    """Repair one model reply into the ``MergedDossier`` shape."""
    payload = parse_json_object(raw)
    cleaned = _empty_merged()
    if not payload:
        return cleaned
    cleaned["version"] = _to_int(_get(payload, "version"), 1) or 1
    cleaned["summary"] = _text(_get(payload, "summary", "overview", "abstract"), 2000)
    cleaned["topics"] = _clean_topics(_get(payload, "topics", "topic_list"))
    cleaned["weeks"] = _clean_weeks(_get(payload, "weeks", "week_links", "weekLinks", "schedule"))
    cleaned["outcomes"] = _clean_outcomes(payload)
    cleaned["assessments"] = _clean_assessments(
        _get(payload, "assessments", "assessment_tasks", "tasks")
    )
    cleaned["readings"] = _clean_readings(_get(payload, "readings", "references"))
    cleaned["policies_dates"] = _clean_policies(
        _get(payload, "policies_dates", "policiesDates", "policies")
    )
    cleaned["key_terms"] = _clean_terms(_get(payload, "key_terms", "keyTerms", "terms", "glossary"))
    cleaned["formulas_examples"] = _clean_formulas(
        _get(payload, "formulas_examples", "formulasExamples", "formulas")
    )
    cleaned["grading_criteria"] = _clean_criteria(
        _get(payload, "grading_criteria", "gradingCriteria", "criteria")
    )
    cleaned["open_questions"] = _clean_open_questions(
        _get(payload, "open_questions", "openQuestions", "questions")
    )
    cleaned["provenance"] = _clean_provenance(_get(payload, "provenance", "sources"))
    cleaned["conflicts"] = _clean_conflicts(_get(payload, "conflicts", "conflict_list"))
    return cleaned


def content_hash(text: str) -> str:
    """sha256 of whitespace-normalised, case-folded text."""
    normalized = " ".join(str(text or "").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
