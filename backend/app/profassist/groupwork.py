"""Group assignments, idea allocation, exemplars, and a pluggable similarity check."""

import uuid
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.errors import ProfassistError
from app.profassist.models import (
    AssignmentIdea,
    Course,
    Exemplar,
    GroupAllocation,
    GroupAssignment,
    Student,
    StudentGroup,
    SubjectOutline,
    Submission,
)
from app.profassist.similarity import cosine, hash_embed


class SimilarityModel(Protocol):
    """Swap this for a trained model later. The page only needs pairwise scores."""

    def score(self, left: str, right: str) -> float: ...


class HashSimilarity:
    """Embedding baseline. It does not train."""

    name = "hash-embedding"

    def score(self, left: str, right: str) -> float:
        return cosine(hash_embed(left), hash_embed(right))


def solution_text(submission: str, shared_brief: str) -> str:
    """Drop the shared idea brief so overlap on the use case is not treated as copying."""
    text = submission or ""
    brief = (shared_brief or "").strip()
    if brief and brief in text:
        text = text.replace(brief, " ")
    return " ".join(text.split())


def pairwise_similarity(
    rows: list[dict[str, str]],
    *,
    model: SimilarityModel | None = None,
    threshold: float = 0.82,
) -> list[dict[str, Any]]:
    """Compare solution text. rows need id, group, idea_id, text, brief."""
    checker = model or HashSimilarity()
    flags = []
    for left in range(len(rows)):
        for right in range(left + 1, len(rows)):
            a, b = rows[left], rows[right]
            left_text = solution_text(a.get("text") or "", a.get("brief") or "")
            right_text = solution_text(b.get("text") or "", b.get("brief") or "")
            if not left_text or not right_text:
                continue
            score = checker.score(left_text, right_text)
            if score < threshold:
                continue
            flags.append(
                {
                    "left_id": a.get("id"),
                    "right_id": b.get("id"),
                    "left_group": a.get("group"),
                    "right_group": b.get("group"),
                    "same_idea": a.get("idea_id") == b.get("idea_id"),
                    "score": round(score, 3),
                    "left_excerpt": left_text[:280],
                    "right_excerpt": right_text[:280],
                    "model": getattr(checker, "name", "custom"),
                }
            )
    return flags


def round_robin(group_ids: list[str], idea_ids: list[str]) -> list[tuple[str, str]]:
    if not idea_ids:
        return []
    return [(group, idea_ids[index % len(idea_ids)]) for index, group in enumerate(group_ids)]


def balance_groups(student_ids: list[str], size: int = 3) -> list[list[str]]:
    if size < 1:
        size = 1
    return [student_ids[index : index + size] for index in range(0, len(student_ids), size)]


