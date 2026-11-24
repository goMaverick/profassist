"""The ordered reviewer list each council runs, edited by an app admin.

Defaults live in code. A university's rows replace them as a whole list, so the
order is the speaking order and the chair is always last.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.errors import ProfassistError
from app.profassist.models import CouncilRole
from app.profassist.runtime import DEFAULT_PROMPTS

KINDS = ("creator", "deterministic", "llm", "chair")
ROLE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MAX_PROMPT_CHARS = 4000
MAX_LABEL_CHARS = 128
MAX_MODEL_CHARS = 128

# Council key -> label, whether a custom LLM reviewer may be added, and the
# default roles in speaking order.
COUNCILS: dict[str, dict[str, Any]] = {
    "material": {
        "label": "Material",
        "allow_custom": True,
        "roles": (
            ("creator", "Creator", "creator", DEFAULT_PROMPTS["slide_studio"], ""),
            (
                "curriculum",
                "Curriculum",
                "deterministic",
                DEFAULT_PROMPTS["reviewer_curriculum"],
                "slide_reviewer",
            ),
            ("evidence", "Evidence", "deterministic", "", "slide_reviewer"),
            ("design", "Design", "deterministic", "", "slide_reviewer"),
            ("chair", "Chair", "chair", DEFAULT_PROMPTS["slide_review"], "slide_reviewer"),
        ),
    },
    "assignment": {
        "label": "Assignment",
        "allow_custom": True,
        "roles": (
            ("creator", "Creator", "creator", DEFAULT_PROMPTS["idea_generator"], ""),
            ("alignment", "Alignment", "deterministic", "", "assignment_reviewer"),
            ("brief", "Brief", "deterministic", "", "assignment_reviewer"),
            ("rubric", "Rubric", "deterministic", "", "assignment_reviewer"),
            (
                "chair",
                "Chair",
                "chair",
                DEFAULT_PROMPTS["assignment_review"],
                "assignment_reviewer",
            ),
        ),
    },
    "grading": {
        "label": "Grading",
        "allow_custom": False,
        "roles": (
            (
                "evidence",
                "Evidence",
                "llm",
                DEFAULT_PROMPTS["persona_evidence"],
                "persona_evidence",
            ),
            ("strict", "Strict", "llm", DEFAULT_PROMPTS["persona_strict"], "persona_strict"),
            (
                "supportive",
                "Supportive",
                "llm",
                DEFAULT_PROMPTS["persona_supportive"],
                "persona_supportive",
            ),
            (
                "chair",
                "Chair",
                "chair",
                "",
                "",
                {"deterministic": True, "judge": "deterministic", "prompt_editable": False},
            ),
        ),
    },
    "outline": {
        "label": "Outline",
        "allow_custom": True,
        "roles": (
            (
                "creator",
                "Creator",
                "creator",
                DEFAULT_PROMPTS["outline_generate"],
                "course_designer",
            ),
            (
                "curriculum",
                "Curriculum",
                "deterministic",
                DEFAULT_PROMPTS["reviewer_curriculum"],
                "outline_review",
            ),
            (
                "alignment",
                "Alignment",
                "deterministic",
                DEFAULT_PROMPTS["reviewer_alignment"],
                "outline_review",
            ),
            (
                "balance",
                "Balance",
                "deterministic",
                DEFAULT_PROMPTS["reviewer_balance"],
                "outline_review",
            ),
            (
                "student",
                "Student",
                "deterministic",
                DEFAULT_PROMPTS["reviewer_student"],
                "outline_review",
            ),
            ("chair", "Chair", "chair", DEFAULT_PROMPTS["reviewer_judge"], "outline_review"),
        ),
    },
}
COUNCIL_KEYS: tuple[str, ...] = tuple(COUNCILS)


def _default_role(key: str, row: tuple) -> dict[str, Any]:
    role_key, label, kind, prompt, agent_key = row[:5]
    config = dict(row[5]) if len(row) > 5 else {}
    return {
        "role_key": role_key,
        "label": label,
        "kind": kind,
        "persona_prompt": prompt,
        "agent_key": agent_key,
        "model": "",
        "position": 0,
        "enabled": True,
        "config": config,
        "custom": False,
    }


def default_roles(key: str) -> list[dict[str, Any]]:
    """The code default council, numbered from one, in speaking order."""
    _validate_key(key)
    roles = [_default_role(key, row) for row in COUNCILS[key]["roles"]]
    for position, role in enumerate(roles, start=1):
        role["position"] = position
    return [_public(role) for role in roles]


def _validate_key(key: str) -> str:
    cleaned = str(key or "").strip()
    if cleaned not in COUNCILS:
        raise ProfassistError(
            400, f"Unknown council '{cleaned}'. Choose one of: {', '.join(COUNCIL_KEYS)}."
        )
    return cleaned


def prompt_editable(role: dict[str, Any]) -> bool:
    """A prompt only counts as editable when a model is actually sent it."""
    raw = role.get("config")
    config: dict[str, Any] = raw if isinstance(raw, dict) else {}
    if "prompt_editable" in config:
        return bool(config["prompt_editable"])
    return role.get("kind") in {"llm", "chair"}


def _public(row: CouncilRole | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, dict):
        role = dict(row)
    else:
        role = {
            "role_key": row.role_key,
            "label": row.label,
            "kind": row.kind,
            "persona_prompt": row.persona_prompt,
            "agent_key": row.agent_key,
            "model": row.model,
            "position": int(row.position or 0),
            "enabled": bool(row.enabled),
            "config": dict(row.config or {}),
            "custom": bool(row.custom),
        }
    role.setdefault("config", {})
    role.setdefault("custom", False)
    role["prompt_editable"] = prompt_editable(role)
    return role


async def load_council_roles(db: AsyncSession, org_id: uuid.UUID, key: str) -> list[dict[str, Any]]:
    """This university's roles in order, or the code default when none are saved."""
    council = _validate_key(key)
    result = await db.execute(
        select(CouncilRole)
        .where(
            CouncilRole.organization_id == org_id,
            CouncilRole.council_key == council,
        )
        .order_by(CouncilRole.position, CouncilRole.role_key)
    )
    rows = [row for row in result.scalars().all() if isinstance(row, CouncilRole)]
    if not rows:
        return default_roles(council)
    return [_public(row) for row in rows]


