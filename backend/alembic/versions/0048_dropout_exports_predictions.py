"""Store private scoped dropout exports, pseudonym bindings, and predictions.

Revision ID: 0048_dropout_exports_predictions
Revises: 0047_integrity_review_revision
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0048_dropout_exports_predictions"
down_revision = "0047_integrity_review_revision"
branch_labels = None
depends_on = None


def _tenant_table(name: str, *, immutable: bool = False) -> None:
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {name}_tenant ON {name} USING "
        "(organization_id::text = current_setting('app.current_org', true)) "
        "WITH CHECK (organization_id::text = current_setting('app.current_org', true))"
    )
    if immutable:
        op.execute(f"GRANT SELECT, INSERT ON {name} TO profassist_app")
        op.execute(f"REVOKE UPDATE, DELETE ON {name} FROM profassist_app")
    else:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {name} TO profassist_app")
        op.execute(f"REVOKE DELETE ON {name} FROM profassist_app")


def upgrade() -> None:
    op.create_table(
        "pa_dropout_exports",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("external_export_id", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("manifest_checksum", sa.String(64), nullable=False),
        sa.Column("snapshots_sha256", sa.String(64), nullable=False),
        sa.Column("outcomes_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("snapshots_csv", sa.Text(), nullable=False),
        sa.Column("outcomes_csv", sa.Text(), nullable=False, server_default=""),
        sa.Column("manifest", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cohorts", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("outcome_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="validated"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "course_id", "checksum", name="uq_pa_dropout_export_checksum"
        ),
    )
    for column in ("organization_id", "course_id"):
        op.create_index(f"pa_dropout_exports_{column}_idx", "pa_dropout_exports", [column])
    _tenant_table("pa_dropout_exports", immutable=True)

    op.create_table(
        "pa_dropout_identities",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("student_key", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "student_key", name="uq_pa_dropout_identity_key"),
    )
    for column in ("organization_id", "student_id"):
        op.create_index(f"pa_dropout_identities_{column}_idx", "pa_dropout_identities", [column])
    _tenant_table("pa_dropout_identities")

    op.create_table(
        "pa_dropout_predictions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "export_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_dropout_exports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("student_key", sa.String(128), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("risk_band", sa.String(16), nullable=False),
        sa.Column("prediction_status", sa.String(16), nullable=False, server_default="scored"),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("feature_schema_version", sa.String(32), nullable=False),
        sa.Column("training_data_hash", sa.String(64), nullable=False),
        sa.Column("batch_id", sa.String(64), nullable=False),
        sa.Column("export_checksum", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "organization_id",
            "course_id",
            "student_id",
            "cutoff_at",
            "model_name",
            "model_version",
            "export_checksum",
            name="uq_pa_dropout_prediction_input",
        ),
    )
    for column in ("organization_id", "course_id", "export_id", "student_id", "batch_id"):
        op.create_index(f"pa_dropout_predictions_{column}_idx", "pa_dropout_predictions", [column])
    _tenant_table("pa_dropout_predictions", immutable=True)


def downgrade() -> None:
    for name in ("pa_dropout_predictions", "pa_dropout_identities", "pa_dropout_exports"):
        op.execute(f"DROP POLICY IF EXISTS {name}_tenant ON {name}")
        op.execute(f"ALTER TABLE {name} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} DISABLE ROW LEVEL SECURITY")
        op.drop_table(name)
