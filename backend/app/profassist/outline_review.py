"""Pre-approval review of a subject outline. Findings name a real section."""

import json
import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.council_config import chair_of, enabled_keys, load_council_roles
from app.profassist.errors import ProfassistError
from app.profassist.models import OutlineReview
from app.profassist.outline import get_outline
from app.profassist.outline_data import POLICIES
from app.profassist.runtime import tool_enabled
from app.profassist.service import capture_movement

BLOOM = (
    "design",
    "implement",
    "evaluate",
    "apply",
    "assess",
    "analyse",
    "analyze",
    "create",
    "communicate",
    "formulate",
    "justify",
)
REVIEWERS = ("curriculum", "alignment", "balance", "student")
REQUIRED_POLICIES = ("academic_integrity", "attendance", "lecture_capture", "sustainability")


def review_outline(
    body: dict[str, Any], instructions: str = "", sources: list[str] | None = None
) -> list[dict[str, Any]]:
    """Deterministic checks. Each finding points at a section and an object id."""
    findings: list[dict[str, Any]] = []
    clos = body.get("clos") or []
    plos = {item.get("code") for item in body.get("plos") or []}
    tasks = body.get("tasks") or []
    weeks = body.get("weeks") or []
    assessed = {code for task in tasks for code in (task.get("lo_codes") or [])}
    clo_codes = {item.get("code") for item in clos}

    for item in clos:
        code = item.get("code") or ""
        mapped = [plo for plo in item.get("plos") or [] if plo in plos]
        if not mapped:
            findings.append(
                _finding(
                    "high",
                    "outcomes",
                    code,
                    "alignment",
                    f"{code} does not map to a program outcome.",
                    {"map_plo": next(iter(plos), "PLO1")},
                )
            )
        text = (item.get("text") or "").lower()
        if not any(verb in text.split() or verb in text for verb in BLOOM):
            findings.append(
                _finding(
                    "medium",
                    "outcomes",
                    code,
                    "curriculum",
                    f"{code} has no clear Bloom verb.",
                    {"prefix": "Evaluate"},
                )
            )
        if code and code not in assessed:
            findings.append(
                _finding(
                    "high",
                    "assessments",
                    code,
                    "balance",
                    f"{code} is not assessed by any task.",
                    {"add_to": (tasks[0].get("number") if tasks else "A1")},
                )
            )

    covered = {plo for item in clos for plo in item.get("plos") or []}
    for plo in sorted(plos - covered):
        findings.append(
            _finding(
                "medium",
                "outcomes",
                plo,
                "alignment",
                f"{plo} is not covered by any course outcome.",
                {"map_from": (clos[0].get("code") if clos else "LO1")},
            )
        )

    weight = sum(int(task.get("weight") or 0) for task in tasks)
    if tasks and weight != 100:
        findings.append(
            _finding(
                "high",
                "assessments",
                "weights",
                "balance",
                f"Assessment weights sum to {weight}, not 100.",
                {"target": 100},
            )
        )

    for week in weeks:
        unknown = [code for code in week.get("lo_codes") or [] if code not in clo_codes]
        if unknown:
            findings.append(
                _finding(
                    "medium",
                    "schedule",
                    f"week-{week.get('week')}",
                    "curriculum",
                    f"Week {week.get('week')} names {', '.join(unknown)}, which is not a course outcome.",
                    {"drop": unknown},
                )
            )

    for index, citation in enumerate(body.get("readings") or [], start=1):
        years = [int(year) for year in re.findall(r"\b(19|20)\d{2}\b", citation)]
        if years and max(years) < 2018:
            findings.append(
                _finding(
                    "low",
                    "readings",
                    f"reading-{index}",
                    "student",
                    f"Reading {index} is from {max(years)}. Consider a newer edition.",
                    {"note": "Check a newer edition."},
                    citation,
                )
            )

    present = {key: bool(body.get(key)) for key in REQUIRED_POLICIES}
    for key in REQUIRED_POLICIES:
        if not present[key]:
            title = next(item["title"] for item in POLICIES if item["key"] == key)
            findings.append(
                _finding(
                    "high",
                    "policies",
                    key,
                    "student",
                    f"The {title.lower()} section is missing.",
                    {"policy": key},
                )
            )

    blob = " ".join(
        [
            body.get("description") or "",
            " ".join(item.get("text") or "" for item in clos),
            " ".join(item.get("topic") or "" for item in weeks),
        ]
    ).lower()
    note = (instructions or "").strip()
    if (
        note
        and note.lower() not in blob
        and not any(word in blob for word in note.lower().split() if len(word) > 5)
    ):
        findings.append(
            _finding(
                "medium",
                "description",
                "instructions",
                "curriculum",
                "The outline does not yet follow the professor's instructions.",
                {"append": note},
                (sources or ["instructions"])[0],
            )
        )
    return findings


