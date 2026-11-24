"""Deterministic merge of per-file dossiers into one course dossier. No model.

Authority decides: the official outline outranks a syllabus, which outranks a
policy extract, a lecture slide, and a reading list. Duplicates collapse by
normalised key or token overlap, provenance is unioned rather than dropped, and
a weight disagreement on the same assessment becomes a recorded conflict. The
result always fits the budget: :func:`shrink_dossier` prunes content by section
value and keeps the audit trail.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.profassist.course_memory.cleaners import (
    ASSESSMENT_CAP,
    CONFLICT_CAP,
    CRITERION_CAP,
    FORMULA_CAP,
    KEY_TERM_CAP,
    OPEN_QUESTION_CAP,
    POLICY_CAP,
    PROVENANCE_CAP,
    READING_CAP,
    TOPIC_CAP,
    WEEK_CAP,
    _codes,
    _empty_merged,
    _get,
    _items,
    _slug,
    _text,
    _to_float,
    _to_int,
    clean_file_dossier,
)
from app.profassist.similarity import tokens

MAX_CHARS = 24_000
JACCARD = 0.85

AUTHORITY: dict[str, int] = {
    "official": 100,
    "syllabus": 80,
    "assignment": 80,
    "rubric": 80,
    "policy": 60,
    "lecture": 40,
    "reading": 20,
    "other": 0,
}

PRUNE_ORDER = (
    "formulas_examples",
    "grading_criteria",
    "readings",
    "key_terms",
    "open_questions",
    "topics",
    "assessments",
    "policies_dates",
    "weeks",
    "outcomes",
    "summary",
)

_DOSSIER_KEYS = (
    "topics",
    "week_links",
    "weekLinks",
    "assessments",
    "claims",
    "document_kind",
    "documentKind",
)


@dataclass(frozen=True)
class _Source:
    filename: str
    kind: str
    authority: int
    data: dict[str, Any]


@dataclass
class _Row:
    source: _Source
    data: dict[str, Any]
    value: str

    def provenance(self, field_name: str) -> dict[str, Any]:
        return {
            "field": field_name,
            "value": self.value,
            "filename": self.source.filename,
            "chunk_ordinal": _claim_ordinal(self.source.data, self.value),
            "kind": self.source.kind,
        }


@dataclass
class _Kept:
    key: str
    data: dict[str, Any]
    authority: int
    provenance: list[dict[str, Any]] = field(default_factory=list)


def _normalize_key(value: Any) -> str:
    return " ".join(tokens(_text(value, 2000)))


def _jaccard(left: str, right: str) -> float:
    left_tokens, right_tokens = set(tokens(left)), set(tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _claim_ordinal(dossier: dict[str, Any], value: str) -> int:
    """The chunk a claim points at, when its quote overlaps this row's value."""
    wanted = set(tokens(value))
    for claim in _items(dossier.get("claims")):
        if not isinstance(claim, dict):
            continue
        quote = set(tokens(str(claim.get("quote") or "")))
        if not quote or not wanted:
            continue
        if len(quote & wanted) / len(quote) >= 0.5:
            return _to_int(claim.get("chunk_ordinal"), 0)
    return _to_int(dossier.get("chunk_ordinal"), 0)


def _row_value(data: dict[str, Any]) -> str:
    for key in ("name", "citation", "term", "title", "topic", "key", "code", "text"):
        value = _text(data.get(key), 500)
        if value:
            return value
    return ""


def _looks_like_dossier(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in _DOSSIER_KEYS)


