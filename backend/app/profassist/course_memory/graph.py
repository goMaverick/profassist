"""LangGraph map-reduce that turns course files into one sourced dossier.

Each document is its own span: a fan-out step sends one extract task per
material, every task returns a ``FileDossier`` or a recorded error, and a merge
node reduces them. The deterministic merge always runs first; a model may refine
it, but a model failure never loses the deterministic result. No node raises.
"""

from __future__ import annotations

import json
import operator
import re
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.profassist import llm
from app.profassist.course_memory.cleaners import (
    clean_file_dossier,
    clean_merged_dossier,
    parse_json_object,
)
from app.profassist.course_memory.merge import merge_dossiers, shrink_dossier
from app.profassist.course_memory.prompts import (
    COURSE_MEMORY_MERGE_RULES,
    FILE_DOSSIER_RULES,
)
from app.profassist.course_memory.schemas import FileDossier, MergedDossier
from app.profassist.observe import invoke_graph
from app.profassist.pii import scrub
from app.profassist.rag import keyword_score

# One file is bounded so one long lecture cannot crowd out the others.
MAX_FILE_CHARS = 24_000
MAX_CHUNKS = 40
FIRST_CHUNKS = 2
ERROR_CHARS = 300

_DROP = object()

# A partial dossier is only a failure when the excerpts clearly name outcomes or
# assessments that the reply dropped. These words are that signal.
_SIGNAL_RE = re.compile(
    r"\bCLOs?\b|\bCLO\d+\b|\bPLOs?\b|\bPLO\d+\b|learning outcomes?"
    r"|\bassessments?\b|\bweights?\b|\bpercentage\b|\bpercent\b|%",
    re.IGNORECASE,
)
RETRY_NOTE = (
    "Return every field; do not stop after summary/topics. Fill outcomes.clos and "
    "assessments from the excerpts, and return [] only when the excerpts do not state them."
)

# Identifiers and codes are never scrubbed: a filename or CLO must stay exact.
_IDENTIFIER_KEYS = frozenset(
    {
        "filename",
        "url",
        "code",
        "id",
        "material_id",
        "chunk_ordinal",
        "lo_codes",
        "clo",
        "plos",
        "kind",
        "document_kind",
    }
)


class ExtractState(TypedDict, total=False):
    """One material in, one file dossier out. A ``dossier`` is precomputed."""

    material_id: str
    filename: str
    ordinal: int
    query: str
    chunks: list[dict[str, Any]]
    dossier: dict[str, Any]


class MemoryState(TypedDict, total=False):
    """Course-wide state. ``dossiers`` and ``errors`` are reduced per file."""

    course_code: str
    materials: list[dict[str, Any]]
    official: dict[str, Any]
    dossiers: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[dict[str, Any]], operator.add]
    merged: dict[str, Any]


def _dossier_contract(rules: str, model: type[Any]) -> str:
    """Rules and the compact JSON schema for one dossier model."""
    schema = json.dumps(model.model_json_schema(), separators=(",", ":"), sort_keys=True)
    return f"{rules}\nSchema (JSON): {schema}"


