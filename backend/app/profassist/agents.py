"""LangGraph flows. Each one drafts. The professor approves outside the graph."""

import itertools
import logging
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.profassist import llm
from app.profassist.council_config import chair_of, default_roles, enabled_keys, message_roles
from app.profassist.errors import ProfassistError
from app.profassist.grading import needs_debate, reconcile
from app.profassist.observe import invoke_graph
from app.profassist.rag import keyword_score
from app.profassist.runtime import debate_settings

PERSONAS = ("evidence", "strict", "supportive")
logger = logging.getLogger(__name__)


class CourseState(TypedDict, total=False):
    task: str
    title: str
    query: str
    chunks: list[dict[str, Any]]
    clos: list[str]
    soul: str
    message: str
    dossier: dict[str, Any]
    result: dict[str, Any]


class GradeState(TypedDict, total=False):
    submission: str
    criterion: dict[str, Any]
    outline: dict[str, Any]
    clos: list[str]
    dossier: dict[str, Any]
    soul: str
    votes: list[dict[str, Any]]
    peer_reviews: list[dict[str, Any]]
    debate_rounds: list[dict[str, Any]]
    judge: dict[str, Any]
    feedback: str
    personas: list[str]
    persona_config: dict[str, dict[str, Any]]


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


def normalise_objective(raw: Any) -> dict[str, Any] | None:
    """One model row as a dict. A bare string is treated as its ``text``.

    Course designers sometimes answer with ``["Explain X"]`` instead of
    ``[{"text": "Explain X"}]``. Every consumer reads ``row["text"]``, so the
    string is wrapped here rather than crashing the route downstream.
    """
    if isinstance(raw, str):
        text = raw.strip()
        return {"text": text} if text else None
    if isinstance(raw, dict):
        value = raw.get("text")
        if isinstance(value, str) and value.strip():
            return raw
    return None


def _draft_course(state: CourseState) -> CourseState:
    task = state.get("task") or "objectives"
    payload = {
        "title": state.get("title"),
        "chunks": state.get("chunks") or [],
        "clos": state.get("clos") or [],
        "soul": state.get("soul") or "",
        "message": state.get("message") or "",
        "dossier": state.get("dossier") or {},
    }
    result = llm.complete(task, payload)
    if task == "course_design":
        return {"result": result}
    if task == "objectives":
        rows = result.get("objectives") if isinstance(result, dict) else result
        if isinstance(rows, str):
            rows = [rows]
        kept = []
        for row in rows or []:
            objective = normalise_objective(row)
            if objective and _supported(objective["text"], state.get("chunks") or []):
                kept.append(objective)
        if not isinstance(result, dict):
            result = {"objectives": kept}
        else:
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
    result, _url = invoke_graph(
        build_course_graph(),
        {"task": task, **state},
        name=f"{task}: {state.get('title') or 'course'}",
        metadata={"kind": task},
    )
    return result.get("result") or {}


def _grade_persona(persona: str, index: int):
    def node(state: GradeState) -> GradeState:
        config = (state.get("persona_config") or {}).get(persona) or {}
        payload: dict[str, Any] = {
            "persona": persona,
            "model": config.get("model") or llm.council_model(index),
            "submission": state.get("submission") or "",
            "criterion": state.get("criterion") or {},
            "outline": state.get("outline") or {},
            "clos": state.get("clos") or [],
            "dossier": state.get("dossier") or {},
            "soul": state.get("soul") or "",
            "peer_reviews": state.get("peer_reviews") or [],
            "peer_note": (
                "Peer reviews are extra evidence only. They do not set the level. "
                "Quote the submission, not the review."
            ),
        }
        prompt = str(config.get("prompt_override") or "").strip()
        if prompt:
            payload["prompt_override"] = prompt
        vote = llm.complete("grade_persona", payload)
        votes = list(state.get("votes") or [])
        votes.append(vote)
        return {"votes": votes}

    return node


