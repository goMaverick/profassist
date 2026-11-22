"""Subject outline, outcomes, schedule, readings, tasks, and policies.

Revision ID: 0034_subject_outline
Revises: 0033_course_flow
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0034_subject_outline"
down_revision = "0033_course_flow"
branch_labels = None
depends_on = None


def _id_cols():
    return [
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.add_column(
        "pa_courses",
        sa.Column("ai_instructions", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "pa_slide_decks",
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "pa_subject_outlines",
        *_id_cols(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(32), nullable=False, server_default=""),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("body", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("pdf_key", sa.String(500), nullable=False, server_default=""),
        sa.Column("docx_key", sa.String(500), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "organization_id", "owner_user_id", "code", name="uq_pa_outline_owner_code"
        ),
    )
    op.create_table(
        "pa_program_outcomes",
        *_id_cols(),
        sa.Column("outline_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outline_id"], ["pa_subject_outlines.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "pa_course_outcomes",
        *_id_cols(),
        sa.Column("outline_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outline_id"], ["pa_subject_outlines.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "pa_outcome_maps",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("clo_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("plo_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["clo_id"], ["pa_course_outcomes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plo_id"], ["pa_program_outcomes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("clo_id", "plo_id", name="uq_pa_clo_plo"),
    )
    op.create_table(
        "pa_outline_weeks",
        *_id_cols(),
        sa.Column("outline_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("topic", sa.Text(), nullable=False, server_default=""),
        sa.Column("lo_codes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("session_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("delivery", sa.String(64), nullable=False, server_default=""),
        sa.Column("assessment_note", sa.String(255), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outline_id"], ["pa_subject_outlines.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "pa_outline_readings",
        *_id_cols(),
        sa.Column("outline_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("citation", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outline_id"], ["pa_subject_outlines.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "pa_outline_tasks",
        *_id_cols(),
        sa.Column("outline_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("assessment_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("number", sa.String(16), nullable=False, server_default=""),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("task_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("due", sa.String(64), nullable=False, server_default=""),
        sa.Column("lo_codes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("brief", sa.Text(), nullable=False, server_default=""),
        sa.Column("criteria", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outline_id"], ["pa_subject_outlines.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "pa_outline_policies",
        *_id_cols(),
        sa.Column("outline_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outline_id"], ["pa_subject_outlines.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "pa_outline_reviews",
        *_id_cols(),
        sa.Column("outline_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("mode", sa.String(32), nullable=False, server_default="single"),
        sa.Column("reviewer", sa.String(64), nullable=False, server_default="curriculum"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("debate", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("trace_url", sa.String(500), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outline_id"], ["pa_subject_outlines.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_column("pa_slide_decks", "instructions")
    op.drop_column("pa_courses", "ai_instructions")
    for name in (
        "pa_outline_reviews",
        "pa_outline_policies",
        "pa_outline_tasks",
        "pa_outline_readings",
        "pa_outline_weeks",
        "pa_outcome_maps",
        "pa_course_outcomes",
        "pa_program_outcomes",
        "pa_subject_outlines",
    ):
        op.drop_table(name)
