"""A slide review on every deck, and the trace link that explains it.

Revision ID: 0040_slide_review
Revises: 0039_course_dossier
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0040_slide_review"
down_revision = "0039_course_dossier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_slide_decks",
        sa.Column("review", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "pa_slide_decks",
        sa.Column("review_trace_url", sa.String(500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("pa_slide_decks", "review_trace_url")
    op.drop_column("pa_slide_decks", "review")
