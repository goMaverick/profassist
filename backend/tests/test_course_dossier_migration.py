"""The course-dossier migration must apply the same tenant policy as 0028."""

from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0039_course_dossier.py"


def test_course_dossier_table_has_the_tenant_rls_policy() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "ALTER TABLE pa_course_dossiers ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE pa_course_dossiers FORCE ROW LEVEL SECURITY" in source
    assert "CREATE POLICY pa_course_dossiers_tenant ON pa_course_dossiers" in source
    assert "current_setting('app.current_org', true)" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON pa_course_dossiers TO profassist_app" in source


def test_downgrade_drops_the_policy_before_the_table() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    policy = source.index("DROP POLICY IF EXISTS pa_course_dossiers_tenant ON pa_course_dossiers")
    table = source.index('op.drop_table("pa_course_dossiers")')
    assert policy < table
