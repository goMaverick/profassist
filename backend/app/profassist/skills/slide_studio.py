"""Multi-hop slide skill. Plan, retrieve, cite, critique, then export."""

import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph


class SlideState(TypedDict, total=False):
    objectives: list[str]
    chunks: list[dict[str, Any]]
    outline: dict[str, Any]
    dossier: dict[str, Any]
    queries: list[dict[str, str]]
    hits: list[dict[str, Any]]
    slides: list[dict[str, Any]]
    preferences: list[str]
    skill: str


from app.profassist import llm
from app.profassist.observe import invoke_graph
from app.profassist.rag import keyword_score
from app.profassist.runtime import prompt_for, tool_enabled
from app.profassist.skills.loader import load_skill
from app.profassist.slides import build_pptx


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [part.strip() for part in parts if len(part.strip()) > 40]


def _cite_fragment(text: str) -> tuple[str, str]:
    """Return (bullet, quote) from a chunk without opening on a partial word.

    The bullet prefers a fragment that starts with a capital letter or digit.
    When every fragment is a continuation, it trims the leading partial word and
    prefixes an ellipsis. The quote stays verbatim so the citation is unchanged.
    """
    fragments = _sentences(text)
    if not fragments:
        whole = " ".join((text or "").split())
        return whole, whole
    for fragment in fragments:
        first = fragment[:1]
        if first.isupper() or first.isdigit():
            return fragment, fragment
    first = fragments[0]
    _head, separator, tail = first.partition(" ")
    if separator and tail.strip():
        return "…" + tail.strip(), first
    return "…" + first, first


def plan_queries(objectives: list[str]) -> list[dict[str, str]]:
    queries = []
    for objective in objectives:
        words = list(re.findall(r"[A-Za-z]{5,}", objective))[:6]
        queries.append({"objective": objective, "query": " ".join(words) or objective})
        if len(words) > 3:
            queries.append({"objective": objective, "query": " ".join(words[:3]), "hop": "2"})
    return queries