def _position(raw: Any) -> int | None:
    """A client position is advisory. Zero or an empty value means "unset"."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise ProfassistError(400, "A role position is a whole number.")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ProfassistError(400, "A role position is a whole number.") from None
    return value or None


def _clean_role(council: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ProfassistError(400, "Every role must be an object.")
    known = {row[0]: row for row in COUNCILS[council]["roles"]}
    role_key = str(raw.get("role_key") or "").strip().lower()
    if not role_key or not ROLE_KEY.match(role_key):
        raise ProfassistError(400, "A role key is a lowercase slug, such as evidence.")
    custom = role_key not in known
    if custom and not COUNCILS[council]["allow_custom"]:
        raise ProfassistError(
            400, f"The {COUNCILS[council]['label'].lower()} council does not accept custom roles."
        )
    kind = str(raw.get("kind") or ("llm" if custom else known[role_key][2])).strip().lower()
    if kind not in KINDS:
        raise ProfassistError(400, "A role kind is creator, deterministic, llm, or chair.")
    if custom and kind != "llm":
        raise ProfassistError(400, "A custom role must be a model reviewer (kind llm).")
    if not custom and kind != known[role_key][2]:
        raise ProfassistError(400, f"The {role_key} role keeps its built-in kind.")
    if kind == "chair" and role_key != "chair":
        raise ProfassistError(400, "The chair role must be named chair.")
    label = str(raw.get("label") or (role_key.replace("_", " ").title())).strip()
    if not label:
        raise ProfassistError(400, "Every role needs a label.")
    prompt = str(raw.get("persona_prompt") or "").strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ProfassistError(400, "A persona prompt is limited to 4000 characters.")
    if custom and not prompt:
        raise ProfassistError(400, "A custom role needs a persona prompt.")
    position = _position(raw.get("position"))
    config = raw.get("config")
    if config is not None and not isinstance(config, dict):
        raise ProfassistError(400, "Role config must be an object.")
    agent_key = str(raw.get("agent_key") or ("" if custom else known[role_key][4])).strip()
    model = str(raw.get("model") or "").strip()
    if len(model) > MAX_MODEL_CHARS:
        raise ProfassistError(400, "A model name is limited to 128 characters.")
    return {
        "role_key": role_key,
        "label": label[:MAX_LABEL_CHARS],
        "kind": kind,
        "persona_prompt": prompt,
        "agent_key": agent_key[:64],
        "model": model,
        "position": position,
        "enabled": bool(raw.get("enabled", True)),
        "config": dict(config or {}),
        "custom": custom,
    }


def normalise_roles(council: str, roles: Any) -> list[dict[str, Any]]:
    """Validate a whole list, then number it from one with the chair last.

    A supplied position is advisory: the list order is the speaking order.
    """
    if not isinstance(roles, list) or not roles:
        raise ProfassistError(400, "A council needs at least one role.")
    cleaned = [_clean_role(council, raw) for raw in roles]
    keys = [role["role_key"] for role in cleaned]
    if len(set(keys)) != len(keys):
        raise ProfassistError(400, "Every role key is used once.")
    supplied = [role["position"] for role in cleaned if role.get("position") is not None]
    if supplied:
        if any(value < 1 or value > len(cleaned) for value in supplied):
            raise ProfassistError(400, "A role position runs from 1 to the number of roles.")
        if len(set(supplied)) != len(supplied):
            raise ProfassistError(400, "Every role position is used once.")
    chairs = [role for role in cleaned if role["kind"] == "chair"]
    if len(chairs) != 1:
        raise ProfassistError(400, "A council has exactly one chair.")
    # The chair always speaks last, whatever order the admin listed it in.
    ordered = [role for role in cleaned if role["kind"] != "chair"] + chairs
    for position, role in enumerate(ordered, start=1):
        role["position"] = position
    return ordered


async def save_council_roles(
    db: AsyncSession, org_id: uuid.UUID, key: str, roles: Any
) -> dict[str, Any]:
    """Replace this university's council with the validated list."""
    council = _validate_key(key)
    cleaned = normalise_roles(council, roles)
    await db.execute(
        delete(CouncilRole).where(
            CouncilRole.organization_id == org_id,
            CouncilRole.council_key == council,
        )
    )
    for role in cleaned:
        db.add(
            CouncilRole(
                organization_id=org_id,
                council_key=council,
                role_key=role["role_key"],
                label=role["label"],
                kind=role["kind"],
                persona_prompt=role["persona_prompt"],
                agent_key=role["agent_key"],
                model=role["model"],
                position=role["position"],
                enabled=role["enabled"],
                config=role["config"],
                custom=role["custom"],
            )
        )
    await db.flush()
    return _view(council, [_public(role) for role in cleaned])


