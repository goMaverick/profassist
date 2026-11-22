"""Synthetic integrity drill-down for the professor.

Two courses, several assignments, and a mix of clear, review, and concern
pairs. A shared sentence that also appears in the brief is marked as a common
source and is not treated as copying. Actions are notes for the professor.
Nothing here is sent to Moodle or to a student.
"""

from typing import Any

COURSES: list[dict[str, Any]] = [
    {
        "code": "MAAI 903",
        "slug": "MAAI903",
        "title": "AI Solutions Design & MLOps",
        "assignments": [
            {
                "number": "1",
                "title": "Workshops",
                "groups": ["A", "B", "C", "D", "E"],
                "pairs": [
                    {
                        "left": "A",
                        "right": "B",
                        "percent": 86,
                        "passages": [
                            {
                                "id": "m1",
                                "percent": 92,
                                "common": False,
                                "writing": "Medium",
                                "left": "The shared draft still contains the typo sustanability.",
                                "right": "The shared draft still contains the typo sustanability.",
                            },
                            {
                                "id": "m2",
                                "percent": 78,
                                "common": False,
                                "writing": "Low",
                                "left": "We interviewed facilities staff and mapped meters to floors.",
                                "right": "We interviewed facilities staff and mapped meters to floors.",
                            },
                        ],
                    },
                    {
                        "left": "C",
                        "right": "D",
                        "percent": 48,
                        "passages": [
                            {
                                "id": "m3",
                                "percent": 70,
                                "common": True,
                                "writing": "Low",
                                "left": "The brief asks for a measurable operational problem.",
                                "right": "The brief asks for a measurable operational problem.",
                            },
                            {
                                "id": "m3b",
                                "percent": 48,
                                "common": False,
                                "writing": "Low",
                                "left": "Peak use follows the afternoon class change.",
                                "right": "Peak use follows the afternoon class change.",
                            },
                        ],
                    },
                ],
            },
            {
                "number": "2",
                "title": "Architecture report",
                "groups": ["A", "B", "C", "D", "E"],
                "pairs": [
                    {
                        "left": "B",
                        "right": "E",
                        "percent": 62,
                        "passages": [
                            {
                                "id": "m4",
                                "percent": 64,
                                "common": False,
                                "writing": "Medium",
                                "left": "The rollback plan names who to call if the API fails.",
                                "right": "The rollback plan names who to call if the API fails.",
                            }
                        ],
                    }
                ],
            },
            {
                "number": "3",
                "title": "Group project",
                "groups": ["A", "B", "C", "D", "E", "F"],
                "pairs": [
                    {
                        "left": "A",
                        "right": "C",
                        "percent": 22,
                        "passages": [],
                    },
                    {
                        "left": "D",
                        "right": "F",
                        "percent": 18,
                        "passages": [
                            {
                                "id": "m5",
                                "percent": 18,
                                "common": False,
                                "writing": "High",
                                "left": "The system optimises throughput across heterogeneous nodes.",
                                "right": "The system optimises throughput across heterogeneous nodes.",
                            }
                        ],
                    },
                ],
            },
        ],
    },
    {
        "code": "MAAI 901",
        "slug": "MAAI901",
        "title": "Applied Machine Learning",
        "assignments": [
            {
                "number": "1",
                "title": "Problem set",
                "groups": ["A", "B", "C", "D"],
                "pairs": [
                    {
                        "left": "A",
                        "right": "C",
                        "percent": 78,
                        "passages": [
                            {
                                "id": "m6",
                                "percent": 81,
                                "common": False,
                                "writing": "High",
                                "left": "The loss falls after epoch four because the learning rate was halved.",
                                "right": "The loss falls after epoch four because the learning rate was halved.",
                            }
                        ],
                    }
                ],
            },
            {
                "number": "2",
                "title": "Lab notes",
                "groups": ["A", "B", "C", "D"],
                "pairs": [
                    {
                        "left": "B",
                        "right": "D",
                        "percent": 41,
                        "passages": [
                            {
                                "id": "m7",
                                "percent": 66,
                                "common": True,
                                "writing": "Low",
                                "left": "Students record the seed and the data version in the lab note.",
                                "right": "Students record the seed and the data version in the lab note.",
                            },
                            {
                                "id": "m7b",
                                "percent": 41,
                                "common": False,
                                "writing": "Low",
                                "left": "The lab note stops before the error bars.",
                                "right": "The lab note stops before the error bars.",
                            },
                        ],
                    }
                ],
            },
        ],
    },
]


