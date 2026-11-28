"""Store model explanations with dropout predictions."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0049_dropout_explanations"
down_revision = "0048_dropout_exports_predictions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pa_dropout_predictions", sa.Column("explanation", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("pa_dropout_predictions", "explanation")
