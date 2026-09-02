"""GEO AI 能力配置 helpers.

Runtime model credentials are platform-managed server secrets. Historical
tenant rows remain readable for compatibility (for example monitoring stance),
but they must never override the credentials used for an AI call.
"""

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
        "hint": "控制台创建 API Key；仅用于 DeepSeek 巡检与母稿，不代替 ChatGPT / 豆包 / Kimi",
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
    stance = getattr(row, "monitoring_stance", None) or "hybrid"
    return {
        "tenant_id": row.tenant_id,
        "provider": row.provider,
        "base_url": row.base_url,
        "model": row.model,
        "enabled": bool(row.enabled),
        "api_key_configured": bool(plain),
        "api_key_masked": mask_api_key(plain),
        "monitoring_stance": stance,
        "note": row.note,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def resolve_llm_credentials(
    session: AsyncSession, tenant_id: int
) -> dict[str, str] | None:
    """Resolve the platform-managed credentials used by every GEO tenant.

    ``session`` and ``tenant_id`` stay in the signature because all existing
    GEO call sites are tenant-scoped. Credentials themselves intentionally come
    only from the geo-service environment, never from a tenant database row.
    """
    del session, tenant_id

    s = get_settings()
    # Prefer DashScope when both platform providers are configured.
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
    try:
        return encrypt(raw.strip())
    except Exception as exc:  # noqa: BLE001 — surface config/crypto failures clearly
        raise ValueError(
            "无法加密凭证：请检查 CRYPTO_MASTER_KEY_B64（需标准 Base64，解码后 32 字节）。"
            "可用：python -c \"from app.security.crypto import generate_master_key_b64 as g; print(g())\""
        ) from exc
