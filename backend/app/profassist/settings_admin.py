"""Admin-editable AI settings, versioned prompts, and per-agent tools."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profassist.models import AgentToolSetting, AiSettings, PromptAudit, PromptVersion
from app.profassist.runtime import DEFAULT_PROMPTS, DEFAULT_TOOLS, bind_runtime, catalog


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
        {"model": settings.model, "base_url": settings.base_url, "provider": settings.provider},
    )


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
) -> dict[str, Any]:
    row = await _settings(db, org_id)
    before = f"{row.provider} {row.model} chat={row.chat_enabled}"
    row.chat_enabled = chat_enabled
    row.provider = provider or "openai"
    row.model = model or "gpt-4o-mini"
    row.base_url = base_url or ""
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
