"""Deadline batch. The professor still approves every draft before a push."""

import uuid

from prefect import flow
from sqlalchemy import select

from app.db.session import get_db_context
from app.profassist.course_memory.service import rebuild_course_memory
from app.profassist.models import Material, Submission
from app.profassist.service import run_grade


@flow(name="profassist-grade-batch", log_prints=True)
async def grade_batch_flow(organization_id: str, assessment_id: str, user_id: str) -> dict:
    graded = 0
    skipped = 0
    async with get_db_context() as db:
        result = await db.execute(
            select(Submission).where(
                Submission.organization_id == uuid.UUID(organization_id),
                Submission.assessment_id == uuid.UUID(assessment_id),
            )
        )
        for submission in result.scalars().all():
            try:
                await run_grade(db, uuid.UUID(organization_id), uuid.UUID(user_id), submission.id)
                graded += 1
            except Exception as exc:  # drafts already approved, or a missing rubric
                skipped += 1
                print(f"skipped {submission.id}: {exc}")
    return {"graded": graded, "skipped": skipped}


@flow(name="profassist-moodle-sync", log_prints=True)
async def moodle_sync_flow(full: bool = False) -> dict:
    """Primary Moodle pull. full=True is the nightly pass."""
    from app.integrations.moodle.gateway import sync_scheduled

    async with get_db_context() as db:
        result = await sync_scheduled(db, full=full)
    print(result)
    return result


@flow(name="profassist-course-memory", log_prints=True)
async def course_memory_flow(organization_id: str, course_id: str, user_id: str) -> dict:
    """Rebuild the merged course dossier after an upload. Never raises."""
    try:
        org = uuid.UUID(organization_id)
        course = uuid.UUID(course_id)
        user = uuid.UUID(user_id)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)[:300]}
    try:
        async with get_db_context() as db:
            result = await rebuild_course_memory(db, org, user, course)
        return {
            "ok": True,
            "trace_url": str(result.get("trace_url") or ""),
            "materials": result.get("materials") or [],
        }
    except Exception as exc:  # a background task must not raise
        try:
            async with get_db_context() as db:
                rows = (
                    (
                        await db.execute(
                            select(Material).where(
                                Material.organization_id == org,
                                Material.course_id == course,
                                Material.owner_user_id == user,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    row.insight_status = "failed"
                await db.flush()
        except Exception:
            pass
        return {"ok": False, "error": str(exc)[:300]}
