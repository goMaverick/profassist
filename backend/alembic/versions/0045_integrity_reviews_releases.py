"""Versioned integrity reviews, immutable snapshots, and active releases.

Revision ID: 0045_integrity_reviews_releases
Revises: 0044_ml_jobs_and_source_versions
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0045_integrity_reviews_releases"
down_revision = "0044_ml_jobs_and_source_versions"
branch_labels = None
depends_on = None


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
    op.create_table(
        "pa_integrity_pair_reviews",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("left_version_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("right_version_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("spans", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("organization_id", "course_id", "assessment_id", "reviewer_user_id"):
        op.create_index(
            f"pa_integrity_pair_reviews_{column}_idx", "pa_integrity_pair_reviews", [column]
        )
    _tenant_table("pa_integrity_pair_reviews")
    op.execute("REVOKE UPDATE, DELETE ON pa_integrity_pair_reviews FROM profassist_app")

    op.create_table(
        "pa_integrity_dataset_snapshots",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("manifest_checksum", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "report_version_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("review_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "assessment_id", "checksum", name="uq_pa_integrity_snapshot_checksum"
        ),
    )
    for column in ("organization_id", "course_id", "assessment_id"):
        op.create_index(
            f"pa_integrity_dataset_snapshots_{column}_idx",
            "pa_integrity_dataset_snapshots",
            [column],
        )
    _tenant_table("pa_integrity_dataset_snapshots")

    op.create_table(
        "pa_ml_releases",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_kind", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("assignment_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("snapshot_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("model_bundle_sha256", sa.String(64), nullable=False),
        sa.Column("gate_evidence", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("gate_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("previous_release_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("actor_user_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("organization_id", "course_id", "assignment_id", "active"):
        op.create_index(f"pa_ml_releases_{column}_idx", "pa_ml_releases", [column])
    _tenant_table("pa_ml_releases")


def downgrade() -> None:
    for name in ("pa_ml_releases", "pa_integrity_dataset_snapshots", "pa_integrity_pair_reviews"):
        op.execute(f"DROP POLICY IF EXISTS {name}_tenant ON {name}")
        op.execute(f"ALTER TABLE {name} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} DISABLE ROW LEVEL SECURITY")
        op.drop_table(name)