def _official_payload(official: dict[str, Any]) -> dict[str, Any]:
    """Accept either a dossier-shaped dict or a subject-outline body."""
    if _looks_like_dossier(official):
        return dict(official)
    body: dict[str, Any] = official
    if isinstance(official.get("body"), dict):
        body = official["body"]
    basics: dict[str, Any] = {}
    if isinstance(body.get("basics"), dict):
        basics = body["basics"]
    topics: list[dict[str, Any]] = []
    week_links: list[dict[str, Any]] = []
    for item in _items(body.get("weeks")):
        if isinstance(item, dict):
            week = _to_int(item.get("week"), 0)
            topic = _text(item.get("topic"), 300)
        else:
            week, topic = 0, _text(item, 300)
        if not topic:
            continue
        topic_entry: dict[str, Any] = {"name": topic}
        if week:
            topic_entry["week"] = week
        topics.append(topic_entry)
        week_links.append({"week": week, "topic": topic})
    clos = [item for item in _items(body.get("clos")) if isinstance(item, dict)]
    mappings = [
        {"clo": _text(item.get("code"), 32), "plos": _codes(item.get("plos"))}
        for item in clos
        if _text(item.get("code"), 32)
    ]
    assessments: list[dict[str, Any]] = []
    for item in _items(body.get("assessment_tasks")):
        if not isinstance(item, dict):
            continue
        name = _text(item.get("title") or item.get("name"), 300)
        if not name:
            continue
        assessment: dict[str, Any] = {
            "name": name,
            "due": _text(item.get("due"), 64),
            "lo_codes": _codes(item.get("lo_codes")),
        }
        weight = _to_float(item.get("weight"))
        if weight is not None:
            assessment["weight"] = weight
        assessments.append(assessment)
    return {
        "document_kind": "syllabus",
        "summary": _text(body.get("description") or basics.get("name"), 2000),
        "topics": topics,
        "week_links": week_links,
        "outcomes": {"clos": clos, "plos": _items(body.get("plos")), "mappings": mappings},
        "assessments": assessments,
        "readings": _items(body.get("readings")),
        "policies_dates": _items(body.get("policies")),
    }


def _sources(dossiers: list[Any], official: dict[str, Any] | None) -> list[_Source]:
    sources: list[_Source] = []
    if isinstance(official, dict) and official:
        cleaned = clean_file_dossier(_official_payload(official))
        filename = _text(official.get("filename") or official.get("source"), 255)
        sources.append(
            _Source(filename or "official outline", "official", AUTHORITY["official"], cleaned)
        )
    for index, dossier in enumerate(dossiers):
        if not isinstance(dossier, dict):
            continue
        nested = dossier.get("dossier") if isinstance(dossier.get("dossier"), dict) else dossier
        filename = _text(_get(dossier, "filename", "name", "source", "file"), 255) or _text(
            _get(nested, "filename", "name", "source", "file"), 255
        )
        kind = _text(_get(nested, "document_kind", "documentKind", "kind", "type"), 32).lower()
        if kind not in AUTHORITY or kind == "official":
            kind = "other"
        sources.append(
            _Source(
                filename or f"document {index + 1}",
                kind,
                AUTHORITY[kind],
                clean_file_dossier(nested),
            )
        )
    sources.sort(key=lambda source: -source.authority)
    return sources


def _topic_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        name = _text(_get(item, "name", "topic", "title"), 300)
        week = _to_int(_get(item, "week", "week_number", "weekNo"), 0)
    else:
        name, week = _text(item, 300), 0
    if not name:
        return None
    data: dict[str, Any] = {"name": name}
    if week > 0:
        data["week"] = week
    return data


def _week_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        week = _to_int(_get(item, "week", "week_number", "weekNo", "number"), 0)
        topic = _text(_get(item, "topic", "name", "title"), 300)
    else:
        week, topic = 0, _text(item, 300)
    if not week and not topic:
        return None
    return {"week": week, "topic": topic}


def _assessment_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        name = _text(_get(item, "name", "title"), 300)
        due = _text(_get(item, "due", "due_date"), 64)
        codes = _codes(_get(item, "lo_codes", "los"))
        weight = _to_float(_get(item, "weight"))
    else:
        name, due, codes, weight = _text(item, 300), "", [], None
    if not name:
        return None
    data: dict[str, Any] = {"name": name, "due": due, "lo_codes": codes}
    if weight is not None:
        data["weight"] = weight
    return data


def _reading_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        citation = _text(_get(item, "citation", "reference", "title"), 1000)
        week = _to_int(_get(item, "week"), 0)
    else:
        citation, week = _text(item, 1000), 0
    if not citation:
        return None
    data: dict[str, Any] = {"citation": citation}
    if week > 0:
        data["week"] = week
    return data


def _policy_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        title = _text(_get(item, "title", "name"), 255)
        key = _text(_get(item, "key", "policy"), 64)
        body = _text(_get(item, "body", "text"), 4000)
        date = _text(_get(item, "date"), 64)
    else:
        title, key, body, date = _text(item, 255), "", "", ""
    if not title and not body:
        return None
    data: dict[str, Any] = {
        "key": key or _slug(title or body),
        "title": title or key,
        "body": body,
    }
    if date:
        data["date"] = date
    return data


