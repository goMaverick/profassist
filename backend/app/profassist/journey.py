"""Fresh-course student work, pulled through the fake Moodle door.

The names and the files are synthetic. The sync and the grade push use the same
connector as a real Moodle connection, and that connector does not open a
network call while MOODLE_MODE is fake.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.errors import ProfassistError
from app.profassist.models import Course, GradeDraft, GroupAssignment, Student, Submission

ROSTER = (
    ("1", "Sara Al Maktoum", "8889101"),
    ("2", "Omar Haddad", "8889102"),
    ("3", "Noor Rahman", "8889103"),
    ("4", "Layla Karim", "8889104"),
    ("5", "Hana Yusuf", "8889105"),
    ("6", "Adam Nasser", "8889106"),
    ("7", "Maya Farouk", "8889107"),
    ("8", "Rami Saleh", "8889108"),
)

PAIRS = (
    ("A", ("1", "2")),
    ("B", ("3", "4")),
    ("C", ("5", "6")),
    ("D", ("7", "8")),
)

_ACTIVE: dict[str, str] = {}


def assignment_number(slug: str) -> str:
    """Assignment number registered for a fresh course. Seeded courses stay on 1."""
    return _ACTIVE.get(slug, "1")


def _slug(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def fresh_board(code: str, title: str, number: str, name: str) -> dict[str, Any]:
    """Integrity board entry for one new assignment. Groups A and B share two sentences."""
    slug = _slug(code) or "COURSE"
    shared = "Peak arrivals cluster in the twenty minutes after the 2pm workshop."
    meter = "The meter on level two reads 42.7 during the Thursday class change."
    brief = "The brief asks each group to name one campus process and measure it for four weeks."
    return {
        "code": code,
        "slug": slug,
        "title": title,
        "assignments": [
            {
                "number": str(number),
                "title": name,
                "groups": ["A", "B", "C", "D"],
                "pairs": [
                    {
                        "left": "A",
                        "right": "B",
                        "percent": 86,
                        "passages": [
                            {
                                "id": "j1",
                                "percent": 92,
                                "common": False,
                                "writing": "Medium",
                                "left": shared,
                                "right": shared,
                            },
                            {
                                "id": "j2",
                                "percent": 88,
                                "common": False,
                                "writing": "Low",
                                "left": meter,
                                "right": meter,
                            },
                            {
                                "id": "j3",
                                "percent": 100,
                                "common": True,
                                "writing": "Low",
                                "left": brief,
                                "right": brief,
                            },
                        ],
                    },
                    {
                        "left": "C",
                        "right": "D",
                        "percent": 22,
                        "passages": [
                            {
                                "id": "j4",
                                "percent": 22,
                                "common": False,
                                "writing": "Low",
                                "left": "We counted the east stair only, and we would repeat that count.",
                                "right": "Our count used the print desk, not the east stair.",
                            }
                        ],
                    },
                ],
            }
        ],
    }


async def _assignment(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> GroupAssignment:
    from app.profassist.groupwork import _assignment as owned

    return await owned(db, org_id, user_id, assignment_id)


async def _course(db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID) -> Course:
    course = await db.get(Course, course_id)
    if course is None or course.organization_id != org_id:
        raise ProfassistError(404, "That course is not in your workspace.")
    return course


async def _ensure_students(db: AsyncSession, org_id: uuid.UUID, course: Course) -> list[Student]:
    slug = _slug(course.code)
    stored: list[Student] = []
    for number, name, student_number in ROSTER:
        external = f"j-{slug}-{number}"
        found = await db.execute(
            select(Student).where(
                Student.organization_id == org_id, Student.external_id == external
            )
        )
        student = found.scalar_one_or_none()
        if student is None:
            student = Student(
                organization_id=org_id,
                course_id=course.id,
                external_id=external,
                display_name=name,
                email="",
                student_number=student_number,
            )
            db.add(student)
            await db.flush()
        stored.append(student)
    return stored


async def form_class(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> dict[str, Any]:
    """Pair a synthetic class list into four groups and give each group an idea."""
    from app.profassist.groupwork import allocate, assignment_view, save_groups

    row = await _assignment(db, org_id, user_id, assignment_id)
    course = await _course(db, org_id, row.course_id)
    students = await _ensure_students(db, org_id, course)
    by_external = {item.external_id: str(item.id) for item in students}
    slug = _slug(course.code)
    groups = [
        {
            "name": f"Group {letter}",
            "member_ids": [by_external[f"j-{slug}-{member}"] for member in members],
        }
        for letter, members in PAIRS
    ]
    await save_groups(db, org_id, user_id, course.id, groups)
    view = await assignment_view(db, org_id, user_id, assignment_id)
    if view["ideas"]:
        view = await allocate(db, org_id, user_id, assignment_id)
    view["message"] = f"{len(groups)} groups are ready. The names are synthetic."
    view["students"] = len(students)
    return view


def _files_for(slug: str, number: str) -> list[dict[str, Any]]:
    from app.profassist.integrity_docs import file_bytes

    submissions = []
    for letter, members in PAIRS:
        data, media, filename = file_bytes(slug, number, letter, "original")
        if not data:
            raise ProfassistError(500, "The submission file was not built.")
        submissions.append(
            {
                "id": f"sub-{slug.lower()}-{letter.lower()}",
                "assignment_id": f"asg-{slug.lower()}",
                "group_name": f"Group {letter}",
                "topic": "group submission",
                "author_id": f"j-{slug}-{members[0]}",
                "text": (
                    f"Group {letter} submitted its own file for this assignment. "
                    "The file is the work the integrity page opens."
                ),
                "files": [{"filename": filename, "content_type": media, "data": data}],
            }
        )
    return submissions


async def receive_submissions(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> dict[str, Any]:
    """Stage PDF and DOCX submissions on the fake connector, then sync them in."""
    from app.integrations.moodle.gateway import sync as gateway_sync
    from app.profassist.groupwork import assignment_view, list_submissions
    from app.profassist.integrity_board import register_course
    from app.profassist.integrity_docs import reset_library
    from app.profassist.moodle import get_connector

    await form_class(db, org_id, user_id, assignment_id)
    row = await _assignment(db, org_id, user_id, assignment_id)
    course = await _course(db, org_id, row.course_id)
    board = fresh_board(course.code, course.title, row.number or "1", row.title or "Assignment")
    register_course(board)
    _ACTIVE[board["slug"]] = str(row.number or "1")
    reset_library()
    slug = board["slug"]
    connector = get_connector()
    stage = getattr(connector, "stage_course_work", None)
    if stage is None:
        raise ProfassistError(
            400, "Student submissions can be staged only while Moodle is in fake mode."
        )
    stage(
        course={
            "id": f"mdl-{slug.lower()}",
            "code": course.code,
            "title": course.title,
            "term": course.term or "",
        },
        students=[
            {
                "id": f"j-{slug}-{number}",
                "course_id": f"mdl-{slug.lower()}",
                "display_name": name,
                "email": "",
                "student_number": student_number,
            }
            for number, name, student_number in ROSTER
        ],
        assignment={
            "id": f"asg-{slug.lower()}",
            "course_id": f"mdl-{slug.lower()}",
            "name": row.title,
            "kind": "assignment",
            "rubric": [],
        },
        submissions=_files_for(slug, str(row.number or "1")),
    )
    pulled = await gateway_sync(db, org_id, user_id, trigger="manual")
    await _ensure_draft(db, org_id, user_id, course.id)
    items = await list_submissions(db, org_id, user_id, assignment_id)
    view = await assignment_view(db, org_id, user_id, assignment_id)
    return {
        "assignment": view,
        "submissions": items,
        "pulled": pulled,
        "slug": slug,
        "number": str(row.number or "1"),
        "message": (
            f"{len(items)} submissions synced. The files are synthetic PDF and DOCX. "
            "Moodle was not contacted."
        ),
    }


async def _ensure_draft(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> GradeDraft | None:
    found = await db.execute(
        select(Submission).where(
            Submission.organization_id == org_id,
            Submission.course_id == course_id,
            Submission.group_name == "Group A",
        )
    )
    submission = found.scalars().first()
    if submission is None:
        return None
    existing = await db.execute(
        select(GradeDraft)
        .where(
            GradeDraft.organization_id == org_id,
            GradeDraft.owner_user_id == user_id,
            GradeDraft.submission_id == submission.id,
        )
        .order_by(GradeDraft.created_at.desc())
    )
    draft = existing.scalars().first()
    if draft is not None:
        return draft
    draft = GradeDraft(
        organization_id=org_id,
        owner_user_id=user_id,
        submission_id=submission.id,
        results=[],
        overall_feedback="A solid first draft. Check the rubric before you approve it.",
        status="draft",
        blind=False,
        blind_revealed=False,
    )
    db.add(draft)
    await db.flush()
    return draft


async def _find_course(db: AsyncSession, org_id: uuid.UUID, course_code: str) -> Course:
    wanted = _slug(course_code)
    result = await db.execute(select(Course).where(Course.organization_id == org_id))
    for course in result.scalars().all():
        if _slug(course.code) == wanted:
            return course
    raise ProfassistError(404, "That course is not in your workspace.")


async def send_grade(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_code: str, group: str
) -> dict[str, Any]:
    """Approve the draft if needed, push it through the fake connector, mark complete."""
    from app.profassist.service import approve_draft, push_draft

    course = await _find_course(db, org_id, course_code)
    found = await db.execute(
        select(Submission).where(
            Submission.organization_id == org_id,
            Submission.course_id == course.id,
            Submission.group_name == group,
        )
    )
    submission = found.scalars().first()
    if submission is None:
        raise ProfassistError(404, "That group has not submitted yet.")
    draft = await _ensure_draft(db, org_id, user_id, course.id)
    if draft is None or draft.submission_id != submission.id:
        draft = (
            (
                await db.execute(
                    select(GradeDraft)
                    .where(
                        GradeDraft.organization_id == org_id,
                        GradeDraft.owner_user_id == user_id,
                        GradeDraft.submission_id == submission.id,
                    )
                    .order_by(GradeDraft.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
    if draft is None:
        raise ProfassistError(404, "There is no grade draft for that group.")
    receipt: dict[str, Any] = {}
    if draft.status == "draft":
        await approve_draft(db, org_id, user_id, draft.id)
        await db.refresh(draft)
    if draft.status == "approved":
        pushed = await push_draft(db, org_id, user_id, draft.id)
        receipt = pushed.get("receipt") or {}
    elif draft.status == "pushed":
        receipt = {
            "mode": "fake",
            "moodle_response": "Already recorded. Moodle was not contacted.",
        }
    assignments = (
        await db.execute(
            select(GroupAssignment).where(
                GroupAssignment.organization_id == org_id,
                GroupAssignment.owner_user_id == user_id,
                GroupAssignment.course_id == course.id,
            )
        )
    ).scalars()
    for item in assignments:
        item.status = "complete"
    await db.flush()
    return {
        "message": "Sent to Moodle",
        "note": receipt.get("moodle_response")
        or "Recorded in ProfAssist. Moodle was not contacted.",
        "mode": receipt.get("mode") or "fake",
        "assignment_status": "complete",
        "group": group,
    }
