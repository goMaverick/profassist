"""Number successive immutable decisions for a report-version pair."""

import sqlalchemy as sa

from alembic import op

revision = "0047_integrity_review_revision"
down_revision = "0046_integrity_flag_offsets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_integrity_pair_reviews",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("pa_integrity_pair_reviews", "revision")