def _term_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        term = _text(_get(item, "term", "name"), 128)
        definition = _text(_get(item, "definition", "text"), 1000)
    else:
        term, definition = _text(item, 128), ""
    if not term:
        return None
    return {"term": term, "definition": definition}


def _formula_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        name = _text(_get(item, "name", "title"), 255)
        body = _text(_get(item, "body", "text"), 2000)
    else:
        name, body = _text(item, 255), ""
    if not name and not body:
        return None
    return {"name": name or body[:64], "body": body}


def _criterion_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        name = _text(_get(item, "name", "criterion", "title"), 255)
        levels = _get(item, "levels", "bands", "descriptors", default={})
    else:
        name, levels = _text(item, 255), {}
    if not name:
        return None
    return {"name": name, "levels": levels}


def _rows(
    sources: list[_Source],
    field_name: str,
    build: Callable[[Any], dict[str, Any] | None],
) -> list[_Row]:
    rows: list[_Row] = []
    for source in sources:
        for item in _items(source.data.get(field_name)):
            data = build(item)
            if data is None:
                continue
            rows.append(_Row(source, data, _row_value(data)))
    return rows


def _collapse(
    rows: list[_Row], key_fn: Callable[[dict[str, Any]], Any], cap: int, field_name: str
) -> tuple[list[dict[str, Any]], list[tuple[int, dict[str, Any]]]]:
    """Keep the highest-authority row per key and union everyone's provenance."""
    kept: list[_Kept] = []
    for row in rows:
        key = _normalize_key(key_fn(row.data))
        match: _Kept | None = None
        if key:
            for existing in kept:
                if existing.key == key or _jaccard(existing.key, key) >= JACCARD:
                    match = existing
                    break
        if match is None:
            kept.append(
                _Kept(
                    key=key,
                    data=dict(row.data),
                    authority=row.source.authority,
                    provenance=[row.provenance(field_name)],
                )
            )
            continue
        for name, value in row.data.items():
            if name not in match.data:
                match.data[name] = value
        match.provenance.append(row.provenance(field_name))
    kept = kept[:cap]
    data = [entry.data for entry in kept]
    provenance = [(entry.authority, item) for entry in kept for item in entry.provenance]
    return data, provenance


def _merge_outcomes(
    sources: list[_Source],
) -> tuple[dict[str, Any], list[tuple[int, dict[str, Any]]]]:
    clos: list[dict[str, str]] = []
    plos: list[dict[str, str]] = []
    mapping_rows: dict[str, dict[str, Any]] = {}
    provenance: list[tuple[int, dict[str, Any]]] = []

    def collect(bucket: list[dict[str, str]], bucket_name: str, field_name: str) -> None:
        index = {_normalize_key(item["code"]): item for item in bucket}
        for source in sources:
            outcomes = source.data.get("outcomes")
            if not isinstance(outcomes, dict):
                continue
            for item in _items(outcomes.get(bucket_name)):
                if not isinstance(item, dict):
                    continue
                code = _text(item.get("code"), 32)
                if not code:
                    continue
                key = _normalize_key(code)
                existing = index.get(key)
                if existing is None:
                    existing = {"code": code, "text": _text(item.get("text"), 1000)}
                    bucket.append(existing)
                    index[key] = existing
                elif not existing.get("text"):
                    existing["text"] = _text(item.get("text"), 1000)
                provenance.append(
                    (
                        source.authority,
                        {
                            "field": field_name,
                            "value": code,
                            "filename": source.filename,
                            "chunk_ordinal": _claim_ordinal(source.data, code),
                            "kind": source.kind,
                        },
                    )
                )

    collect(clos, "clos", "outcomes.clos")
    collect(plos, "plos", "outcomes.plos")

    for source in sources:
        outcomes = source.data.get("outcomes")
        if not isinstance(outcomes, dict):
            continue
        for item in _items(outcomes.get("mappings")):
            if not isinstance(item, dict):
                continue
            clo = _text(item.get("clo"), 32)
            if not clo:
                continue
            row = mapping_rows.setdefault(_normalize_key(clo), {"clo": clo, "plos": []})
            known = {_normalize_key(code) for code in row["plos"]}
            for code in _items(item.get("plos")):
                text = _text(code, 32)
                if text and _normalize_key(text) not in known:
                    row["plos"].append(text)
                    known.add(_normalize_key(text))
            provenance.append(
                (
                    source.authority,
                    {
                        "field": "outcomes.mappings",
                        "value": clo,
                        "filename": source.filename,
                        "chunk_ordinal": _claim_ordinal(source.data, clo),
                        "kind": source.kind,
                    },
                )
            )
    return (
        {"clos": clos, "plos": plos, "mappings": list(mapping_rows.values())},
        provenance,
    )


