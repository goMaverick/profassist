"""Authenticated FastMCP server. The same tools the chat uses are exposed at /mcp.

Every request carries a professor's JWT (or an admin API key) and an optional
``X-Organization-Id``. A middleware opens the database session, resolves the
active organization, and stores the request context in a contextvar. Tools run
the real handlers through ``invoke_tool``; a mutation returns ``needs_confirm``
first and only runs when the caller passes ``confirm=True``.
"""

import json
import logging
import secrets
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.security import verify_token
from app.profassist.platform_tools import (
    TOOL_SPECS,
    clear_tool_actor,
    set_tool_actor,
    tool_catalog,
    tool_spec,
)
from app.repositories import member_repo, organization_repo
from app.services.user import UserService

logger = logging.getLogger(__name__)

MCP_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("pa_mcp_context", default=None)


def current_mcp_context() -> dict[str, Any] | None:
    """The authenticated MCP request context, or None outside a request."""
    return MCP_CONTEXT.get()


class MCPAuthError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


@asynccontextmanager
async def mcp_session() -> AsyncGenerator[Any]:
    """Open a database session with the application's own factory."""
    from app.db.session import get_db_context

    async with get_db_context() as db:
        yield db


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers") or []
    }


async def _buffered_receive(receive: Receive) -> tuple[bytes, Receive]:
    """Read the request body once and return a receive that replays it."""
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    body = b"".join(chunks)
    sent = False

    async def replay() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return body, replay


def _requested_tool(body: bytes) -> str | None:
    """The tool name in a JSON-RPC tools/call body, if this request is one."""
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if isinstance(item, dict) and item.get("method") == "tools/call":
            params = item.get("params") or {}
            name = params.get("name")
            if isinstance(name, str):
                return name
    return None


def _bearer(headers: dict[str, str]) -> str:
    raw = headers.get("authorization", "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return ""


def _api_key_ok(headers: dict[str, str]) -> bool:
    supplied = headers.get("x-api-key", "")
    return bool(supplied) and secrets.compare_digest(supplied, settings.API_KEY)


async def _resolve_org(db: Any, user_id: uuid.UUID, header: str) -> Any:
    """Read the requested org, or the user's first membership."""
    if header:
        try:
            org_id = uuid.UUID(header)
        except ValueError as exc:
            raise MCPAuthError(400, "X-Organization-Id is not a valid UUID.") from exc
        if user_id.int:
            membership = await member_repo.get(db, organization_id=org_id, user_id=user_id)
            if membership is None:
                raise MCPAuthError(404, "Organization not found or access denied.")
        org = await organization_repo.get_by_id(db, org_id)
        if org is None:
            raise MCPAuthError(404, "Organization not found.")
        return org

    if not user_id.int:
        raise MCPAuthError(400, "X-Organization-Id is required for an API key request.")
    memberships = await member_repo.list_orgs_for_user(db, user_id)
    if not memberships:
        raise MCPAuthError(404, "This account has no workspace yet.")
    org = await organization_repo.get_by_id(db, memberships[0].organization_id)
    if org is None:
        raise MCPAuthError(404, "Organization not found.")
    return org


async def _resolve_context(db: Any, headers: dict[str, str]) -> dict[str, Any]:
    """Verify a JWT or admin API key and return the MCP request context."""
    token = _bearer(headers)
    api_key = _api_key_ok(headers)
    user_id = uuid.UUID(int=0)
    is_admin = False

    payload = verify_token(token) if token else None
    if payload is not None and payload.get("type") == "access" and payload.get("sub"):
        try:
            user_id = uuid.UUID(str(payload["sub"]))
        except ValueError as exc:
            raise MCPAuthError(401, "Invalid token payload.") from exc
        try:
            user = await UserService(db).get_by_id(user_id)
        except Exception as exc:
            raise MCPAuthError(401, "User not found.") from exc
        if not user or not user.is_active:
            raise MCPAuthError(401, "User account is disabled.")
        is_admin = bool(getattr(user, "is_app_admin", False))
        if api_key:
            is_admin = True
    elif api_key:
        # A shared API key has no professor identity. It only reaches admin tools.
        is_admin = True
    else:
        raise MCPAuthError(401, "Sign in with Authorization: Bearer <JWT>.")

    org = await _resolve_org(db, user_id, headers.get("x-organization-id", "").strip())
    await db.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org.id)})
    return {
        "db": db,
        "user_id": user_id,
        "org_id": org.id,
        "is_admin": is_admin,
        "service": user_id.int == 0,
    }


