"""Assignment council: alignment, brief, and rubric reviewers, then a chair.

Each enabled reviewer and the deterministic checks are evidence for the chair.
The chair may summarise them and set a tone, but it never invents a gap. A clean
assignment comes back clean.
"""

import logging
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.profassist import agents, llm
from app.profassist.assignment_data import REPORT_SECTIONS
from app.profassist.council_config import chair_of, default_roles, enabled_keys, message_roles
from app.profassist.observe import invoke_graph, step_trace_url

logger = logging.getLogger(__name__)

LEVELS = ("beginning", "developing", "proficient", "advanced")
REVIEW_ROLES = ("alignment", "brief", "rubric")
MAX_COUNCIL_ISSUES = agents.MAX_REVIEW_ISSUES
MAX_STRENGTHS = agents.MAX_STRENGTHS


class AssignmentCouncilState(TypedDict, total=False):
    document: dict[str, Any]
    rubric: list[dict[str, Any]]
    outcomes: list[str]
    outline: dict[str, Any]
    dossier: dict[str, Any]
    council_roles: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    role_issues: list[dict[str, Any]]
    drafted: dict[str, Any]
    degraded: bool
    issues: list[dict[str, Any]]
    verdict: str
    score: int
    summary: str
    strengths: list[str]
    messages: list[dict[str, str]]
    roles: list[str]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    digits = re.findall(r"\d+", str(value))
    return int(digits[0]) if digits else default


def _issue(reviewer: str, severity: str, issue: str, fix: str, code: str) -> dict[str, Any]:
    return {
        "reviewer": reviewer,
        "severity": severity,
        "issue": issue,
        "fix": fix,
        "code": code,
    }


def _mapped_codes(outline: dict[str, Any]) -> set[str]:
    """CLO codes the outline's assessment map says are assessed."""
    mapped: set[str] = set()
    for row in outline.get("outcome_measures") or []:
        if isinstance(row, dict):
            code = _text(row.get("lo_code"))
            if code:
                mapped.add(code)
    for task in outline.get("assessment_tasks") or []:
        if isinstance(task, dict):
            for code in task.get("lo_codes") or []:
                if _text(code):
                    mapped.add(_text(code))
    return mapped