def score_of(findings: list[dict[str, Any]]) -> int:
    penalty = {"high": 15, "medium": 7, "low": 3}
    lost = sum(penalty.get(item.get("severity"), 0) for item in findings if not item.get("applied"))
    return max(0, 100 - lost)


def _finding(
    severity: str,
    section: str,
    object_id: str,
    reviewer: str,
    message: str,
    fix: dict[str, Any],
    citation: str = "",
) -> dict[str, Any]:
    return {
        "id": f"{section}:{object_id}",
        "severity": severity,
        "section": section,
        "object_id": object_id,
        "reviewer": reviewer,
        "message": message,
        "fix": fix,
        "applied": False,
        "citation": citation,
    }


def apply_fix(body: dict[str, Any], finding: dict[str, Any]) -> dict[str, Any]:
    """Apply one suggested fix. Unknown fixes leave the outline unchanged."""
    updated = dict(body)
    updated["clos"] = [dict(item) for item in body.get("clos") or []]
    updated["tasks"] = [dict(item) for item in body.get("tasks") or []]
    updated["weeks"] = [dict(item) for item in body.get("weeks") or []]
    updated["policies"] = list(body.get("policies") or [])
    fix = finding.get("fix") or {}
    if "map_plo" in fix:
        for item in updated["clos"]:
            if item.get("code") == finding.get("object_id"):
                item["plos"] = list(dict.fromkeys([*(item.get("plos") or []), fix["map_plo"]]))
    if "prefix" in fix:
        for item in updated["clos"]:
            if item.get("code") == finding.get("object_id") and not str(
                item.get("text") or ""
            ).lower().startswith("evaluate"):
                item["text"] = f"{fix['prefix']} {item.get('text') or ''}".strip()
    if "add_to" in fix:
        for task in updated["tasks"]:
            if task.get("number") == fix["add_to"]:
                task["lo_codes"] = list(
                    dict.fromkeys([*(task.get("lo_codes") or []), finding.get("object_id")])
                )
    if "target" in fix and updated["tasks"]:
        others = sum(int(task.get("weight") or 0) for task in updated["tasks"][:-1])
        updated["tasks"][-1]["weight"] = max(0, 100 - others)
    if "drop" in fix:
        week_no = str(finding.get("object_id") or "").replace("week-", "")
        for week in updated["weeks"]:
            if str(week.get("week")) == week_no:
                week["lo_codes"] = [
                    code for code in week.get("lo_codes") or [] if code not in fix["drop"]
                ]
    if "policy" in fix:
        policy = next(item for item in POLICIES if item["key"] == fix["policy"])
        updated[fix["policy"]] = policy["body"]
    if "append" in fix:
        updated["description"] = ((updated.get("description") or "") + "\n" + fix["append"]).strip()
    return updated


