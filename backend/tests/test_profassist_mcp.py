"""Authenticated /mcp: JWT context, admin gate, and mutation confirmation."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token

USER_ID = uuid.uuid4()
ORG_ID = uuid.uuid4()
JSON_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


class _DB:
    async def execute(self, *_args, **_kwargs):
        return None


def _rpc_headers(*, user_id: uuid.UUID = USER_ID, bearer: bool = True) -> dict[str, str]:
    headers = {**JSON_HEADERS, "X-Organization-Id": str(ORG_ID)}
    if bearer:
        headers["Authorization"] = f"Bearer {create_access_token(user_id)}"
    return headers


def _call(client: TestClient, headers: dict[str, str], name: str, arguments: dict) -> object:
    return client.post(
        "/mcp/",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": {"arguments": arguments}},
        },
    )


@pytest.fixture
def mcp_client(monkeypatch: pytest.MonkeyPatch):
    from app.profassist import mcp_server

    state = {"is_admin": False}

    class _UserService:
        def __init__(self, _db):
            pass

        async def get_by_id(self, user_id):
            return SimpleNamespace(id=user_id, is_active=True, is_app_admin=state["is_admin"])

    @asynccontextmanager
    async def fake_session():
        yield _DB()

    async def fake_member_get(_db, *, organization_id, user_id):
        return SimpleNamespace(organization_id=organization_id, user_id=user_id)

    async def fake_org_get(_db, org_id):
        return SimpleNamespace(id=org_id)

    async def fake_memberships(_db, _user_id):
        return [SimpleNamespace(organization_id=ORG_ID)]

    monkeypatch.setattr(mcp_server, "UserService", _UserService)
    monkeypatch.setattr(mcp_server, "mcp_session", fake_session)
    monkeypatch.setattr(mcp_server.member_repo, "get", fake_member_get)
    monkeypatch.setattr(mcp_server.member_repo, "list_orgs_for_user", fake_memberships)
    monkeypatch.setattr(mcp_server.organization_repo, "get_by_id", fake_org_get)

    http_app = mcp_server.create_mcp_http_app()
    app = FastAPI(lifespan=http_app.lifespan)
    app.mount("/mcp", http_app)
    with TestClient(app) as client:
        yield client, state


def test_mcp_rejects_a_request_without_a_token(mcp_client) -> None:
    client, _state = mcp_client
    response = _call(client, JSON_HEADERS, "list_courses", {})

    assert response.status_code == 401
    assert "Sign in" in response.json()["detail"]


def test_mcp_runs_a_real_tool_with_a_valid_jwt(mcp_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _state = mcp_client
    seen: dict = {}

    async def fake_invoke(db, name, arguments, *, confirmed=False):
        seen.update(db=db, name=name, arguments=arguments, confirmed=confirmed)
        return {
            "tool": name,
            "result": [{"code": "MAAI903", "title": "AI Foundations"}],
            "needs_confirm": False,
        }

    monkeypatch.setattr("app.profassist.platform_tools.invoke_tool", fake_invoke)
    response = _call(client, _rpc_headers(), "list_courses", {"code": "MAAI903"})

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["isError"] is False
    assert body["result"]["structuredContent"]["tool"] == "list_courses"
    assert seen["name"] == "list_courses"
    assert seen["arguments"] == {"code": "MAAI903"}
    assert seen["confirmed"] is False


def test_mcp_hides_admin_tools_from_a_non_admin(mcp_client) -> None:
    client, state = mcp_client
    state["is_admin"] = False

    response = _call(client, _rpc_headers(), "admin_ai_settings", {})

    assert response.status_code == 403
    assert "administrator" in response.json()["detail"]


def test_mcp_admin_tool_runs_for_an_admin(mcp_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, state = mcp_client
    state["is_admin"] = True
    seen: dict = {}

    async def fake_invoke(db, name, arguments, *, confirmed=False):
        seen.update(name=name, confirmed=confirmed)
        return {"tool": name, "result": {"chat_enabled": True}, "needs_confirm": False}

    monkeypatch.setattr("app.profassist.platform_tools.invoke_tool", fake_invoke)
    response = _call(client, _rpc_headers(), "admin_ai_settings", {})

    assert response.status_code == 200
    assert seen["name"] == "admin_ai_settings"


def test_mcp_mutation_waits_for_confirm(mcp_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _state = mcp_client
    seen: list[bool] = []

    async def fake_invoke(db, name, arguments, *, confirmed=False):
        seen.append(confirmed)
        if not confirmed:
            return {
                "tool": name,
                "needs_confirm": True,
                "preview": "replace the groups",
                "confirm_with": "confirm",
            }
        return {"tool": name, "result": {"groups": []}, "needs_confirm": False}

    monkeypatch.setattr("app.profassist.platform_tools.invoke_tool", fake_invoke)

    pending = client.post(
        "/mcp/",
        headers=_rpc_headers(),
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "create_groups",
                "arguments": {"arguments": {"code": "MAAI903"}},
            },
        },
    )
    assert pending.status_code == 200
    assert pending.json()["result"]["structuredContent"]["needs_confirm"] is True
    assert seen[-1] is False

    executed = client.post(
        "/mcp/",
        headers=_rpc_headers(),
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "create_groups",
                "arguments": {"arguments": {"code": "MAAI903"}, "confirm": True},
            },
        },
    )
    assert executed.status_code == 200
    assert executed.json()["result"]["structuredContent"]["needs_confirm"] is False
    assert seen[-1] is True


def test_mcp_api_key_only_reaches_admin_tools(mcp_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _state = mcp_client
    headers = {
        **JSON_HEADERS,
        "X-API-Key": settings.API_KEY,
        "X-Organization-Id": str(ORG_ID),
    }

    denied = _call(client, headers, "list_courses", {})
    assert denied.status_code == 403

    async def fake_invoke(db, name, arguments, *, confirmed=False):
        return {"tool": name, "result": {"chat_enabled": True}, "needs_confirm": False}

    monkeypatch.setattr("app.profassist.platform_tools.invoke_tool", fake_invoke)
    allowed = _call(client, headers, "admin_ai_settings", {})
    assert allowed.status_code == 200


def test_invoke_tool_returns_needs_confirm_then_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.profassist import platform_tools

    platform_tools.set_tool_actor(ORG_ID, USER_ID, is_admin=False)
    try:
        pending = asyncio.run(
            platform_tools.invoke_tool(None, "create_groups", {"groups": []}, confirmed=False)
        )
        assert pending["needs_confirm"] is True
        assert pending["confirm_with"] == "confirm"

        async def fake_handler(_db, _current, _args):
            return {"groups": [{"name": "Group 1"}]}

        monkeypatch.setitem(platform_tools._HANDLERS, "create_groups", fake_handler)
        executed = asyncio.run(
            platform_tools.invoke_tool(None, "create_groups", {"groups": []}, confirmed=True)
        )
        assert executed["needs_confirm"] is False
        assert executed["result"] == {"groups": [{"name": "Group 1"}]}
    finally:
        platform_tools.clear_tool_actor()


def test_mount_mcp_chains_lifespan_and_requires_auth() -> None:
    from app.profassist import mcp_server

    app = FastAPI()
    mcp_server.mount_mcp(app)
    with TestClient(app) as client:
        response = client.post(
            "/mcp/",
            headers=JSON_HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )

    assert response.status_code == 401
