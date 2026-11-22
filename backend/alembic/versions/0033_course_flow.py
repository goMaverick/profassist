"""Course design, rubric versions, submission files, and sync status.

Revision ID: 0033_course_flow
Revises: 0032_professor_about
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0033_course_flow"
down_revision = "0032_professor_about"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_courses", sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "pa_courses",
        sa.Column("last_sync_status", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "pa_slide_decks",
        sa.Column("week", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pa_assessments",
        sa.Column("weight", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pa_assessments",
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="assignment"),
    )
    op.add_column(
        "pa_assessments",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "pa_assessments",
        sa.Column("history", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "pa_assessments",
        sa.Column("alignment", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "pa_submissions",
        sa.Column("peer_reviews", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "pa_submissions",
        sa.Column("origin", sa.String(length=32), nullable=False, server_default="moodle"),
    )
    op.add_column(
        "pa_submissions",
        sa.Column("author_external_id", sa.String(length=64), nullable=False, server_default=""),
    )
    op.create_table(
        "pa_submission_files",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("storage_key", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["pa_submissions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_pa_submission_files_org", "pa_submission_files", ["organization_id"])
    op.create_table(
        "pa_course_designs",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("body", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("history", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["pa_courses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "organization_id", "course_id", "owner_user_id", name="uq_pa_design_owner"
        ),
    )
    op.create_index("ix_pa_course_designs_org", "pa_course_designs", ["organization_id"])
    op.create_index("ix_pa_course_designs_owner", "pa_course_designs", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_pa_course_designs_owner", table_name="pa_course_designs")
    op.drop_index("ix_pa_course_designs_org", table_name="pa_course_designs")
    op.drop_table("pa_course_designs")
    op.drop_index("ix_pa_submission_files_org", table_name="pa_submission_files")
    op.drop_table("pa_submission_files")
    op.drop_column("pa_submissions", "author_external_id")
    op.drop_column("pa_submissions", "origin")
    op.drop_column("pa_submissions", "peer_reviews")
    op.drop_column("pa_assessments", "alignment")
    op.drop_column("pa_assessments", "history")
    op.drop_column("pa_assessments", "version")
    op.drop_column("pa_assessments", "kind")
    op.drop_column("pa_assessments", "weight")
    op.drop_column("pa_slide_decks", "week")
    op.drop_column("pa_courses", "last_sync_status")
    op.drop_column("pa_courses", "last_sync_at")