def _norm(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _status(percent: int, counted: int) -> str:
    if counted == 0 or percent < 40:
        return "Clear"
    if percent >= 75:
        return "Concern"
    return "Review"


def _writing_flag(passages: list[dict[str, Any]]) -> bool:
    return any(item.get("writing") == "High" and not item.get("common") for item in passages)


def _pair_id(course: str, number: str, left: str, right: str) -> str:
    return f"{_norm(course)}-{number}-{left}-{right}"


def _course(code: str) -> dict[str, Any] | None:
    wanted = _norm(code)
    for course in COURSES:
        if course["slug"] == wanted or _norm(course["code"]) == wanted:
            return course
    return None


def _assignment(course: dict[str, Any], number: str) -> dict[str, Any] | None:
    for item in course["assignments"]:
        if str(item["number"]) == str(number):
            return item
    return None


def _known(item: dict[str, Any], left: str, right: str) -> dict[str, Any] | None:
    for pair in item["pairs"]:
        ends = {pair["left"], pair["right"]}
        if ends == {left, right}:
            return pair
    return None


def _cell(item: dict[str, Any], left: str, right: str) -> int:
    if left == right:
        return 100
    found = _known(item, left, right)
    if found:
        return int(found["percent"])
    return 12 + (abs(ord(left) - ord(right)) % 5) * 3


def _counted(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in passages if not item.get("common")]


def assignment_card(course: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    flagged = 0
    highest = 0
    writing = 0
    for pair in item["pairs"]:
        counted = _counted(pair["passages"])
        status = _status(int(pair["percent"]), len(counted))
        if status != "Clear":
            flagged += 1
        highest = max(highest, int(pair["percent"]) if counted or not pair["passages"] else 0)
        if _writing_flag(pair["passages"]):
            writing += 1
    overall = "Clear"
    if any(
        _status(int(pair["percent"]), len(_counted(pair["passages"]))) == "Concern"
        for pair in item["pairs"]
    ):
        overall = "Concern"
    elif flagged:
        overall = "Review"
    return {
        "course": course["code"],
        "slug": course["slug"],
        "title": course["title"],
        "number": item["number"],
        "name": item["title"],
        "groups": len(item["groups"]),
        "flagged_pairs": flagged,
        "highest": highest,
        "writing_flags": writing,
        "status": overall,
    }


def overview(course: str = "all") -> dict[str, Any]:
    wanted = None if not course or course == "all" else _norm(course)
    rows = []
    for item in COURSES:
        if wanted and item["slug"] != wanted:
            continue
        cards = [assignment_card(item, assignment) for assignment in item["assignments"]]
        rows.append(
            {
                "code": item["code"],
                "slug": item["slug"],
                "title": item["title"],
                "assignments": cards,
            }
        )
    cards = [card for row in rows for card in row["assignments"]]
    return {
        "courses": [
            {"code": row["code"], "slug": row["slug"], "title": row["title"]} for row in rows
        ],
        "summary": {
            "courses": len(rows),
            "assignments": len(cards),
            "groups": sum(card["groups"] for card in cards),
            "review": sum(1 for card in cards if card["status"] == "Review"),
            "concern": sum(1 for card in cards if card["status"] == "Concern"),
        },
        "items": cards,
    }


def assignment_matrix(course: str, number: str) -> dict[str, Any]:
    found = _course(course)
    if found is None:
        return {"error": "That course is not in this workspace."}
    item = _assignment(found, number)
    if item is None:
        return {"error": "That assignment is not in this course."}
    groups = item["groups"]
    matrix = [[_cell(item, left, right) for right in groups] for left in groups]
    pairs = []
    for left_index, left in enumerate(groups):
        for right in groups[left_index + 1 :]:
            known = _known(item, left, right)
            passages = (known or {}).get("passages") or []
            counted = _counted(passages)
            percent = _cell(item, left, right)
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "percent": percent,
                    "shared": len(counted),
                    "writing": _writing_flag(passages),
                    "status": _status(
                        percent, len(counted) if known else (1 if percent >= 40 else 0)
                    ),
                }
            )
    pairs.sort(key=lambda row: row["percent"], reverse=True)
    return {
        "course": found["code"],
        "slug": found["slug"],
        "assignment": item["number"],
        "name": item["title"],
        "groups": groups,
        "matrix": matrix,
        "pairs": pairs,
        "card": assignment_card(found, item),
    }


def pair_detail(course: str, number: str, left: str, right: str) -> dict[str, Any]:
    found = _course(course)
    item = _assignment(found, number) if found else None
    if found is None or item is None:
        return {"error": "That pair is not in this workspace."}
    known = _known(item, left, right)
    passages = list((known or {}).get("passages") or [])
    percent = _cell(item, left, right)
    left_body = _submission(item["title"], left, passages, side="left")
    right_body = _submission(item["title"], right, passages, side="right")
    return {
        "course": found["code"],
        "slug": found["slug"],
        "assignment": item["number"],
        "name": item["title"],
        "left": left,
        "right": right,
        "percent": percent,
        "status": _status(percent, len(_counted(passages))),
        "left_text": left_body,
        "right_text": right_body,
        "passages": passages,
        "why": (
            "The highlight is the wording that appears in both submissions. "
            "A line that also appears in the assignment brief or the readings is marked "
            "as a common source and is not treated as copying."
        ),
    }


def _submission(
    title: str, group: str, passages: list[dict[str, Any]], side: str
) -> list[dict[str, str]]:
    blocks = [
        {"id": "", "text": f"Group {group} — {title}."},
        {"id": "", "text": "The group describes its own setting and the limit of the evidence."},
    ]
    for passage in passages:
        blocks.append({"id": passage["id"], "text": passage[side]})
    blocks.append({"id": "", "text": "The rest of the report is the group's own wording."})
    return blocks


def concerns(code: str, number: str = "") -> dict[str, Any]:
    board = overview(code or "MAAI903")
    items = board["items"]
    if number:
        items = [item for item in items if str(item["number"]) == str(number)]
    worrying = [item for item in items if item["status"] != "Clear"]
    picked = worrying or items
    first = picked[0] if picked else None
    href = "/integrity"
    if first:
        href = f"/integrity?course={first['slug']}&assignment={first['number']}"
    lines = [
        f"{item['course']} assignment {item['number']} ({item['name']}): {item['status']}, "
        f"highest {item['highest']}% across {item['flagged_pairs']} pairs to read."
        for item in picked
    ]
    return {
        "course": code,
        "assignment": number,
        "items": picked,
        "href": href,
        "message": " ".join(lines) or "Nothing needs a look on that assignment.",
    }