async def _send_json(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
    await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)


class MCPAuthMiddleware:
    """Authenticate every /mcp request and bind its database context."""

    def __init__(self, app: ASGIApp, *, lifespan: Any = None) -> None:
        self.app = app
        self.lifespan = lifespan or getattr(app, "lifespan", None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        body, replay = await _buffered_receive(receive)
        if not _bearer(headers) and not _api_key_ok(headers):
            await _send_json(scope, receive, send, 401, "Sign in with Authorization: Bearer <JWT>.")
            return
        try:
            async with mcp_session() as db:
                context = await _resolve_context(db, headers)
                tool_name = _requested_tool(body)
                spec = tool_spec(tool_name) if tool_name else None
                if spec is not None and spec["admin"] and not context["is_admin"]:
                    await _send_json(
                        scope, receive, send, 403, "That tool is for an administrator."
                    )
                    return
                if context["service"] and (spec is None or not spec["admin"]):
                    await _send_json(
                        scope,
                        receive,
                        send,
                        403,
                        "X-API-Key is only accepted for administrator tools.",
                    )
                    return

                token = MCP_CONTEXT.set(context)
                set_tool_actor(context["org_id"], context["user_id"], is_admin=context["is_admin"])
                try:
                    await self.app(scope, replay, send)
                finally:
                    clear_tool_actor()
                    MCP_CONTEXT.reset(token)
        except MCPAuthError as exc:
            await _send_json(scope, receive, send, exc.status, exc.detail)


async def _run_tool(name: str, arguments: dict[str, Any] | None, confirm: bool) -> dict[str, Any]:
    """Run one real professor tool inside the authenticated request context."""
    from app.profassist.platform_tools import invoke_tool

    context = current_mcp_context()
    if context is None:
        return {"error": "Sign in before using this tool.", "status": 401}
    spec = tool_spec(name)
    if spec is not None and spec["admin"] and not context["is_admin"]:
        return {"error": "That tool is for an administrator.", "status": 403}
    payload = await invoke_tool(context["db"], name, arguments or {}, confirmed=confirm)
    payload["arguments"] = arguments or {}
    return payload


def _register_tool(server: Any, name: str, description: str) -> None:
    async def run_tool(
        arguments: dict[str, Any] | None = None, confirm: bool = False
    ) -> dict[str, Any]:
        return await _run_tool(name, arguments, confirm)

    run_tool.__name__ = f"tool_{name}"
    run_tool.__doc__ = description
    server.tool(name=name, description=description)(run_tool)


def build_mcp_server() -> Any:
    """Build the FastMCP registry. Import is delayed so the app starts without it."""
    from fastmcp import FastMCP

    server = FastMCP("ProfAssist")

    @server.tool(
        name="list_profassist_tools",
        description="List the professor tools and whether each one is enabled.",
    )
    async def list_profassist_tools() -> list[dict[str, Any]]:
        return tool_catalog()

    for spec in TOOL_SPECS:
        description = str(spec.get("summary") or spec["name"])
        if spec["confirm"]:
            description += " Pass confirm=true to run this change."
        _register_tool(server, spec["name"], description)

    return server


def create_mcp_http_app() -> MCPAuthMiddleware:
    """The authenticated ASGI app that ``mount_mcp`` mounts at /mcp."""
    server = build_mcp_server()
    try:
        http_app = server.http_app(path="/", json_response=True, stateless_http=True)
    except TypeError:  # older FastMCP without the keyword arguments
        http_app = server.http_app(path="/")
    return MCPAuthMiddleware(http_app, lifespan=getattr(http_app, "lifespan", None))


def _chain_lifespan(app: Any, mcp_lifespan: Callable[[Any], Any] | None) -> None:
    """Run the FastMCP session manager inside the parent app's lifespan."""
    if mcp_lifespan is None:
        return
    original = app.router.lifespan_context

    @asynccontextmanager
    async def combined(app_: Any) -> AsyncGenerator[Any]:
        async with original(app_) as state, mcp_lifespan(app_):
            yield state

    app.router.lifespan_context = combined


def mount_mcp(app: Any) -> None:
    """Mount FastMCP when the package is installed. The app still starts without it."""
    try:
        import fastmcp  # noqa: F401
    except Exception:
        logger.info("fastmcp is not installed; /mcp is not mounted")
        return
    http_app = create_mcp_http_app()
    _chain_lifespan(app, http_app.lifespan)
    app.mount("/mcp", http_app)
