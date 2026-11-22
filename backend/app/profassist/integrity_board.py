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
                            {
                                "id": "m2b",
                                "percent": 100,
                                "common": True,
                                "writing": "Low",
                                "left": "The brief asks each group to name one campus process and measure it for four weeks.",
                                "right": "The brief asks each group to name one campus process and measure it for four weeks.",
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


ROSTER: dict[str, dict[str, str]] = {
    "A": {"members": "Sara Al Maktoum, Omar Haddad", "submitted": "4 Nov 2026"},
    "B": {"members": "Noor Rahman, Layla Karim", "submitted": "4 Nov 2026"},
    "C": {"members": "Hana Yusuf, Adam Cole", "submitted": "5 Nov 2026"},
    "D": {"members": "Priya Nair, Jonah Ellis", "submitted": "5 Nov 2026"},
    "E": {"members": "Mina Farouk, Chris Adeyemi", "submitted": "6 Nov 2026"},
    "F": {"members": "Lina Haddad, Samir Qureshi", "submitted": "6 Nov 2026"},
}

OPENERS: dict[str, str] = {
    "A": (
        "We watched the Knowledge Hub doors across four teaching weeks and counted "
        "entries in ten-minute blocks. The tally stayed in the group notebook. We did "
        "not borrow a figure from facilities."
    ),
    "B": (
        "We started from the published timetable and then stood at the same doors the "
        "following week. Two of us counted while the third kept the clock. The notebook "
        "is the record we are submitting."
    ),
    "C": (
        "Our count covered the east stair, because that is the route from the afternoon "
        "labs. We kept one sheet per day and checked the totals together each evening."
    ),
    "D": (
        "We measured queue time at the print desk rather than the door. A phone timer "
        "and a paper log were enough, and we discarded any session where the desk closed early."
    ),
    "E": (
        "The group split the building by floor. One person stayed on level two and one "
        "in the basement, and we compared the sheets before writing this up."
    ),
    "F": (
        "We followed one workshop room for three weeks and noted when the booking and "
        "the actual use disagreed. The disagreement is the finding, not a side comment."
    ),
}

SETTINGS: dict[str, str] = {
    "A": "The rooms we watched are the ones booked for the afternoon workshop, not the evening labs.",
    "B": "We ignored the evening session because the doors were already locked when we arrived.",
    "C": "Rain on the second Tuesday pushed people to the covered stair, and we noted that on the sheet.",
    "D": "The desk log names the hour, not the student, so the sheet has no personal data.",
    "E": "We photographed the meter labels and typed the readings the same evening.",
    "F": "A room counted as empty only when we waited five minutes past the booking start.",
}

MIDDLES: dict[str, str] = {
    "A": "The afternoon pattern was steady enough to plan around. What follows is the method we actually used.",
    "B": "After the first week we stopped guessing from the timetable and wrote down only what we saw.",
    "C": "The east stair is quieter than the main door, so a small difference still shows up in the sheet.",
    "D": "Queue time moved more than headcount, which is why we kept both numbers.",
    "E": "The basement meters were harder to read, so we treated that floor as its own zone.",
    "F": "Empty booked rooms were the surprise. The notes below are the ones we would defend.",
}

CLOSERS: dict[str, str] = {
    "A": (
        "We would run the count for one more week before asking for a change to the "
        "room rules. The recommendation is ours, and it is still a draft for the tutor."
    ),
    "B": (
        "A second week of door counts would tell us whether the Thursday spike is real. "
        "Until then we are not asking for a timetable change."
    ),
    "C": (
        "The stair count is too small to redesign the building. It is enough to say "
        "which door the next group should watch."
    ),
    "D": (
        "The print desk is a different problem from the door. We are leaving the booking "
        "system alone and flagging the queue instead."
    ),
    "E": (
        "Level two and the basement should not be averaged. The pilot we suggest is "
        "only for the floor we could read clearly."
    ),
    "F": (
        "We can name the rooms that stay empty. We cannot yet say why the booking was made, "
        "and that limit is part of the report."
    ),
}


def _count(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


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


def _pair_status(course: dict[str, Any], item: dict[str, Any], pair: dict[str, Any]) -> str:
    from app.profassist.integrity_docs import decision_status, load_decisions, pair_matches

    matches = pair_matches(course["slug"], str(item["number"]), pair["left"], pair["right"])
    decided = decision_status(
        matches,
        load_decisions().get(
            _pair_id(course["slug"], str(item["number"]), pair["left"], pair["right"]), {}
        ),
    )
    if decided:
        return decided
    return _status(int(pair["percent"]), len(_counted(pair["passages"])))


def assignment_card(course: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    flagged = 0
    highest = 0
    writing = 0
    statuses = []
    for pair in item["pairs"]:
        counted = _counted(pair["passages"])
        status = _pair_status(course, item, pair)
        statuses.append(status)
        if status != "Clear":
            flagged += 1
        highest = max(highest, int(pair["percent"]) if counted or not pair["passages"] else 0)
        if _writing_flag(pair["passages"]):
            writing += 1
    overall = "Clear"
    if "Concern" in statuses:
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
        "line": (
            f"{_count(len(item['groups']), 'group', 'groups')} · "
            f"{_count(flagged, 'pair', 'pairs')} to read · "
            f"{_count(writing, 'writing flag', 'writing flags')}"
        ),
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
    from app.profassist.integrity_docs import document_side, load_decisions, pair_matches, summarise

    matches = pair_matches(found["slug"], str(item["number"]), left, right)
    decisions = load_decisions().get(_pair_id(found["slug"], str(item["number"]), left, right), {})
    for match in matches:
        match["decision"] = decisions.get(match["id"], "pending")
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
        "left_meta": _group_meta(left, item["number"]),
        "right_meta": _group_meta(right, item["number"]),
        "passages": passages,
        "matches": matches,
        "decisions": summarise(matches, decisions),
        "documents": {
            "left": document_side(found["slug"], str(item["number"]), left),
            "right": document_side(found["slug"], str(item["number"]), right),
        },
        "why": (
            "The highlight is the wording that appears in both submissions. "
            "A line that also appears in the assignment brief or the readings is marked "
            "as a common source and is not treated as copying."
        ),
    }


def _group_meta(group: str, number: str) -> dict[str, str]:
    roster = ROSTER.get(group, {"members": f"Group {group}", "submitted": "4 Nov 2026"})
    submitted = roster["submitted"]
    if str(number) == "2":
        submitted = {"A": "18 Nov 2026", "B": "18 Nov 2026", "C": "19 Nov 2026"}.get(
            group, "19 Nov 2026"
        )
    if str(number) == "3":
        submitted = "2 Dec 2026" if group in {"A", "B"} else "3 Dec 2026"
    return {"members": roster["members"], "submitted": submitted}


def _run(text: str, passage_id: str = "", common: bool = False) -> dict[str, Any]:
    return {"text": text, "id": passage_id, "common": common}


def _submission(
    title: str, group: str, passages: list[dict[str, Any]], side: str
) -> list[dict[str, Any]]:
    del title
    lead = MIDDLES.get(group, "The notes below are the ones we would defend.")
    shared: list[dict[str, Any]] = [_run(lead)]
    for passage in passages:
        shared.append(_run(" "))
        shared.append(
            _run(
                str(passage.get(side) or ""),
                str(passage.get("id") or ""),
                bool(passage.get("common")),
            )
        )
    if not passages:
        shared.append(_run(" Nothing in this section repeats another group's wording."))
    return [
        {
            "runs": [
                _run(OPENERS.get(group, "We measured one campus process and kept our own notes."))
            ]
        },
        {"runs": [_run(SETTINGS.get(group, "We wrote down only what we saw."))]},
        {"runs": shared},
        {"runs": [_run(CLOSERS.get(group, "The rest of this report is the group's own wording."))]},
    ]


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
    from app.profassist.integrity_docs import pair_matches

    lines = []
    match_rows: list[dict[str, Any]] = []
    for item in picked:
        detail = ""
        if first and item is first:
            rows = pair_matches(item["slug"], str(item["number"]), "A", "B") or pair_matches(
                item["slug"], str(item["number"]), "A", "C"
            )
            match_rows = [
                {
                    "n": index + 1,
                    "percent": row["percent"],
                    "page": row["page_left"],
                    "quote": row["quote"],
                    "source": row["tag"],
                }
                for index, row in enumerate(rows[:8])
            ]
            if match_rows:
                detail = f" First match is on page {match_rows[0]['page']}."
        lines.append(
            f"{item['course']} assignment {item['number']} ({item['name']}): {item['status']}, "
            f"highest {item['highest']}% across {_count(item['flagged_pairs'], 'pair', 'pairs')} to read.{detail}"
        )
    return {
        "course": code,
        "assignment": number,
        "items": picked,
        "matches": match_rows,
        "href": href,
        "message": " ".join(lines) or "Nothing needs a look on that assignment.",
    }
