"""Integrity board for recognized submissions. Empty until real submissions are registered."""

import re
import uuid
from itertools import pairwise
from typing import Any

from sqlalchemy import select

from app.profassist.models import (
    Assessment,
    Course,
    GroupAssignment,
    IntegrityFlag,
    IntegritySourceVersion,
    Submission,
)
from app.profassist.similarity import compare_submissions

COURSES: list[dict[str, Any]] = []


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


def _spoken_code(code: str) -> str:
    compact = _norm(code)
    split = ""
    letters = ""
    digits = ""
    for char in compact:
        if char.isdigit():
            digits += char
        else:
            letters += char
    if letters and digits:
        split = f"{letters} {digits}"
    return split or code or "This course"


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


def register_course(course: dict[str, Any]) -> None:
    """Add a course the professor just created. Replaces the same slug."""
    slug = course["slug"]
    for index, item in enumerate(COURSES):
        if item["slug"] == slug:
            COURSES[index] = course
            return
    COURSES.append(course)


def unregister_course(slug: str) -> None:
    wanted = _norm(slug)
    COURSES[:] = [item for item in COURSES if item["slug"] != wanted]


def _group_letter(name: str) -> str:
    text = (name or "").strip()
    if text.lower().startswith("group "):
        return text[6:].strip().upper()[:1]
    return text.upper()[:1] if len(text) == 1 else ""


