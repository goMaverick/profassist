"""Per-professor portrait and deck master. Not shared across professors.

Revision ID: 0032_professor_about
Revises: 0031_debate_providers
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0032_professor_about"
down_revision = "0031_debate_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_style_profiles",
        sa.Column("about_md", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "pa_style_profiles",
        sa.Column(
            "about_history",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "pa_style_profiles",
        sa.Column("template_key", sa.String(length=500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("pa_style_profiles", "template_key")
    op.drop_column("pa_style_profiles", "about_history")
    op.drop_column("pa_style_profiles", "about_md")
