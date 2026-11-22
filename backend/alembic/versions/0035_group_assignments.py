"""Group assignments, ideas, allocations, exemplars, and submission idea link.

Revision ID: 0035_group_assignments
Revises: 0034_subject_outline
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0035_group_assignments"
down_revision = "0034_subject_outline"
branch_labels = None
depends_on = None


def _stamp():
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
    op.add_column("pa_submissions", sa.Column("idea_id", PG_UUID(as_uuid=True), nullable=True))
    op.create_table(
        "pa_group_assignments",
        *_stamp(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("outline_task_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("assessment_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("number", sa.String(16), nullable=False, server_default=""),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("due", sa.String(64), nullable=False, server_default=""),
        sa.Column("lo_codes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "pa_assignment_ideas",
        *_stamp(),
        sa.Column("assignment_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False, server_default=""),
        sa.Column("deliverables", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["pa_group_assignments.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "pa_student_groups",
        *_stamp(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("member_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "pa_group_allocations",
        *_stamp(),
        sa.Column("group_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("idea_id", PG_UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["pa_student_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["idea_id"], ["pa_assignment_ideas.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", name="uq_pa_group_one_idea"),
    )
    op.create_table(
        "pa_exemplars",
        *_stamp(),
        sa.Column("idea_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("model_answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("strong", sa.Text(), nullable=False, server_default=""),
        sa.Column("average", sa.Text(), nullable=False, server_default=""),
        sa.Column("weak", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["idea_id"], ["pa_assignment_ideas.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("idea_id", name="uq_pa_exemplar_idea"),
    )


def downgrade() -> None:
    op.drop_table("pa_exemplars")
    op.drop_table("pa_group_allocations")
    op.drop_table("pa_student_groups")
    op.drop_table("pa_assignment_ideas")
    op.drop_table("pa_group_assignments")
    op.drop_column("pa_submissions", "idea_id")
