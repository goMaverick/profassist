"""Scope student groups to one assignment.

Revision ID: 0037_assignment_groups
Revises: 0036_moodle_schedule
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0037_assignment_groups"
down_revision = "0036_moodle_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_student_groups",
        sa.Column("assignment_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.create_index("pa_student_groups_assignment_id_idx", "pa_student_groups", ["assignment_id"])


def downgrade() -> None:
    op.drop_index("pa_student_groups_assignment_id_idx", table_name="pa_student_groups")
    op.drop_column("pa_student_groups", "assignment_id")
