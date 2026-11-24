"""One Moodle connection per university: validation, storage, and masked reads.

The web-service token is a bearer credential. It is encrypted with
``app.core.crypto`` and the server ``SECRET_KEY``, and no read path ever returns
it. ``Token redaction`` lives in :mod:`app.profassist.moodle` so every error and
audit row shares the same scrubber.
"""

import ipaddress
import socket
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.config import moodle_mode
from app.profassist.errors import ProfassistError
from app.profassist.models import MoodleActivity, MoodleConnection
from app.profassist.moodle import _redact

_LOCAL_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})

_EMPTY_SCOPE = {"mode": "all", "idnumbers": [], "shortnames": []}


def _clean_scope(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalise a course scope; anything unusable becomes "every visible course"."""
    raw = raw or {}
    mode = str(raw.get("mode") or "all")
    if mode == "idnumbers":
        values = [str(item).strip() for item in raw.get("idnumbers") or [] if str(item).strip()]
        if values:
            return {"mode": "idnumbers", "idnumbers": values, "shortnames": []}
    if mode == "shortnames":
        values = [str(item).strip() for item in raw.get("shortnames") or [] if str(item).strip()]
        if values:
            return {"mode": "shortnames", "idnumbers": [], "shortnames": values}
    return dict(_EMPTY_SCOPE)


def _blocked_ip(host: str) -> bool:
    from app.core.sanitize import _is_ip_blocked

    return _is_ip_blocked(host)


def _check_host(host: str, allow_private: bool) -> None:
    if host in _LOCAL_NAMES or host.endswith(".localhost"):
        if not allow_private:
            raise ProfassistError(
                422,
                "Localhost is blocked. Set MOODLE_ALLOW_PRIVATE=true only for local development.",
            )
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not allow_private and _blocked_ip(str(address)):
            raise ProfassistError(422, "The Moodle address points at a private network.")
        return
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ProfassistError(422, f"Could not resolve the Moodle host name {host!r}.") from exc
    for info in infos:
        if _blocked_ip(str(info[4][0])):
            raise ProfassistError(422, "The Moodle host name resolves to a private network.")


def validate_base_url(raw: str) -> str:
    """Reject schemes and addresses that would let a tenant reach our network."""
    from app.core.config import settings
    from app.profassist.config import moodle_allow_private

    value = (raw or "").strip().rstrip("/")
    if not value:
        raise ProfassistError(422, "Enter the Moodle base URL.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ProfassistError(422, "The Moodle base URL must start with https://.")
    if parsed.username is not None or parsed.password is not None:
        raise ProfassistError(422, "The Moodle base URL must not contain a username or password.")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ProfassistError(422, "The Moodle base URL has no host name.")
    # The development flag never weakens production.
    allow_private = moodle_allow_private() and settings.ENVIRONMENT != "production"
    if settings.ENVIRONMENT == "production" and parsed.scheme != "https":
        raise ProfassistError(422, "Moodle must be reached over https:// in production.")
    # Plain http is a development convenience for a local Moodle only.
    if parsed.scheme == "http" and not allow_private:
        raise ProfassistError(422, "Use https:// for the Moodle address.")
    _check_host(host, allow_private)
    return value


async def _row(db: AsyncSession, org_id: uuid.UUID) -> MoodleConnection | None:
    result = await db.execute(
        select(MoodleConnection).where(MoodleConnection.organization_id == org_id)
    )
    return result.scalar_one_or_none()


def masked_view(row: MoodleConnection | None) -> dict[str, Any]:
    """A safe shape for the admin screen. No ciphertext, no token bytes."""
    if row is None:
        return {
            "configured": False,
            "label": "",
            "base_url": "",
            "token_state": "none",
            "token_hint": "",
            "status": "unverified",
            "last_checked_at": "",
            "last_check_error": "",
            "site_url": "",
            "site_name": "",
            "release": "",
            "version": "",
            "siteid": "",
            "capabilities": {},
            "course_scope": dict(_EMPTY_SCOPE),
            "push_enabled": False,
            "token_rotated_at": "",
        }
    return {
        "configured": bool(row.ws_token_enc),
        "label": row.label or "",
        "base_url": row.base_url or "",
        "token_state": "saved" if row.ws_token_enc else "none",
        "token_hint": f"?{row.ws_token_hint}" if row.ws_token_hint else "",
        "status": row.status or "unverified",
        "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else "",
        "last_check_error": _redact(row.last_check_error),
        "site_url": row.site_url or "",
        "site_name": row.site_name or "",
        "release": row.release or "",
        "version": row.version or "",
        "siteid": row.siteid or "",
        "capabilities": row.capabilities or {},
        "course_scope": _clean_scope(row.course_scope),
        "push_enabled": bool(row.push_enabled),
        "token_rotated_at": row.token_rotated_at.isoformat() if row.token_rotated_at else "",
    }


async def activity_log_state(db: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    """Whether any Moodle activity features are stored for this workspace.

    The bundled simulator exposes ``local_profassist_get_activity``; a stock
    Moodle does not. The note says so, and an advisory score changes nothing.
    """
    result = await db.execute(
        select(MoodleActivity.features).where(MoodleActivity.organization_id == org_id)
    )
    rows = result.scalars().all()
    if any(isinstance(row, dict) and bool(row) for row in rows):
        return {
            "available": True,
            "reason": (
                "Moodle activity features are stored. They were pulled with "
                "local_profassist_get_activity, a demo-only function in the bundled "
                "simulator; a stock Moodle does not expose it. Dropout scores are "
                "advisory and change nothing."
            ),
        }
    return {
        "available": False,
        "reason": (
            "No Moodle activity features are stored yet. The bundled demo simulator "
            "can expose local_profassist_get_activity; a stock Moodle does not. Until "
            "rows exist, dropout risk stays unscored."
        ),
    }


def env_fallback() -> dict[str, Any]:
    """Describe the process-wide demo connection without exposing the token."""
    from app.profassist.config import moodle_base_url, moodle_mode, moodle_ws_token

    base_url = moodle_base_url()
    token = moodle_ws_token()
    return {
        "available": bool(base_url and token) and moodle_mode() == "real",
        "base_url": base_url,
        "token_configured": bool(token),
    }


async def get_view(db: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    row = await _row(db, org_id)
    view = masked_view(row)
    view["mode"] = moodle_mode()
    view["activity_logs"] = await activity_log_state(db, org_id)
    view["env_fallback"] = env_fallback()
    return view


async def save_connection(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    *,
    label: str,
    base_url: str,
    ws_token: str,
    course_scope: dict[str, Any] | None,
    push_enabled: bool,
) -> dict[str, Any]:
    """Create or update the single connection for this university.

    An empty token keeps the stored ciphertext, which lets the form show a
    masked value and still save other fields.
    """
    from app.core.config import settings
    from app.core.crypto import encrypt_value

    cleaned_url = validate_base_url(base_url)
    row = await _row(db, org_id)
    token = (ws_token or "").strip()
    if row is None:
        if not token:
            raise ProfassistError(422, "Enter the Moodle web-service token.")
        row = MoodleConnection(organization_id=org_id, created_by=user_id, status="unverified")
        db.add(row)
    rotated = False
    if token:
        row.ws_token_enc = encrypt_value(token, settings.SECRET_KEY)
        row.ws_token_hint = token[-4:]
        row.token_rotated_at = datetime.now(UTC)
        rotated = True
    if not row.ws_token_enc:
        raise ProfassistError(422, "Enter the Moodle web-service token.")
    if row.base_url != cleaned_url or rotated:
        row.status = "unverified"
        row.last_check_error = ""
    row.base_url = cleaned_url
    row.label = (label or "").strip()[:128]
    row.course_scope = _clean_scope(course_scope)
    row.push_enabled = bool(push_enabled)
    await db.flush()
    return masked_view(row)


async def disable_connection(db: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    """Turn the connection off and destroy the token ciphertext."""
    row = await _row(db, org_id)
    if row is None:
        raise ProfassistError(404, "No Moodle connection is configured for this workspace.")
    row.status = "disabled"
    row.ws_token_enc = ""
    row.ws_token_hint = ""
    row.push_enabled = False
    row.last_check_error = ""
    await db.flush()
    return masked_view(row)
