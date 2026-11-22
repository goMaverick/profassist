"""Deadline batch. The professor still approves every draft before a push."""

import uuid

from prefect import flow
from sqlalchemy import select

from app.db.session import get_db_context
from app.profassist.models import Submission
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