def _weight_of(data: dict[str, Any]) -> float | None:
    weight = data.get("weight")
    return float(weight) if isinstance(weight, (int, float)) else None


def _weight_text(value: float) -> str:
    return f"{value:.1f}%".replace(".0%", "%")


def _assessment_conflicts(rows: list[_Row]) -> list[dict[str, Any]]:
    """Same assessment name, different weight: the best source wins and we say so."""
    groups: dict[str, list[_Row]] = {}
    for row in rows:
        key = _normalize_key(row.data.get("name"))
        if key:
            groups.setdefault(key, []).append(row)
    conflicts: list[dict[str, Any]] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        weights = {
            weight for weight in (_weight_of(row.data) for row in group) if weight is not None
        }
        if len(weights) < 2:
            continue
        winner = max(group, key=lambda row: row.source.authority)
        winner_weight = _weight_of(winner.data)
        if winner_weight is None:
            continue
        seen: set[float] = set()
        for row in group:
            if row is winner:
                continue
            weight = _weight_of(row.data)
            if weight is None or weight == winner_weight or weight in seen:
                continue
            seen.add(weight)
            if winner.source.authority > row.source.authority:
                reason = (
                    f"{winner.source.filename} ({winner.source.kind}) outranks "
                    f"{row.source.filename} ({row.source.kind})"
                )
            else:
                reason = (
                    f"equal authority; {winner.source.filename} kept over {row.source.filename}"
                )
            conflicts.append(
                {
                    "field": f"assessment weight: {_text(winner.data.get('name'), 128)}",
                    "winner": _weight_text(winner_weight),
                    "loser": _weight_text(weight),
                    "reason": reason,
                }
            )
            if len(conflicts) >= CONFLICT_CAP:
                return conflicts
    return conflicts


