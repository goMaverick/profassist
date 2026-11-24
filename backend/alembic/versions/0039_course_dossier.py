"""Material insight and one course dossier per professor.

Revision ID: 0039_course_dossier
Revises: 0038_assignment_document
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0039_course_dossier"
down_revision = "0038_assignment_document"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_materials",
        sa.Column("insight", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "pa_materials",
        sa.Column("insight_status", sa.String(32), nullable=False, server_default="pending"),
    )
    op.add_column(
        "pa_materials",
        sa.Column("trace_url", sa.String(500), nullable=False, server_default=""),
    )
    op.create_table(
        "pa_course_dossiers",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("body", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("trace_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("history", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["pa_courses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "organization_id", "course_id", "owner_user_id", name="uq_pa_dossier_owner"
        ),
    )
    op.create_index("ix_pa_course_dossiers_org", "pa_course_dossiers", ["organization_id"])
    op.create_index("ix_pa_course_dossiers_course", "pa_course_dossiers", ["course_id"])
    op.create_index("ix_pa_course_dossiers_owner", "pa_course_dossiers", ["owner_user_id"])

    # Same tenant boundary as 0028_profassist: a non-superuser role sees only
    # rows whose organization matches the session GUC set by the request.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'profassist_app') THEN
                CREATE ROLE profassist_app NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute("ALTER TABLE pa_course_dossiers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pa_course_dossiers FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY pa_course_dossiers_tenant ON pa_course_dossiers
        USING (organization_id::text = current_setting('app.current_org', true))
        WITH CHECK (organization_id::text = current_setting('app.current_org', true))
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON pa_course_dossiers TO profassist_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS pa_course_dossiers_tenant ON pa_course_dossiers")
    op.drop_index("ix_pa_course_dossiers_owner", table_name="pa_course_dossiers")
    op.drop_index("ix_pa_course_dossiers_course", table_name="pa_course_dossiers")
    op.drop_index("ix_pa_course_dossiers_org", table_name="pa_course_dossiers")
    op.drop_table("pa_course_dossiers")
    op.drop_column("pa_materials", "trace_url")
    op.drop_column("pa_materials", "insight_status")
    op.drop_column("pa_materials", "insight")
