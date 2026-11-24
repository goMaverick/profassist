"""Council settings: the ordered reviewers each council runs.

Revision ID: 0043_council_settings
Revises: 0042_moodle_activity_features

One row per role, keyed by university, council, and role. The tenant policy
matches 0028/0039/0041 so a workspace only ever sees its own councils.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0043_council_settings"
down_revision = "0042_moodle_activity_features"
branch_labels = None
depends_on = None

_ENABLE_ROLE = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'profassist_app') THEN
        CREATE ROLE profassist_app NOLOGIN;
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.create_table(
        "pa_council_roles",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("council_key", sa.String(32), nullable=False),
        sa.Column("role_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False, server_default="llm"),
        sa.Column("persona_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("agent_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("custom", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "organization_id", "council_key", "role_key", name="uq_pa_council_role"
        ),
    )
    op.create_index("pa_council_roles_organization_id_idx", "pa_council_roles", ["organization_id"])

    op.execute(_ENABLE_ROLE)
    op.execute("ALTER TABLE pa_council_roles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pa_council_roles FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY pa_council_roles_tenant ON pa_council_roles
        USING (organization_id::text = current_setting('app.current_org', true))
        WITH CHECK (organization_id::text = current_setting('app.current_org', true))
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON pa_council_roles TO profassist_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS pa_council_roles_tenant ON pa_council_roles")
    op.execute("ALTER TABLE pa_council_roles NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pa_council_roles DISABLE ROW LEVEL SECURITY")
    op.drop_index("pa_council_roles_organization_id_idx", table_name="pa_council_roles")
    op.drop_table("pa_council_roles")