def register_synced_submissions(
    code: str, title: str, assignments: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Show the pairs from a Moodle sync on the integrity board.

    Each assignment item is ``{"number", "title", "submissions": [...]}`` where a
    submission has ``group_name``, ``topic``, and already-scrubbed ``text``. Only
    non-clear pairs are kept, so a course with no shared wording is not added.
    The board is in-memory, exactly like the seeded demo board.
    """
    from app.profassist.similarity import compare_submissions

    items: list[dict[str, Any]] = []
    for item in assignments:
        rows = [row for row in item.get("submissions") or [] if isinstance(row, dict)]
        if len(rows) < 2:
            continue
        groups = sorted(
            {letter for row in rows if (letter := _group_letter(row.get("group_name") or ""))}
        )
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for flag in compare_submissions(rows):
            left = _group_letter(flag.get("left_group") or "")
            right = _group_letter(flag.get("right_group") or "")
            if not left or not right or left == right:
                continue
            key = (left, right) if left < right else (right, left)
            percent = max(1, min(100, round(float(flag.get("score") or 0) * 100)))
            pair = grouped.setdefault(
                key,
                {"left": key[0], "right": key[1], "percent": 0, "passages": []},
            )
            pair["percent"] = max(int(pair["percent"]), percent)
            pair["passages"].append(
                {
                    "id": f"{flag.get('section') or 'body'}-{len(pair['passages']) + 1}",
                    "percent": percent,
                    "common": False,
                    "writing": "Medium" if percent >= 50 else "Low",
                    "left": flag.get("passage_a") or "",
                    "right": flag.get("passage_b") or "",
                }
            )
        if grouped:
            items.append(
                {
                    "number": str(item.get("number") or "1"),
                    "title": str(item.get("title") or "Synced assignment"),
                    "groups": groups,
                    "pairs": sorted(
                        grouped.values(), key=lambda pair: int(pair["percent"]), reverse=True
                    ),
                }
            )
    if not items:
        return None
    board = {"code": code, "slug": _norm(code) or "COURSE", "title": title, "assignments": items}
    register_course(board)
    return board


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
    """The same cases the integrity page and the home to-do count.

    Every non-clear pair, across every assignment in the course, with the two
    group names, the similarity, and a link that opens that pair.
    """
    named = (code or "").strip()
    board = overview(named or "MAAI903")
    missing = bool(named) and not board["items"]
    if missing:
        board = overview("all")
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

    lines: list[str] = []
    cases: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []
    if missing:
        pair_count = sum(int(item["flagged_pairs"]) for item in worrying)
        assignment_count = len({(item["slug"], str(item["number"])) for item in worrying})
        if pair_count:
            lines.append(
                f"{_spoken_code(named)} has no copying cases yet. "
                f"{pair_count} cases need a look across {assignment_count} assignments in other courses."
            )
        else:
            lines.append(f"{_spoken_code(named)} has no copying cases yet.")
    for item in picked:
        if worrying and item["status"] == "Clear":
            continue
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
        matrix = assignment_matrix(item["slug"], str(item["number"]))
        for pair in matrix.get("pairs") or []:
            if pair.get("status") == "Clear":
                continue
            case_href = (
                f"/integrity?course={item['slug']}&assignment={item['number']}"
                f"&pair={pair['left']}-{pair['right']}"
            )
            cases.append(
                {
                    "course": item["course"],
                    "slug": item["slug"],
                    "assignment": str(item["number"]),
                    "name": item["name"],
                    "groups": [pair["left"], pair["right"]],
                    "percent": pair["percent"],
                    "status": pair["status"],
                    "href": case_href,
                }
            )
            lines.append(
                f"Group {pair['left']} and Group {pair['right']} are {pair['percent']}% similar. "
                f"[Open the case]({case_href})."
            )
            href = href if href != "/integrity" else case_href
    if cases:
        href = cases[0]["href"]
    if not lines:
        lines.append("Nothing needs a look on that assignment.")
    return {
        "course": code,
        "assignment": number,
        "items": picked,
        "cases": cases,
        "matches": match_rows,
        "href": href,
        "message": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# Durable board backed by Submission / IntegrityFlag rows.
# ---------------------------------------------------------------------------


async def _load_all(db: Any, statement: Any) -> list[Any]:
    result = await db.execute(statement)
    return list(result.scalars().all())


def _owned_clause(model: Any, user_id: Any) -> Any:
    return (model.owner_user_id == user_id) | (model.owner_user_id.is_(None))


async def _db_catalog(
    db: Any, org_id: Any, user_id: Any
) -> tuple[list[Any], list[Any], list[Any], list[Any], list[Any]]:
    """Courses, assessments, group assignments, submissions, and flags.

    Five queries in this order. Tests replace ``db.execute`` with a small queue.
    """
    courses = await _load_all(db, select(Course).where(Course.organization_id == org_id))
    assessments = await _load_all(
        db,
        select(Assessment).where(
            Assessment.organization_id == org_id,
            _owned_clause(Assessment, user_id),
        ),
    )
    group_assignments = await _load_all(
        db,
        select(GroupAssignment).where(
            GroupAssignment.organization_id == org_id,
            _owned_clause(GroupAssignment, user_id),
        ),
    )
    submissions = await _load_all(
        db,
        select(Submission).where(Submission.organization_id == org_id),
    )
    flags = await _load_all(
        db,
        select(IntegrityFlag).where(
            IntegrityFlag.organization_id == org_id,
            _owned_clause(IntegrityFlag, user_id),
        ),
    )
    # The SQL already scopes, but keep the boundary in Python too so a mocked
    # or reused session can never widen the board.
    courses = [row for row in courses if _same(getattr(row, "organization_id", org_id), org_id)]
    assessments = [
        row
        for row in assessments
        if _same(getattr(row, "organization_id", org_id), org_id) and _owner_ok(row, user_id)
    ]
    group_assignments = [
        row
        for row in group_assignments
        if _same(getattr(row, "organization_id", org_id), org_id) and _owner_ok(row, user_id)
    ]
    submissions = [
        row for row in submissions if _same(getattr(row, "organization_id", org_id), org_id)
    ]
    flags = [
        row
        for row in flags
        if _same(getattr(row, "organization_id", org_id), org_id) and _owner_ok(row, user_id)
    ]
    return courses, assessments, group_assignments, submissions, flags


def _same(value: Any, expected: Any) -> bool:
    return str(value) == str(expected)


def _owner_ok(row: Any, user_id: Any) -> bool:
    owner = getattr(row, "owner_user_id", None)
    return owner is None or _same(owner, user_id)


def _course_slug(course: Any) -> str:
    return (
        _norm(str(getattr(course, "code", "") or ""))
        or _norm(str(getattr(course, "external_id", "") or ""))
        or "COURSE"
    )


def _course_matches(course: Any, wanted: str | None) -> bool:
    if not wanted:
        return True
    values = {
        _course_slug(course),
        _norm(str(getattr(course, "code", "") or "")),
        _norm(str(getattr(course, "external_id", "") or "")),
    }
    return wanted in values


def _find_course(courses: list[Any], wanted: str) -> Any | None:
    target = _norm(wanted)
    for course in courses:
        if _course_matches(course, target):
            return course
    return None


def _assessment_refs(
    courses: list[Any], assessments: list[Any], group_assignments: list[Any]
) -> list[dict[str, Any]]:
    """One display row per assessment, enriched by a published group assignment."""
    by_assessment: dict[str, Any] = {}
    for assignment in group_assignments:
        key = str(getattr(assignment, "assessment_id", "") or "")
        if key and key not in by_assessment:
            by_assessment[key] = assignment
    refs: list[dict[str, Any]] = []
    for course in courses:
        rows = [
            assessment
            for assessment in assessments
            if str(getattr(assessment, "course_id", "")) == str(getattr(course, "id", ""))
        ]
        rows.sort(
            key=lambda row: (
                str(getattr(row, "created_at", "") or ""),
                str(getattr(row, "id", "")),
            )
        )
        for index, assessment in enumerate(rows, start=1):
            published = by_assessment.get(str(getattr(assessment, "id", "")))
            external = str(getattr(assessment, "external_id", "") or "")
            number = str(getattr(published, "number", "") or external or index)
            title = str(
                getattr(published, "title", "") or getattr(assessment, "title", "") or "Assignment"
            )
            refs.append(
                {
                    "course": course,
                    "slug": _course_slug(course),
                    "assessment": assessment,
                    "number": number,
                    "title": title,
                    "order": index,
                }
            )
    return refs


def _group_labels(rows: list[Any]) -> dict[str, str]:
    """Map each stored group name to a short label. Group A and A both become A."""
    names = sorted({str(getattr(row, "group_name", "") or "").strip() for row in rows})
    names.sort(key=lambda name: not bool(_group_letter(name)))
    labels: dict[str, str] = {}
    used: set[str] = set()
    for name in names:
        letter = _group_letter(name)
        if not letter:
            letter = next(
                (candidate for candidate in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if candidate not in used),
                f"G{len(used) + 1}",
            )
        labels[name] = letter
        used.add(letter)
    return labels


def _assessment_rows(assessment: Any, submissions: list[Any]) -> list[Any]:
    key = str(getattr(assessment, "id", ""))
    return [row for row in submissions if str(getattr(row, "assessment_id", "")) == key]


def _as_percent(score: Any) -> int:
    try:
        value = float(score or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return 0
    return max(1, min(100, round(value * 100)))


def _pair_entry(left: str, right: str) -> dict[str, Any]:
    return {
        "left": left,
        "right": right,
        "percent": 0,
        "passages": [],
        "analysis_source": "legacy-heuristic",
    }


def _group_of(row: Any, labels: dict[str, str]) -> str:
    return labels.get(str(getattr(row, "group_name", "") or "").strip(), "")


def _pair_map(
    rows: list[Any], flags: list[Any], labels: dict[str, str]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Pair scores from stored flags, with a deterministic computed fallback."""
    by_id = {str(getattr(row, "id", "")): row for row in rows}
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for flag in flags:
        if (
            getattr(flag, "source", "legacy") == "worker"
            and getattr(flag, "status", "open") != "open"
        ):
            continue
        left = by_id.get(str(getattr(flag, "left_submission_id", "")))
        right = by_id.get(str(getattr(flag, "right_submission_id", "")))
        if left is None or right is None:
            continue
        left_label = _group_of(left, labels)
        right_label = _group_of(right, labels)
        if not left_label or not right_label or left_label == right_label:
            continue
        key = (left_label, right_label) if left_label < right_label else (right_label, left_label)
        percent = _as_percent(getattr(flag, "score", 0))
        reverse = left_label > right_label
        entry = pairs.setdefault(key, _pair_entry(key[0], key[1]))
        source = str(getattr(flag, "source", "legacy") or "legacy")
        entry["analysis_source"] = "worker" if source == "worker" else "legacy-record"
        if source == "worker" and str(getattr(flag, "section", "")) != "coverage":
            entry.setdefault(
                "review_versions",
                [
                    str(
                        getattr(flag, "right_version_id" if reverse else "left_version_id", "")
                        or ""
                    ),
                    str(
                        getattr(flag, "left_version_id" if reverse else "right_version_id", "")
                        or ""
                    ),
                ],
            )
        entry["percent"] = max(int(entry["percent"]), percent)
        writing = str(getattr(flag, "kind", "") or "").lower() == "writing"
        if source == "worker" and str(getattr(flag, "section", "")) == "coverage":
            continue
        entry["passages"].append(
            {
                "id": f"{getattr(flag, 'section', '') or 'body'}-{len(entry['passages']) + 1}",
                "percent": percent,
                "common": False,
                "writing": "High" if writing else ("Medium" if percent >= 50 else "Low"),
                "left": str(getattr(flag, "passage_b" if reverse else "passage_a", "") or ""),
                "right": str(getattr(flag, "passage_a" if reverse else "passage_b", "") or ""),
                "left_version_id": str(
                    getattr(flag, "right_version_id" if reverse else "left_version_id", "") or ""
                ),
                "right_version_id": str(
                    getattr(flag, "left_version_id" if reverse else "right_version_id", "") or ""
                ),
                "left_start": getattr(flag, "right_start" if reverse else "left_start", None),
                "left_end": getattr(flag, "right_end" if reverse else "left_end", None),
                "right_start": getattr(flag, "left_start" if reverse else "right_start", None),
                "right_end": getattr(flag, "left_end" if reverse else "right_end", None),
                "source": str(getattr(flag, "source", "legacy") or "legacy"),
            }
        )
    stored = set(pairs)
    computed = compare_submissions(
        [
            {
                "id": str(getattr(row, "id", "")),
                "group_name": str(getattr(row, "group_name", "") or ""),
                "topic": str(getattr(row, "topic", "") or ""),
                "text": str(
                    getattr(row, "scrubbed_text", "") or getattr(row, "raw_text", "") or ""
                ),
            }
            for row in rows
        ]
    )
    for flag in computed:
        left = by_id.get(str(flag.get("left_id") or ""))
        right = by_id.get(str(flag.get("right_id") or ""))
        if left is None or right is None:
            continue
        left_label = _group_of(left, labels)
        right_label = _group_of(right, labels)
        if not left_label or not right_label or left_label == right_label:
            continue
        key = (left_label, right_label) if left_label < right_label else (right_label, left_label)
        if key in stored:
            continue
        percent = _as_percent(flag.get("score"))
        entry = pairs.setdefault(key, _pair_entry(key[0], key[1]))
        entry["percent"] = max(int(entry["percent"]), percent)
        entry["passages"].append(
            {
                "id": f"{flag.get('section') or 'body'}-{len(entry['passages']) + 1}",
                "percent": percent,
                "common": False,
                "writing": "Medium" if percent >= 50 else "Low",
                "left": str(flag.get("passage_a") or ""),
                "right": str(flag.get("passage_b") or ""),
            }
        )
    return pairs


def _db_pair_status(pair: dict[str, Any]) -> str:
    counted = len([item for item in pair.get("passages") or [] if not item.get("common")])
    return _status(int(pair.get("percent") or 0), counted)


def _overall_status(statuses: list[str]) -> str:
    if "Concern" in statuses:
        return "Concern"
    if any(status != "Clear" for status in statuses):
        return "Review"
    return "Clear"


def _card_for_ref(ref: dict[str, Any]) -> dict[str, Any]:
    pairs = list(ref["pairs"].values())
    statuses = [_db_pair_status(pair) for pair in pairs]
    flagged = sum(1 for status in statuses if status != "Clear")
    highest = max((int(pair["percent"]) for pair in pairs), default=0)
    writing = sum(1 for pair in pairs if _writing_flag(pair.get("passages") or []))
    groups = len(set(ref["labels"].values()))
    course = ref["course"]
    return {
        "course": str(getattr(course, "code", "") or ""),
        "slug": ref["slug"],
        "title": str(getattr(course, "title", "") or ""),
        "number": str(ref["number"]),
        "name": str(ref["title"]),
        "groups": groups,
        "flagged_pairs": flagged,
        "highest": highest,
        "writing_flags": writing,
        "status": _overall_status(statuses),
        "analysis_sources": sorted(
            {str(pair.get("analysis_source") or "legacy-heuristic") for pair in pairs}
        ),
        "line": (
            f"{_count(groups, 'group', 'groups')} · "
            f"{_count(flagged, 'pair', 'pairs')} to read · "
            f"{_count(writing, 'writing flag', 'writing flags')}"
        ),
        "course_id": str(getattr(course, "id", "") or ""),
        "assessment_id": str(getattr(ref["assessment"], "id", "") or ""),
    }


def _prepare_refs(
    courses: list[Any],
    assessments: list[Any],
    group_assignments: list[Any],
    submissions: list[Any],
    flags: list[Any],
    wanted: str | None = None,
) -> list[dict[str, Any]]:
    refs = _assessment_refs(courses, assessments, group_assignments)
    prepared: list[dict[str, Any]] = []
    for ref in refs:
        if not _course_matches(ref["course"], wanted):
            continue
        rows = _assessment_rows(ref["assessment"], submissions)
        if not rows:
            continue
        labels = _group_labels(rows)
        ref["rows"] = rows
        ref["labels"] = labels
        ref["pairs"] = _pair_map(rows, flags, labels)
        prepared.append(ref)
    return prepared


def _find_ref(refs: list[dict[str, Any]], number: str) -> dict[str, Any] | None:
    target = str(number)
    # The overview links by display number. Resolve all display numbers
    # before considering aliases, since another assignment's ordinal can match.
    for ref in refs:
        if target == str(ref["number"]):
            return ref
    for ref in refs:
        assessment = ref["assessment"]
        if target in {str(ref["title"]), str(getattr(assessment, "external_id", "") or "")}:
            return ref
    return next((ref for ref in refs if target == str(ref["order"])), None)


async def overview_db(db: Any, org_id: Any, user_id: Any, course: str = "all") -> dict[str, Any]:
    """Courses and assignments with real submissions. Empty until a sync or upload."""
    wanted = None if not course or course == "all" else _norm(course)
    courses, assessments, group_assignments, submissions, flags = await _db_catalog(
        db, org_id, user_id
    )
    refs = _prepare_refs(courses, assessments, group_assignments, submissions, flags, wanted)
    cards = [_card_for_ref(ref) for ref in refs]
    courses_out: list[dict[str, str]] = []
    seen: set[str] = set()
    for ref in refs:
        slug = ref["slug"]
        if slug in seen:
            continue
        seen.add(slug)
        courses_out.append(
            {
                "code": str(getattr(ref["course"], "code", "") or ""),
                "slug": slug,
                "title": str(getattr(ref["course"], "title", "") or ""),
            }
        )
    cards.sort(key=lambda card: (card["slug"], str(card["number"])))
    return {
        "courses": courses_out,
        "summary": {
            "courses": len(courses_out),
            "assignments": len(cards),
            "groups": sum(card["groups"] for card in cards),
            "review": sum(1 for card in cards if card["status"] == "Review"),
            "concern": sum(1 for card in cards if card["status"] == "Concern"),
        },
        "items": cards,
    }


async def assignment_matrix_db(
    db: Any, org_id: Any, user_id: Any, course: str, number: str
) -> dict[str, Any]:
    courses, assessments, group_assignments, submissions, flags = await _db_catalog(
        db, org_id, user_id
    )
    found = _find_course(courses, course)
    if found is None:
        return {"error": "That course is not in this workspace."}
    refs = _prepare_refs([found], assessments, group_assignments, submissions, flags)
    ref = _find_ref(refs, number)
    if ref is None:
        return {"error": "That assignment is not in this course."}
    groups = sorted(set(ref["labels"].values()))
    matrix = [
        [
            100
            if left == right
            else int(
                ref["pairs"]
                .get((left, right) if left < right else (right, left), {"percent": 0})
                .get("percent", 0)
            )
            for right in groups
        ]
        for left in groups
    ]
    pairs: list[dict[str, Any]] = []
    for index, left in enumerate(groups):
        for right in groups[index + 1 :]:
            key = (left, right) if left < right else (right, left)
            entry = ref["pairs"].get(key)
            if entry is None:
                pairs.append(
                    {
                        "left": left,
                        "right": right,
                        "percent": 0,
                        "shared": 0,
                        "writing": False,
                        "status": "Clear",
                        "analysis_source": "legacy-heuristic",
                    }
                )
                continue
            passages = entry.get("passages") or []
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "percent": int(entry["percent"]),
                    "shared": len([item for item in passages if not item.get("common")]),
                    "writing": _writing_flag(passages),
                    "status": _db_pair_status(entry),
                    "analysis_source": entry.get("analysis_source", "legacy-heuristic"),
                }
            )
    pairs.sort(key=lambda row: row["percent"], reverse=True)
    course_row = ref["course"]
    return {
        "course": str(getattr(course_row, "code", "") or ""),
        "slug": ref["slug"],
        "assignment": str(ref["number"]),
        "name": str(ref["title"]),
        "groups": groups,
        "matrix": matrix,
        "pairs": pairs,
        "card": _card_for_ref(ref),
    }


