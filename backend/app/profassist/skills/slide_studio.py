"""Multi-hop slide skill. Plan, retrieve, cite, critique, then export."""

import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph


class SlideState(TypedDict, total=False):
    objectives: list[str]
    chunks: list[dict[str, Any]]
    queries: list[dict[str, str]]
    hits: list[dict[str, Any]]
    slides: list[dict[str, Any]]
    skill: str


from app.profassist import llm
from app.profassist.rag import keyword_score
from app.profassist.runtime import prompt_for, tool_enabled
from app.profassist.skills.loader import load_skill
from app.profassist.slides import build_pptx


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [part.strip() for part in parts if len(part.strip()) > 40]


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
        sentence = (_sentences(hit.get("text") or "") or [hit.get("text") or ""])[0]
        if not sentence:
            continue
        bullets.append(
            {
                "text": sentence,
                "citation": {
                    "filename": hit.get("filename") or "note",
                    "section": hit.get("section") or "note",
                    "quote": sentence,
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
            if text and text in source:
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


def run_slide_studio(objectives: list[str], chunks: list[dict[str, Any]]) -> dict[str, Any]:
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
        return {"slides": slides}

    graph = StateGraph(SlideState)
    graph.add_node("plan", plan)
    graph.add_node("retrieve", retrieve)
    graph.add_node("draft", draft)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", END)
    result = graph.compile().invoke(
        {"objectives": objectives, "chunks": chunks, "skill": skill["instructions"]}
    )
    slides = result.get("slides") or []
    pptx = b""
    if tool_enabled("slide_studio", "pptx"):
        exportable = []
        for slide in slides:
            if slide.get("gap"):
                continue
            exportable.append(
                {
                    "title": slide.get("title"),
                    "bullets": [
                        bullet["text"] if isinstance(bullet, dict) else bullet
                        for bullet in slide.get("bullets") or []
                    ],
                    "notes": slide.get("notes") or "",
                }
            )
        if exportable:
            pptx = build_pptx("Slide studio", exportable)
    llm.trace("slide_studio", {"task": "slide_studio", "mode": llm.mode()})
    return {
        "skill": skill["name"],
        "tools": skill["tools"],
        "slides": slides,
        "gaps": [slide["objective"] for slide in slides if slide.get("gap")],
        "pptx": pptx,
    }
