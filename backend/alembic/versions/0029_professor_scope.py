"""Professor-private rows, AI settings, prompts, and memory.

Revision ID: 0029_professor_scope
Revises: 0028_profassist
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0029_professor_scope"
down_revision = "0028_profassist"
branch_labels = None
depends_on = None

OWNER_TABLES = [
    "pa_materials",
    "pa_chunks",
    "pa_objectives",
    "pa_slide_decks",
    "pa_assessments",
    "pa_grade_drafts",
    "pa_integrity_flags",
    "pa_reflections",
]


def upgrade() -> None:
    for table in OWNER_TABLES:
        op.add_column(table, sa.Column("owner_user_id", PG_UUID(as_uuid=True), nullable=True))
        op.create_index(f"ix_{table}_owner", table, ["owner_user_id"])

    op.create_table(
        "pa_ai_settings",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chat_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider", sa.String(64), nullable=False, server_default="openai"),
        sa.Column("model", sa.String(128), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", name="uq_pa_ai_settings_org"),
    )
    op.create_table(
        "pa_prompt_versions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_key", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "pa_prompt_audit",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_key", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_user_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("before", sa.Text(), nullable=False, server_default=""),
        sa.Column("after", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "pa_agent_tools",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_key", sa.String(64), nullable=False),
        sa.Column("tool_key", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "agent_key", "tool_key", name="uq_pa_agent_tool"),
    )
    op.create_table(
        "pa_memories",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False, server_default="preference"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pa_memories_owner", "pa_memories", ["organization_id", "owner_user_id"])


def downgrade() -> None:
    op.drop_table("pa_memories")
    op.drop_table("pa_agent_tools")
    op.drop_table("pa_prompt_audit")
    op.drop_table("pa_prompt_versions")
    op.drop_table("pa_ai_settings")
    for table in OWNER_TABLES:
        op.drop_index(f"ix_{table}_owner", table_name=table)
        op.drop_column(table, "owner_user_id")
