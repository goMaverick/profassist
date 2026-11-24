"""The Moodle connection migration must add the tenant policy and backfill 0036."""

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0041_moodle_connection.py"
)


def test_the_new_table_has_the_tenant_rls_policy() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "ALTER TABLE pa_moodle_connections ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE pa_moodle_connections FORCE ROW LEVEL SECURITY" in source
    assert "CREATE POLICY pa_moodle_connections_tenant ON pa_moodle_connections" in source
    assert "current_setting('app.current_org', true)" in source
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON pa_moodle_connections TO profassist_app" in source
    )
    assert "uq_pa_moodle_connections_org" in source


def test_the_0036_tables_are_backfilled() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        'for table in ("pa_moodle_sync_runs", "pa_moodle_groups", "pa_moodle_activity")' in source
    )
    assert 'f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"' in source
    assert 'f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"' in source
    assert "CREATE POLICY {table}_tenant ON {table}" in source
    assert 'f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO profassist_app"' in source
    assert "current_setting('app.current_org', true)" in source


def test_downgrade_drops_the_policy_before_the_table() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    policy = source.index("DROP POLICY IF EXISTS pa_moodle_connections_tenant")
    table = source.index('op.drop_table("pa_moodle_connections")')
    assert policy < table