def _alignment_checks(
    document: dict[str, Any], outcomes: list[str], outline: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    raw_details = document.get("class_details")
    details = raw_details if isinstance(raw_details, dict) else {}
    clos = [item for item in outline.get("clos") or [] if isinstance(item, dict)]
    if not clos and not outcomes:
        issues.append(
            _issue(
                "alignment",
                "high",
                "The assignment is not tied to any course learning outcome.",
                "Link the assessment to at least one CLO.",
                "no_outcomes",
            )
        )

    if not outline:
        issues.append(
            _issue(
                "alignment",
                "medium",
                "No official course outline is available to align the assessment to.",
                "Attach or draft the course outline, then review the alignment.",
                "missing_outline",
            )
        )
    else:
        mapped = _mapped_codes(outline)
        has_map = bool(mapped) or any(
            _text((row or {}).get("measures"))
            for row in outline.get("outcome_measures") or []
            if isinstance(row, dict)
        )
        if not has_map:
            issues.append(
                _issue(
                    "alignment",
                    "medium",
                    "The outline has no assessment map.",
                    "Map each CLO to the assessment that measures it.",
                    "missing_assessment_map",
                )
            )
        elif clos:
            for clo in clos:
                code = _text(clo.get("code"))
                if code and code not in mapped:
                    issues.append(
                        _issue(
                            "alignment",
                            "high",
                            f"{code} is not assessed by any task in the outline.",
                            "Add the outcome to an assessment in the outline's map.",
                            "unassessed_outcome",
                        )
                    )

    raw_weight = _text(details.get("weight"))
    if raw_weight and re.search(r"\d", raw_weight) and _number(raw_weight) == 0:
        issues.append(
            _issue(
                "alignment",
                "high",
                "The assessment carries a numeric weight of 0.",
                "Give the assessment a non-zero weight, or make it formative.",
                "zero_weight",
            )
        )
    return issues


def _brief_checks(document: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    raw_details = document.get("class_details")
    details = raw_details if isinstance(raw_details, dict) else {}
    for key, label in (
        ("overview", "overview"),
        ("problem_choices", "problem choices"),
        ("deliverables", "deliverables"),
    ):
        if not document.get(key):
            issues.append(
                _issue(
                    "brief",
                    "high",
                    f"The brief has no {label}.",
                    f"Write the {label} before the assignment is finished.",
                    f"empty_{key}",
                )
            )

    sections = [item for item in document.get("report_sections") or [] if isinstance(item, dict)]
    present = {_text(item.get("number")) for item in sections}
    missing = [
        template["number"] for template in REPORT_SECTIONS if template["number"] not in present
    ]
    if missing:
        issues.append(
            _issue(
                "brief",
                "high",
                f"The brief is missing {len(missing)} report section(s): {', '.join(missing)}.",
                "Use the eleven-section template so the report is complete.",
                "missing_report_sections",
            )
        )

    assessment = _text(details.get("assessment"))
    if not assessment or assessment.casefold() == "new assignment":
        issues.append(
            _issue(
                "brief",
                "high",
                "The assessment has no name.",
                "Name the assessment in the class details.",
                "unnamed_assessment",
            )
        )
    if not _text(details.get("weight")):
        issues.append(
            _issue(
                "brief",
                "medium",
                "The brief does not state the assessment weight.",
                "Add the weight to the class details.",
                "missing_weight",
            )
        )
    if not _text(details.get("report_due")):
        issues.append(
            _issue(
                "brief",
                "medium",
                "The brief does not state when the report is due.",
                "Add the due week or date to the class details.",
                "missing_due",
            )
        )
    return issues


def _rubric_checks(rubric: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not rubric:
        return [
            _issue(
                "rubric",
                "high",
                "The rubric has no criteria.",
                "Add at least one criterion whose weight totals 100.",
                "no_criteria",
            )
        ]

    total = sum(_number(item.get("weight")) for item in rubric if isinstance(item, dict))
    if total != 100:
        issues.append(
            _issue(
                "rubric",
                "high",
                f"Rubric weights total {total}, not 100.",
                "Adjust the criterion weights so they total 100.",
                "rubric_total",
            )
        )

    names: dict[str, str] = {}
    duplicates: list[str] = []
    for item in rubric:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if not name:
            continue
        key = name.casefold()
        if key in names and name not in duplicates:
            duplicates.append(name)
        names.setdefault(key, name)
        raw_levels = item.get("levels")
        if isinstance(raw_levels, dict):
            levels = raw_levels
        else:
            levels = {level: item.get(level) for level in LEVELS}
        for level in LEVELS:
            if not _text(levels.get(level)):
                issues.append(
                    _issue(
                        "rubric",
                        "medium",
                        f'The criterion "{name}" is missing the {level} level.',
                        f"Describe what {level} work looks like for this criterion.",
                        "missing_level",
                    )
                )
    for name in duplicates:
        issues.append(
            _issue(
                "rubric",
                "medium",
                f'More than one criterion is named "{name}".',
                "Give each criterion a distinct name.",
                "duplicate_criterion",
            )
        )
    return issues


def assignment_checks(
    document: dict[str, Any] | None,
    rubric: list[dict[str, Any]] | None,
    outcomes: list[str] | None,
    outline: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Deterministic findings, each tagged with the reviewer who owns it."""
    document = document if isinstance(document, dict) else {}
    rubric = [item for item in rubric or [] if isinstance(item, dict)]
    outcome_texts = [_text(item) for item in outcomes or [] if _text(item)]
    outline = outline if isinstance(outline, dict) else {}
    return [
        *_alignment_checks(document, outcome_texts, outline),
        *_brief_checks(document),
        *_rubric_checks(rubric),
    ]


def _reviewer_text(reviewer: str, issues: list[dict[str, Any]]) -> str:
    found = [
        " ".join(_text(item.get("issue")).split())
        for item in issues
        if isinstance(item, dict) and item.get("reviewer") == reviewer
    ]
    found = [text for text in found if text]
    if not found:
        return "No issues from my pass."
    return f"{reviewer.capitalize()} pass: " + "; ".join(found[:3]) + "."


def _strictest(issues: list[dict[str, Any]], limit: int = 3) -> list[str]:
    rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    ordered = sorted(
        (item for item in issues if isinstance(item, dict)),
        key=lambda item: rank.get(_text(item.get("severity")).lower(), 4),
    )
    return [
        " ".join(_text(item.get("issue")).split()) for item in ordered if _text(item.get("issue"))
    ][:limit]


_CONTRADICTING_PHRASES = (
    "meets all requirements",
    "meet all requirements",
    "all requirements are met",
    "no issues",
    "nothing to change",
    "fully compliant",
    "ready to submit",
    "clean bill",
)
_REVISION_MARKERS = (
    "revise",
    "revision",
    "issue",
    "fix",
    "address",
    "missing",
    "gap",
    "incomplete",
    "insufficient",
    "needs",
    "should",
    "lacks",
    "clarify",
    "improve",
    "inconsistent",
    "unclear",
)


def _acknowledges_revision(summary: str) -> bool:
    """Whether a model summary fits a revise verdict instead of contradicting it."""
    text = " ".join(_text(summary).lower().split())
    if not text:
        return False
    if any(phrase in text for phrase in _CONTRADICTING_PHRASES):
        return False
    return any(marker in text for marker in _REVISION_MARKERS)


def _deterministic_summary(issues: list[dict[str, Any]]) -> str:
    """A summary derived only from the strictest findings, never the model prose."""
    strictest = _strictest(issues)
    if not strictest:
        return ""
    lead = f"The council found {len(issues)} issue(s)."
    return f"{lead} The strictest: {'; '.join(strictest)}."


def _chair_text(verdict: str, score: int, issues: list[dict[str, Any]], summary: str = "") -> str:
    message = f"The council verdict is {verdict} with a score of {score}."
    if summary:
        message += " " + " ".join(summary.split())
    strictest = _strictest(issues)
    if not strictest:
        return message + " No issues were raised."
    return message + " The strictest issues: " + "; ".join(strictest) + "."


def build_messages(
    issues: list[dict[str, Any]],
    verdict: str,
    score: int,
    summary: str = "",
    roles: list[str] | None = None,
) -> list[dict[str, str]]:
    reviewers = [role for role in (roles or list(REVIEW_ROLES)) if role != "chair"]
    messages = [
        {"role": reviewer, "text": _reviewer_text(reviewer, issues)} for reviewer in reviewers
    ]
    messages.append({"role": "chair", "text": _chair_text(verdict, score, issues, summary)})
    return messages


def _assignment_roles(council_roles: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if council_roles:
        return [role for role in council_roles if isinstance(role, dict)]
    return default_roles("assignment")


def _custom_role_issues(
    roles: list[dict[str, Any]], payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Every enabled llm reviewer with a prompt. Its findings sit beside the checks."""
    found: list[dict[str, Any]] = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        if role.get("kind") != "llm" or not role.get("enabled"):
            continue
        role_key = _text(role.get("role_key"))
        prompt = _text(role.get("persona_prompt"))
        if not role_key or not prompt:
            continue
        request = {
            **payload,
            "reviewer": role_key,
            "role": _text(role.get("label")) or role_key,
            "prompt_override": prompt,
        }
        if _text(role.get("model")):
            request["model"] = _text(role.get("model"))
        try:
            reply = llm.complete("council_review", request)
        except Exception as exc:
            logger.info("Assignment reviewer %s failed: %s", role_key, exc)
            continue
        raw = reply.get("issues") if isinstance(reply, dict) else None
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            message = _text(item.get("issue") or item.get("message"))
            if not message:
                continue
            severity = _text(item.get("severity")).lower()
            if severity not in {"high", "medium", "low", "info"}:
                severity = "medium"
            found.append(
                _issue(
                    role_key,
                    severity,
                    message,
                    _text(item.get("fix")),
                    _text(item.get("code")) or f"role_{role_key}",
                )
            )
        if len(found) >= MAX_COUNCIL_ISSUES:
            break
    return found[:MAX_COUNCIL_ISSUES]


def _check(state: AssignmentCouncilState) -> AssignmentCouncilState:
    roles = _assignment_roles(state.get("council_roles"))
    checks = assignment_checks(
        state.get("document") or {},
        state.get("rubric") or [],
        state.get("outcomes") or [],
        state.get("outline") or {},
    )
    enabled = set(enabled_keys(roles, "deterministic"))
    checks = [
        item for item in checks if not item.get("reviewer") or item.get("reviewer") in enabled
    ]
    return {"checks": checks, "council_roles": roles}


def _chair(state: AssignmentCouncilState) -> AssignmentCouncilState:
    roles = _assignment_roles(state.get("council_roles"))
    payload = {
        "document": state.get("document") or {},
        "rubric": state.get("rubric") or [],
        "outcomes": state.get("outcomes") or [],
        "outline": state.get("outline") or {},
        "dossier": state.get("dossier") or {},
        "checks": state.get("checks") or [],
    }
    role_issues = _custom_role_issues(roles, payload)
    chair = chair_of(roles)
    if chair is None:
        return {"drafted": {}, "role_issues": role_issues, "degraded": False}
    request: dict[str, Any] = dict(payload)
    if _text(chair.get("persona_prompt")):
        request["prompt_override"] = _text(chair.get("persona_prompt"))
    if _text(chair.get("model")):
        request["model"] = _text(chair.get("model"))
    try:
        drafted = llm.complete("assignment_review", request)
    except Exception as exc:
        logger.info("Assignment chair failed; the checks and reviewer issues stand: %s", exc)
        return {"drafted": {}, "role_issues": role_issues, "degraded": True}
    if not isinstance(drafted, dict):
        return {"drafted": {}, "role_issues": role_issues, "degraded": True}
    return {"drafted": drafted, "role_issues": role_issues, "degraded": False}


def _merge(state: AssignmentCouncilState) -> AssignmentCouncilState:
    drafted = state.get("drafted") or {}
    roles = _assignment_roles(state.get("council_roles"))
    role_keys = message_roles(roles)
    issues = [
        dict(item)
        for item in [*(state.get("checks") or []), *(state.get("role_issues") or [])]
        if isinstance(item, dict)
    ][:MAX_COUNCIL_ISSUES]
    score = agents.review_score(issues)
    high = any(_text(item.get("severity")).lower() == "high" for item in issues)
    verdict = "revise" if high or score < 70 else "pass"
    chair_verdict = _text(drafted.get("verdict")).lower()
    if verdict == "pass" and chair_verdict == "revise" and issues:
        verdict = "revise"
    model_summary = " ".join(_text(drafted.get("summary")).split())
    if issues and not _acknowledges_revision(model_summary):
        # A positive model summary beside real findings is a contradiction.
        summary = _deterministic_summary(issues)
        chair_summary = ""
    else:
        summary = model_summary
        chair_summary = model_summary
    strengths = [
        _text(item)
        for item in drafted.get("strengths") or []
        if isinstance(item, str) and _text(item)
    ][:MAX_STRENGTHS]
    return {
        "issues": issues,
        "score": score,
        "verdict": verdict,
        "summary": summary,
        "strengths": strengths,
        "messages": build_messages(issues, verdict, score, chair_summary, roles=role_keys),
        "roles": role_keys,
    }


def build_assignment_council_graph():
    graph = StateGraph(AssignmentCouncilState)
    graph.add_node("check", _check)
    graph.add_node("chair", _chair)
    graph.add_node("merge", _merge)
    graph.set_entry_point("check")
    graph.add_edge("check", "chair")
    graph.add_edge("chair", "merge")
    graph.add_edge("merge", END)
    return graph.compile()


def run_assignment_council(
    document: dict[str, Any] | None,
    rubric: list[dict[str, Any]] | None,
    outcomes: list[str] | None,
    outline: dict[str, Any] | None,
    dossier: dict[str, Any] | None = None,
    council_roles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check, chair, merge. The chair may summarise; it never adds a finding."""
    source = document if isinstance(document, dict) else {}
    details = source.get("class_details")
    details = details if isinstance(details, dict) else {}
    title = _text(details.get("assessment"))[:120]
    roles = _assignment_roles(council_roles)
    result, url = invoke_graph(
        build_assignment_council_graph(),
        {
            "document": document or {},
            "rubric": [item for item in rubric or [] if isinstance(item, dict)],
            "outcomes": [_text(item) for item in outcomes or [] if _text(item)],
            "outline": outline or {},
            "dossier": dossier or {},
            "council_roles": roles,
        },
        name=f"assignment-council: {title or 'assignment'}",
        metadata={"kind": "assignment_review"},
    )
    role_keys = result.get("roles") or message_roles(roles)
    return {
        "verdict": _text(result.get("verdict")) or "revise",
        "score": int(result.get("score") or 0),
        "issues": result.get("issues") or [],
        "role_issues": result.get("role_issues") or [],
        "summary": _text(result.get("summary")),
        "strengths": result.get("strengths") or [],
        "checks": result.get("checks") or [],
        "messages": result.get("messages") or build_messages([], "revise", 0, roles=role_keys),
        "roles": role_keys,
        "trace_url": url or step_trace_url() or "",
        "degraded": bool(result.get("degraded")),
    }