async def run_review(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    *,
    mode: str,
    reviewer: str,
) -> dict[str, Any]:
    from app.profassist.llm import complete
    from app.profassist.observe import step_trace_url

    row = await get_outline(db, org_id, user_id, outline_id)
    roles = await load_council_roles(db, org_id, "outline")
    enabled = [name for name in enabled_keys(roles, "deterministic") if name in REVIEWERS]
    chosen = [reviewer] if mode == "single" else list(enabled)
    chosen = [name for name in chosen if name in enabled]
    chosen = [name for name in chosen if tool_enabled("outline_review", name)]
    if not chosen:
        raise ProfassistError(
            400,
            "No outline reviewer is enabled. Turn one on in the council settings, then review.",
        )
    findings = [
        item
        for item in review_outline(row.body or {}, row.instructions or "")
        if item["reviewer"] in chosen
    ]
    debate = []
    if mode == "council" and tool_enabled("outline_review", "debate") and findings:
        debate.append(
            {
                "round": 1,
                "note": "Reviewers compared severities and kept the stricter reading where they disagreed.",
            }
        )
    chair = chair_of(roles)
    chair_request: dict[str, Any] = {}
    if chair is not None:
        if str(chair.get("persona_prompt") or "").strip():
            chair_request["prompt_override"] = str(chair["persona_prompt"]).strip()
        if str(chair.get("model") or "").strip():
            chair_request["model"] = str(chair["model"]).strip()
    summary = (
        complete(
            "outline_review",
            {
                "instructions": row.instructions or "",
                "mode": mode,
                "reviewer": reviewer,
                "findings": findings,
                **chair_request,
            },
        )
        if chair is not None
        else {}
    )
    version = (
        await db.execute(
            select(func.count())
            .select_from(OutlineReview)
            .where(OutlineReview.outline_id == row.id)
        )
    ).scalar_one()
    stored = OutlineReview(
        organization_id=org_id,
        owner_user_id=user_id,
        outline_id=row.id,
        course_id=row.course_id,
        version=int(version or 0) + 1,
        mode=mode,
        reviewer=reviewer if mode == "single" else "council",
        score=score_of(findings),
        findings=findings,
        debate=debate,
        summary=summary.get("summary") or "",
        trace_url=step_trace_url() or "",
    )
    db.add(stored)
    await db.flush()
    return _public(stored)


async def apply_review_fix(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    outline_id: uuid.UUID,
    review_id: uuid.UUID,
    finding_id: str,
) -> dict[str, Any]:
    outline = await get_outline(db, org_id, user_id, outline_id)
    review = await db.get(OutlineReview, review_id)
    if review is None or review.outline_id != outline.id or review.organization_id != org_id:
        from app.profassist.errors import ProfassistError

        raise ProfassistError(404, "That review is not on this outline.")
    findings = [dict(item) for item in review.findings or []]
    target = next((item for item in findings if item.get("id") == finding_id), None)
    if target is None:
        from app.profassist.errors import ProfassistError

        raise ProfassistError(404, "That finding is not in this review.")
    before_text = json.dumps(outline.body or {}, sort_keys=True, ensure_ascii=False)
    outline.body = apply_fix(outline.body or {}, target)
    target["applied"] = True
    review.findings = findings
    review.score = score_of(findings)
    await db.flush()
    await capture_movement(
        db,
        org_id,
        user_id,
        "objective",
        before_text,
        json.dumps(outline.body or {}, sort_keys=True, ensure_ascii=False),
        "outline-review-fix",
    )
    return _public(review)


def _public(row: OutlineReview) -> dict[str, Any]:
    findings = row.findings or []
    return {
        "id": str(row.id),
        "version": row.version,
        "mode": row.mode,
        "reviewer": row.reviewer,
        "score": row.score,
        "findings": findings,
        "debate": row.debate or [],
        "summary": row.summary,
        "trace_url": row.trace_url,
        "unresolved_high": sum(
            1 for item in findings if item.get("severity") == "high" and not item.get("applied")
        ),
    }
