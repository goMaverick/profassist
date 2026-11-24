"""Security hotfix tests for the ProfAssist surface.

Covers the confirmed backend issues:
  * integrity view/download endpoints no longer serve anonymous callers;
  * assessment push enforces the same owner rule as the rest of the workspace;
  * approving a draft never contacts Moodle, even with MOODLE_PUSH_ENABLED on;
  * a failed Moodle sync leaves a durable audit row behind;
  * None vector payloads and Presidio failures no longer crash or vanish.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.deps import get_current_user
from app.core.config import settings
from app.main import app
from app.profassist.deps import get_profassist_org


def _user(user_id=None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.has_role.return_value = True
    return user


INTEGRITY_GETS = [
    ("/integrity/overview", {"course": "MAAI903"}),
    ("/integrity/matrix", {"course": "MAAI903", "number": "1"}),
    ("/integrity/pair", {"course": "MAAI903", "number": "1", "left": "A", "right": "B"}),
    ("/integrity/file", {"course": "MAAI903", "number": "1", "group": "A", "which": "pdf"}),
]


@pytest.mark.anyio
@pytest.mark.parametrize("path,params", INTEGRITY_GETS)
async def test_integrity_endpoints_require_authentication(client, path, params):
    response = await client.get(f"{settings.API_V1_STR}/profassist{path}", params=params)

    assert response.status_code == 401, response.text


@pytest.mark.anyio
async def test_assessment_push_hides_another_users_assessment(client, mock_db_session):
    from app.api.routes.v1 import profassist as route

    user = _user()
    org = SimpleNamespace(id=uuid.uuid4())
    row = MagicMock()
    row.id = uuid.uuid4()
    row.organization_id = org.id
    row.owner_user_id = uuid.uuid4()  # someone else
    mock_db_session.get = AsyncMock(return_value=row)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_profassist_org] = lambda: org

    with patch.object(route, "push_record", new=AsyncMock()) as push:
        response = await client.post(f"{settings.API_V1_STR}/profassist/assessments/{row.id}/push")

    assert response.status_code == 404
    push.assert_not_called()


@pytest.mark.anyio
async def test_assessment_push_allows_the_owner(client, mock_db_session):
    from app.api.routes.v1 import profassist as route

    user = _user()
    org = SimpleNamespace(id=uuid.uuid4())
    row = MagicMock()
    row.id = uuid.uuid4()
    row.organization_id = org.id
    row.owner_user_id = user.id
    row.status = "approved"
    row.title = "Assignment 2"
    row.brief = "Brief"
    mock_db_session.get = AsyncMock(return_value=row)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_profassist_org] = lambda: org

    with patch.object(route, "push_record", new=AsyncMock(return_value={"pushed": True})) as push:
        response = await client.post(f"{settings.API_V1_STR}/profassist/assessments/{row.id}/push")

    assert response.status_code == 200
    assert response.json() == {"receipt": {"pushed": True}}
    push.assert_awaited_once()


def test_approving_never_pushes_even_when_push_is_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.core.config import settings as settings_module
    from app.profassist.grade_notes import load_feedback, release_feedback, save_feedback

    monkeypatch.setattr(settings_module, "MEDIA_DIR", tmp_path)
    monkeypatch.setenv("MOODLE_MODE", "fake")
    save_feedback("professor", "Group A", {"overall": "A solid draft."})

    # Push flag on, connector poisoned: approval must not call it.
    monkeypatch.setenv("MOODLE_PUSH_ENABLED", "true")
    connector = MagicMock()
    connector.push.side_effect = AssertionError("approve must not push")
    with patch("app.profassist.moodle.get_connector", return_value=connector):
        held = release_feedback("professor", "Group A")

    connector.push.assert_not_called()
    assert held["pushed"] is False
    assert held["audit"]["note"] == "Approved. Nothing sent until push."
    assert held["message"] == "Approved. Nothing sent until push."
    assert load_feedback("professor", "Group A")["release"] == "held"


@pytest.mark.anyio
async def test_failed_moodle_sync_keeps_its_audit_row(monkeypatch: pytest.MonkeyPatch):
    from app.integrations.moodle import gateway
    from app.profassist.errors import ProfassistError

    monkeypatch.setenv("MOODLE_MODE", "fake")
    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    org_id = uuid.uuid4()

    with (
        patch(
            "app.profassist.service.pull_moodle",
            new=AsyncMock(side_effect=RuntimeError("moodle down")),
        ),
        pytest.raises(ProfassistError),
    ):
        await gateway.sync(db, org_id, None, trigger="manual")

    row = db.add.call_args[0][0]
    assert row.status == "error"
    assert "moodle down" in row.error
    assert row.organization_id == org_id
    # flushed for the row, then committed so the request rollback cannot drop it
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_vector_documents_tolerate_a_none_payload():
    from app.services.rag.vectorstore import QdrantVectorStore

    # Built without __init__ so the test never opens a Qdrant connection.
    store = object.__new__(QdrantVectorStore)
    store._ensure_collection = AsyncMock()  # type: ignore[method-assign]
    store.client = MagicMock()
    store.client.scroll = AsyncMock(return_value=([SimpleNamespace(payload=None)], None))

    assert await store.get_documents("course-a") == []


def test_presidio_failure_is_logged_and_regex_scrub_still_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from presidio_analyzer import AnalyzerEngine

    from app.profassist import pii

    with (
        patch.object(AnalyzerEngine, "analyze", side_effect=RuntimeError("model missing")),
        caplog.at_level("WARNING", logger="app.profassist.pii"),
    ):
        result = pii.scrub("Email ada@university.edu now", [])

    assert "@" not in result.text
    assert any("Presidio extra pass unavailable" in record.message for record in caplog.records)