def _debate(state: GradeState) -> GradeState:
    """If the council is far apart, each member reads the others and revises."""
    settings = debate_settings()
    votes = list(state.get("votes") or [])
    rounds: list[dict[str, Any]] = []
    if not settings["enabled"] or not needs_debate(votes, settings["threshold"]):
        return {"votes": votes, "debate_rounds": []}
    current = votes
    for number in range(1, settings["max_rounds"] + 1):
        if not needs_debate(current, settings["threshold"]):
            break
        revised = []
        for vote in current:
            peers = [peer for peer in current if peer.get("persona") != vote.get("persona")]
            config = (state.get("persona_config") or {}).get(vote.get("persona")) or {}
            payload: dict[str, Any] = {
                "persona": vote.get("persona"),
                "round": number,
                "previous": {
                    "level": vote.get("level"),
                    "quotes": vote.get("quotes"),
                    "reasoning": vote.get("reasoning"),
                },
                "peers": [
                    {
                        "persona": peer.get("persona"),
                        "level": peer.get("level"),
                        "quotes": peer.get("quotes"),
                        "reasoning": peer.get("reasoning"),
                    }
                    for peer in peers
                ],
                "submission": state.get("submission") or "",
                "criterion": state.get("criterion") or {},
                "outline": state.get("outline") or {},
                "clos": state.get("clos") or [],
                "dossier": state.get("dossier") or {},
            }
            prompt = str(config.get("prompt_override") or "").strip()
            if prompt:
                payload["prompt_override"] = prompt
            model = str(config.get("model") or "").strip()
            if model:
                payload["model"] = model
            try:
                revised.append(llm.complete("grade_revise", payload))
            except ProfassistError as exc:
                if exc.status != 429:
                    raise
                # The three votes already exist. A busy model should not throw them away.
                return {"votes": votes, "debate_rounds": rounds}
        current = revised
        rounds.append({"round": number, "votes": revised})
    return {"votes": current, "debate_rounds": rounds}


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
    try:
        written = llm.complete(
            "feedback",
            {
                "quote": quote,
                "level": judge.get("level"),
                "soul": state.get("soul") or "",
                "criterion": state.get("criterion") or {},
            },
        )
    except ProfassistError as exc:
        if exc.status != 429:
            raise
        return {"feedback": ""}
    return {"feedback": written.get("feedback") or ""}


def grading_personas(personas: list[str] | None = None) -> list[str]:
    """The enabled persona keys, in the council's order, without duplicates."""
    source = PERSONAS if personas is None else personas
    keys: list[str] = []
    for persona in source:
        name = str(persona or "").strip()
        if name in PERSONAS and name not in keys:
            keys.append(name)
    return keys


def build_grading_graph(
    personas: list[str] | None = None,
    persona_config: dict[str, dict[str, Any]] | None = None,
):
    keys = grading_personas(personas)
    if not keys:
        raise ProfassistError(400, "Enable at least one grading persona in Council Settings.")
    graph = StateGraph(GradeState)
    for index, persona in enumerate(keys):
        graph.add_node(persona, _grade_persona(persona, index))
    graph.add_node("debate", _debate)
    graph.add_node("judge", _judge)
    graph.add_node("feedback", _feedback)
    graph.set_entry_point(keys[0])
    for current, following in itertools.pairwise(keys):
        graph.add_edge(current, following)
    graph.add_edge(keys[-1], "debate")
    graph.add_edge("debate", "judge")
    graph.add_edge("judge", "feedback")
    graph.add_edge("feedback", END)
    return graph.compile()