def _ordinal(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_error(exc: Exception) -> str:
    try:
        return scrub(f"{type(exc).__name__}: {exc}").text[:ERROR_CHARS]
    except Exception:
        return type(exc).__name__


def _mentions_signals(excerpts: list[dict[str, Any]]) -> bool:
    """True when the excerpts name a CLO, an assessment, a weight, or a percent."""
    return any(_SIGNAL_RE.search(str(excerpt.get("text") or "")) for excerpt in excerpts)


def _is_partial_dossier(dossier: dict[str, Any]) -> bool:
    """A dossier with no CLOs and no assessments, the two fields a syllabus has."""
    outcomes = dossier.get("outcomes")
    clos = outcomes.get("clos") if isinstance(outcomes, dict) else None
    return not clos and not dossier.get("assessments")


def _dossier_weight(dossier: dict[str, Any]) -> int:
    """How much course memory a dossier carries. The richer reply wins a retry."""
    score = 0
    for key in (
        "topics",
        "week_links",
        "assessments",
        "readings",
        "policies_dates",
        "key_terms",
        "formulas_examples",
        "grading_criteria",
        "open_questions",
        "claims",
    ):
        value = dossier.get(key)
        if isinstance(value, list):
            score += len(value)
    outcomes = dossier.get("outcomes")
    if isinstance(outcomes, dict):
        for key in ("clos", "plos", "mappings"):
            value = outcomes.get(key)
            if isinstance(value, list):
                score += len(value)
    return score


def _richer_dossier(first: dict[str, Any], retry: dict[str, Any]) -> dict[str, Any]:
    """Keep the first reply unless the retry carries more, then fill its gaps."""
    if _dossier_weight(retry) <= _dossier_weight(first):
        return first
    merged = dict(first)
    for key, value in retry.items():
        if isinstance(value, list) and value:
            merged[key] = value
        elif isinstance(value, dict):
            base = dict(first.get(key) or {}) if isinstance(first.get(key), dict) else {}
            base.update({inner: item for inner, item in value.items() if item})
            merged[key] = base
        elif value is not None and value != "":
            merged[key] = value
    return merged


def pii_gate_dossier(dossier: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Scrub free text in a dossier, dropping a field that cannot be cleaned.

    Identifier fields (filenames, codes, ordinals) are kept exact. ``scrub``
    quarantines text where a name may still be present. That field is removed
    rather than guessed at, so a single suspect value cannot block the rest of
    the document. Never raises.
    """
    dropped = 0

    def walk(value: Any) -> Any:
        nonlocal dropped
        if isinstance(value, str):
            try:
                cleaned = scrub(value)
            except Exception:
                dropped += 1
                return _DROP
            if cleaned.quarantined:
                dropped += 1
                return _DROP
            return cleaned.text
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key in _IDENTIFIER_KEYS:
                    result[key] = item
                    continue
                gated = walk(item)
                if gated is not _DROP:
                    result[key] = gated
            return result
        if isinstance(value, (list, tuple)):
            rows: list[Any] = []
            for item in value:
                gated = walk(item)
                if gated is not _DROP:
                    rows.append(gated)
            return rows
        return value

    try:
        clean = walk(dossier)
    except Exception:
        return {}, dropped
    return (clean if isinstance(clean, dict) else {}), dropped


def _salient(chunks: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    """Keyword rank when the query names the file; otherwise keep document order."""
    if not (query or "").strip():
        return chunks[:limit]
    scored = [
        (keyword_score(query, str(chunk.get("text") or "")), index, chunk)
        for index, chunk in enumerate(chunks)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    positive = [chunk for score, _index, chunk in scored if score > 0]
    if positive:
        return positive[:limit]
    return [chunk for _score, _index, chunk in scored[:limit]]


def build_excerpts(
    *,
    material_id: str,
    filename: str,
    chunks: list[dict[str, Any]],
    query: str = "",
) -> list[dict[str, Any]]:
    """First two chunks plus keyword-salient ones, bounded to 24k characters."""
    ordered = sorted(
        (chunk for chunk in chunks if str(chunk.get("text") or "").strip()),
        key=lambda chunk: _ordinal(chunk.get("ordinal")),
    )
    picked: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for chunk in [*ordered[:FIRST_CHUNKS], *_salient(ordered, query, MAX_CHUNKS)]:
        key = (_ordinal(chunk.get("ordinal")), str(chunk.get("text") or "")[:40])
        if key in seen:
            continue
        seen.add(key)
        picked.append(chunk)
        if len(picked) >= MAX_CHUNKS:
            break

    excerpts: list[dict[str, Any]] = []
    used = 0
    for chunk in picked:
        remaining = MAX_FILE_CHARS - used
        if remaining <= 0:
            break
        text = str(chunk.get("text") or "").strip()
        if len(text) > remaining:
            text = text[:remaining]
        if not text:
            continue
        excerpts.append(
            {
                "material_id": material_id,
                "filename": filename,
                "ordinal": _ordinal(chunk.get("ordinal")),
                "text": text,
            }
        )
        used += len(text)
    return excerpts


def extract_material_dossier(
    *,
    material_id: str,
    filename: str,
    chunks: list[dict[str, Any]],
    query: str = "",
    dossier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One file in, one file dossier out, or ``{"error": ...}``.

    A precomputed dossier means the file is unchanged since the last rebuild, so
    the model is not called again. The result is always gated for PII.
    """
    try:
        if isinstance(dossier, dict) and dossier:
            gated, _dropped = pii_gate_dossier(dossier)
            gated["filename"] = filename
            gated["material_id"] = material_id
            return {"dossier": gated}
        excerpts = build_excerpts(
            material_id=material_id,
            filename=filename,
            chunks=chunks,
            query=query,
        )
        if not excerpts:
            return {
                "dossier": {
                    "document_kind": "other",
                    "filename": filename,
                    "material_id": material_id,
                    "claims": [],
                }
            }
        payload = {
            "material_id": material_id,
            "filename": filename,
            "chunks": excerpts,
            "contract": _dossier_contract(FILE_DOSSIER_RULES, FileDossier),
        }
        dossier = clean_file_dossier(parse_json_object(llm.complete("dossier_extract", payload)))
        if _is_partial_dossier(dossier) and _mentions_signals(excerpts):
            # Gemini may legally stop after summary/topics; ask once more, stricter.
            try:
                retry = llm.complete("dossier_extract", {**payload, "retry_note": RETRY_NOTE})
                dossier = _richer_dossier(dossier, clean_file_dossier(parse_json_object(retry)))
            except Exception:
                pass
        gated, _dropped = pii_gate_dossier(dossier)
        gated["filename"] = filename
        gated["material_id"] = material_id
        return {"dossier": gated}
    except Exception as exc:
        return {"error": _safe_error(exc)}


def _extract(state: ExtractState) -> dict[str, Any]:
    material_id = str(state.get("material_id") or "")
    filename = str(state.get("filename") or "document")
    precomputed = state.get("dossier") if isinstance(state.get("dossier"), dict) else None
    outcome = extract_material_dossier(
        material_id=material_id,
        filename=filename,
        chunks=state.get("chunks") or [],
        query=str(state.get("query") or ""),
        dossier=precomputed,
    )
    if "error" in outcome:
        return {
            "dossiers": [],
            "errors": [
                {
                    "material_id": material_id,
                    "filename": filename,
                    "error": str(outcome["error"]),
                }
            ],
        }
    return {"dossiers": [outcome["dossier"]], "errors": []}


def _fan_out(state: MemoryState) -> list[Send] | list[str]:
    """One span per material. No materials still needs the merge node."""
    materials = [item for item in (state.get("materials") or []) if isinstance(item, dict)]
    if not materials:
        return ["merge"]
    course_code = str(state.get("course_code") or "")
    sends: list[Send] = []
    for material in materials:
        filename = str(material.get("filename") or "document")
        sends.append(
            Send(
                "extract",
                {
                    "material_id": str(material.get("material_id") or material.get("id") or ""),
                    "filename": filename,
                    "ordinal": _ordinal(material.get("ordinal")),
                    "query": " ".join(part for part in (course_code, filename) if part),
                    "chunks": material.get("chunks") or [],
                    "dossier": (
                        material.get("dossier")
                        if isinstance(material.get("dossier"), dict)
                        else None
                    ),
                },
            )
        )
    return sends or ["merge"]


def _dispatch(state: MemoryState) -> MemoryState:
    return {}


def _has_content(payload: dict[str, Any]) -> bool:
    """A merge reply with no course memory is junk and loses to the deterministic one."""
    if str(payload.get("summary") or "").strip():
        return True
    for key in (
        "topics",
        "weeks",
        "week_links",
        "assessments",
        "readings",
        "policies_dates",
        "key_terms",
        "formulas_examples",
        "grading_criteria",
        "open_questions",
        "provenance",
        "conflicts",
    ):
        if payload.get(key):
            return True
    outcomes = payload.get("outcomes")
    return bool(
        isinstance(outcomes, dict)
        and any(outcomes.get(key) for key in ("clos", "plos", "mappings"))
    )


def _trim_dossiers(dossiers: list[Any], limit: int = MAX_FILE_CHARS) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    used = 0
    for dossier in dossiers:
        if not isinstance(dossier, dict):
            continue
        size = len(json.dumps(dossier, ensure_ascii=False, sort_keys=True))
        if picked and used + size > limit:
            break
        picked.append(dossier)
        used += size
    return picked


def _merge(state: MemoryState) -> dict[str, Any]:
    dossiers = state.get("dossiers") or []
    official = state.get("official") or None
    try:
        deterministic = merge_dossiers(dossiers, official)
    except Exception:
        try:
            deterministic = merge_dossiers([], None)
        except Exception:
            deterministic = {}
    merged = deterministic
    try:
        raw = llm.complete(
            "dossier_merge",
            {
                "course_code": state.get("course_code") or "",
                "official": state.get("official") or {},
                "dossiers": _trim_dossiers(dossiers),
                "deterministic": deterministic,
                "contract": _dossier_contract(COURSE_MEMORY_MERGE_RULES, MergedDossier),
            },
        )
        payload = parse_json_object(raw)
        if _has_content(payload):
            proposed, _dropped = pii_gate_dossier(clean_merged_dossier(payload))
            if not proposed.get("provenance"):
                proposed["provenance"] = deterministic.get("provenance") or []
            if not proposed.get("conflicts"):
                proposed["conflicts"] = deterministic.get("conflicts") or []
            merged = proposed
    except Exception:
        merged = deterministic
    return {"merged": shrink_dossier(merged)}


def build_memory_graph():
    """Dispatch -> one extract span per material -> merge."""
    graph = StateGraph(MemoryState)
    graph.add_node("dispatch", _dispatch)
    graph.add_node("extract", _extract)
    graph.add_node("merge", _merge)
    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges("dispatch", _fan_out)
    graph.add_edge("extract", "merge")
    graph.add_edge("merge", END)
    return graph.compile()


def run_memory_state(
    materials: list[dict[str, Any]], official: dict[str, Any] | None, *, course_code: str
) -> tuple[dict[str, Any], str | None]:
    """Run the graph and keep the per-file dossiers and errors for the caller."""
    state = {
        "course_code": course_code,
        "materials": [dict(material) for material in materials or []],
        "official": official or {},
        "dossiers": [],
        "errors": [],
    }
    result, trace = invoke_graph(
        build_memory_graph(),
        state,
        name=f"course-memory: {course_code}",
        metadata={"kind": "course_memory"},
    )
    return (result if isinstance(result, dict) else {}), trace


def run_course_memory(
    materials: list[dict[str, Any]], official: dict[str, Any] | None, *, course_code: str
) -> tuple[dict[str, Any], str | None]:
    """The merged course dossier and its public trace url."""
    result, trace = run_memory_state(materials, official, course_code=course_code)
    merged = result.get("merged")
    if not isinstance(merged, dict) or not merged:
        merged = merge_dossiers(result.get("dossiers") or [], official or None)
    return shrink_dossier(merged), trace


__all__ = [
    "ExtractState",
    "MemoryState",
    "build_excerpts",
    "build_memory_graph",
    "extract_material_dossier",
    "pii_gate_dossier",
    "run_course_memory",
    "run_memory_state",
]
