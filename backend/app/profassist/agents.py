"""LangGraph flows. Each one drafts. The professor approves outside the graph."""

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.profassist import llm
from app.profassist.grading import reconcile
from app.profassist.rag import keyword_score

PERSONAS = ("evidence", "strict", "supportive")


class CourseState(TypedDict, total=False):
    task: str
    title: str
    query: str
    chunks: list[dict[str, Any]]
    clos: list[str]
    soul: str
    result: dict[str, Any]


class GradeState(TypedDict, total=False):
    submission: str
    criterion: dict[str, Any]
    soul: str
    votes: list[dict[str, Any]]
    judge: dict[str, Any]
    feedback: str


def _supported(text: str, chunks: list[dict[str, Any]]) -> bool:
    if not chunks:
        return False
    blob = " ".join(chunk.get("text") or "" for chunk in chunks).lower()
    words = [word for word in text.lower().split() if len(word) > 4]
    if len(words) < 3:
        return False
    hits = sum(1 for word in words if word in blob)
    return hits / len(words) >= 0.55


def _retrieve(state: CourseState) -> CourseState:
    query = state.get("query") or state.get("title") or ""
    chunks = state.get("chunks") or []
    ranked = sorted(
        chunks, key=lambda chunk: keyword_score(query, chunk.get("text") or ""), reverse=True
    )
    return {"chunks": ranked[:4]}


def _draft_course(state: CourseState) -> CourseState:
    task = state.get("task") or "objectives"
    payload = {
        "title": state.get("title"),
        "chunks": state.get("chunks") or [],
        "clos": state.get("clos") or [],
        "soul": state.get("soul") or "",
    }
    result = llm.complete(task, payload)
    if task == "objectives":
        kept = []
        for objective in result.get("objectives") or []:
            if _supported(objective.get("text") or "", state.get("chunks") or []):
                kept.append(objective)
        result["objectives"] = kept
    if task == "slides":
        source = "\n".join(chunk.get("text") or "" for chunk in state.get("chunks") or [])
        slides = []
        for slide in result.get("slides") or []:
            bullets = [
                bullet for bullet in slide.get("bullets") or [] if bullet and bullet in source
            ]
            if bullets:
                slide = dict(slide)
                slide["bullets"] = bullets
                slides.append(slide)
        result["slides"] = slides
    return {"result": result}


def build_course_graph():
    graph = StateGraph(CourseState)
    graph.add_node("retrieve", _retrieve)
    graph.add_node("draft", _draft_course)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", END)
    return graph.compile()


def run_course(task: str, **state: Any) -> dict[str, Any]:
    result = build_course_graph().invoke({"task": task, **state})
    return result.get("result") or {}


def _grade_persona(persona: str, index: int):
    def node(state: GradeState) -> GradeState:
        vote = llm.complete(
            "grade_persona",
            {
                "persona": persona,
                "model": llm.council_model(index),
                "submission": state.get("submission") or "",
                "criterion": state.get("criterion") or {},
                "soul": state.get("soul") or "",
            },
        )
        votes = list(state.get("votes") or [])
        votes.append(vote)
        return {"votes": votes}

    return node


def _judge(state: GradeState) -> GradeState:
    judge = reconcile(state.get("votes") or [], state.get("submission") or "")
    return {"judge": judge}


def _feedback(state: GradeState) -> GradeState:
    judge = state.get("judge") or {}
    if judge.get("evidence_status") != "ok":
        return {
            "feedback": (
                "No feedback draft. The council did not produce reliable evidence, "
                "so this criterion is left for you."
            )
        }
    quote = (judge.get("quotes") or [""])[0]
    written = llm.complete(
        "feedback",
        {
            "quote": quote,
            "level": judge.get("level"),
            "soul": state.get("soul") or "",
            "criterion": state.get("criterion") or {},
        },
    )
    return {"feedback": written.get("feedback") or ""}


def build_grading_graph():
    graph = StateGraph(GradeState)
    graph.add_node("evidence", _grade_persona("evidence", 0))
    graph.add_node("strict", _grade_persona("strict", 1))
    graph.add_node("supportive", _grade_persona("supportive", 2))
    graph.add_node("judge", _judge)
    graph.add_node("feedback", _feedback)
    graph.set_entry_point("evidence")
    graph.add_edge("evidence", "strict")
    graph.add_edge("strict", "supportive")
    graph.add_edge("supportive", "judge")
    graph.add_edge("judge", "feedback")
    graph.add_edge("feedback", END)
    return graph.compile()


def run_grading_council(submission: str, criterion: dict[str, Any], soul: str) -> dict[str, Any]:
    result = build_grading_graph().invoke(
        {"submission": submission, "criterion": criterion, "soul": soul, "votes": []}
    )
    return {
        "votes": result.get("votes") or [],
        "judge": result.get("judge") or {},
        "feedback": result.get("feedback") or "",
    }


def run_reflection(proposal: str) -> str:
    """A short graph: one reflection node the professor can accept or ignore."""

    class ReflectState(TypedDict, total=False):
        proposal: str
        text: str

    def node(state: ReflectState) -> ReflectState:
        written = llm.complete("reflection", {"proposal": state.get("proposal") or ""})
        return {"text": written.get("proposal") or state.get("proposal") or ""}

    graph = StateGraph(ReflectState)
    graph.add_node("reflect", node)
    graph.set_entry_point("reflect")
    graph.add_edge("reflect", END)
    return graph.compile().invoke({"proposal": proposal}).get("text") or proposal
