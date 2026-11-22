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
            "release": "draft",
        }
    )
    _path(user_id, group).write_text(json.dumps(current))
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
