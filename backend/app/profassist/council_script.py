"""Scripted council beats. Demo mode replays these with pauses so the animation is visible."""

from typing import Any

AGENTS = {
    "curriculum": {"name": "Curriculum reviewer", "color": "#6929c4", "icon": "education"},
    "alignment": {"name": "Assessment expert", "color": "#8a3ffc", "icon": "checkmark"},
    "balance": {"name": "Integrity officer", "color": "#007d79", "icon": "chart"},
    "student": {"name": "Student voice", "color": "#b28600", "icon": "user"},
    "judge": {"name": "Chair", "color": "#da1e28", "icon": "gavel"},
    "evidence": {"name": "Evidence", "color": "#0f62fe", "icon": "document"},
    "strict": {"name": "Strict", "color": "#da1e28", "icon": "warning"},
    "supportive": {"name": "Supportive", "color": "#198038", "icon": "favorite"},
}


def script_for(scene: str) -> list[dict[str, Any]]:
    """Ordered events. delay is seconds before the event is shown."""
    if scene == "review":
        speakers = ["curriculum", "alignment", "balance", "student"]
        lines = [
            "I am checking the weekly outcomes against the course outcomes.",
            "Two program outcomes are thin. I would map them before accreditation.",
            "The weights need to land on 100, and week 7 is carrying a summative task.",
            "A student would ask where attendance and integrity are written down.",
        ]
    elif scene == "assessment":
        speakers = ["evidence", "strict", "supportive", "judge"]
        lines = [
            "The selected outcomes need an artefact a student can submit.",
            "I would keep the weight modest until the rubric quotes the outcome.",
            "A workshop plus a short report would let them show the work.",
            "One assignment, tied to those outcomes, with a four-level rubric.",
        ]
    else:
        speakers = ["evidence", "strict", "supportive"]
        lines = [
            "I am marking only what is quoted from the submission.",
            "The limitation is present, so I will not drop the level.",
            "The attempt is clear. I agree if the quote stays in the feedback.",
        ]
    events: list[dict[str, Any]] = [{"type": "step", "step": "marking", "delay": 0.2}]
    for index, (speaker, line) in enumerate(zip(speakers, lines, strict=False)):
        persona = AGENTS[speaker]
        events.append(
            {
                "type": "agent",
                "id": speaker,
                "name": persona["name"],
                "color": persona["color"],
                "icon": persona["icon"],
                "state": "thinking",
                "text": "",
                "delay": 0.7,
            }
        )
        events.append(
            {
                "type": "agent",
                "id": speaker,
                "name": persona["name"],
                "color": persona["color"],
                "icon": persona["icon"],
                "state": "speaking",
                "text": line,
                "delay": 0.9,
            }
        )
        if index:
            events.append(
                {
                    "type": "arrow",
                    "from": speakers[index - 1],
                    "to": speaker,
                    "delay": 0.25,
                }
            )
    events.append({"type": "step", "step": "debate", "delay": 0.4})
    events.append(
        {
            "type": "arrow",
            "from": speakers[0],
            "to": speakers[-1],
            "delay": 0.3,
        }
    )
    events.append(
        {
            "type": "agent",
            "id": speakers[1] if len(speakers) > 1 else speakers[0],
            "name": AGENTS[speakers[1] if len(speakers) > 1 else speakers[0]]["name"],
            "color": AGENTS[speakers[1] if len(speakers) > 1 else speakers[0]]["color"],
            "icon": AGENTS[speakers[1] if len(speakers) > 1 else speakers[0]]["icon"],
            "state": "speaking",
            "text": "I hear you. I will keep the quote and move one step toward your level.",
            "delay": 1.0,
        }
    )
    events.append({"type": "step", "step": "judge", "delay": 0.35})
    judge = AGENTS["judge"]
    events.append(
        {
            "type": "agent",
            "id": "judge",
            "name": judge["name"],
            "color": judge["color"],
            "icon": judge["icon"],
            "state": "thinking",
            "text": "",
            "delay": 0.6,
        }
    )
    events.append(
        {
            "type": "agent",
            "id": "judge",
            "name": judge["name"],
            "color": judge["color"],
            "icon": judge["icon"],
            "state": "speaking",
            "text": "The council agrees on the evidence that is actually in the text.",
            "delay": 0.9,
        }
    )
    events.append({"type": "step", "step": "feedback", "delay": 0.3})
    events.append(
        {
            "type": "verdict",
            "text": "Verdict reached.",
            "delay": 0.4,
        }
    )
    return events