def _provenance_list(entries: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Union provenance, keep the highest-authority 100, order deterministically."""
    unique: dict[tuple[Any, ...], tuple[int, dict[str, Any]]] = {}
    for authority, item in entries:
        key = (
            item.get("field"),
            item.get("value"),
            item.get("filename"),
            item.get("chunk_ordinal"),
            item.get("kind"),
        )
        existing = unique.get(key)
        if existing is None or authority > existing[0]:
            unique[key] = (authority, item)
    ordered = sorted(
        unique.values(),
        key=lambda pair: (
            -pair[0],
            str(pair[1].get("field")),
            str(pair[1].get("filename")),
            _to_int(pair[1].get("chunk_ordinal")),
            str(pair[1].get("kind")),
            str(pair[1].get("value")),
        ),
    )
    selected = [item for _, item in ordered[:PROVENANCE_CAP]]
    selected.sort(
        key=lambda item: (
            str(item.get("field")),
            str(item.get("filename")),
            _to_int(item.get("chunk_ordinal")),
            str(item.get("kind")),
            str(item.get("value")),
        )
    )
    return selected


def _open_questions(
    sources: list[_Source],
) -> tuple[list[str], list[tuple[int, dict[str, Any]]]]:
    questions: list[str] = []
    seen: set[str] = set()
    provenance: list[tuple[int, dict[str, Any]]] = []
    for source in sources:
        for item in _items(source.data.get("open_questions")):
            value = _text(item, 500)
            key = _normalize_key(value)
            if not value or key in seen:
                continue
            seen.add(key)
            questions.append(value)
            provenance.append(
                (
                    source.authority,
                    {
                        "field": "open_questions",
                        "value": value,
                        "filename": source.filename,
                        "chunk_ordinal": _claim_ordinal(source.data, value),
                        "kind": source.kind,
                    },
                )
            )
            if len(questions) >= OPEN_QUESTION_CAP:
                return questions, provenance
    return questions, provenance


def _pick_summary(sources: list[_Source]) -> str:
    for source in sources:
        summary = _text(source.data.get("summary"), 2000)
        if summary:
            return summary
    return ""


def _size(dossier: dict[str, Any]) -> int:
    return len(json.dumps(dossier, ensure_ascii=False, sort_keys=True))


def _prune_dict(value: dict[str, Any]) -> bool:
    for key in ("mappings", "plos", "clos"):
        rows = value.get(key)
        if isinstance(rows, list) and rows:
            rows.pop()
            return True
    return False


def shrink_dossier(dossier: dict[str, Any]) -> dict[str, Any]:
    """Trim to the total budget: cheapest content first, conflicts always kept."""
    data = _empty_merged()
    data.update({key: value for key, value in dossier.items() if key in data})
    if _size(data) <= MAX_CHARS:
        return data
    for section in PRUNE_ORDER:
        value = data.get(section)
        if isinstance(value, list):
            while value and _size(data) > MAX_CHARS:
                value.pop()
        elif isinstance(value, dict):
            while _size(data) > MAX_CHARS and _prune_dict(value):
                pass
        elif isinstance(value, str):
            while value and _size(data) > MAX_CHARS:
                value = value[: len(value) // 2] if len(value) > 40 else ""
                data[section] = value
        if _size(data) <= MAX_CHARS:
            return data
    provenance = data.get("provenance")
    if isinstance(provenance, list):
        while provenance and _size(data) > MAX_CHARS:
            provenance.pop()
    return data


def merge_dossiers(
    dossiers: list[dict[str, Any]] | None = None, official: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One deterministic course dossier from per-file dossiers and the outline."""
    sources = _sources(list(dossiers or []), official)
    merged = _empty_merged()
    if not sources:
        return shrink_dossier(merged)
    merged["summary"] = _pick_summary(sources)
    provenance: list[tuple[int, dict[str, Any]]] = []

    topics, rows = _collapse(
        _rows(sources, "topics", _topic_item), lambda data: data.get("name"), TOPIC_CAP, "topics"
    )
    merged["topics"] = topics
    provenance.extend(rows)

    weeks, rows = _collapse(
        _rows(sources, "week_links", _week_item),
        lambda data: f"week {data['week']}" if data.get("week") else data.get("topic"),
        WEEK_CAP,
        "weeks",
    )
    merged["weeks"] = weeks
    provenance.extend(rows)

    merged["outcomes"], rows = _merge_outcomes(sources)
    provenance.extend(rows)

    assessment_rows = _rows(sources, "assessments", _assessment_item)
    merged["conflicts"] = _assessment_conflicts(assessment_rows)
    merged["assessments"], rows = _collapse(
        assessment_rows, lambda data: data.get("name"), ASSESSMENT_CAP, "assessments"
    )
    provenance.extend(rows)

    merged["readings"], rows = _collapse(
        _rows(sources, "readings", _reading_item),
        lambda data: data.get("citation"),
        READING_CAP,
        "readings",
    )
    provenance.extend(rows)

    merged["policies_dates"], rows = _collapse(
        _rows(sources, "policies_dates", _policy_item),
        lambda data: data.get("key") or data.get("title"),
        POLICY_CAP,
        "policies_dates",
    )
    provenance.extend(rows)

    merged["key_terms"], rows = _collapse(
        _rows(sources, "key_terms", _term_item),
        lambda data: data.get("term"),
        KEY_TERM_CAP,
        "key_terms",
    )
    provenance.extend(rows)

    merged["formulas_examples"], rows = _collapse(
        _rows(sources, "formulas_examples", _formula_item),
        lambda data: data.get("name"),
        FORMULA_CAP,
        "formulas_examples",
    )
    provenance.extend(rows)

    merged["grading_criteria"], rows = _collapse(
        _rows(sources, "grading_criteria", _criterion_item),
        lambda data: data.get("name"),
        CRITERION_CAP,
        "grading_criteria",
    )
    provenance.extend(rows)

    merged["open_questions"], rows = _open_questions(sources)
    provenance.extend(rows)

    merged["provenance"] = _provenance_list(provenance)
    return shrink_dossier(merged)
