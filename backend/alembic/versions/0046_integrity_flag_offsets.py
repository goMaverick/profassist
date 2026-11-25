"""Retain worker span offsets on persisted integrity evidence."""

import sqlalchemy as sa

from alembic import op

revision = "0046_integrity_flag_offsets"
down_revision = "0045_integrity_reviews_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("left_start", "left_end", "right_start", "right_end"):
        op.add_column("pa_integrity_flags", sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in ("right_end", "right_start", "left_end", "left_start"):
        op.drop_column("pa_integrity_flags", column)