async def _assignment(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> GroupAssignment:
    row = await db.get(GroupAssignment, assignment_id)
    if row is None or row.organization_id != org_id or row.owner_user_id != user_id:
        raise ProfassistError(404, "That assignment is not in your workspace.")
    return row


async def create_from_task(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    course_id: uuid.UUID,
    number: str,
    title: str,
    weight: int,
    due: str,
    lo_codes: list[str],
    outline_task_id: str = "",
    assessment_id: str = "",
    body: str = "",
) -> dict[str, Any]:
    row = GroupAssignment(
        organization_id=org_id,
        owner_user_id=user_id,
        course_id=course_id,
        outline_task_id=uuid.UUID(outline_task_id) if outline_task_id else None,
        assessment_id=uuid.UUID(assessment_id) if assessment_id else None,
        number=number,
        title=title,
        body=body,
        weight=weight,
        due=due,
        lo_codes=lo_codes,
    )
    db.add(row)
    await db.flush()
    return _assignment_public(row, [], [])


async def draft_text(title: str, lo_codes: list[str], instructions: str) -> str:
    from app.profassist.llm import complete

    drafted = complete(
        "assignment_text",
        {"title": title, "lo_codes": lo_codes, "instructions": instructions},
    )
    return drafted.get("body") or ""


async def propose_ideas(title: str, body: str, lo_codes: list[str]) -> list[dict[str, str]]:
    from app.profassist.llm import complete

    if not tool_enabled():
        return []
    drafted = complete(
        "ideas",
        {"title": title, "body": body, "lo_codes": lo_codes, "instructions": body},
    )
    return drafted.get("ideas") or []


def tool_enabled() -> bool:
    from app.profassist.runtime import tool_enabled as enabled

    return enabled("idea_generator", "propose")


async def save_ideas(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    ideas: list[dict[str, str]],
) -> dict[str, Any]:
    row = await _assignment(db, org_id, user_id, assignment_id)
    await db.execute(
        AssignmentIdea.__table__.delete().where(AssignmentIdea.assignment_id == row.id)
    )
    stored = []
    for item in ideas:
        idea = AssignmentIdea(
            organization_id=org_id,
            owner_user_id=user_id,
            assignment_id=row.id,
            title=item.get("title") or "Idea",
            brief=item.get("brief") or "",
            deliverables=item.get("deliverables") or "",
            evidence=item.get("evidence") or "",
        )
        db.add(idea)
        stored.append(idea)
    await db.flush()
    return await assignment_view(db, org_id, user_id, assignment_id)


async def save_groups(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    await db.execute(
        StudentGroup.__table__.delete().where(
            StudentGroup.organization_id == org_id,
            StudentGroup.owner_user_id == user_id,
            StudentGroup.course_id == course_id,
        )
    )
    created = []
    for item in groups:
        row = StudentGroup(
            organization_id=org_id,
            owner_user_id=user_id,
            course_id=course_id,
            name=item.get("name") or "Group",
            member_ids=item.get("member_ids") or [],
        )
        db.add(row)
        created.append(row)
    await db.flush()
    return [{"id": str(row.id), "name": row.name, "member_ids": row.member_ids} for row in created]


async def allocate(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    pairs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    row = await _assignment(db, org_id, user_id, assignment_id)
    ideas = (
        (await db.execute(select(AssignmentIdea).where(AssignmentIdea.assignment_id == row.id)))
        .scalars()
        .all()
    )
    groups = (
        (
            await db.execute(
                select(StudentGroup).where(
                    StudentGroup.organization_id == org_id,
                    StudentGroup.course_id == row.course_id,
                    StudentGroup.owner_user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if pairs is None:
        pairs = [
            {"group_id": group, "idea_id": idea}
            for group, idea in round_robin(
                [str(item.id) for item in groups], [str(item.id) for item in ideas]
            )
        ]
    await db.execute(
        GroupAllocation.__table__.delete().where(
            GroupAllocation.group_id.in_([item.id for item in groups])
        )
    )
    for pair in pairs:
        db.add(
            GroupAllocation(
                organization_id=org_id,
                owner_user_id=user_id,
                group_id=uuid.UUID(pair["group_id"]),
                idea_id=uuid.UUID(pair["idea_id"]),
            )
        )
    await db.flush()
    return await assignment_view(db, org_id, user_id, assignment_id)


async def write_exemplars(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> dict[str, Any]:
    from app.profassist.llm import complete
    from app.profassist.runtime import tool_enabled as enabled

    if not enabled("exemplar", "write"):
        raise ProfassistError(403, "The exemplar agent is turned off.")
    row = await _assignment(db, org_id, user_id, assignment_id)
    ideas = (
        (await db.execute(select(AssignmentIdea).where(AssignmentIdea.assignment_id == row.id)))
        .scalars()
        .all()
    )
    for idea in ideas:
        drafted = complete(
            "exemplar",
            {
                "title": idea.title,
                "brief": idea.brief,
                "instructions": row.body,
                "lo_codes": row.lo_codes,
            },
        )
        existing = (
            await db.execute(select(Exemplar).where(Exemplar.idea_id == idea.id))
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                Exemplar(
                    organization_id=org_id,
                    owner_user_id=user_id,
                    idea_id=idea.id,
                    model_answer=drafted.get("model_answer") or "",
                    strong=drafted.get("strong") or "",
                    average=drafted.get("average") or "",
                    weak=drafted.get("weak") or "",
                )
            )
        else:
            existing.model_answer = drafted.get("model_answer") or existing.model_answer
            existing.strong = drafted.get("strong") or existing.strong
            existing.average = drafted.get("average") or existing.average
            existing.weak = drafted.get("weak") or existing.weak
    await db.flush()
    return await assignment_view(db, org_id, user_id, assignment_id)


async def publish_assignment(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> dict[str, Any]:
    from app.integrations.moodle.gateway import push as moodle_push

    row = await _assignment(db, org_id, user_id, assignment_id)
    receipt = await moodle_push(
        {
            "type": "assignment",
            "id": str(row.id),
            "title": row.title,
            "body": row.body,
        }
    )
    row.status = "published"
    await db.flush()
    view = await assignment_view(db, org_id, user_id, assignment_id)
    view["receipt"] = receipt
    return view


async def similarity_report(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> dict[str, Any]:
    row = await _assignment(db, org_id, user_id, assignment_id)
    ideas = {
        item.id: item
        for item in (
            await db.execute(select(AssignmentIdea).where(AssignmentIdea.assignment_id == row.id))
        ).scalars()
    }
    allocations = (
        (await db.execute(select(GroupAllocation).where(GroupAllocation.idea_id.in_(list(ideas)))))
        .scalars()
        .all()
        if ideas
        else []
    )
    idea_by_group = {item.group_id: item.idea_id for item in allocations}
    groups = {
        item.id: item
        for item in (
            await db.execute(select(StudentGroup).where(StudentGroup.course_id == row.course_id))
        ).scalars()
    }
    submissions = (
        (
            await db.execute(
                select(Submission).where(
                    Submission.organization_id == org_id,
                    Submission.course_id == row.course_id,
                )
            )
        )
        .scalars()
        .all()
    )
    prepared = []
    for submission in submissions:
        idea_id = submission.idea_id
        group = next((item for item in groups.values() if item.name == submission.group_name), None)
        if idea_id is None and group is not None:
            idea_id = idea_by_group.get(group.id)
        idea = ideas.get(idea_id) if idea_id else None
        if idea is None:
            continue
        prepared.append(
            {
                "id": str(submission.id),
                "group": submission.group_name,
                "idea_id": str(idea.id),
                "text": submission.scrubbed_text or submission.raw_text,
                "brief": idea.brief,
            }
        )
    flags = pairwise_similarity(prepared)
    return {
        "model": HashSimilarity.name,
        "trained": False,
        "threshold": 0.82,
        "pairs": flags,
        "note": "Shared idea briefs are removed before the comparison. A trained model can replace HashSimilarity later.",
    }


def merge_catalog(
    tasks: list[dict[str, Any]], stored: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Numbered outline tasks, with a saved assignment filling in the same number."""
    by_number = {str(item.get("number") or ""): item for item in stored}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        number = str(task.get("number") or "")
        existing = by_number.get(number)
        rows.append(
            {
                "id": (existing or {}).get("id") or "",
                "number": number,
                "title": (existing or {}).get("title")
                or task.get("name")
                or task.get("title")
                or number,
                "due": (existing or {}).get("due") or task.get("due") or "",
                "weight": (existing or {}).get("weight", task.get("weight") or 0),
                "status": (existing or {}).get("status") or "in outline",
                "lo_codes": task.get("lo_codes") or (existing or {}).get("lo_codes") or [],
                "brief": task.get("brief") or (existing or {}).get("body") or "",
                "criteria": task.get("criteria") or [],
            }
        )
        seen.add(number)
    for item in stored:
        number = str(item.get("number") or "")
        if number in seen:
            continue
        rows.append(
            {
                "id": item.get("id") or "",
                "number": number,
                "title": item.get("title") or number,
                "due": item.get("due") or "",
                "weight": item.get("weight") or 0,
                "status": item.get("status") or "draft",
                "lo_codes": item.get("lo_codes") or [],
                "brief": item.get("body") or "",
                "criteria": [],
            }
        )
    return rows


def _code(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


async def list_for_course(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> list[dict[str, Any]]:
    course = await db.get(Course, course_id)
    if course is None or course.organization_id != org_id:
        raise ProfassistError(404, "That course is not in this university.")
    stored_rows = (
        (
            await db.execute(
                select(GroupAssignment).where(
                    GroupAssignment.organization_id == org_id,
                    GroupAssignment.owner_user_id == user_id,
                    GroupAssignment.course_id == course_id,
                )
            )
        )
        .scalars()
        .all()
    )
    stored = [
        {
            "id": str(row.id),
            "number": row.number,
            "title": row.title,
            "due": row.due,
            "weight": row.weight,
            "status": row.status,
            "lo_codes": row.lo_codes,
            "body": row.body,
        }
        for row in stored_rows
    ]
    outlines = (
        (
            await db.execute(
                select(SubjectOutline).where(
                    SubjectOutline.organization_id == org_id,
                    SubjectOutline.owner_user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    wanted = _code(course.code)
    tasks: list[dict[str, Any]] = []
    for outline in outlines:
        body = outline.body or {}
        basics = body.get("basics") or {}
        code_matches = _code(str(basics.get("code") or outline.code)) == wanted
        if outline.course_id != course_id and not code_matches:
            continue
        tasks.extend(body.get("tasks") or [])
    return merge_catalog(tasks, stored)


async def assess_summary(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> dict[str, int]:
    from sqlalchemy import func

    from app.profassist.models import GradeDraft, IntegrityFlag

    groups = await db.scalar(
        select(func.count())
        .select_from(StudentGroup)
        .where(
            StudentGroup.organization_id == org_id,
            StudentGroup.owner_user_id == user_id,
            StudentGroup.course_id == course_id,
        )
    )
    submissions = await db.scalar(
        select(func.count())
        .select_from(Submission)
        .where(Submission.organization_id == org_id, Submission.course_id == course_id)
    )
    flags = await db.scalar(
        select(func.count())
        .select_from(IntegrityFlag)
        .where(
            IntegrityFlag.organization_id == org_id,
            IntegrityFlag.course_id == course_id,
            IntegrityFlag.status == "open",
        )
    )
    drafts = (
        (
            await db.execute(
                select(GradeDraft).where(
                    GradeDraft.organization_id == org_id,
                    GradeDraft.owner_user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    approved = sum(1 for row in drafts if row.status == "approved")
    return {
        "groups": int(groups or 0),
        "submissions": int(submissions or 0),
        "flags": int(flags or 0),
        "approved": approved,
        "drafts": len(drafts),
    }


async def list_submissions(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> list[dict[str, Any]]:
    row = await _assignment(db, org_id, user_id, assignment_id)
    query = select(Submission).where(
        Submission.organization_id == org_id,
        Submission.course_id == row.course_id,
    )
    if row.assessment_id:
        query = query.where(Submission.assessment_id == row.assessment_id)
    rows = (await db.execute(query)).scalars().all()
    items = []
    for submission in rows:
        text = submission.scrubbed_text or ""
        items.append(
            {
                "id": str(submission.id),
                "group_name": submission.group_name,
                "topic": submission.topic,
                "origin": submission.origin,
                "excerpt": text[:180],
            }
        )
    return items


async def roster(db: AsyncSession, org_id: uuid.UUID, course_id: uuid.UUID) -> list[dict[str, str]]:
    rows = (
        await db.execute(
            select(Student).where(Student.organization_id == org_id, Student.course_id == course_id)
        )
    ).scalars()
    return [{"id": str(row.id), "name": row.display_name} for row in rows]


async def assignment_view(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID
) -> dict[str, Any]:
    row = await _assignment(db, org_id, user_id, assignment_id)
    ideas = (
        (await db.execute(select(AssignmentIdea).where(AssignmentIdea.assignment_id == row.id)))
        .scalars()
        .all()
    )
    exemplars = (
        (
            await db.execute(
                select(Exemplar).where(Exemplar.idea_id.in_([item.id for item in ideas]))
            )
        )
        .scalars()
        .all()
        if ideas
        else []
    )
    by_idea = {item.idea_id: item for item in exemplars}
    groups = (
        (
            await db.execute(
                select(StudentGroup).where(
                    StudentGroup.course_id == row.course_id, StudentGroup.owner_user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    allocations = (
        (
            await db.execute(
                select(GroupAllocation).where(
                    GroupAllocation.group_id.in_([item.id for item in groups])
                )
            )
        )
        .scalars()
        .all()
        if groups
        else []
    )
    return _assignment_public(
        row,
        [
            {
                "id": str(idea.id),
                "title": idea.title,
                "brief": idea.brief,
                "deliverables": idea.deliverables,
                "evidence": idea.evidence,
                "exemplar": _exemplar_public(by_idea.get(idea.id)),
            }
            for idea in ideas
        ],
        [
            {
                "group_id": str(item.group_id),
                "idea_id": str(item.idea_id),
            }
            for item in allocations
        ],
        [{"id": str(item.id), "name": item.name, "member_ids": item.member_ids} for item in groups],
    )


def _exemplar_public(row: Exemplar | None) -> dict[str, str] | None:
    if row is None:
        return None
    return {
        "model_answer": row.model_answer,
        "strong": row.strong,
        "average": row.average,
        "weak": row.weak,
    }


def _assignment_public(row, ideas, allocations, groups=None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "course_id": str(row.course_id),
        "number": row.number,
        "title": row.title,
        "body": row.body,
        "weight": row.weight,
        "due": row.due,
        "lo_codes": row.lo_codes,
        "status": row.status,
        "ideas": ideas,
        "groups": groups or [],
        "allocations": allocations,
    }
