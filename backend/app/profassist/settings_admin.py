"""Admin-editable AI settings, versioned prompts, and per-agent tools."""

import importlib.util
import os
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.lessons import condense_about
from app.profassist.memory import list_memories
from app.profassist.models import (
    AgentToolSetting,
    AiSettings,
    Course,
    PromptAudit,
    PromptVersion,
    StyleProfile,
)
from app.profassist.providers import AGENTS
from app.profassist.providers import catalog as provider_catalog
from app.profassist.runtime import DEFAULT_PROMPTS, DEFAULT_TOOLS, bind_runtime, catalog, set_about


async def _settings(db: AsyncSession, org_id: uuid.UUID) -> AiSettings:
    result = await db.execute(select(AiSettings).where(AiSettings.organization_id == org_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = AiSettings(organization_id=org_id)
        db.add(row)
        await db.flush()
    return row


async def load_runtime(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> None:
    from app.profassist.observe import set_actor

    set_actor(str(org_id), str(user_id or ""))
    settings = await _settings(db, org_id)
    prompt_rows = await db.execute(
        select(PromptVersion).where(
            PromptVersion.organization_id == org_id, PromptVersion.active.is_(True)
        )
    )
    prompts = {row.agent_key: row.body for row in prompt_rows.scalars().all()}
    tool_rows = await db.execute(
        select(AgentToolSetting).where(AgentToolSetting.organization_id == org_id)
    )
    tools = {f"{row.agent_key}.{row.tool_key}": row.enabled for row in tool_rows.scalars().all()}
    bind_runtime(
        prompts,
        tools,
        {
            "model": settings.model,
            "base_url": settings.base_url,
            "provider": settings.provider,
            "agents": settings.agent_models or {},
            "debate": {
                "enabled": settings.debate_enabled,
                "threshold": settings.debate_threshold,
                "max_rounds": settings.debate_max_rounds,
            },
        },
    )
    await _prime_about(db, org_id, user_id)


async def _prime_about(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    """Per professor, per university. Never the global prompt."""
    if user_id is None:
        set_about("")
        return
    profile = (
        await db.execute(
            select(StyleProfile).where(
                StyleProfile.organization_id == org_id, StyleProfile.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    courses = [
        row.code
        for row in (
            await db.execute(select(Course).where(Course.organization_id == org_id))
        ).scalars()
    ]
    memories = await list_memories(db, org_id, user_id)
    saved = profile.about_md if profile else ""
    set_about(
        saved.strip() or condense_about(profile.soul_md if profile else "", memories, courses)
    )


def _secret_state(name: str) -> dict[str, str]:
    """Say whether a secret is set. Never return the value."""
    present = bool(os.getenv(name, "").strip())
    return {"name": name, "state": "set, hidden" if present else "not set"}


def connection_status() -> dict[str, Any]:
    """Read-only picture of servers that are configured outside this screen.

    Secrets are reduced to "set, hidden" or "not set". Host names and modes are
    not secrets, so those are shown in full.
    """
    from app.core.config import settings
    from app.profassist.config import (
        langfuse_enabled,
        llm_base_url,
        llm_model,
        moodle_mode,
        moodle_push_enabled,
    )
    from app.profassist.observe import public_base

    fastmcp = importlib.util.find_spec("fastmcp") is not None
    secret_names = (
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "XAI_API_KEY",
        "MISTRAL_API_KEY",
        "AZURE_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "QDRANT_API_KEY",
        "MOODLE_WS_TOKEN",
    )
    return {
        "moodle_mode": moodle_mode(),
        "moodle_push_enabled": moodle_push_enabled(),
        "moodle_base_url": os.getenv("MOODLE_BASE_URL", "").strip() or "not set",
        "model_from_env": llm_model(),
        "base_url": llm_base_url() or "not set",
        "langfuse_enabled": langfuse_enabled(),
        "langfuse_host": public_base(),
        "qdrant_host": settings.QDRANT_HOST,
        "qdrant_port": settings.QDRANT_PORT,
        "mcp_installed": fastmcp,
        "mcp_path": "/mcp" if fastmcp else "not mounted",
        "secrets": [_secret_state(name) for name in secret_names],
    }


async def admin_view(db: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    settings = await _settings(db, org_id)
    version_rows = list(
        (
            await db.execute(
                select(PromptVersion)
                .where(PromptVersion.organization_id == org_id)
                .order_by(PromptVersion.agent_key, PromptVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    audit_rows = list(
        (
            await db.execute(
                select(PromptAudit)
                .where(PromptAudit.organization_id == org_id)
                .order_by(PromptAudit.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    tool_rows = await db.execute(
        select(AgentToolSetting).where(AgentToolSetting.organization_id == org_id)
    )
    stored = {(row.agent_key, row.tool_key): row.enabled for row in tool_rows.scalars().all()}
    tools = []
    for agent, names in DEFAULT_TOOLS.items():
        for name in names:
            tools.append({"agent": agent, "tool": name, "enabled": stored.get((agent, name), True)})
    from app.profassist.observe import prompt_status

    published = {row.agent_key: row.body for row in version_rows if row.active}
    sources = [prompt_status(name, published.get(name)) for name in DEFAULT_PROMPTS]
    return {
        "chat_enabled": settings.chat_enabled,
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url,
        "debate_enabled": settings.debate_enabled,
        "debate_threshold": settings.debate_threshold,
        "debate_max_rounds": settings.debate_max_rounds,
        "providers": provider_catalog(),
        "agents": AGENTS,
        "agent_models": settings.agent_models or {},
        "moodle_sync_paused": settings.moodle_sync_paused,
        "moodle_sync_minutes": settings.moodle_sync_minutes,
        "moodle_nightly_enabled": settings.moodle_nightly_enabled,
        "moodle_nightly_hour": settings.moodle_nightly_hour,
        "prompts": [
            {
                "agent": row.agent_key,
                "version": row.version,
                "body": row.body,
                "active": row.active,
            }
            for row in version_rows
        ],
        "prompt_sources": sources,
        "defaults": catalog()["prompts"],
        "tools": tools,
        "connections": connection_status(),
        "audit": [
            {
                "agent": row.agent_key,
                "version": row.version,
                "action": row.action,
                "before": row.before,
                "after": row.after,
            }
            for row in audit_rows[:20]
        ],
    }


async def save_model_settings(
    db: AsyncSession,
    org_id: uuid.UUID,
    actor: uuid.UUID,
    chat_enabled: bool,
    provider: str,
    model: str,
    base_url: str,
    debate_enabled: bool = True,
    debate_threshold: int = 0,
    debate_max_rounds: int = 1,
    agent_models: dict | None = None,
    moodle_sync_paused: bool = False,
    moodle_sync_minutes: int = 30,
    moodle_nightly_enabled: bool = True,
    moodle_nightly_hour: int = 2,
) -> dict[str, Any]:
    from app.profassist.moodle_schedule import normalize_hour, normalize_minutes

    row = await _settings(db, org_id)
    before = f"{row.provider} {row.model} chat={row.chat_enabled}"
    row.chat_enabled = chat_enabled
    row.provider = provider or "openai"
    row.model = model or "gpt-4o-mini"
    row.base_url = base_url or ""
    row.debate_enabled = debate_enabled
    row.debate_threshold = max(0, int(debate_threshold))
    row.debate_max_rounds = max(0, min(3, int(debate_max_rounds)))
    row.agent_models = agent_models or {}
    row.moodle_sync_paused = moodle_sync_paused
    row.moodle_sync_minutes = normalize_minutes(int(moodle_sync_minutes))
    row.moodle_nightly_enabled = moodle_nightly_enabled
    row.moodle_nightly_hour = normalize_hour(int(moodle_nightly_hour))
    db.add(
        PromptAudit(
            organization_id=org_id,
            agent_key="settings",
            version=0,
            action="update_model",
            actor_user_id=actor,
            before=before,
            after=f"{row.provider} {row.model} chat={row.chat_enabled}",
        )
    )
    return await admin_view(db, org_id)


async def save_prompt(
    db: AsyncSession, org_id: uuid.UUID, actor: uuid.UUID, agent_key: str, body: str
) -> dict[str, Any]:
    if agent_key not in DEFAULT_PROMPTS:
        agent_key = "chat"
    current = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.organization_id == org_id, PromptVersion.agent_key == agent_key)
        .order_by(PromptVersion.version.desc())
    )
    rows = list(current.scalars().all())
    previous = next((row.body for row in rows if row.active), DEFAULT_PROMPTS[agent_key])
    version = (rows[0].version + 1) if rows else 1
    for row in rows:
        row.active = False
    db.add(
        PromptVersion(
            organization_id=org_id,
            agent_key=agent_key,
            version=version,
            body=body,
            active=True,
            created_by=actor,
        )
    )
    db.add(
        PromptAudit(
            organization_id=org_id,
            agent_key=agent_key,
            version=version,
            action="publish",
            actor_user_id=actor,
            before=previous,
            after=body,
        )
    )
    await db.flush()
    return await admin_view(db, org_id)


async def set_tool(
    db: AsyncSession,
    org_id: uuid.UUID,
    actor: uuid.UUID,
    agent_key: str,
    tool_key: str,
    enabled: bool,
) -> dict[str, Any]:
    result = await db.execute(
        select(AgentToolSetting).where(
            AgentToolSetting.organization_id == org_id,
            AgentToolSetting.agent_key == agent_key,
            AgentToolSetting.tool_key == tool_key,
        )
    )
    row = result.scalar_one_or_none()
    before = "default" if row is None else str(row.enabled)
    if row is None:
        row = AgentToolSetting(
            organization_id=org_id, agent_key=agent_key, tool_key=tool_key, enabled=enabled
        )
        db.add(row)
    else:
        row.enabled = enabled
    db.add(
        PromptAudit(
            organization_id=org_id,
            agent_key=agent_key,
            version=0,
            action="toggle_tool",
            actor_user_id=actor,
            before=f"{tool_key}={before}",
            after=f"{tool_key}={enabled}",
        )
    )
    return await admin_view(db, org_id)


async def chat_is_enabled(db: AsyncSession, org_id: uuid.UUID) -> bool:
    settings = await _settings(db, org_id)
    return bool(settings.chat_enabled)
