"""Tenant-scoped tables. Every row carries organization_id."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _org() -> Mapped[uuid.UUID]:
    return mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class Course(Base, TimestampMixin):
    __tablename__ = "pa_courses"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_pa_course_code"),)

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    term: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    clos: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    ai_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Material(Base, TimestampMixin):
    __tablename__ = "pa_materials"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pa_courses.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scrubbed_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    pii_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class Chunk(Base, TimestampMixin):
    __tablename__ = "pa_chunks"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    material_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pa_materials.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    ordinal: Mapped[int] = mapped_column(nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class Objective(Base, TimestampMixin):
    __tablename__ = "pa_objectives"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    ordinal: Mapped[int] = mapped_column(nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    source_chunk_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class SlideDeck(Base, TimestampMixin):
    __tablename__ = "pa_slide_decks"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slides: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    week: Mapped[int] = mapped_column(nullable=False, default=0)
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Assessment(Base, TimestampMixin):
    __tablename__ = "pa_assessments"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    clos: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    weight: Mapped[int] = mapped_column(nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="assignment")
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    alignment: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class RubricCriterion(Base, TimestampMixin):
    __tablename__ = "pa_rubric_criteria"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pa_assessments.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    weight: Mapped[int] = mapped_column(nullable=False, default=1)
    levels: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class StyleProfile(Base, TimestampMixin):
    __tablename__ = "pa_style_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_pa_style_user"),)

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    soul_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    about_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    about_history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    template_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class Student(Base, TimestampMixin):
    __tablename__ = "pa_students"
    __table_args__ = (UniqueConstraint("organization_id", "external_id", name="uq_pa_student_ext"),)

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    student_number: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class Submission(Base, TimestampMixin):
    __tablename__ = "pa_submissions"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_id", name="uq_pa_submission_ext"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    group_name: Mapped[str] = mapped_column(String(128), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scrubbed_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pii_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    peer_reviews: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="moodle")
    author_external_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    idea_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class SubmissionFile(Base, TimestampMixin):
    __tablename__ = "pa_submission_files"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pa_submissions.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")


class CourseDesign(Base, TimestampMixin):
    """One course outline per professor. Not shared with other professors."""

    __tablename__ = "pa_course_designs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "course_id", "owner_user_id", name="uq_pa_design_owner"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pa_courses.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class SubjectOutline(Base, TimestampMixin):
    """Working subject outline for one professor. Finished rows are normalized below."""

    __tablename__ = "pa_subject_outlines"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "owner_user_id", "code", name="uq_pa_outline_owner_code"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    pdf_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    docx_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ProgramOutcome(Base, TimestampMixin):
    __tablename__ = "pa_program_outcomes"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    outline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_subject_outlines.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")


class CourseOutcome(Base, TimestampMixin):
    __tablename__ = "pa_course_outcomes"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    outline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_subject_outlines.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")


class OutcomeMap(Base, TimestampMixin):
    __tablename__ = "pa_outcome_maps"
    __table_args__ = (UniqueConstraint("clo_id", "plo_id", name="uq_pa_clo_plo"),)

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    clo_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_course_outcomes.id", ondelete="CASCADE"),
        nullable=False,
    )
    plo_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_program_outcomes.id", ondelete="CASCADE"),
        nullable=False,
    )


class OutlineWeek(Base, TimestampMixin):
    __tablename__ = "pa_outline_weeks"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    outline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_subject_outlines.id", ondelete="CASCADE"),
        nullable=False,
    )
    week: Mapped[int] = mapped_column(nullable=False, default=1)
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lo_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    session_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    delivery: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    assessment_note: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class OutlineReading(Base, TimestampMixin):
    __tablename__ = "pa_outline_readings"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    outline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_subject_outlines.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False, default=1)
    citation: Mapped[str] = mapped_column(Text, nullable=False, default="")


class OutlineTask(Base, TimestampMixin):
    """An assessment on the subject outline, numbered A1, A2, and linked to CLOs."""

    __tablename__ = "pa_outline_tasks"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    outline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_subject_outlines.id", ondelete="CASCADE"),
        nullable=False,
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    number: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    weight: Mapped[int] = mapped_column(nullable=False, default=0)
    due: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    lo_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    criteria: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class OutlinePolicy(Base, TimestampMixin):
    __tablename__ = "pa_outline_policies"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    outline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_subject_outlines.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")


class GroupAssignment(Base, TimestampMixin):
    """A published assignment for groups, tied to one outline assessment."""

    __tablename__ = "pa_group_assignments"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    outline_task_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    number: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    weight: Mapped[int] = mapped_column(nullable=False, default=0)
    due: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    lo_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")


class AssignmentIdea(Base, TimestampMixin):
    __tablename__ = "pa_assignment_ideas"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_group_assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deliverables: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")


class StudentGroup(Base, TimestampMixin):
    __tablename__ = "pa_student_groups"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    member_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class GroupAllocation(Base, TimestampMixin):
    __tablename__ = "pa_group_allocations"
    __table_args__ = (UniqueConstraint("group_id", name="uq_pa_group_one_idea"),)

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_student_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    idea_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_assignment_ideas.id", ondelete="CASCADE"),
        nullable=False,
    )


class Exemplar(Base, TimestampMixin):
    __tablename__ = "pa_exemplars"
    __table_args__ = (UniqueConstraint("idea_id", name="uq_pa_exemplar_idea"),)

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    idea_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_assignment_ideas.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    strong: Mapped[str] = mapped_column(Text, nullable=False, default="")
    average: Mapped[str] = mapped_column(Text, nullable=False, default="")
    weak: Mapped[str] = mapped_column(Text, nullable=False, default="")


class OutlineReview(Base, TimestampMixin):
    """One versioned review of a subject outline. Older runs stay on the course."""

    __tablename__ = "pa_outline_reviews"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    outline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_subject_outlines.id", ondelete="CASCADE"),
        nullable=False,
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="single")
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False, default="curriculum")
    score: Mapped[int] = mapped_column(nullable=False, default=0)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    debate: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trace_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class GradeDraft(Base, TimestampMixin):
    __tablename__ = "pa_grade_drafts"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pa_submissions.id", ondelete="CASCADE"), nullable=False
    )
    results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    overall_feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    blind: Mapped[bool] = mapped_column(nullable=False, default=False)
    blind_revealed: Mapped[bool] = mapped_column(nullable=False, default=False)
    bundle_version: Mapped[str] = mapped_column(String(64), nullable=False, default="poc-1")
    trace_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    professor_levels: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class IntegrityFlag(Base, TimestampMixin):
    __tablename__ = "pa_integrity_flags"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    left_submission_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    right_submission_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    section: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    passage_a: Mapped[str] = mapped_column(Text, nullable=False, default="")
    passage_b: Mapped[str] = mapped_column(Text, nullable=False, default="")
    score: Mapped[float] = mapped_column(nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="fingerprint")
    viva: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rare_details: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")


class Approval(Base, TimestampMixin):
    __tablename__ = "pa_approvals"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MoodleSyncRun(Base, TimestampMixin):
    """One audit row for a Moodle pull. The schedule is the usual writer."""

    __tablename__ = "pa_moodle_sync_runs"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="schedule")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="fake")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MoodleGroup(Base, TimestampMixin):
    __tablename__ = "pa_moodle_groups"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    moodle_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    grouping: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="fake")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MoodleActivity(Base, TimestampMixin):
    __tablename__ = "pa_moodle_activity"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    course_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    student_external_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_access: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    logins_14d: Mapped[int] = mapped_column(nullable=False, default=0)
    completion: Mapped[float] = mapped_column(nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="fake")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MoodlePush(Base, TimestampMixin):
    __tablename__ = "pa_moodle_pushes"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Reflection(Base, TimestampMixin):
    __tablename__ = "pa_reflections"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    proposal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")


class PiiVault(Base, TimestampMixin):
    __tablename__ = "pa_pii_vault"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class AiSettings(Base, TimestampMixin):
    """One row per university. Admins edit it; professors do not."""

    __tablename__ = "pa_ai_settings"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_pa_ai_settings_org"),)

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    chat_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="gpt-4o-mini")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    debate_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    debate_threshold: Mapped[int] = mapped_column(nullable=False, default=0)
    debate_max_rounds: Mapped[int] = mapped_column(nullable=False, default=1)
    agent_models: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    moodle_sync_paused: Mapped[bool] = mapped_column(nullable=False, default=False)
    moodle_sync_minutes: Mapped[int] = mapped_column(nullable=False, default=30)
    moodle_nightly_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    moodle_nightly_hour: Mapped[int] = mapped_column(nullable=False, default=2)


class PromptVersion(Base, TimestampMixin):
    __tablename__ = "pa_prompt_versions"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class PromptAudit(Base, TimestampMixin):
    __tablename__ = "pa_prompt_audit"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    before: Mapped[str] = mapped_column(Text, nullable=False, default="")
    after: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AgentToolSetting(Base, TimestampMixin):
    __tablename__ = "pa_agent_tools"
    __table_args__ = (
        UniqueConstraint("organization_id", "agent_key", "tool_key", name="uq_pa_agent_tool"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    agent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class ProfessorMemory(Base, TimestampMixin):
    """Per-professor memory. Never shared with another professor in the same university."""

    __tablename__ = "pa_memories"

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = _org()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="preference")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
