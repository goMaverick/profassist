"""Store the Langfuse trace link on a grade draft.

Revision ID: 0030_grade_trace
Revises: 0029_professor_scope
"""

import sqlalchemy as sa

from alembic import op

revision = "0030_grade_trace"
down_revision = "0029_professor_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_grade_drafts",
        sa.Column("trace_url", sa.String(500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("pa_grade_drafts", "trace_url")
