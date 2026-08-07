"""Multi-media auto-push orchestration (webhook + social_api).

Ready = channel enabled + publish_mode=auto_publish + active account with
credentials + matching exported variant. Ops only need to fill credentials.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.channel_registry import profile_key_for_registry_type
from app.geo.content.connectors.social import (
    SOCIAL_PLATFORMS,
    build_social_payload,
    post_social,
)
from app.geo.content.connectors.webhook import (
    build_webhook_payload,
    decrypt_credentials_json,
    post_webhook,
)
from app.models import (
    GeoChannelAccount,
    GeoChannelVariant,
    GeoContentTask,
    GeoPublishingChannel,
)

logger = logging.getLogger(__name__)

WEB_TYPES = frozenset({"website", "docs"})
AUTO_PUSH_TYPES = WEB_TYPES | SOCIAL_PLATFORMS


def account_push_kind(auth_type: str | None, channel_type: str) -> str | None:
    at = str(auth_type or "").lower()
    ct = str(channel_type or "").lower()
    if ct in WEB_TYPES and at == "webhook":
        return "webhook"
    if ct in SOCIAL_PLATFORMS and at in {"social_api", "api_key", "oauth2"}:
        return "social"
    return None


def variant_key_for_channel(channel_type: str) -> str:
    adapt = profile_key_for_registry_type(channel_type)
    return adapt or channel_type


async def list_push_targets(
    session: AsyncSession,
    *,
    tenant_id: int,
    task: GeoContentTask,
    variants: list[GeoChannelVariant] | None = None,
) -> list[dict[str, Any]]:
    """Describe every auto-push slot for this task (ready or blocked + reason)."""
    channels = list(
        await session.scalars(
            select(GeoPublishingChannel)
            .where(
                GeoPublishingChannel.tenant_id == tenant_id,
                GeoPublishingChannel.enabled.is_(True),
            )
            .order_by(GeoPublishingChannel.sort_order, GeoPublishingChannel.id)
        )
    )
    accounts = list(
        await session.scalars(
            select(GeoChannelAccount).where(
                GeoChannelAccount.tenant_id == tenant_id,
                GeoChannelAccount.status == "active",
            )
        )
    )
    by_channel: dict[int, list[GeoChannelAccount]] = {}
    for acc in accounts:
        by_channel.setdefault(int(acc.channel_id), []).append(acc)

    if variants is None:
        variants = list(
            await session.scalars(
                select(GeoChannelVariant).where(GeoChannelVariant.task_id == task.id)
            )
        )
    var_map = {str(v.channel).lower(): v for v in variants}

    targets: list[dict[str, Any]] = []
    for ch in channels:
        ctype = str(ch.channel_type or "").lower()
        if ctype not in AUTO_PUSH_TYPES:
            continue
        adapt = variant_key_for_channel(ctype)
        variant = var_map.get(adapt) or var_map.get(ctype)
        mode = str(ch.publish_mode or "manual_only")
        accs = by_channel.get(int(ch.id), [])
        pushable_accs = [
            a
            for a in accs
            if account_push_kind(a.auth_type, ctype) and a.credentials_encrypted
        ]

        base = {
            "channel_id": ch.id,
            "channel_name": ch.name,
            "channel_type": ctype,
            "adapt_key": adapt,
            "publish_mode": mode,
            "variant_status": variant.status if variant else None,
            "has_variant": variant is not None,
            "accounts": [
                {
                    "account_id": a.id,
                    "display_name": a.display_name,
                    "auth_type": a.auth_type,
                    "has_credentials": bool(a.credentials_encrypted),
                    "push_kind": account_push_kind(a.auth_type, ctype),
                }
                for a in accs
            ],
        }

        reasons: list[str] = []
        if mode != "auto_publish":
            reasons.append("发布模式不是 auto_publish（在发布渠道里改为 auto_publish）")
        if variant is None:
            reasons.append(f"无渠道稿（任务里生成并导出 {adapt}）")
        elif variant.status not in {"exported", "published"}:
            reasons.append("渠道稿未导出")
        if not pushable_accs:
            if ctype in WEB_TYPES:
                reasons.append("缺少 webhook 账号+凭证")
            else:
                reasons.append(
                    "缺少社交账号凭证（gateway: api_url+token · wechat_mp: app_id+secret · oauth2: 授权后 token）"
                )

        if reasons:
            targets.append(
                {
                    **base,
                    "ready": False,
                    "block_reasons": reasons,
                    "account_id": None,
                    "default_account_id": None,
                }
            )
            continue

        for a in pushable_accs:
            targets.append(
                {
                    **base,
                    "ready": True,
                    "block_reasons": [],
                    "account_id": a.id,
                    "account_name": a.display_name,
                    "auth_type": a.auth_type,
                    "push_kind": account_push_kind(a.auth_type, ctype),
                    "default_account_id": a.id,
                }
            )
    return targets


async def execute_single_push(
    session: AsyncSession,
    *,
    task: GeoContentTask,
    variant: GeoChannelVariant,
    channel_row: GeoPublishingChannel,
    account: GeoChannelAccount,
    mode: str,
    article: Any | None,
) -> dict[str, Any]:
    """Execute remote push for one channel+account. Does not write publication."""
    ctype = str(channel_row.channel_type or "").lower()
    channel = str(variant.channel or "").lower()
    kind = account_push_kind(account.auth_type, ctype)
    if not kind:
        raise ValueError(f"账号鉴权类型与渠道 {ctype} 不匹配")
    if not account.credentials_encrypted:
        raise ValueError("账号未配置凭证")

    credentials = decrypt_credentials_json(account.credentials_encrypted)
    if kind == "social":
        if not credentials.get("platform"):
            credentials = {**credentials, "platform": ctype}
        payload = build_social_payload(
            platform=str(credentials.get("platform") or ctype),
            mode=mode,
            tenant_id=task.tenant_id,
            task_id=task.id,
            channel=channel,
            title=variant.title or task.title or "",
            body_markdown=variant.body_markdown or "",
            body_html=getattr(article, "body_html", None) if article else None,
        )
        remote = await post_social(credentials, payload)
        # Persist refreshed OAuth / WeChat tokens
        patch = remote.get("credential_patch") if isinstance(remote, dict) else None
        if isinstance(patch, dict) and patch:
            try:
                from app.geo.content.ai_settings import encrypt_api_key

                merged = {**credentials, **patch}
                account.credentials_encrypted = encrypt_api_key(
                    json.dumps(merged, ensure_ascii=False, sort_keys=True)
                )
                await session.flush()
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist social credential patch account=%s", account.id)
    else:
        payload = build_webhook_payload(
            action=mode,
            tenant_id=task.tenant_id,
            task_id=task.id,
            channel=channel,
            channel_type=channel_row.channel_type,
            title=variant.title or task.title or "",
            body_markdown=variant.body_markdown or "",
            export_format=variant.export_format or "markdown",
            base_url=channel_row.base_url,
        )
        remote = await post_webhook(credentials, payload)

    return {
        "ok": True,
        "connector": kind,
        "platform": remote.get("platform") or ctype,
        "channel": channel,
        "channel_type": ctype,
        "channel_id": channel_row.id,
        "channel_name": channel_row.name,
        "account_id": account.id,
        "account_name": account.display_name,
        "http_status": remote.get("http_status"),
        "remote_url": remote.get("remote_url"),
        "host": remote.get("webhook_host") or remote.get("host"),
        "mode": mode,
        "response": remote.get("response"),
    }


async def tenant_auto_push_matrix(
    session: AsyncSession,
    *,
    tenant_id: int,
) -> dict[str, Any]:
    """Tenant-level readiness matrix (no task): config checklist for ops."""
    channels = list(
        await session.scalars(
            select(GeoPublishingChannel)
            .where(GeoPublishingChannel.tenant_id == tenant_id)
            .order_by(GeoPublishingChannel.sort_order, GeoPublishingChannel.id)
        )
    )
    accounts = list(
        await session.scalars(
            select(GeoChannelAccount).where(GeoChannelAccount.tenant_id == tenant_id)
        )
    )
    by_ch: dict[int, list[GeoChannelAccount]] = {}
    for a in accounts:
        by_ch.setdefault(int(a.channel_id), []).append(a)

    rows: list[dict[str, Any]] = []
    ready_n = 0
    for ch in channels:
        ctype = str(ch.channel_type or "").lower()
        if ctype not in AUTO_PUSH_TYPES:
            continue
        accs = by_ch.get(int(ch.id), [])
        pushable = [
            a
            for a in accs
            if a.status == "active"
            and account_push_kind(a.auth_type, ctype)
            and a.credentials_encrypted
        ]
        auto = str(ch.publish_mode) == "auto_publish" and bool(ch.enabled)
        config_ready = auto and len(pushable) > 0
        if config_ready:
            ready_n += 1
        tips: list[str] = []
        if not ch.enabled:
            tips.append("渠道已停用")
        if str(ch.publish_mode) != "auto_publish":
            tips.append("改为 auto_publish")
        if not pushable:
            tips.append(
                "配置 webhook 凭证"
                if ctype in WEB_TYPES
                else "配置 social_api（api_url + access_token）"
            )
        rows.append(
            {
                "channel_id": ch.id,
                "name": ch.name,
                "channel_type": ctype,
                "enabled": bool(ch.enabled),
                "publish_mode": ch.publish_mode,
                "adapt_key": variant_key_for_channel(ctype),
                "push_kind": "webhook" if ctype in WEB_TYPES else "social",
                "account_count": len(accs),
                "ready_accounts": len(pushable),
                "config_ready": config_ready,
                "tips": tips,
                "credential_schema": (
                    {
                        "auth_type": "webhook",
                        "fields": ["webhook_url", "method?", "secret?", "headers?"],
                    }
                    if ctype in WEB_TYPES
                    else {
                        "auth_type": "social_api",
                        "fields": [
                            "platform",
                            "api_url",
                            "access_token",
                            "method?",
                            "headers?",
                        ],
                    }
                ),
            }
        )
    return {
        "tenant_id": tenant_id,
        "items": rows,
        "ready_count": ready_n,
        "total_auto_types": len(rows),
        "hint": "config_ready=true 后，任务导出渠道稿+审校通过即可一键推送",
    }
