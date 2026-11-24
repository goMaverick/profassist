"""The Moodle connector: token redaction, admin scope, SSRF, and per-org secrets.

The session below is a small in-memory stand-in for AsyncSession, so the real
service functions and routes run without a database.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import DateTime
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.sql.elements import BindParameter, Null

from app.core.config import settings
from app.core.crypto import decrypt_value, encrypt_value
from app.profassist.errors import ProfassistError
from app.profassist.models import MoodleConnection
from app.profassist.moodle import MoodleConnectionSpec, RealMoodleConnector, _redact
from app.profassist.moodle_connection import (
    disable_connection,
    get_view,
    save_connection,
    validate_base_url,
)


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        return self.first()

    def scalar_one(self) -> object:
        return self._rows[0]


def _criteria(statement) -> list[tuple[str, object]]:
    filters: list[tuple[str, object]] = []
    for criterion in getattr(statement, "_where_criteria", ()):
        key = getattr(getattr(criterion, "left", None), "key", None)
        if not key:
            continue
        right = getattr(criterion, "right", None)
        if isinstance(right, Null):
            filters.append((key, None))
        elif isinstance(right, BindParameter):
            filters.append((key, right.value))
    return filters


def _matches(row: object, filters: list[tuple[str, object]]) -> bool:
    return all(getattr(row, key, object()) == value for key, value in filters)


def _apply_defaults(row: object) -> None:
    for attr in sa_inspect(type(row)).mapper.column_attrs:
        if getattr(row, attr.key, None) is not None:
            continue
        column = attr.columns[0]
        default = column.default
        value: object | None = None
        if default is not None:
            arg = default.arg
            if callable(arg):
                try:
                    value = arg(None)
                except TypeError:
                    value = arg()
            else:
                value = arg
        elif column.server_default is not None and isinstance(column.type, DateTime):
            from datetime import UTC, datetime

            value = datetime.now(UTC)
        else:
            continue
        setattr(row, attr.key, value)


class FakeSession:
    def __init__(self) -> None:
        self.rows: list[object] = []
        self.commits = 0

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        for row in self.rows:
            _apply_defaults(row)

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        filters = _criteria(statement)
        if entity is None:
            # A ``select(func.count())...select_from(Model)`` query: count the
            # rows this stand-in would have returned.
            froms = statement.get_final_froms()
            table_name = getattr(froms[0], "name", None) if froms else None
            rows = [
                row
                for row in self.rows
                if getattr(type(row), "__tablename__", None) == table_name
                and _matches(row, filters)
            ]
            return _Result([len(rows)])
        return _Result(
            [row for row in self.rows if isinstance(row, entity) and _matches(row, filters)]
        )


def _connector(token: str = "supersecret") -> RealMoodleConnector:
    return RealMoodleConnector(
        MoodleConnectionSpec(
            base_url="https://93.184.216.34",
            token=token,
            source="org",
        )
    )


# Token redaction


def test_redact_removes_every_token_shape() -> None:
    cleaned = _redact(
        "GET https://moodle.example/webservice/rest/server.php?wstoken=supersecret&x=1"
    )
    assert "supersecret" not in cleaned
    assert "wstoken=***" in cleaned
    assert "supersecret" not in _redact("redirect to /pluginfile.php?token=supersecret")
    assert "supersecret" not in _redact("wstoken=supersecret")


def test_connect_error_never_carries_the_token() -> None:
    def boom(*_args, **_kwargs):
        raise httpx.ConnectError("cannot reach https://moodle.example?wstoken=supersecret")

    with patch("httpx.request", boom), pytest.raises(ProfassistError) as caught:
        _connector().list_courses()

    assert caught.value.status == 503
    assert "supersecret" not in caught.value.detail
    assert "wstoken=***" in caught.value.detail


@pytest.mark.parametrize(
    "code,status",
    [
        ("required_capability_exception", 403),
        ("invalid_parameter_exception", 422),
        ("webservice_access_exception", 503),
        ("moodle_exception", 503),
    ],
)
def test_moodle_error_codes_map_to_actionable_statuses(code: str, status: int) -> None:
    class _Response:
        status_code = 200

        def json(self):
            return {"exception": code, "errorcode": code, "message": "Denied"}

    with patch("httpx.request", return_value=_Response()), pytest.raises(ProfassistError) as caught:
        _connector().list_courses()

    assert caught.value.status == status
    assert "Denied" in caught.value.detail


def test_http_500_is_not_reported_as_a_bad_gateway() -> None:
    class _Response:
        status_code = 500

        def json(self):
            return {}

    with patch("httpx.request", return_value=_Response()), pytest.raises(ProfassistError) as caught:
        _connector().list_courses()

    assert caught.value.status == 503


def test_a_retryable_status_is_retried_once() -> None:
    calls: list[int] = []

    class _Ok:
        status_code = 200

        def json(self):
            return []

    class _Busy:
        status_code = 503

        def json(self):
            return {}

    def fake(*_args, **_kwargs):
        calls.append(1)
        return _Busy() if len(calls) == 1 else _Ok()

    with patch("httpx.request", fake):
        assert _connector().list_courses() == []
    assert len(calls) == 2


# Connector correctness


def test_site_info_reports_the_capability_checklist() -> None:
    payload = {
        "siteurl": "https://moodle.example.edu",
        "sitename": "Example Moodle",
        "release": "4.5 (Build: 20241007)",
        "version": 2024100700,
        "siteid": 3,
        "userid": 9,
        "username": "wsservice",
        "downloadfiles": 1,
        "uploadfiles": 0,
        "enablecompletion": 1,
        "functions": [{"name": "core_course_get_courses"}, {"name": "mod_assign_get_submissions"}],
    }

    class _Response:
        status_code = 200

        def json(self):
            return payload

    with patch("httpx.request", return_value=_Response()):
        info = _connector().site_info()

    assert info["release"] == "4.5 (Build: 20241007)"
    assert info["siteid"] == "3"
    assert info["version"] == "2024100700"
    assert info["capabilities"]["functions"] == [
        "core_course_get_courses",
        "mod_assign_get_submissions",
    ]
    assert info["capabilities"]["downloadfiles"] is True
    assert info["capabilities"]["uploadfiles"] is False
    assert info["capabilities"]["enablecompletion"] is True


def test_students_filter_warnings_and_use_the_idnumber() -> None:
    seen: list[tuple[str, dict]] = []

    def fake_ws(function: str, params: dict):
        seen.append((function, params))
        return [
            {"id": 7, "fullname": "Sara", "email": "sara@example.edu", "idnumber": "8881001"},
            {"warningcode": "unknownuser", "message": "skip"},
        ]

    client = _connector()
    client._ws = fake_ws  # type: ignore[method-assign]

    students = client.list_students("3")

    assert seen[0][0] == "core_enrol_get_enrolled_users"
    assert seen[0][1]["options[0][name]"] == "withcapability"
    assert seen[0][1]["options[0][value]"] == "mod/assign:submit"
    assert seen[0][1]["onlyactive"] == 1
    assert students == [
        {
            "id": "7",
            "course_id": "3",
            "display_name": "Sara",
            "email": "sara@example.edu",
            "student_number": "8881001",
        }
    ]


def test_only_submitted_latest_attempts_are_kept() -> None:
    def fake_ws(function: str, params: dict):
        if function == "core_group_get_course_groups":
            return [{"id": 5, "name": "Group A"}]
        assert params["status"] == "submitted"
        return {
            "assignments": [
                {
                    "submissions": [
                        {"id": 11, "userid": 7, "groupid": 5, "latest": 1, "status": "submitted"},
                        {"id": 12, "userid": 7, "groupid": 5, "latest": 0, "status": "submitted"},
                        {"id": 13, "userid": 7, "groupid": 5, "latest": 1, "status": "draft"},
                    ]
                }
            ]
        }

    client = _connector()
    client._ws = fake_ws  # type: ignore[method-assign]

    rows = client.list_submissions("42", "3")

    assert [row["id"] for row in rows] == ["11"]
    assert rows[0]["group_name"] == "Group A"


def test_rubric_ids_scores_and_max_level_are_preserved() -> None:
    def fake_ws(function: str, params: dict):
        if function == "mod_assign_get_assignments":
            return {"courses": [{"assignments": [{"id": 1, "cmid": 44, "name": "Report"}]}]}
        assert function == "core_grading_get_definitions"
        return {
            "areas": [
                {
                    "definitions": [
                        {
                            "rubric": {
                                "criteria": [
                                    {
                                        "id": 101,
                                        "description": "Depth",
                                        "levels": [
                                            {"id": 501, "score": 1, "definition": "Thin"},
                                            {"id": 502, "score": 3, "definition": "Deep"},
                                        ],
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

    client = _connector()
    client._ws = fake_ws  # type: ignore[method-assign]

    assignment = client.list_assignments("3")[0]
    criterion = assignment["rubric"][0]

    assert criterion["criterionid"] == 101
    assert criterion["level_details"][0]["levelid"] == 501
    assert criterion["level_details"][1]["score"] == 3
    assert criterion["max_level"] == 3


def test_course_scope_uses_courses_by_field_and_drops_the_front_page() -> None:
    seen: list[tuple[str, dict]] = []

    def fake_ws(function: str, params: dict):
        seen.append((function, params))
        return {
            "courses": [
                {"id": 8, "idnumber": "MAAI903", "fullname": "AI", "format": "topics"},
                {"id": 1, "idnumber": "", "fullname": "Front page", "format": "site"},
            ]
        }

    client = RealMoodleConnector(
        MoodleConnectionSpec(
            base_url="https://93.184.216.34",
            token="t",
            course_scope={"mode": "idnumbers", "idnumbers": ["MAAI903"]},
            source="org",
        )
    )
    client._ws = fake_ws  # type: ignore[method-assign]

    courses = client.list_courses()

    assert seen == [("core_course_get_courses_by_field", {"field": "idnumber", "value": "MAAI903"})]
    assert courses == [{"id": "8", "code": "MAAI903", "title": "AI", "term": ""}]


# SSRF


def test_production_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(ProfassistError):
        validate_base_url("http://93.184.216.34")
    assert validate_base_url("https://93.184.216.34/moodle") == "https://93.184.216.34/moodle"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1",
        "https://10.0.0.5",
        "https://192.168.1.4",
        "https://169.254.169.254",
        "ftp://moodle.example.edu",
        "https://user:pass@moodle.example.edu",
    ],
)
def test_private_and_unsupported_addresses_are_blocked(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.delenv("MOODLE_ALLOW_PRIVATE", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    with pytest.raises(ProfassistError):
        validate_base_url(url)


def test_the_development_flag_never_weakens_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOODLE_ALLOW_PRIVATE", "true")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(ProfassistError):
        validate_base_url("https://localhost:8080")


def test_localhost_needs_the_development_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOODLE_ALLOW_PRIVATE", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    with pytest.raises(ProfassistError):
        validate_base_url("http://localhost:8080")

    monkeypatch.setenv("MOODLE_ALLOW_PRIVATE", "true")
    assert validate_base_url("http://localhost:8080") == "http://localhost:8080"


# Storage


@pytest.mark.anyio
async def test_token_is_encrypted_and_never_read_back() -> None:
    db = FakeSession()
    org_id = uuid.uuid4()

    view = await save_connection(
        db,
        org_id,
        uuid.uuid4(),
        label="Campus Moodle",
        base_url="https://93.184.216.34",
        ws_token="supersecret",
        course_scope={"mode": "idnumbers", "idnumbers": ["MAAI903"]},
        push_enabled=True,
    )

    row = db.rows[0]
    assert isinstance(row, MoodleConnection)
    assert row.ws_token_enc.startswith("enc:")
    assert "supersecret" not in row.ws_token_enc
    assert decrypt_value(row.ws_token_enc, settings.SECRET_KEY) == "supersecret"
    assert row.ws_token_hint == "cret"

    assert view["token_state"] == "saved"
    assert view["token_hint"] == "?cret"
    assert "supersecret" not in str(view)
    assert "enc:" not in str(view)
    assert view["push_enabled"] is True
    assert view["course_scope"]["idnumbers"] == ["MAAI903"]


@pytest.mark.anyio
async def test_a_new_token_rotates_and_an_empty_one_keeps_the_ciphertext() -> None:
    db = FakeSession()
    org_id = uuid.uuid4()
    await save_connection(
        db,
        org_id,
        None,
        label="",
        base_url="https://93.184.216.34",
        ws_token="first-token",
        course_scope={},
        push_enabled=False,
    )
    row = db.rows[0]
    first = row.ws_token_enc

    await save_connection(
        db,
        org_id,
        None,
        label="Updated",
        base_url="https://93.184.216.34",
        ws_token="rotated-token",
        course_scope={},
        push_enabled=False,
    )
    assert row.ws_token_enc != first
    assert decrypt_value(row.ws_token_enc, settings.SECRET_KEY) == "rotated-token"
    assert row.label == "Updated"

    kept = row.ws_token_enc
    await save_connection(
        db,
        org_id,
        None,
        label="Updated",
        base_url="https://93.184.216.34",
        ws_token="   ",
        course_scope={},
        push_enabled=False,
    )
    assert row.ws_token_enc == kept


@pytest.mark.anyio
async def test_deleting_disables_and_clears_the_token() -> None:
    db = FakeSession()
    org_id = uuid.uuid4()
    await save_connection(
        db,
        org_id,
        None,
        label="",
        base_url="https://93.184.216.34",
        ws_token="supersecret",
        course_scope={},
        push_enabled=True,
    )
    row = db.rows[0]

    view = await disable_connection(db, org_id)

    assert row.status == "disabled"
    assert row.ws_token_enc == ""
    assert row.ws_token_hint == ""
    assert view["configured"] is False


@pytest.mark.anyio
async def test_a_foreign_org_gets_a_not_found_and_no_view() -> None:
    db = FakeSession()
    org_id = uuid.uuid4()
    await save_connection(
        db,
        org_id,
        None,
        label="",
        base_url="https://93.184.216.34",
        ws_token="supersecret",
        course_scope={},
        push_enabled=False,
    )

    with pytest.raises(ProfassistError) as caught:
        await disable_connection(db, uuid.uuid4())
    assert caught.value.status == 404

    view = await get_view(db, uuid.uuid4())
    assert view["configured"] is False
    assert view["token_state"] == "none"


# Gateway


def _stored_connection(db: FakeSession, org_id: uuid.UUID) -> MoodleConnection:
    row = MoodleConnection(
        organization_id=org_id,
        label="Campus",
        base_url="https://93.184.216.34",
        ws_token_enc=encrypt_value("supersecret", settings.SECRET_KEY),
        ws_token_hint="cret",
        status="unverified",
        capabilities={},
        course_scope={},
    )
    db.add(row)
    return row


@pytest.mark.anyio
async def test_a_successful_test_persists_the_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.moodle import gateway

    monkeypatch.delenv("MOODLE_MODE", raising=False)
    db = FakeSession()
    org_id = uuid.uuid4()
    row = _stored_connection(db, org_id)
    await db.flush()
    info = {
        "site_url": "https://moodle.example.edu",
        "site_name": "Example",
        "release": "4.5",
        "version": "2024100700",
        "siteid": "3",
        "capabilities": {
            "functions": ["core_course_get_courses"],
            "downloadfiles": True,
            "uploadfiles": False,
            "enablecompletion": True,
        },
        "warnings": [],
    }
    fake = SimpleNamespace(mode="real", site_info=lambda: info)

    with patch.object(gateway, "adapter", return_value=fake):
        result = await gateway.test_connection(db, org_id)

    assert result["ok"] is True
    assert row.status == "ok"
    assert row.release == "4.5"
    assert row.siteid == "3"
    assert row.capabilities["downloadfiles"] is True
    assert [item["ok"] for item in result["checklist"]] == [True, True, True, False, True]


@pytest.mark.anyio
async def test_a_failed_test_redacts_the_error_it_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.moodle import gateway

    monkeypatch.delenv("MOODLE_MODE", raising=False)
    db = FakeSession()
    org_id = uuid.uuid4()
    row = _stored_connection(db, org_id)
    await db.flush()

    def explode():
        raise ProfassistError(503, "cannot reach ?wstoken=supersecret")

    fake = SimpleNamespace(mode="real", site_info=explode)

    with patch.object(gateway, "adapter", return_value=fake):
        result = await gateway.test_connection(db, org_id)

    assert result["ok"] is False
    assert "supersecret" not in result["error"]
    assert "supersecret" not in row.last_check_error
    assert row.status == "error"


@pytest.mark.anyio
async def test_a_failed_sync_keeps_a_redacted_audit_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.moodle import gateway

    monkeypatch.setenv("MOODLE_MODE", "fake")
    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    with (
        patch(
            "app.profassist.service.pull_moodle",
            new=AsyncMock(side_effect=RuntimeError("wstoken=supersecret")),
        ),
        pytest.raises(ProfassistError) as caught,
    ):
        await gateway.sync(db, uuid.uuid4(), None, trigger="manual")

    row = db.add.call_args[0][0]
    assert row.status == "error"
    assert "supersecret" not in row.error
    assert "supersecret" not in caught.value.detail


@pytest.mark.anyio
async def test_connection_for_decrypts_this_orgs_token() -> None:
    from app.integrations.moodle import gateway

    db = FakeSession()
    org_id = uuid.uuid4()
    _stored_connection(db, org_id)
    await db.flush()

    spec = await gateway.connection_for(db, org_id)

    assert spec is not None
    assert spec.source == "org"
    assert spec.base_url == "https://93.184.216.34"
    assert spec.token == "supersecret"


@pytest.mark.anyio
async def test_a_disabled_row_blocks_the_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.moodle import gateway

    monkeypatch.delenv("MOODLE_MODE", raising=False)
    monkeypatch.setenv("MOODLE_BASE_URL", "https://93.184.216.34")
    monkeypatch.setenv("MOODLE_WS_TOKEN", "env-token")
    db = FakeSession()
    org_id = uuid.uuid4()
    db.add(
        MoodleConnection(
            organization_id=org_id,
            base_url="https://93.184.216.34",
            ws_token_enc="",
            status="disabled",
            capabilities={},
            course_scope={},
        )
    )
    await db.flush()

    assert await gateway.connection_for(db, org_id) is None


@pytest.mark.anyio
async def test_scheduled_sync_skips_an_org_with_no_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.moodle import gateway

    monkeypatch.delenv("MOODLE_MODE", raising=False)
    monkeypatch.delenv("MOODLE_BASE_URL", raising=False)
    monkeypatch.delenv("MOODLE_WS_TOKEN", raising=False)
    org_id = uuid.uuid4()

    db = MagicMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _Result([org_id]),  # orgs with AI settings
            _Result([org_id]),  # orgs with courses
            _Result([org_id]),  # orgs with a Moodle row
            _Result([]),  # this org's AI settings
            _Result([]),  # last scheduled run
            _Result([]),  # last nightly run
            _Result([]),  # connection row
        ]
    )

    result = await gateway.sync_scheduled(db, full=False)

    assert result == {"ran": 0, "skipped": 1, "full": False}
    db.commit.assert_not_awaited()


# Routes


def _user(admin: bool) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_app_admin = admin
    user.has_role.return_value = True
    return user


def _override(admin: bool, db: object, org_id: uuid.UUID) -> None:
    from app.api.deps import get_current_user, get_db_session
    from app.main import app
    from app.profassist.deps import get_profassist_org

    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _user(admin)
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=org_id)


@pytest.mark.anyio
async def test_moodle_connection_and_legacy_sync_require_an_app_admin(client) -> None:
    from app.api.deps import get_current_user, get_db_session
    from app.main import app
    from app.profassist.deps import get_profassist_org

    app.dependency_overrides[get_db_session] = lambda: FakeSession()
    app.dependency_overrides[get_current_user] = lambda: _user(False)
    app.dependency_overrides[get_profassist_org] = lambda: SimpleNamespace(id=uuid.uuid4())

    prefix = f"{settings.API_V1_STR}/profassist"
    for method, path in (
        ("get", "/moodle/connection"),
        ("delete", "/moodle/connection"),
        ("post", "/moodle/connection/test"),
        ("post", "/moodle/test"),
        ("post", "/moodle/sync"),
        ("get", "/moodle/audit"),
    ):
        response = await getattr(client, method)(f"{prefix}{path}")
        assert response.status_code == 403, (method, path, response.text)


@pytest.mark.anyio
async def test_a_member_can_read_the_redacted_status(client) -> None:
    org_id = uuid.uuid4()
    _override(False, FakeSession(), org_id)

    response = await client.get(f"{settings.API_V1_STR}/profassist/moodle/status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["connection"]["configured"] is False
    assert "supersecret" not in response.text


@pytest.mark.anyio
async def test_status_reports_db_totals_alongside_the_last_run(client) -> None:
    """An idempotent re-sync imports nothing, but the workspace is not empty."""
    from app.profassist.models import Course, MoodleSyncRun, Student, Submission

    org_id = uuid.uuid4()
    other_org = uuid.uuid4()
    db = FakeSession()
    db.add(Course(organization_id=org_id, code="PIPE903", title="Pipelines"))
    db.add(Course(organization_id=other_org, code="OTHER1", title="Another tenant"))
    for index in range(2):
        db.add(
            Student(
                organization_id=org_id,
                course_id=uuid.uuid4(),
                external_id=f"student-{index}",
                display_name=f"Student {index}",
            )
        )
    db.add(
        Student(
            organization_id=other_org,
            course_id=uuid.uuid4(),
            external_id="elsewhere",
            display_name="Another tenant student",
        )
    )
    db.add(
        Submission(
            organization_id=org_id,
            course_id=uuid.uuid4(),
            assessment_id=uuid.uuid4(),
            external_id="submission-1",
        )
    )
    db.add(
        MoodleSyncRun(
            organization_id=org_id,
            trigger="manual",
            mode="fake",
            status="ok",
            counts={"courses": 0, "students": 0, "submissions": 0},
            error="",
        )
    )
    _override(True, db, org_id)

    response = await client.get(f"{settings.API_V1_STR}/profassist/moodle/status")

    assert response.status_code == 200, response.text
    body = response.json()
    # The run itself imported nothing new; the totals are what is stored now.
    assert body["counts"] == {"courses": 0, "students": 0, "submissions": 0}
    assert body["totals"] == {"courses": 1, "students": 2, "submissions": 1}


@pytest.mark.anyio
async def test_admin_reads_a_masked_connection(client) -> None:
    org_id = uuid.uuid4()
    db = FakeSession()
    await save_connection(
        db,
        org_id,
        None,
        label="Campus Moodle",
        base_url="https://93.184.216.34",
        ws_token="supersecret",
        course_scope={},
        push_enabled=False,
    )
    _override(True, db, org_id)

    response = await client.get(f"{settings.API_V1_STR}/profassist/moodle/connection")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_state"] == "saved"
    assert body["token_hint"] == "?cret"
    assert "supersecret" not in response.text
    assert "enc:" not in response.text


@pytest.mark.anyio
async def test_admin_saves_a_token_without_ever_seeing_it(client) -> None:
    org_id = uuid.uuid4()
    db = FakeSession()
    _override(True, db, org_id)

    response = await client.put(
        f"{settings.API_V1_STR}/profassist/moodle/connection",
        json={
            "label": "Campus Moodle",
            "base_url": "https://93.184.216.34",
            "ws_token": "supersecret",
            "course_scope": {"mode": "all"},
            "push_enabled": True,
        },
    )

    assert response.status_code == 200, response.text
    assert "supersecret" not in response.text
    assert "enc:" not in response.text
    assert response.json()["push_enabled"] is True
    assert db.rows[0].ws_token_enc.startswith("enc:")


@pytest.mark.anyio
async def test_a_bad_base_url_is_rejected_and_nothing_is_saved(client) -> None:
    org_id = uuid.uuid4()
    db = FakeSession()
    _override(True, db, org_id)

    response = await client.put(
        f"{settings.API_V1_STR}/profassist/moodle/connection",
        json={
            "label": "",
            "base_url": "https://169.254.169.254",
            "ws_token": "supersecret",
            "course_scope": {},
            "push_enabled": False,
        },
    )

    assert response.status_code == 422, response.text
    assert db.rows == []
