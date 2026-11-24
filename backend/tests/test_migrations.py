"""Migration tests -- verify Alembic upgrade/downgrade on a dedicated test DB.

``alembic downgrade base`` drops every table. Running that against the
developer's ``profassist`` database destroys their data, so these tests are
opt-in: they only run when ``TEST_DATABASE_URL`` points at a separate
database. The test database is created automatically when missing.

Setup::

    createdb profassist_test   # optional -- the tests create it if missing
    export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/profassist_test
    pytest tests/test_migrations.py

The subprocesses never use ``settings.DATABASE_URL``; see ``_alembic_env``.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEV_DB_NAME = "profassist"
MAINTENANCE_DB = "postgres"


def _test_db_url() -> str | None:
    """The dedicated test database URL, or None when not configured."""
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    return url or None


def _db_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def _with_driver(url: str, driver: str) -> str:
    scheme, separator, rest = url.partition("://")
    if not separator:
        return url
    return f"{scheme.split('+', 1)[0]}+{driver}://{rest}"


def _assert_safe_db_name(name: str) -> None:
    """Refuse destructive migrations against the developer database."""
    if not name:
        raise ValueError("TEST_DATABASE_URL must include a database name")
    if name == DEV_DB_NAME:
        raise ValueError(
            f"Refusing to run destructive migration tests against {DEV_DB_NAME!r}; "
            "point TEST_DATABASE_URL at a dedicated test database"
        )


def _connect_params(url: str) -> dict[str, object]:
    parts = urlsplit(url)
    return {
        "host": parts.hostname or "localhost",
        "port": parts.port or 5432,
        "user": parts.username or "postgres",
        "password": parts.password or "",
    }


def _server_available(url: str) -> bool:
    """True when the Postgres server accepts a maintenance connection."""
    import psycopg2
    from psycopg2 import OperationalError

    try:
        connection = psycopg2.connect(
            **_connect_params(url), dbname=MAINTENANCE_DB, connect_timeout=5
        )
    except OperationalError:
        return False
    connection.close()
    return True


def _ensure_test_db(url: str) -> None:
    """Create the test database if it does not exist yet."""
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    name = _db_name(url)
    _assert_safe_db_name(name)
    connection = psycopg2.connect(**_connect_params(url), dbname=MAINTENANCE_DB, connect_timeout=5)
    connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cursor.fetchone() is None:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        connection.close()


def _alembic_env(url: str) -> dict[str, str]:
    """Environment for alembic subprocesses, pinned to the *test* database.

    ``settings.DATABASE_URL(_SYNC)`` are computed from ``POSTGRES_*`` rather
    than being plain settings fields, so overriding the URL names alone is a
    no-op. We set both: ``POSTGRES_*`` for the current config and the URL names
    for ``alembic/env.py``'s explicit override.
    """
    name = _db_name(url)
    _assert_safe_db_name(name)

    env = os.environ.copy()
    params = _connect_params(url)
    env["POSTGRES_HOST"] = str(params["host"])
    env["POSTGRES_PORT"] = str(params["port"])
    env["POSTGRES_USER"] = str(params["user"])
    env["POSTGRES_PASSWORD"] = str(params["password"])
    env["POSTGRES_DB"] = name
    env["DATABASE_URL"] = _with_driver(url, "asyncpg")
    env["DATABASE_URL_SYNC"] = _with_driver(url, "psycopg2")
    return env


def _skip_reason() -> str | None:
    url = _test_db_url()
    if url is None:
        return (
            "TEST_DATABASE_URL is not set -- destructive migration tests are "
            "skipped so they cannot wipe the developer database"
        )
    try:
        _assert_safe_db_name(_db_name(url))
    except ValueError as exc:
        return str(exc)
    if not _server_available(url):
        return f"Test Postgres server is not reachable: {url}"
    return None


_SKIP_REASON = _skip_reason()


class TestTestDatabaseGuard:
    """The safety check must reject names that would destroy developer data."""

    def test_refuses_developer_database_name(self) -> None:
        with pytest.raises(ValueError, match=DEV_DB_NAME):
            _assert_safe_db_name(DEV_DB_NAME)

    def test_refuses_missing_database_name(self) -> None:
        with pytest.raises(ValueError, match="database name"):
            _assert_safe_db_name("")


class TestMigrations:
    """Alembic migration integrity against the dedicated test database."""

    pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")

    @pytest.fixture(scope="class")
    @staticmethod
    def alembic_env() -> dict[str, str]:
        url = _test_db_url()
        assert url is not None
        _ensure_test_db(url)
        return _alembic_env(url)

    @staticmethod
    def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            capture_output=True,
            text=True,
            cwd=BACKEND_DIR,
            env=env,
        )

    def test_upgrade_head(self, alembic_env: dict[str, str]) -> None:
        """All migrations can be applied."""
        result = self._run(alembic_env, "upgrade", "head")
        assert result.returncode == 0, f"Migration upgrade failed:\n{result.stderr}"

    def test_downgrade_base(self, alembic_env: dict[str, str]) -> None:
        """All migrations can be rolled back."""
        up = self._run(alembic_env, "upgrade", "head")
        assert up.returncode == 0, f"Migration upgrade failed:\n{up.stderr}"

        down = self._run(alembic_env, "downgrade", "base")
        assert down.returncode == 0, f"Migration downgrade failed:\n{down.stderr}"

    def test_upgrade_downgrade_cycle(self, alembic_env: dict[str, str]) -> None:
        """Upgrade -> downgrade -> upgrade stays consistent."""
        for action, target in [
            ("upgrade", "head"),
            ("downgrade", "base"),
            ("upgrade", "head"),
        ]:
            result = self._run(alembic_env, action, target)
            assert result.returncode == 0, f"alembic {action} {target} failed:\n{result.stderr}"

    def test_current_matches_head(self, alembic_env: dict[str, str]) -> None:
        """Current revision matches head after an upgrade."""
        up = self._run(alembic_env, "upgrade", "head")
        assert up.returncode == 0, f"Migration upgrade failed:\n{up.stderr}"

        heads = self._run(alembic_env, "heads")
        assert heads.returncode == 0
        if not heads.stdout.strip():
            pytest.skip("No migration revisions found -- nothing to verify")

        current = self._run(alembic_env, "current")
        assert current.returncode == 0
        assert "(head)" in current.stdout, (
            f"Current revision is not at head:\nstdout: {current.stdout}\nstderr: {current.stderr}"
        )
