"""Private feedback on a graded submission.

Comments stay on this computer until the professor approves the grade and
MOODLE_PUSH_ENABLED is on. Even then the fake connector does not contact Moodle.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.profassist.config import moodle_push_enabled

RUBRIC = [
    {
        "criterion": "Problem definition",
        "comment": "The problem is a real campus process. Say who would use the count.",
    },
    {
        "criterion": "Solution design",
        "comment": "The meter map is clear. Name the fallback if a meter cannot be read.",
    },
    {
        "criterion": "Ethical risk",
        "comment": "The sheet has no student names. Add who is allowed to see the counts.",
    },
]

OVERALL = "A solid first draft. Fix the shared spelling and tie the Thursday number to a decision."

BANK = [
    "Add the missing citation.",
    "This claim needs a number from your own count.",
    "Good use of the brief. Keep going.",
]

COUNCIL = [
    {"name": "Evidence grader", "initials": "E", "color": "#6929c4"},
    {"name": "Method grader", "initials": "M", "color": "#007d79"},
    {"name": "Fairness grader", "initials": "F", "color": "#8a3ffc"},
    {"name": "Chair", "initials": "C", "color": "#0f62fe"},
]


def _bands(weight: int) -> list[dict[str, Any]]:
    if weight >= 40:
        spans = [
            ("Excellent", 34, 40, 36),
            ("Good", 28, 33, 32),
            ("Fair", 20, 27, 24),
            ("Poor", 0, 19, 12),
        ]
    else:
        spans = [
            ("Excellent", 26, 30, 28),
            ("Good", 21, 25, 24),
            ("Fair", 15, 20, 17),
            ("Poor", 0, 14, 8),
        ]
    return [
        {"name": name, "low": low, "high": high, "points": points}
        for name, low, high, points in spans
    ]


def _points(weight: int, band: str) -> int:
    for row in _bands(weight):
        if row["name"] == band:
            return int(row["points"])
    return 0


def letter_for(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 75:
        return "B"
    if score >= 65:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def draft_mark(group: str = "Group A") -> dict[str, Any]:
    """What the grading council drafted from the Workshops rubric. Synthetic demo only."""
    criteria = [
        {
            "id": "problem",
            "name": "Problem definition",
            "weight": 30,
            "band": "Good",
            "reason": "They named a campus process and counted it. They did not say who would use the result.",
            "evidence": "Peak arrivals cluster in the twenty minutes after the 2pm workshop.",
            "agreed": True,
            "graders": [
                {"name": "Evidence grader", "band": "Good", "reason": "The count is in the text."},
                {"name": "Method grader", "band": "Good", "reason": "The process is named."},
                {"name": "Fairness grader", "band": "Good", "reason": "No student is singled out."},
            ],
        },
        {
            "id": "design",
            "name": "Solution design",
            "weight": 40,
            "band": "Good",
            "reason": "The meter map is a real design. The fallback if a meter cannot be read is missing.",
            "evidence": "The meter on level two reads 42.7 during the Thursday class change.",
            "agreed": False,
            "graders": [
                {"name": "Evidence grader", "band": "Good", "reason": "42.7 is their own reading."},
                {
                    "name": "Method grader",
                    "band": "Fair",
                    "reason": "They never say what happens if a meter cannot be read.",
                },
                {
                    "name": "Fairness grader",
                    "band": "Good",
                    "reason": "The method does not name a student.",
                },
            ],
        },
        {
            "id": "ethics",
            "name": "Ethical risk",
            "weight": 30,
            "band": "Good",
            "reason": "The sheet keeps hours, not names. Say who is allowed to see the counts.",
            "evidence": "The brief asks each group to name one campus process and measure it for four weeks.",
            "agreed": True,
            "graders": [
                {
                    "name": "Evidence grader",
                    "band": "Good",
                    "reason": "The brief sentence is used as the task, not as a finding.",
                },
                {"name": "Method grader", "band": "Good", "reason": "The limit is stated."},
                {
                    "name": "Fairness grader",
                    "band": "Good",
                    "reason": "No personal data is in the count.",
                },
            ],
        },
    ]
    for row in criteria:
        row["bands"] = _bands(int(row["weight"]))
        row["score"] = _points(int(row["weight"]), str(row["band"]))
        if row["id"] == "ethics":
            row["score"] = 22
        row["page"] = 1
        row["box"] = {"x": 0.1, "y": 0.4, "w": 0.7, "h": 0.03}
    if group in {"Group A", "A"}:
        from app.profassist.integrity_docs import locate_sentence

        for row in criteria:
            found = locate_sentence("MAAI903", "1", "A", str(row["evidence"]))
            if not found:
                continue
            row["page"] = found["page"]
            row["box"] = found["box"]
    total = sum(int(row["score"]) for row in criteria)
    return {
        "rubric": "Workshops rubric",
        "source": "Assignment 1 brief",
        "total": total,
        "out_of": 100,
        "letter": letter_for(total),
        "confidence": "Medium" if any(not row["agreed"] for row in criteria) else "High",
        "council": COUNCIL,
        "criteria": criteria,
    }


def _path(user_id: str, group: str) -> Path:
    safe = "".join(ch for ch in f"{user_id}-{group}" if ch.isalnum() or ch in {"-", "_"})
    path = Path(settings.MEDIA_DIR) / "profassist" / "feedback" / f"{safe}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _seed(group: str) -> dict[str, Any]:
    comments: list[dict[str, Any]] = []
    if group in {"Group A", "A"}:
        from app.profassist.integrity_docs import locate_sentence

        planted = [
            (
                "Peak arrivals cluster in the twenty minutes after the 2pm workshop.",
                "Ask the group to explain this arrival window in their own words.",
            ),
            (
                "The meter on level two reads 42.7 during the Thursday class change.",
                "Say what 42.7 means for the pilot, not only that the meter moved.",
            ),
        ]
        for sentence, note in planted:
            found = locate_sentence("MAAI903", "1", "A", sentence)
            if not found:
                continue
            comments.append(
                {
                    "id": uuid.uuid4().hex[:8],
                    "page": found["page"],
                    "box": found["box"],
                    "quote": sentence,
                    "text": note,
                }
            )
    return {
        "group": group,
        "comments": comments,
        "rubric": [dict(row) for row in RUBRIC],
        "overall": OVERALL,
        "bank": list(BANK),
        "release": "draft",
        "ai_grade": draft_mark(group),
        "overrides": {},
    }


def load_feedback(user_id: str, group: str) -> dict[str, Any]:
    path = _path(user_id, group)
    if not path.exists():
        return _seed(group)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return _seed(group)
    data.setdefault("comments", [])
    data.setdefault("rubric", [dict(row) for row in RUBRIC])
    data.setdefault("overall", OVERALL)
    data.setdefault("bank", list(BANK))
    data.setdefault("release", "draft")
    data.setdefault("overrides", {})
    data["ai_grade"] = draft_mark(data.get("group") or group)
    return data


def save_feedback(user_id: str, group: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_feedback(user_id, group)
    current.update(
        {
            "group": group,
            "comments": payload.get("comments", current["comments"]),
            "rubric": payload.get("rubric", current["rubric"]),
            "overall": payload.get("overall", current["overall"]),
            "bank": payload.get("bank", current["bank"]),
            "overrides": payload.get("overrides", current.get("overrides") or {}),
            "release": "draft",
        }
    )
    stored = {key: value for key, value in current.items() if key != "ai_grade"}
    _path(user_id, group).write_text(json.dumps(stored))
    current["ai_grade"] = draft_mark(group)
    return current


def release_feedback(user_id: str, group: str) -> dict[str, Any]:
    """Approve keeps the notes private unless push is explicitly enabled."""
    notes = load_feedback(user_id, group)
    audit = {
        "target_type": "grade_feedback",
        "action": "approved",
        "note": "Feedback approved with the grade. Nothing was sent until push is enabled.",
    }
    if not moodle_push_enabled():
        notes["release"] = "held"
        _path(user_id, group).write_text(json.dumps(notes))
        return {
            "pushed": False,
            "message": "Saved with the grade. Moodle was not contacted because push is off.",
            "audit": audit,
        }
    from app.profassist.moodle import get_connector

    receipt = get_connector().push(
        {
            "type": "grade",
            "group": group,
            "feedback": notes.get("overall") or "",
            "rubric": notes.get("rubric") or [],
            "comments": notes.get("comments") or [],
        }
    )
    notes["release"] = "pushed"
    _path(user_id, group).write_text(json.dumps(notes))
    audit["note"] = "Feedback pushed with the grade. Moodle was not contacted."
    return {
        "pushed": True,
        "message": receipt.get("moodle_response", ""),
        "receipt": receipt,
        "audit": audit,
    }