def retrieve_hops(
    queries: list[dict[str, str]], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Two hops. The second hop prefers a different file that shares a term."""
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in queries:
        ranked = sorted(
            chunks,
            key=lambda chunk: keyword_score(item["query"], chunk.get("text") or ""),
            reverse=True,
        )
        for chunk in ranked:
            if keyword_score(item["query"], chunk.get("text") or "") <= 0:
                break
            key = str(chunk.get("id"))
            if key in seen:
                continue
            seen.add(key)
            row = dict(chunk)
            row["objective"] = item["objective"]
            row["query"] = item["query"]
            picked.append(row)
            break
        else:
            continue
        # Cross-document link: another file containing the same query terms.
        first_file = picked[-1].get("filename")
        for chunk in ranked[1:]:
            if chunk.get("filename") == first_file:
                continue
            if keyword_score(item["query"], chunk.get("text") or "") <= 0:
                continue
            key = str(chunk.get("id"))
            if key in seen:
                continue
            seen.add(key)
            row = dict(chunk)
            row["objective"] = item["objective"]
            row["query"] = item["query"]
            row["linked_from"] = first_file
            picked.append(row)
            break
    return picked


def cite_slide(objective: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    bullets = []
    for hit in hits:
        bullet, quote = _cite_fragment(hit.get("text") or "")
        if not bullet:
            continue
        bullets.append(
            {
                "text": bullet,
                "citation": {
                    "filename": hit.get("filename") or "note",
                    "section": hit.get("section") or "note",
                    "quote": quote,
                    "chunk_id": hit.get("id"),
                },
            }
        )
    return {
        "title": objective[:90],
        "objective": objective,
        "bullets": bullets[:3],
        "notes": prompt_for("slide_studio"),
        "gap": not bullets,
    }


def critique(slides: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = "\n".join(chunk.get("text") or "" for chunk in chunks)
    kept = []
    for slide in slides:
        bullets = []
        for bullet in slide.get("bullets") or []:
            text = bullet["text"] if isinstance(bullet, dict) else str(bullet)
            grounded = text in source or (
                len(text) > 1 and text.startswith("…") and text[1:] in source
            )
            if text and grounded:
                bullets.append(
                    bullet if isinstance(bullet, dict) else {"text": text, "citation": {}}
                )
        slide = dict(slide)
        slide["bullets"] = bullets
        slide["gap"] = not bullets
        if slide["gap"]:
            slide["notes"] = (
                "Gap: the uploaded notes do not cover this objective. Nothing was invented."
            )
        kept.append(slide)
    return kept


def _wants(preferences: list[str], *phrases: str) -> bool:
    blob = " ".join(str(item).lower() for item in preferences)
    return any(phrase in blob for phrase in phrases)


_LENGTH_HINT = re.compile(r"about\s+(\d+)\s+characters", re.IGNORECASE)
_SHORTER_DEFAULT = 100
_SHORTER_MAX = 220
# Do not touch a bullet that is already short; 40 is the practical floor.
_SHORTER_FLOOR = 40


def _shorter_limit(preferences: list[str]) -> int:
    """The professor's stated bullet length, clamped to a readable range."""
    match = _LENGTH_HINT.search(" ".join(preferences))
    if not match:
        return _SHORTER_DEFAULT
    return max(_SHORTER_FLOOR, min(_SHORTER_MAX, int(match.group(1))))


def _shorten(text: str, limit: int) -> str:
    """Trim an over-long bullet at the last word boundary before the limit."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    boundary = head.rfind(" ")
    if boundary > 0:
        return head[:boundary].rstrip()
    return head


def _sentence_case(title: str) -> str:
    words = title.split()
    if len(words) < 2:
        return title
    converted = [words[0]]
    converted.extend(word if word.isupper() else word.lower() for word in words[1:])
    return " ".join(converted)


def _citation_filename(slide: dict[str, Any]) -> str:
    for bullet in slide.get("bullets") or []:
        if isinstance(bullet, dict):
            filename = (bullet.get("citation") or {}).get("filename")
            if filename:
                return str(filename)
    return ""


def apply_style_preferences(
    slides: list[dict[str, Any]], preferences: list[str] | None
) -> list[dict[str, Any]]:
    """Deterministic style rules. The citation quote stays verbatim."""
    prefs = [str(item) for item in preferences or [] if str(item).strip()]
    if not prefs:
        return slides
    fewer = _wants(prefs, "fewer bullets")
    shorter = _wants(prefs, "shorter bullets")
    limit = _shorter_limit(prefs) if shorter else 0
    add_notes = _wants(prefs, "speaker notes")
    sentence = _wants(prefs, "sentence-case")
    styled: list[dict[str, Any]] = []
    for slide in slides:
        current = dict(slide)
        bullets: list[Any] = []
        for bullet in current.get("bullets") or []:
            if isinstance(bullet, dict):
                row = dict(bullet)
                text = str(row.get("text") or "")
                if shorter:
                    row["text"] = _shorten(text, limit)
                bullets.append(row)
            else:
                text = str(bullet)
                if shorter:
                    text = _shorten(text, limit)
                bullets.append(text)
        if fewer:
            bullets = bullets[:1]
        current["bullets"] = bullets
        notes = str(current.get("speaker_notes") or current.get("notes") or "").strip()
        if add_notes and not notes:
            filename = _citation_filename({"bullets": bullets})
            note = f"From the notes - {filename}" if filename else "From the notes"
            current["notes"] = note
            if "speaker_notes" in current:
                current["speaker_notes"] = note
        if sentence:
            current["title"] = _sentence_case(str(current.get("title") or ""))
        styled.append(current)
    return styled


def run_slide_studio(
    objectives: list[str],
    chunks: list[dict[str, Any]],
    template: bytes | None = None,
    title: str = "Slide studio",
    instructions: str = "",
    outline: dict[str, Any] | None = None,
    dossier: dict[str, Any] | None = None,
    preferences: list[str] | None = None,
) -> dict[str, Any]:
    skill = load_skill("slide-studio")

    def plan(state: SlideState) -> SlideState:
        if not tool_enabled("slide_studio", "plan"):
            return {"queries": [{"objective": item, "query": item} for item in state["objectives"]]}
        return {"queries": plan_queries(state["objectives"])}

    def retrieve(state: SlideState) -> SlideState:
        if not tool_enabled("slide_studio", "retrieve"):
            return {"hits": []}
        return {"hits": retrieve_hops(state.get("queries") or [], state.get("chunks") or [])}

    def draft(state: SlideState) -> SlideState:
        hits = state.get("hits") or []
        slides = []
        for objective in state.get("objectives") or []:
            related = [hit for hit in hits if hit.get("objective") == objective]
            slides.append(cite_slide(objective, related))
        if tool_enabled("slide_studio", "critique"):
            slides = critique(slides, state.get("chunks") or [])
        slides = apply_style_preferences(slides, state.get("preferences") or [])
        return {"slides": slides}

    graph = StateGraph(SlideState)
    graph.add_node("plan", plan)
    graph.add_node("retrieve", retrieve)
    graph.add_node("draft", draft)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", END)
    result, trace_url = invoke_graph(
        graph.compile(),
        {
            "objectives": objectives,
            "chunks": chunks,
            "outline": outline or {},
            "dossier": dossier or {},
            "preferences": preferences or [],
            "skill": skill["instructions"],
        },
        name="slide-studio",
        metadata={
            "kind": "slide_studio",
            "professor_instructions": instructions,
            "preferences": preferences or [],
        },
    )
    slides = result.get("slides") or []
    pptx = b""
    if tool_enabled("slide_studio", "pptx"):
        exportable = []
        for slide in slides:
            if slide.get("gap"):
                continue
            citations = []
            for bullet in slide.get("bullets") or []:
                if isinstance(bullet, dict):
                    filename = (bullet.get("citation") or {}).get("filename")
                    if filename:
                        citations.append(filename)
            exportable.append(
                {
                    "title": slide.get("title"),
                    "bullets": slide.get("bullets") or [],
                    "notes": slide.get("notes") or "",
                    "citations": citations,
                }
            )
        if exportable:
            pptx = build_pptx(title, exportable, template=template)
    llm.trace("slide_studio", {"task": "slide_studio", "mode": llm.mode()})
    return {
        "skill": skill["name"],
        "tools": skill["tools"],
        "slides": slides,
        "gaps": [slide["objective"] for slide in slides if slide.get("gap")],
        "preferences": preferences or [],
        "pptx": pptx,
        "trace_url": trace_url or "",
    }
