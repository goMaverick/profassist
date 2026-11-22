"""Per-university Moodle sync interval and sync audit.

Revision ID: 0036_moodle_schedule
Revises: 0035_group_assignments
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0036_moodle_schedule"
down_revision = "0035_group_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pa_ai_settings",
        sa.Column("moodle_sync_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "pa_ai_settings",
        sa.Column("moodle_sync_minutes", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column(
        "pa_ai_settings",
        sa.Column("moodle_nightly_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "pa_ai_settings",
        sa.Column("moodle_nightly_hour", sa.Integer(), nullable=False, server_default="2"),
    )
    op.create_table(
        "pa_moodle_sync_runs",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("trigger", sa.String(32), nullable=False, server_default="schedule"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="fake"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("counts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "pa_moodle_groups",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("moodle_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("grouping", sa.String(255), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False, server_default="fake"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "pa_moodle_activity",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("student_external_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("last_access", sa.String(64), nullable=False, server_default=""),
        sa.Column("logins_14d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(16), nullable=False, server_default="fake"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("pa_moodle_activity")
    op.drop_table("pa_moodle_groups")
    op.drop_table("pa_moodle_sync_runs")
    op.drop_column("pa_ai_settings", "moodle_nightly_hour")
    op.drop_column("pa_ai_settings", "moodle_nightly_enabled")
    op.drop_column("pa_ai_settings", "moodle_sync_minutes")
    op.drop_column("pa_ai_settings", "moodle_sync_paused")
