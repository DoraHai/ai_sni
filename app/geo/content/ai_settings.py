"""GEO AI 能力配置：默认走阿里云百炼 OpenAI 兼容接口。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.geo_ai_setting import GeoAiSetting
from app.security.crypto import decrypt, encrypt

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "dashscope": {
        "label": "阿里云百炼（DashScope）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "deepseek-v3",
        "hint": "控制台创建 API Key；OpenAI 兼容模式调用 DeepSeek / 通义等模型",
    },
    "deepseek": {
        "label": "DeepSeek 官方",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "hint": "直连 api.deepseek.com（阿里云 ECS 可用）",
    },
}


def mask_api_key(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip()
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def preset_payload() -> list[dict[str, str]]:
    return [
        {"provider": key, **value} for key, value in PROVIDER_PRESETS.items()
    ]


async def get_ai_setting_row(
    session: AsyncSession, tenant_id: int
) -> GeoAiSetting | None:
    return await session.scalar(
        select(GeoAiSetting).where(GeoAiSetting.tenant_id == tenant_id)
    )


async def ensure_ai_setting(
    session: AsyncSession, tenant_id: int
) -> GeoAiSetting:
    row = await get_ai_setting_row(session, tenant_id)
    if row is not None:
        return row
    preset = PROVIDER_PRESETS["dashscope"]
    row = GeoAiSetting(
        tenant_id=tenant_id,
        provider="dashscope",
        base_url=preset["base_url"],
        model=preset["model"],
        api_key_encrypted=None,
        enabled=True,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def _decrypt_key(row: GeoAiSetting) -> str | None:
    if not row.api_key_encrypted:
        return None
    try:
        return decrypt(row.api_key_encrypted)
    except Exception:
        return None


def settings_public_payload(row: GeoAiSetting) -> dict[str, Any]:
    plain = _decrypt_key(row)
    return {
        "tenant_id": row.tenant_id,
        "provider": row.provider,
        "base_url": row.base_url,
        "model": row.model,
        "enabled": bool(row.enabled),
        "api_key_configured": bool(plain),
        "api_key_masked": mask_api_key(plain),
        "note": row.note,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def resolve_llm_credentials(
    session: AsyncSession, tenant_id: int
) -> dict[str, str] | None:
    """Resolve API credentials for GEO AI calls.

    Priority: tenant enabled + key → env DASHSCOPE_API_KEY / DEEPSEEK_API_KEY.
    """
    row = await get_ai_setting_row(session, tenant_id)
    if row is not None and row.enabled:
        key = _decrypt_key(row)
        if key:
            return {
                "api_key": key,
                "base_url": (row.base_url or PROVIDER_PRESETS["dashscope"]["base_url"]).rstrip(
                    "/"
                ),
                "model": row.model or PROVIDER_PRESETS["dashscope"]["model"],
                "provider": row.provider or "dashscope",
                "source": "tenant",
            }

    s = get_settings()
    # Prefer DashScope env for 阿里云路径
    dash_key = (getattr(s, "dashscope_api_key", None) or "").strip()
    if dash_key:
        preset = PROVIDER_PRESETS["dashscope"]
        return {
            "api_key": dash_key,
            "base_url": (
                getattr(s, "dashscope_base_url", None) or preset["base_url"]
            ).rstrip("/"),
            "model": getattr(s, "dashscope_model", None) or preset["model"],
            "provider": "dashscope",
            "source": "env_dashscope",
        }
    if s.deepseek_api_key:
        return {
            "api_key": s.deepseek_api_key,
            "base_url": s.deepseek_base_url.rstrip("/"),
            "model": s.deepseek_model,
            "provider": "deepseek",
            "source": "env_deepseek",
        }
    return None


def apply_provider_preset(provider: str) -> dict[str, str]:
    key = (provider or "dashscope").strip().lower()
    if key not in PROVIDER_PRESETS:
        key = "dashscope"
    preset = PROVIDER_PRESETS[key]
    return {
        "provider": key,
        "base_url": preset["base_url"],
        "model": preset["model"],
    }


def encrypt_api_key(raw: str) -> str:
    return encrypt(raw.strip())