def _passage_ranges(
    text: str, passages: list[dict[str, Any]], side: str
) -> list[tuple[int, int, dict[str, Any]]]:
    ranges = []
    for passage in passages:
        start, end = passage.get(f"{side}_start"), passage.get(f"{side}_end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text):
            ranges.append((start, end, passage))
            continue
        words = str(passage.get(side) or "").split()
        if words:
            pattern = r"\s+".join(re.escape(word) for word in words)
            ranges.extend(
                (match.start(), match.end(), passage) for match in re.finditer(pattern, text)
            )
    return ranges


def _document_paragraphs(
    text: str, passages: list[dict[str, Any]], side: str
) -> list[dict[str, Any]]:
    if not text.strip():
        return [{"runs": [_run("No text was stored for this submission.")]}]

    # Keep offsets in the original text, including CRLF and leading whitespace.
    paragraph_breaks = list(re.finditer(r"(?>\r\n|[\r\n])[^\S\r\n]*(?>\r\n|[\r\n])", text))
    paragraph_starts = [0, *(match.end() for match in paragraph_breaks)]
    paragraph_ends = [*(match.start() for match in paragraph_breaks), len(text)]
    ranges = _passage_ranges(text, passages, side)
    paragraphs: list[dict[str, Any]] = []
    for start, end in zip(paragraph_starts, paragraph_ends, strict=True):
        body = text[start:end]
        if not body.strip():
            continue
        start += len(body) - len(body.lstrip())
        end -= len(body) - len(body.rstrip())
        overlapping = [
            (max(start, lower), min(end, upper), passage)
            for lower, upper, passage in ranges
            if lower < end and upper > start
        ]
        boundaries = sorted(
            {start, end, *(point for lower, upper, _ in overlapping for point in (lower, upper))}
        )
        runs = []
        for lower, upper in pairwise(boundaries):
            covered = [passage for a, b, passage in overlapping if a <= lower and upper <= b]
            ids = list(dict.fromkeys(str(passage.get("id") or "") for passage in covered))
            run = _run(
                text[lower:upper],
                ids[0] if ids else "",
                bool(ids) and all(p.get("common") for p in covered),
            )
            if len(ids) > 1:
                run["ids"] = ids
            runs.append(run)
        paragraphs.append({"runs": runs})
    return paragraphs


def _submitted_label(submission: Any) -> str:
    created = getattr(submission, "created_at", None)
    if created is None:
        return ""
    try:
        return created.strftime("%d %b %Y")
    except AttributeError:
        return str(created)[:10]


def _matches_from_passages(
    passages: list[dict[str, Any]], decisions: dict[str, str]
) -> list[dict[str, Any]]:
    labels = {
        "shared": "Shared",
        "brief": "From the brief - not counted",
        "readings": "From readings - not counted",
    }
    box = {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
    matches: list[dict[str, Any]] = []
    for index, passage in enumerate(passages):
        left = str(passage.get("left") or "")
        common = bool(passage.get("common"))
        if common and "reading" in left.lower():
            source = "readings"
        elif common:
            source = "brief"
        else:
            source = "shared"
        match_id = str(passage.get("id") or f"m{index + 1}")
        matches.append(
            {
                "id": match_id,
                "percent": int(passage.get("percent") or 0),
                "source": source,
                "tag": labels[source],
                "quote": left or str(passage.get("right") or ""),
                "context": "",
                "page_left": 1,
                "page_right": 1,
                "left_box": dict(box),
                "right_box": dict(box),
                "decision": decisions.get(match_id, "pending"),
                "left_start": passage.get("left_start"),
                "left_end": passage.get("left_end"),
                "right_start": passage.get("right_start"),
                "right_end": passage.get("right_end"),
                "left_version_id": passage.get("left_version_id"),
                "right_version_id": passage.get("right_version_id"),
                "analysis_source": passage.get("source") or "legacy-heuristic",
            }
        )
    matches.sort(key=lambda row: row["percent"], reverse=True)
    return matches


def _empty_document(group: str) -> dict[str, Any]:
    return {
        "group": group,
        "origin": "",
        "converter": "",
        "pages": 0,
        "view": "",
        "original": "",
        "filename": "",
    }


def _first_for_group(rows: list[Any], labels: dict[str, str], group: str) -> Any | None:
    matches = [row for row in rows if _group_of(row, labels) == group]
    if not matches:
        return None
    matches.sort(key=lambda row: str(getattr(row, "id", "")))
    return matches[0]


async def pair_detail_db(
    db: Any, org_id: Any, user_id: Any, course: str, number: str, left: str, right: str
) -> dict[str, Any]:
    courses, assessments, group_assignments, submissions, flags = await _db_catalog(
        db, org_id, user_id
    )
    found = _find_course(courses, course)
    if found is None:
        return {"error": "That course is not in this workspace."}
    refs = _prepare_refs([found], assessments, group_assignments, submissions, flags)
    ref = _find_ref(refs, number)
    if ref is None:
        return {"error": "That assignment is not in this course."}
    labels = ref["labels"]
    left_label = _group_letter(str(left)) or str(left).upper()[:1]
    right_label = _group_letter(str(right)) or str(right).upper()[:1]
    if left_label not in set(labels.values()) or right_label not in set(labels.values()):
        return {"error": "That pair is not in this workspace."}
    left_row = _first_for_group(ref["rows"], labels, left_label)
    right_row = _first_for_group(ref["rows"], labels, right_label)
    if left_row is None or right_row is None:
        return {"error": "That pair is not in this workspace."}
    key = (left_label, right_label) if left_label < right_label else (right_label, left_label)
    entry = ref["pairs"].get(key) or _pair_entry(key[0], key[1])
    passages = list(entry.get("passages") or [])
    review_versions = entry.get("review_versions") or []
    if review_versions:
        passages = [
            passage
            for passage in passages
            if passage.get("left_version_id") == review_versions[0]
            and passage.get("right_version_id") == review_versions[1]
        ]
    percent = int(entry.get("percent") or 0)
    pair_id = _pair_id(ref["slug"], str(ref["number"]), left_label, right_label)
    from app.profassist.integrity_docs import load_decisions, summarise

    decisions = load_decisions().get(pair_id, {})
    matches = _matches_from_passages(passages, decisions)
    left_text = str(
        getattr(left_row, "scrubbed_text", "") or getattr(left_row, "raw_text", "") or ""
    )
    right_text = str(
        getattr(right_row, "scrubbed_text", "") or getattr(right_row, "raw_text", "") or ""
    )
    version_ids = {
        str(value)
        for passage in passages
        for value in (passage.get("left_version_id"), passage.get("right_version_id"))
        if value
    }
    version_map: dict[str, IntegritySourceVersion] = {}
    if version_ids:
        version_result = await db.execute(
            select(IntegritySourceVersion).where(
                IntegritySourceVersion.organization_id == org_id,
                IntegritySourceVersion.id.in_([uuid.UUID(value) for value in version_ids]),
            )
        )
        version_map = {str(row.id): row for row in version_result.scalars().all()}
        texts = {key: row.text_content for key, row in version_map.items()}
        for passage in passages:
            if passage.get("left_version_id") in texts:
                left_text = texts[passage["left_version_id"]]
                break
        for passage in passages:
            if passage.get("right_version_id") in texts:
                right_text = texts[passage["right_version_id"]]
                break
    if review_versions:
        left_version_id, right_version_id = review_versions
        if left_version_id not in version_map or right_version_id not in version_map:
            version_result = await db.execute(
                select(IntegritySourceVersion).where(
                    IntegritySourceVersion.organization_id == org_id,
                    IntegritySourceVersion.id.in_(
                        [uuid.UUID(left_version_id), uuid.UUID(right_version_id)]
                    ),
                ),
            )
            version_map.update({str(row.id): row for row in version_result.scalars().all()})
        left_version = version_map.get(left_version_id)
        right_version = version_map.get(right_version_id)
        if left_version is not None and right_version is not None:
            left_text = left_version.text_content
            right_text = right_version.text_content
            left_row = next(
                (
                    row
                    for row in ref["rows"]
                    if str(getattr(row, "id", "")) == str(left_version.submission_id)
                ),
                left_row,
            )
            right_row = next(
                (
                    row
                    for row in ref["rows"]
                    if str(getattr(row, "id", "")) == str(right_version.submission_id)
                ),
                right_row,
            )
    course_row = ref["course"]
    return {
        "course": str(getattr(course_row, "code", "") or ""),
        "slug": ref["slug"],
        "assignment": str(ref["number"]),
        "course_id": str(getattr(course_row, "id", "") or ""),
        "assessment_id": str(getattr(ref["assessment"], "id", "") or ""),
        "name": str(ref["title"]),
        "left": left_label,
        "right": right_label,
        "left_version_id": review_versions[0] if review_versions else None,
        "right_version_id": review_versions[1] if review_versions else None,
        "percent": percent,
        "status": _db_pair_status(entry),
        "analysis_source": entry.get("analysis_source", "legacy-heuristic"),
        "left_text": _document_paragraphs(left_text, passages, "left"),
        "right_text": _document_paragraphs(right_text, passages, "right"),
        "left_meta": {
            "members": "",
            "submitted": _submitted_label(left_row),
        },
        "right_meta": {
            "members": "",
            "submitted": _submitted_label(right_row),
        },
        "passages": passages,
        "matches": matches,
        "decisions": summarise(matches, decisions),
        "documents": {
            "left": _empty_document(left_label),
            "right": _empty_document(right_label),
        },
        "why": (
            "The highlight is the wording that appears in both submissions. "
            "A line that also appears in the assignment brief or the readings is marked "
            "as a common source and is not treated as copying."
        ),
    }
