"""Store the brief document and group settings on a group assignment.

Revision ID: 0038_assignment_document
Revises: 0037_assignment_groups
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0038_assignment_document"
down_revision = "0037_assignment_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_group_assignments",
        sa.Column("document", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "pa_group_assignments",
        sa.Column("blind", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "pa_group_assignments",
        sa.Column("group_mode", sa.String(16), nullable=False, server_default="individual"),
    )


def downgrade() -> None:
    op.drop_column("pa_group_assignments", "group_mode")
    op.drop_column("pa_group_assignments", "blind")
    op.drop_column("pa_group_assignments", "document")