async def reset_council(db: AsyncSession, org_id: uuid.UUID, key: str) -> dict[str, Any]:
    """Delete this university's rows so the code default speaks again."""
    council = _validate_key(key)
    await db.execute(
        delete(CouncilRole).where(
            CouncilRole.organization_id == org_id,
            CouncilRole.council_key == council,
        )
    )
    await db.flush()
    return _view(council, default_roles(council))


def _view(council: str, roles: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "key": council,
        "label": COUNCILS[council]["label"],
        "allow_custom": bool(COUNCILS[council]["allow_custom"]),
        "roles": roles,
    }


async def council_view(db: AsyncSession, org_id: uuid.UUID, key: str) -> dict[str, Any]:
    council = _validate_key(key)
    return _view(council, await load_council_roles(db, org_id, council))


def enabled_keys(roles: list[dict[str, Any]], kind: str | None = None) -> list[str]:
    """Enabled role keys in order, optionally limited to one kind."""
    keys: list[str] = []
    for role in roles:
        if not isinstance(role, dict) or not role.get("enabled"):
            continue
        if kind is not None and role.get("kind") != kind:
            continue
        role_key = str(role.get("role_key") or "").strip()
        if role_key:
            keys.append(role_key)
    return keys


def chair_of(roles: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The enabled chair, or None when the admin turned it off."""
    for role in roles:
        if isinstance(role, dict) and role.get("kind") == "chair" and role.get("enabled"):
            return role
    return None


def role_of(roles: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for role in roles:
        if isinstance(role, dict) and role.get("role_key") == key:
            return role
    return None


def message_roles(roles: list[dict[str, Any]]) -> list[str]:
    """The speaking order for the transcript: reviewers first, chair last.

    The creator drafts before the council; it is not a reviewer message.
    """
    creators = {
        str(role.get("role_key") or "")
        for role in roles
        if isinstance(role, dict) and role.get("kind") == "creator"
    }
    keys = enabled_keys(roles)
    return [key for key in keys if key != "chair" and key not in creators] + ["chair"]
