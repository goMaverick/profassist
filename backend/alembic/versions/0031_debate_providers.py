"""Council debate settings and per-agent provider choices.

Revision ID: 0031_debate_providers
Revises: 0030_grade_trace
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0031_debate_providers"
down_revision = "0030_grade_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_ai_settings",
        sa.Column("debate_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "pa_ai_settings",
        sa.Column("debate_threshold", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pa_ai_settings",
        sa.Column("debate_max_rounds", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "pa_ai_settings",
        sa.Column("agent_models", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("pa_ai_settings", "agent_models")
    op.drop_column("pa_ai_settings", "debate_max_rounds")
    op.drop_column("pa_ai_settings", "debate_threshold")
    op.drop_column("pa_ai_settings", "debate_enabled")