def run_grading_council(
    submission: str,
    criterion: dict[str, Any],
    soul: str,
    *,
    title: str = "assignment",
    peer_reviews: list[dict[str, Any]] | None = None,
    outline: dict[str, Any] | None = None,
    clos: list[str] | None = None,
    dossier: dict[str, Any] | None = None,
    personas: list[str] | None = None,
    persona_config: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    keys = grading_personas(personas)
    result, url = invoke_graph(
        build_grading_graph(keys, persona_config),
        {
            "submission": submission,
            "criterion": criterion,
            "outline": outline or {},
            "clos": clos or [],
            "dossier": dossier or {},
            "soul": soul,
            "votes": [],
            "peer_reviews": peer_reviews or [],
            "personas": keys,
            "persona_config": persona_config or {},
        },
        name=f"grade: {title} / {criterion.get('name') or 'criterion'}",
        metadata={"kind": "grade", "criterion": criterion.get("name")},
    )
    return {
        "votes": result.get("votes") or [],
        "debate_rounds": result.get("debate_rounds") or [],
        "judge": result.get("judge") or {},
        "feedback": result.get("feedback") or "",
        "trace_url": url,
    }


def run_reflection(proposal: str, professor: dict[str, Any] | None = None) -> str:
    """A short graph: one reflection node that rewrites the portrait."""

    class ReflectState(TypedDict, total=False):
        proposal: str
        professor: dict[str, Any]
        text: str

    def node(state: ReflectState) -> ReflectState:
        written = llm.complete(
            "reflection",
            {
                "proposal": state.get("proposal") or "",
                "professor": state.get("professor") or {},
            },
        )
        return {"text": written.get("proposal") or state.get("proposal") or ""}

    graph = StateGraph(ReflectState)
    graph.add_node("reflect", node)
    graph.set_entry_point("reflect")
    graph.add_edge("reflect", END)
    result, _url = invoke_graph(
        graph.compile(),
        {"proposal": proposal, "professor": professor or {}},
        name="reflection",
        metadata={"kind": "reflection"},
    )
    return result.get("text") or proposal


class BriefingState(TypedDict, total=False):
    facts: dict[str, Any]
    result: dict[str, Any]


def run_briefing(facts: dict[str, Any]) -> dict[str, Any]:
    """A one-node graph: the chief-of-staff briefing from the supplied facts."""

    def node(state: BriefingState) -> BriefingState:
        written = llm.complete("briefing", {"facts": state.get("facts") or {}})
        return {"result": written}

    graph = StateGraph(BriefingState)
    graph.add_node("brief", node)
    graph.set_entry_point("brief")
    graph.add_edge("brief", END)
    result, url = invoke_graph(
        graph.compile(),
        {"facts": facts},
        name="briefing",
        metadata={"kind": "briefing"},
    )
    drafted = result.get("result") or {}
    if not isinstance(drafted, dict):
        drafted = {}
    bullets = drafted.get("bullets")
    return {
        "headline": str(drafted.get("headline") or ""),
        "bullets": bullets if isinstance(bullets, list) else [],
        "focus": str(drafted.get("focus") or ""),
        "trace_url": url,
    }


FILENAME = re.compile(r"[A-Za-z0-9_.-]+\.(?:pdf|docx|pptx|potx|txt|md|html?)\b", re.IGNORECASE)
MAX_BULLETS = 3
MAX_BULLET_CHARS = 220
MAX_REVIEW_ISSUES = 12
WEEK_GAP_CAP = 2
MAX_STRENGTHS = 6
REVIEW_ROLES = ("curriculum", "evidence", "design")
CODE_REVIEWERS = {
    "missing_title": "design",
    "no_bullets": "design",
    "too_many_bullets": "design",
    "long_bullet": "design",
    "duplicate_title": "design",
    "missing_citation": "evidence",
    "unverified_quote": "evidence",
    "gap": "evidence",
    "uncovered_week": "curriculum",
    "uncovered_outcome": "curriculum",
    "missing_objective": "curriculum",
}


class SlideReviewState(TypedDict, total=False):
    deck: dict[str, Any]
    outline: dict[str, Any]
    dossier: dict[str, Any]
    preferences: list[str]
    chunks: list[dict[str, Any]]
    council_roles: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    gaps: list[str]
    role_issues: list[dict[str, Any]]
    drafted: dict[str, Any]
    issues: list[dict[str, Any]]
    strengths: list[str]
    verdict: str
    score: int
    messages: list[dict[str, str]]
    roles: list[str]
    degraded: bool


def _issue(
    slide: Any,
    severity: str,
    issue: str,
    fix: str,
    code: str = "",
    reviewer: str = "",
) -> dict[str, Any]:
    item = {"slide": slide, "severity": severity, "issue": issue, "fix": fix, "code": code}
    if reviewer:
        item["reviewer"] = reviewer
    return item


def _bullet_text(bullet: Any) -> str:
    if isinstance(bullet, dict):
        return " ".join(str(bullet.get("text") or "").split())
    return " ".join(str(bullet or "").split())


def _has_citation(bullet: Any) -> bool:
    """A structured citation, or a source filename written on the slide."""
    if isinstance(bullet, dict):
        citation = bullet.get("citation")
        if isinstance(citation, dict) and (citation.get("filename") or citation.get("quote")):
            return True
        return bool(FILENAME.search(str(bullet.get("text") or "")))
    return bool(FILENAME.search(str(bullet or "")))


def _label(slide: dict[str, Any], index: int) -> str:
    title = str(slide.get("title") or "").strip()
    return title or f"Slide {index + 1}"


def _deck_gaps(deck: dict[str, Any]) -> list[str]:
    """Objectives the notes could not support, from the build or the slides."""
    gaps = [str(item).strip() for item in deck.get("gaps") or [] if str(item).strip()]
    for slide in deck.get("slides") or []:
        if not isinstance(slide, dict) or not slide.get("gap"):
            continue
        objective = str(slide.get("objective") or slide.get("title") or "").strip()
        if objective and objective not in gaps:
            gaps.append(objective)
    return gaps


def _week_issues(slides: list[dict[str, Any]], outline: dict[str, Any]) -> list[dict[str, Any]]:
    """Outline weeks no slide title or objective mentions. Capped, and only advice."""
    weeks = [week for week in outline.get("weeks") or [] if isinstance(week, dict)]
    if not weeks:
        return []
    covered = " ".join(
        str(value or "")
        for slide in slides
        for value in (slide.get("title"), slide.get("objective"))
    ).casefold()
    issues: list[dict[str, Any]] = []
    for week in weeks:
        topic = str(week.get("topic") or "").strip()
        try:
            number = int(week.get("week") or 0)
        except (TypeError, ValueError):
            number = 0
        if number <= 0 and not topic:
            continue
        if number > 0 and f"week {number}" in covered:
            continue
        words = [word for word in re.findall(r"[A-Za-z][A-Za-z'-]+", topic) if len(word) > 4]
        if words and any(word.casefold() in covered for word in words):
            continue
        issues.append(
            _issue(
                "Outline",
                "info",
                f"Week {number or '?'} ({topic or 'no topic'}) has no matching slide.",
                "Add a slide for that week, or say that the notes do not cover it.",
                "uncovered_week",
                reviewer="curriculum",
            )
        )
        if len(issues) >= WEEK_GAP_CAP:
            break
    return issues


def _outcome_issues(slides: list[dict[str, Any]], outline: dict[str, Any]) -> list[dict[str, Any]]:
    """Course outcomes that no slide title or objective mentions."""
    clos = [item for item in outline.get("clos") or [] if isinstance(item, dict)]
    if not clos:
        return []
    covered = " ".join(
        str(value or "")
        for slide in slides
        for value in (slide.get("title"), slide.get("objective"))
    ).casefold()
    issues: list[dict[str, Any]] = []
    for clo in clos:
        code = str(clo.get("code") or "").strip()
        text = str(clo.get("text") or "").strip()
        if not code and not text:
            continue
        if code and code.casefold() in covered:
            continue
        words = [word for word in re.findall(r"[A-Za-z][A-Za-z'-]+", text) if len(word) > 4]
        if words and any(word.casefold() in covered for word in words):
            continue
        label = code or text
        issues.append(
            _issue(
                "Outline",
                "info",
                f"{label} ({text or 'no text'}) has no matching slide.",
                "Add a slide for that outcome, or say that the notes do not cover it.",
                "uncovered_outcome",
                reviewer="curriculum",
            )
        )
    return issues


def _objective_issues(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """No slide names the objective it serves."""
    if not slides:
        return []
    if any(str(slide.get("objective") or "").strip() for slide in slides):
        return []
    return [
        _issue(
            "Deck",
            "info",
            "The deck does not name the objective each slide serves.",
            "Add the course outcome or objective that each slide supports.",
            "missing_objective",
            reviewer="curriculum",
        )
    ]


def _quote_issues(
    slides: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """A cited quote that does not appear in the supplied notes, whitespace aside."""
    if not chunks:
        return []
    blob = " ".join(
        " ".join(str(chunk.get("text") or "").split())
        for chunk in chunks
        if isinstance(chunk, dict)
    ).casefold()
    if not blob:
        return []
    issues: list[dict[str, Any]] = []
    for index, slide in enumerate(slides):
        label = _label(slide, index)
        for bullet in slide.get("bullets") or []:
            if not isinstance(bullet, dict):
                continue
            citation = bullet.get("citation")
            if not isinstance(citation, dict):
                continue
            quote = " ".join(str(citation.get("quote") or "").split()).casefold()
            if not quote or quote in blob:
                continue
            text = _bullet_text(bullet)
            issues.append(
                _issue(
                    label,
                    "medium",
                    f'The cited passage for "{text[:80]}" is not in the supplied notes.',
                    "Cite a passage that appears in the supplied notes, or remove the claim.",
                    "unverified_quote",
                    reviewer="evidence",
                )
            )
    return issues


def slide_checks(
    deck: dict[str, Any],
    outline: dict[str, Any] | None = None,
    chunks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic defects. Each issue names a slide and a concrete fix."""
    slides = [slide for slide in deck.get("slides") or [] if isinstance(slide, dict)]
    issues: list[dict[str, Any]] = []
    titles: dict[str, list[str]] = {}
    for index, slide in enumerate(slides):
        label = _label(slide, index)
        title = str(slide.get("title") or "").strip()
        raw_bullets = [bullet for bullet in slide.get("bullets") or [] if _bullet_text(bullet)]
        if not title:
            issues.append(
                _issue(
                    label,
                    "high",
                    "The slide has no title.",
                    "Name the one idea of the slide.",
                    "missing_title",
                    reviewer="design",
                )
            )
        else:
            key = " ".join(title.casefold().split())
            titles.setdefault(key, []).append(title)
        if not raw_bullets:
            issues.append(
                _issue(
                    label,
                    "high",
                    "The slide has no bullets.",
                    "Add one to three bullets, each citing a note.",
                    "no_bullets",
                    reviewer="design",
                )
            )
        for bullet in raw_bullets:
            text = _bullet_text(bullet)
            if not _has_citation(bullet):
                issues.append(
                    _issue(
                        label,
                        "medium",
                        f'The bullet "{text[:80]}" has no citation.',
                        "Cite the source filename for this bullet, or remove the claim.",
                        "missing_citation",
                        reviewer="evidence",
                    )
                )
        if len(raw_bullets) > MAX_BULLETS:
            issues.append(
                _issue(
                    label,
                    "low",
                    f"The slide has {len(raw_bullets)} bullets; three is the most a reader keeps.",
                    "Move the extra bullets to the speaker notes.",
                    "too_many_bullets",
                    reviewer="design",
                )
            )
        long_bullet = next(
            (
                text
                for text in (_bullet_text(bullet) for bullet in raw_bullets)
                if len(text) > MAX_BULLET_CHARS
            ),
            "",
        )
        if long_bullet:
            issues.append(
                _issue(
                    label,
                    "low",
                    f"A bullet runs to {len(long_bullet)} characters.",
                    f"Cut it to one sentence of {MAX_BULLET_CHARS} characters or fewer.",
                    "long_bullet",
                    reviewer="design",
                )
            )
    for shared in titles.values():
        if len(shared) < 2:
            continue
        issues.append(
            _issue(
                "Deck",
                "medium",
                f'{len(shared)} slides share the title "{shared[0]}".',
                "Give each slide a distinct title.",
                "duplicate_title",
                reviewer="design",
            )
        )
    for gap in _deck_gaps(deck):
        slide = next(
            (
                _label(item, position)
                for position, item in enumerate(slides)
                if str(item.get("objective") or item.get("title") or "").strip() == gap
            ),
            "Deck",
        )
        issues.append(
            _issue(
                slide,
                "high",
                f"No source passage covers: {gap.rstrip('.')}.",
                "Upload a note that covers it, or say on the slide that the notes do not.",
                "gap",
                reviewer="evidence",
            )
        )
    issues.extend(_week_issues(slides, outline or {}))
    issues.extend(_outcome_issues(slides, outline or {}))
    issues.extend(_objective_issues(slides))
    issues.extend(_quote_issues(slides, chunks or []))
    return issues


def review_score(issues: list[dict[str, Any]]) -> int:
    """100 minus the weighted defects. An info note costs nothing."""
    penalty = {"high": 20, "medium": 10, "low": 3}
    lost = sum(penalty.get(str(item.get("severity") or "").lower(), 0) for item in issues)
    return max(0, 100 - lost)


def _reviewer_of(issue: dict[str, Any]) -> str:
    reviewer = str(issue.get("reviewer") or "").strip().lower()
    if reviewer:
        return reviewer
    return CODE_REVIEWERS.get(str(issue.get("code") or ""), "")


def _reviewer_text(reviewer: str, issues: list[dict[str, Any]]) -> str:
    found = [
        " ".join(str(item.get("issue") or "").split())
        for item in issues
        if isinstance(item, dict) and _reviewer_of(item) == reviewer
    ]
    found = [text for text in found if text]
    if not found:
        return "No issues from my pass."
    return f"{reviewer.capitalize()} pass: " + "; ".join(found[:3]) + "."


def _strictest(issues: list[dict[str, Any]], limit: int = 3) -> list[str]:
    rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    ordered = sorted(
        (item for item in issues if isinstance(item, dict)),
        key=lambda item: rank.get(str(item.get("severity") or "").lower(), 4),
    )
    return [
        " ".join(str(item.get("issue") or "").split())
        for item in ordered
        if str(item.get("issue") or "").strip()
    ][:limit]


def _chair_text(verdict: str, score: int, issues: list[dict[str, Any]]) -> str:
    message = f"The council verdict is {verdict} with a score of {score}."
    strictest = _strictest(issues)
    if not strictest:
        return message + " No issues were raised."
    return message + " The strictest issues: " + "; ".join(strictest) + "."


def build_review_messages(
    issues: list[dict[str, Any]],
    verdict: str,
    score: int,
    roles: list[str] | None = None,
) -> list[dict[str, str]]:
    """One message per reviewer pass, then the chair, in the council's order."""
    reviewers = [role for role in (roles or list(REVIEW_ROLES)) if role != "chair"]
    messages = [
        {"role": reviewer, "text": _reviewer_text(reviewer, issues)} for reviewer in reviewers
    ]
    messages.append({"role": "chair", "text": _chair_text(verdict, score, issues)})
    return messages


def _stored_messages(review: dict[str, Any]) -> list[dict[str, str]] | None:
    """Replay a saved transcript when it is a real one, whatever its roles."""
    stored = review.get("messages")
    if not isinstance(stored, list) or not stored:
        return None
    cleaned: list[dict[str, str]] = []
    for item in stored:
        if not isinstance(item, dict):
            return None
        role = str(item.get("role") or "").strip().lower()
        if not role or not isinstance(item.get("text"), str):
            return None
        cleaned.append({"role": role, "text": " ".join(item["text"].split())})
    if cleaned[-1]["role"] != "chair":
        return None
    if sum(1 for item in cleaned if item["role"] == "chair") != 1:
        return None
    return cleaned


def review_messages(review: dict[str, Any] | None) -> list[dict[str, str]]:
    """The council messages for a review, or a synthesis for an older one.

    A saved transcript keeps its custom roles. A review without one is rebuilt
    from its ``roles`` list, and an older review falls back to the legacy three
    reviewers and the chair.
    """
    source = review if isinstance(review, dict) else {}
    stored = _stored_messages(source)
    if stored is not None:
        return stored
    issues = [item for item in source.get("issues") or [] if isinstance(item, dict)]
    verdict = str(source.get("verdict") or "revise")
    try:
        score = int(source.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    roles = [str(role) for role in source.get("roles") or [] if str(role).strip()]
    return build_review_messages(issues, verdict, score, roles=roles or None)


def _normalise_issue(raw: Any) -> dict[str, Any] | None:
    """One issue from either the checks or the model, in the same shape."""
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("issue") or raw.get("message") or "").strip()
    if not text:
        return None
    severity = str(raw.get("severity") or "").strip().lower()
    if severity not in {"high", "medium", "low", "info"}:
        severity = "medium"
    slide = raw.get("slide")
    label = slide if isinstance(slide, int) else str(slide or "").strip()
    if not isinstance(label, int) and not label:
        label = "Deck"
    item = {
        "slide": label,
        "severity": severity,
        "issue": text,
        "fix": str(raw.get("fix") or "").strip(),
    }
    code = str(raw.get("code") or "").strip()
    if code:
        item["code"] = code
    reviewer = str(raw.get("reviewer") or "").strip().lower()
    if not reviewer:
        reviewer = CODE_REVIEWERS.get(code, "")
    if reviewer:
        item["reviewer"] = reviewer
    return item


def _material_roles(council_roles: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if council_roles:
        return [role for role in council_roles if isinstance(role, dict)]
    return default_roles("material")


def _deterministic_findings(
    checks: list[dict[str, Any]], roles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Only an enabled reviewer's findings reach the score."""
    enabled = set(enabled_keys(roles, "deterministic"))
    if not enabled:
        return []
    kept: list[dict[str, Any]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        reviewer = _reviewer_of(item)
        if reviewer and reviewer not in enabled:
            continue
        kept.append(item)
    return kept


def _role_issue(raw: Any, role_key: str) -> dict[str, Any] | None:
    item = _normalise_issue(raw)
    if item is None:
        return None
    item["reviewer"] = role_key
    item.setdefault("code", f"role_{role_key}")
    return item


def _custom_role_findings(
    roles: list[dict[str, Any]], payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Run an admin-added llm reviewer. A failure simply adds no finding."""
    findings: list[dict[str, Any]] = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        if role.get("kind") != "llm" or not role.get("custom") or not role.get("enabled"):
            continue
        role_key = str(role.get("role_key") or "").strip()
        prompt = str(role.get("persona_prompt") or "").strip()
        if not role_key or not prompt:
            continue
        request = {
            **payload,
            "reviewer": role_key,
            "role": str(role.get("label") or role_key),
            "prompt_override": prompt,
        }
        if role.get("model"):
            request["model"] = str(role["model"])
        try:
            reply = llm.complete("council_review", request)
        except Exception as exc:
            logger.info("Custom reviewer %s failed: %s", role_key, exc)
            continue
        raw = reply.get("issues") if isinstance(reply, dict) else None
        for item in raw or []:
            issue = _role_issue(item, role_key)
            if issue is not None:
                findings.append(issue)
        if len(findings) >= MAX_REVIEW_ISSUES:
            break
    return findings[:MAX_REVIEW_ISSUES]


def _chair_request(roles: list[dict[str, Any]]) -> dict[str, Any]:
    """The chair's prompt and model override, when the chair is enabled."""
    chair = chair_of(roles)
    if chair is None:
        return {}
    request: dict[str, Any] = {}
    prompt = str(chair.get("persona_prompt") or "").strip()
    if prompt:
        request["prompt_override"] = prompt
    model = str(chair.get("model") or "").strip()
    if model:
        request["model"] = model
    return request


def _check_slide_deck(state: SlideReviewState) -> SlideReviewState:
    roles = _material_roles(state.get("council_roles"))
    deck = state.get("deck") or {}
    checks = slide_checks(deck, state.get("outline") or {}, state.get("chunks") or [])
    gaps = _deck_gaps(deck) if "evidence" in enabled_keys(roles, "deterministic") else []
    return {
        "checks": _deterministic_findings(checks, roles),
        "gaps": gaps,
        "council_roles": roles,
    }


def _review_slide_deck(state: SlideReviewState) -> SlideReviewState:
    """Ask the custom reviewers and the chair. A failure leaves the checks standing."""
    roles = _material_roles(state.get("council_roles"))
    payload = {
        "deck": state.get("deck") or {},
        "checks": state.get("checks") or [],
        "outline": state.get("outline") or {},
        "dossier": state.get("dossier") or {},
        "preferences": list(state.get("preferences") or []),
    }
    role_issues = _custom_role_findings(roles, payload)
    if chair_of(roles) is None:
        return {"drafted": {}, "role_issues": role_issues, "degraded": False}
    try:
        drafted = llm.complete("slide_review", {**payload, **_chair_request(roles)})
    except Exception as exc:
        logger.info("Slide review fell back to the deterministic checks: %s", exc)
        return {"drafted": {}, "role_issues": role_issues, "degraded": True}
    if not isinstance(drafted, dict):
        return {"drafted": {}, "role_issues": role_issues, "degraded": True}
    return {"drafted": drafted, "role_issues": role_issues, "degraded": False}


def _merge_slide_review(state: SlideReviewState) -> SlideReviewState:
    """Deterministic findings first, then custom reviewers, then the chair's view."""
    drafted = state.get("drafted") or {}
    roles = _material_roles(state.get("council_roles"))
    role_keys = message_roles(roles)
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in [
        *(state.get("checks") or []),
        *(state.get("role_issues") or []),
        *(drafted.get("issues") or []),
    ]:
        item = _normalise_issue(raw)
        if item is None:
            continue
        key = (str(item["slide"]), str(item["issue"]).strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= MAX_REVIEW_ISSUES:
            break
    score = review_score(merged)
    high = any(item["severity"] == "high" for item in merged)
    verdict = "revise" if high or score < 70 or state.get("gaps") else "pass"
    strengths = [
        str(item).strip()
        for item in drafted.get("strengths") or []
        if isinstance(item, str) and item.strip()
    ]
    return {
        "issues": merged,
        "score": score,
        "verdict": verdict,
        "strengths": strengths[:MAX_STRENGTHS],
        "messages": build_review_messages(merged, verdict, score, roles=role_keys),
        "roles": role_keys,
    }


def build_slide_review_graph():
    graph = StateGraph(SlideReviewState)
    graph.add_node("check", _check_slide_deck)
    graph.add_node("review", _review_slide_deck)
    graph.add_node("merge", _merge_slide_review)
    graph.set_entry_point("check")
    graph.add_edge("check", "review")
    graph.add_edge("review", "merge")
    graph.add_edge("merge", END)
    return graph.compile()


def run_slide_review(
    deck: dict[str, Any],
    outline: dict[str, Any] | None = None,
    dossier: dict[str, Any] | None = None,
    preferences: list[str] | None = None,
    chunks: list[dict[str, Any]] | None = None,
    council_roles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check, review, merge. The deck itself is never rewritten here."""
    title = str((deck or {}).get("title") or "deck")[:120]
    roles = _material_roles(council_roles)
    result, url = invoke_graph(
        build_slide_review_graph(),
        {
            "deck": deck or {},
            "outline": outline or {},
            "dossier": dossier or {},
            "preferences": [str(item) for item in preferences or [] if str(item).strip()],
            "chunks": [chunk for chunk in chunks or [] if isinstance(chunk, dict)],
            "council_roles": roles,
        },
        name=f"slide-review: {title}",
        metadata={"kind": "slide_review"},
    )
    return {
        "verdict": str(result.get("verdict") or "revise"),
        "score": int(result.get("score") or 0),
        "issues": result.get("issues") or [],
        "strengths": result.get("strengths") or [],
        "checks": result.get("checks") or [],
        "messages": review_messages(result),
        "roles": result.get("roles") or message_roles(roles),
        "trace_url": url or "",
        "degraded": bool(result.get("degraded")),
    }
