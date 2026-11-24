"""One encrypted Moodle connection per university.

Revision ID: 0041_moodle_connection
Revises: 0040_slide_review

The 0036 Moodle tables were created without a tenant policy. This revision adds
the connection table, applies the same RLS policy as 0028/0039, and backfills the
policy and ``profassist_app`` grant for the three tables that missed it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0041_moodle_connection"
down_revision = "0040_slide_review"
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
        "pa_moodle_connections",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("ws_token_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("ws_token_hint", sa.String(8), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="unverified"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("site_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("site_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("release", sa.String(64), nullable=False, server_default=""),
        sa.Column("version", sa.String(64), nullable=False, server_default=""),
        sa.Column("siteid", sa.String(64), nullable=False, server_default=""),
        sa.Column("capabilities", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("course_scope", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("token_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", name="uq_pa_moodle_connections_org"),
    )
    op.create_index(
        "pa_moodle_connections_organization_id_idx", "pa_moodle_connections", ["organization_id"]
    )

    op.execute(_ENABLE_ROLE)

    op.execute("ALTER TABLE pa_moodle_connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pa_moodle_connections FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY pa_moodle_connections_tenant ON pa_moodle_connections
        USING (organization_id::text = current_setting('app.current_org', true))
        WITH CHECK (organization_id::text = current_setting('app.current_org', true))
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON pa_moodle_connections TO profassist_app")

    # Backfill the tenant boundary the 0036 tables never received.
    for table in ("pa_moodle_sync_runs", "pa_moodle_groups", "pa_moodle_activity"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
            USING (organization_id::text = current_setting('app.current_org', true))
            WITH CHECK (organization_id::text = current_setting('app.current_org', true))
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO profassist_app")


def downgrade() -> None:
    for table in ("pa_moodle_activity", "pa_moodle_groups", "pa_moodle_sync_runs"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS pa_moodle_connections_tenant ON pa_moodle_connections")
    op.drop_index("pa_moodle_connections_organization_id_idx", table_name="pa_moodle_connections")
    op.drop_table("pa_moodle_connections")
