"""租户级渠道成稿提示词：查询生效值 / 写入覆盖 / 供润色 resolve。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.channel_polish_defaults import (
    DEFAULT_SYSTEM_PROMPT,
    SYSTEM_CHANNEL_KEY,
    default_min_body_chars,
    default_voice_for_channel,
    list_default_prompts,
)
from app.geo.content.channel_profiles import CHANNEL_PROFILES, SUPPORTED_CHANNELS
from app.geo.content.channel_registry import profile_key_for_registry_type
from app.models.geo_channel_polish_prompt import GeoChannelPolishPrompt
from app.models.geo_publishing_channel import GeoPublishingChannel


async def _rows_by_key(
    session: AsyncSession, tenant_id: int
) -> dict[str, GeoChannelPolishPrompt]:
    rows = (
        await session.scalars(
            select(GeoChannelPolishPrompt).where(
                GeoChannelPolishPrompt.tenant_id == tenant_id
            )
        )
    ).all()
    return {r.channel_key: r for r in rows}


async def get_or_create_row(
    session: AsyncSession, tenant_id: int, channel_key: str
) -> GeoChannelPolishPrompt:
    row = await session.scalar(
        select(GeoChannelPolishPrompt).where(
            GeoChannelPolishPrompt.tenant_id == tenant_id,
            GeoChannelPolishPrompt.channel_key == channel_key,
        )
    )
    if row is not None:
        return row
    row = GeoChannelPolishPrompt(tenant_id=tenant_id, channel_key=channel_key)
    session.add(row)
    await session.flush()
    return row


def _channel_payload(key: str, row: GeoChannelPolishPrompt | None) -> dict[str, Any]:
    profile = CHANNEL_PROFILES.get(key)
    voice_default = default_voice_for_channel(key)
    min_default = default_min_body_chars(key)
    custom_voice = bool(row and (row.voice_prompt or "").strip())
    custom_min = bool(row and row.min_body_chars is not None)
    return {
        "channel_key": key,
        "display_name": profile.display_name if profile else key,
        "voice_prompt": (row.voice_prompt or "").strip() if custom_voice else voice_default,
        "voice_default": voice_default,
        "min_body_chars": int(row.min_body_chars) if custom_min else min_default,
        "min_body_chars_default": min_default,
        "is_custom_voice": custom_voice,
        "is_custom_min_body_chars": custom_min,
    }


async def enabled_adapt_keys(session: AsyncSession, tenant_id: int) -> list[str]:
    """Adapt keys currently enabled on 分发平台 (website/docs share website)."""
    rows = (
        await session.scalars(
            select(GeoPublishingChannel).where(
                GeoPublishingChannel.tenant_id == tenant_id,
                GeoPublishingChannel.enabled.is_(True),
            )
        )
    ).all()
    keys: list[str] = []
    for row in rows:
        adapt = profile_key_for_registry_type(getattr(row, "channel_type", None))
        if adapt and adapt in CHANNEL_PROFILES and adapt not in keys:
            keys.append(adapt)
    return keys


async def has_publishing_rows(session: AsyncSession, tenant_id: int) -> bool:
    row = await session.scalar(
        select(GeoPublishingChannel.id).where(GeoPublishingChannel.tenant_id == tenant_id)
    )
    return row is not None


async def set_adapt_channel_enabled(
    session: AsyncSession,
    tenant_id: int,
    adapt_key: str,
    *,
    enabled: bool,
    created_by: int | None = None,
) -> None:
    """Enable/create or disable publishing rows that map to this polish tab."""
    if adapt_key not in CHANNEL_PROFILES:
        raise ValueError(f"不支持的渠道: {adapt_key}")
    rows = list(
        await session.scalars(
            select(GeoPublishingChannel).where(GeoPublishingChannel.tenant_id == tenant_id)
        )
    )
    matched = [
        r
        for r in rows
        if profile_key_for_registry_type(r.channel_type) == adapt_key
    ]
    if enabled:
        if matched:
            for row in matched:
                row.enabled = True
        else:
            profile = CHANNEL_PROFILES[adapt_key]
            auto = adapt_key in {"website", "docs", "wechat", "zhihu", "baijiahao", "toutiao"}
            session.add(
                GeoPublishingChannel(
                    tenant_id=tenant_id,
                    name=profile.display_name,
                    channel_type=adapt_key,
                    publish_mode="auto_publish" if auto else "manual_only",
                    enabled=True,
                    sort_order=80,
                    created_by=created_by,
                )
            )
        await get_or_create_row(session, tenant_id, adapt_key)
        return
    for row in matched:
        row.enabled = False


async def get_effective_prompts(session: AsyncSession, tenant_id: int) -> dict[str, Any]:
    by_key = await _rows_by_key(session, tenant_id)
    sys_row = by_key.get(SYSTEM_CHANNEL_KEY)
    custom_system = bool(sys_row and (sys_row.system_prompt or "").strip())
    system_prompt = (
        (sys_row.system_prompt or "").strip() if custom_system else DEFAULT_SYSTEM_PROMPT
    )

    keys = await enabled_adapt_keys(session, tenant_id)
    if not keys and not await has_publishing_rows(session, tenant_id):
        keys = list(SUPPORTED_CHANNELS)

    channels = [_channel_payload(key, by_key.get(key)) for key in keys]
    present = {c["channel_key"] for c in channels}
    available = [
        {"channel_key": key, "display_name": CHANNEL_PROFILES[key].display_name}
        for key in SUPPORTED_CHANNELS
        if key not in present
    ]

    return {
        "tenant_id": tenant_id,
        "system_prompt": system_prompt,
        "system_prompt_default": DEFAULT_SYSTEM_PROMPT,
        "is_custom_system": custom_system,
        "channels": channels,
        "available_channels": available,
        "defaults": list_default_prompts(),
    }


async def resolve_for_channel(
    session: AsyncSession, tenant_id: int, channel: str
) -> dict[str, Any]:
    """Return {system_prompt, voice_prompt, min_body_chars} for one polish call."""
    by_key = await _rows_by_key(session, tenant_id)
    sys_row = by_key.get(SYSTEM_CHANNEL_KEY)
    system = (
        (sys_row.system_prompt or "").strip()
        if sys_row and (sys_row.system_prompt or "").strip()
        else DEFAULT_SYSTEM_PROMPT
    )
    row = by_key.get(channel)
    voice = (
        (row.voice_prompt or "").strip()
        if row and (row.voice_prompt or "").strip()
        else default_voice_for_channel(channel)
    )
    min_chars = (
        int(row.min_body_chars)
        if row and row.min_body_chars is not None
        else default_min_body_chars(channel)
    )
    return {
        "system_prompt": system,
        "voice_prompt": voice,
        "min_body_chars": min_chars,
    }


async def upsert_prompts(
    session: AsyncSession,
    tenant_id: int,
    *,
    system_prompt: str | None = None,
    reset_system: bool = False,
    channels: list[dict[str, Any]] | None = None,
    add_channel_key: str | None = None,
    remove_channel_key: str | None = None,
    updated_by: int | None = None,
) -> dict[str, Any]:
    """Apply overrides. reset_* / channel reset clears custom values (use defaults).

    add/remove keeps 语气与字数 tabs in sync with enabled 分发平台.
    """
    if reset_system:
        row = await get_or_create_row(session, tenant_id, SYSTEM_CHANNEL_KEY)
        row.system_prompt = None
        row.updated_by = updated_by
    elif system_prompt is not None:
        text = system_prompt.strip()
        row = await get_or_create_row(session, tenant_id, SYSTEM_CHANNEL_KEY)
        row.system_prompt = text or None
        row.updated_by = updated_by

    for item in channels or []:
        key = str(item.get("channel_key") or "").strip()
        if key not in CHANNEL_PROFILES:
            continue
        row = await get_or_create_row(session, tenant_id, key)
        if item.get("reset"):
            row.voice_prompt = None
            row.min_body_chars = None
            row.updated_by = updated_by
            continue
        if "voice_prompt" in item:
            vp = item.get("voice_prompt")
            if vp is None:
                row.voice_prompt = None
            else:
                text = str(vp).strip()
                row.voice_prompt = text or None
        if "min_body_chars" in item:
            raw = item.get("min_body_chars")
            if raw is None:
                row.min_body_chars = None
            else:
                try:
                    n = int(raw)
                except (TypeError, ValueError):
                    n = default_min_body_chars(key)
                row.min_body_chars = max(100, min(n, 20000))
        row.updated_by = updated_by

    add_key = str(add_channel_key or "").strip().lower()
    if add_key:
        await set_adapt_channel_enabled(
            session, tenant_id, add_key, enabled=True, created_by=updated_by
        )
    remove_key = str(remove_channel_key or "").strip().lower()
    if remove_key:
        await set_adapt_channel_enabled(
            session, tenant_id, remove_key, enabled=False, created_by=updated_by
        )

    await session.commit()
    return await get_effective_prompts(session, tenant_id)
