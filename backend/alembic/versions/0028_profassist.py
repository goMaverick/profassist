"""ProfAssist tables and tenant policies.

Revision ID: 0028_profassist
Revises: 0027_user_magic_link_epoch
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0028_profassist"
down_revision = "0027_user_magic_link_epoch"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", PG_UUID(as_uuid=True), primary_key=True)


def _org() -> sa.Column:
    return sa.Column(
        "organization_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def _times() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "pa_courses",
        _id(),
        _org(),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("term", sa.String(32), nullable=False, server_default=""),
        sa.Column("external_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("clos", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        *_times(),
        sa.UniqueConstraint("organization_id", "code", name="uq_pa_course_code"),
    )
    op.create_table(
        "pa_materials",
        _id(),
        _org(),
        sa.Column(
            "course_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("scrubbed_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("pii_report", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("storage_key", sa.String(500), nullable=False, server_default=""),
        *_times(),
    )
    op.create_table(
        "pa_chunks",
        _id(),
        _org(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column(
            "material_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        *_times(),
    )
    op.create_index("ix_pa_chunks_course", "pa_chunks", ["course_id"])
    op.create_table(
        "pa_objectives",
        _id(),
        _org(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("source_chunk_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        *_times(),
    )
    op.create_table(
        "pa_slide_decks",
        _id(),
        _org(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("slides", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("storage_key", sa.String(500), nullable=False, server_default=""),
        *_times(),
    )
    op.create_table(
        "pa_assessments",
        _id(),
        _org(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False, server_default=""),
        sa.Column("clos", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("external_id", sa.String(64), nullable=False, server_default=""),
        *_times(),
    )
    op.create_table(
        "pa_rubric_criteria",
        _id(),
        _org(),
        sa.Column(
            "assessment_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("levels", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_times(),
    )
    op.create_table(
        "pa_style_profiles",
        _id(),
        _org(),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("soul_md", sa.Text(), nullable=False, server_default=""),
        *_times(),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_pa_style_user"),
    )
    op.create_table(
        "pa_students",
        _id(),
        _org(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("student_number", sa.String(64), nullable=False, server_default=""),
        *_times(),
        sa.UniqueConstraint("organization_id", "external_id", name="uq_pa_student_ext"),
    )
    op.create_table(
        "pa_submissions",
        _id(),
        _org(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("group_name", sa.String(128), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False, server_default=""),
        sa.Column("raw_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("scrubbed_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("pii_report", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_times(),
        sa.UniqueConstraint("organization_id", "external_id", name="uq_pa_submission_ext"),
    )
    op.create_table(
        "pa_grade_drafts",
        _id(),
        _org(),
        sa.Column(
            "submission_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("pa_submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("results", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("overall_feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("blind", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("blind_revealed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("bundle_version", sa.String(64), nullable=False, server_default="poc-1"),
        sa.Column("professor_levels", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_times(),
    )
    op.create_table(
        "pa_integrity_flags",
        _id(),
        _org(),
        sa.Column("course_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("left_submission_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("right_submission_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("section", sa.String(64), nullable=False, server_default=""),
        sa.Column("passage_a", sa.Text(), nullable=False, server_default=""),
        sa.Column("passage_b", sa.Text(), nullable=False, server_default=""),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(32), nullable=False, server_default="fingerprint"),
        sa.Column("viva", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("rare_details", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        *_times(),
    )
    op.create_table(
        "pa_approvals",
        _id(),
        _org(),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        *_times(),
    )
    op.create_table(
        "pa_moodle_pushes",
        _id(),
        _org(),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_times(),
    )
    op.create_table(
        "pa_reflections",
        _id(),
        _org(),
        sa.Column("proposal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        *_times(),
    )
    op.create_table(
        "pa_pii_vault",
        _id(),
        _org(),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default=""),
        *_times(),
    )

    # Policies apply to a non-superuser role. The Compose database user is a
    # superuser, so the application also filters every query by organization_id.
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
    tables = [
        "pa_courses",
        "pa_materials",
        "pa_chunks",
        "pa_objectives",
        "pa_slide_decks",
        "pa_assessments",
        "pa_rubric_criteria",
        "pa_style_profiles",
        "pa_students",
        "pa_submissions",
        "pa_grade_drafts",
        "pa_integrity_flags",
        "pa_approvals",
        "pa_moodle_pushes",
        "pa_reflections",
        "pa_pii_vault",
    ]
    for table in tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant ON {table}
            USING (organization_id::text = current_setting('app.current_org', true))
            WITH CHECK (organization_id::text = current_setting('app.current_org', true))
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO profassist_app")


def downgrade() -> None:
    for table in [
        "pa_pii_vault",
        "pa_reflections",
        "pa_moodle_pushes",
        "pa_approvals",
        "pa_integrity_flags",
        "pa_grade_drafts",
        "pa_submissions",
        "pa_students",
        "pa_style_profiles",
        "pa_rubric_criteria",
        "pa_assessments",
        "pa_slide_decks",
        "pa_objectives",
        "pa_chunks",
        "pa_materials",
        "pa_courses",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
        op.drop_table(table)
