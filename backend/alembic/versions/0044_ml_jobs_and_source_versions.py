"""Durable ML jobs and immutable integrity source versions.

Revision ID: 0044_ml_jobs_and_source_versions
Revises: 0043_council_settings
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0044_ml_jobs_and_source_versions"
down_revision = "0043_council_settings"
branch_labels = None
depends_on = None

_ENABLE_ROLE = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'profassist_app') THEN
        CREATE ROLE profassist_app NOLOGIN;
    END IF;
END $$;
"""


def _tenant_table(name: str) -> None:
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {name}_tenant ON {name} USING "
        "(organization_id::text = current_setting('app.current_org', true)) "
        "WITH CHECK (organization_id::text = current_setting('app.current_org', true))"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO profassist_app")


def upgrade() -> None:
    op.add_column(
        "pa_integrity_flags",
        sa.Column("source", sa.String(32), nullable=False, server_default="legacy"),
    )
    op.add_column("pa_integrity_flags", sa.Column("job_id", PG_UUID(as_uuid=True), nullable=True))
    op.add_column(
        "pa_integrity_flags", sa.Column("left_version_id", PG_UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "pa_integrity_flags", sa.Column("right_version_id", PG_UUID(as_uuid=True), nullable=True)
    )
    op.create_index("pa_integrity_flags_job_id_idx", "pa_integrity_flags", ["job_id"])
    op.execute(_ENABLE_ROLE)
    op.create_table(
        "pa_integrity_source_versions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column(
            "submission_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "submission_id", "version", name="uq_pa_integrity_source_version"
        ),
        sa.UniqueConstraint(
            "organization_id", "submission_id", "content_hash", name="uq_pa_integrity_source_hash"
        ),
    )
    op.create_index(
        "pa_integrity_source_versions_organization_id_idx",
        "pa_integrity_source_versions",
        ["organization_id"],
    )
    op.create_index(
        "pa_integrity_source_versions_course_id_idx", "pa_integrity_source_versions", ["course_id"]
    )
    op.create_index(
        "pa_integrity_source_versions_assessment_id_idx",
        "pa_integrity_source_versions",
        ["assessment_id"],
    )
    _tenant_table("pa_integrity_source_versions")
    op.create_table(
        "pa_ml_jobs",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("assignment_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "source_version_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("model_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("model_version", sa.String(64), nullable=False, server_default=""),
        sa.Column("result", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("prefect_flow_run_id", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "operation", "input_fingerprint", name="uq_pa_ml_job_input"
        ),
    )
    for column in ("organization_id", "course_id", "assignment_id", "requested_by", "status"):
        op.create_index(f"pa_ml_jobs_{column}_idx", "pa_ml_jobs", [column])
    _tenant_table("pa_ml_jobs")


def downgrade() -> None:
    for name in ("pa_ml_jobs", "pa_integrity_source_versions"):
        op.execute(f"DROP POLICY IF EXISTS {name}_tenant ON {name}")
        op.execute(f"ALTER TABLE {name} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} DISABLE ROW LEVEL SECURITY")
        op.drop_table(name)
    op.drop_index("pa_integrity_flags_job_id_idx", table_name="pa_integrity_flags")
    op.drop_column("pa_integrity_flags", "right_version_id")
    op.drop_column("pa_integrity_flags", "left_version_id")
    op.drop_column("pa_integrity_flags", "job_id")
    op.drop_column("pa_integrity_flags", "source")
