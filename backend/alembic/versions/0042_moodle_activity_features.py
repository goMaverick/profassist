"""Store the day-35 dropout feature snapshot on each Moodle activity row.

Revision ID: 0042_moodle_activity_features
Revises: 0041_moodle_connection

The 0036 table carried three ad-hoc counters. The dropout adapter needs the 14
allowlisted columns, so the whole snapshot lives in one JSONB object. An empty
object means the LMS did not supply a feature row.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0042_moodle_activity_features"
down_revision = "0041_moodle_connection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_moodle_activity",
        sa.Column(
            "features",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("pa_moodle_activity", "features")
