"""Operational alerts for GEO overview / publishing (non-blocking)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    GeoChannelAccount,
    GeoContentTask,
    GeoPublishingChannel,
    GeoVisibilityPatrolRun,
    GeoVisibilityPatrolSettings,
)


def _parse_exp(raw: Any) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", ""))
    except ValueError:
        return None


def account_token_health(creds: dict[str, Any] | None) -> dict[str, Any]:
    """Classify token expiry for social/oauth accounts."""
    if not creds:
        return {
            "token_expires_at": None,
            "token_expired": False,
            "token_expiring_soon": False,
            "oauth_authorized": False,
            "provider": None,
        }
    exp = _parse_exp(creds.get("token_expires_at"))
    token = bool(str(creds.get("access_token") or "").strip())
    now = datetime.utcnow()
    expired = bool(exp and exp <= now)
    soon = bool(exp and not expired and exp <= now + timedelta(hours=48))
    provider = str(creds.get("provider") or "") or None
    if provider == "oauth2" or creds.get("authorize_url"):
        oauth_ok = token
    else:
        oauth_ok = token or bool(creds.get("app_id") and creds.get("app_secret"))
    return {
        "token_expires_at": exp.isoformat(timespec="seconds") if exp else None,
        "token_expired": expired,
        "token_expiring_soon": soon,
        "oauth_authorized": bool(oauth_ok),
        "provider": provider,
    }


async def build_ops_alerts(
    session: AsyncSession,
    *,
    tenant_id: int,
) -> dict[str, Any]:
    """Aggregate actionable ops alerts for dashboard."""
    from app.config import get_settings
    from app.geo.content.connectors.social import decrypt_credentials_json
    from app.geo.content.multi_push import tenant_auto_push_matrix
    from app.geo.content.patrol import count_patrol_runs_today

    alerts: list[dict[str, Any]] = []

    # ---- patrol ----
    day_limit = int(getattr(get_settings(), "geo_patrol_max_runs_per_day", 24) or 24)
    used = await count_patrol_runs_today(session, tenant_id)
    settings_row = await session.get(GeoVisibilityPatrolSettings, tenant_id)
    last = await session.scalar(
        select(GeoVisibilityPatrolRun)
        .where(GeoVisibilityPatrolRun.tenant_id == tenant_id)
        .order_by(GeoVisibilityPatrolRun.id.desc())
        .limit(1)
    )
    if last and last.status == "failed":
        alerts.append(
            {
                "level": "error",
                "code": "patrol_failed",
                "title": f"最近巡检 #{last.id} 失败",
                "detail": (last.error or "未知错误")[:240],
                "href": "/geo/visibility/patrol",
            }
        )
    elif last and last.status == "completed":
        summary = last.summary or {}
        fail = int(summary.get("cells_fail") or 0)
        if fail:
            alerts.append(
                {
                    "level": "warning",
                    "code": "patrol_cell_fail",
                    "title": f"最近巡检有 {fail} 格失败",
                    "detail": "请检查引擎 Key / LLM 配置",
                    "href": "/geo/visibility/patrol",
                }
            )
    if used >= day_limit:
        alerts.append(
            {
                "level": "warning",
                "code": "patrol_quota",
                "title": f"今日巡检已达配额 {used}/{day_limit}",
                "detail": "可调高 GEO_PATROL_MAX_RUNS_PER_DAY 或明日再试",
                "href": "/geo/visibility/patrol",
            }
        )
    if settings_row is not None and not bool(settings_row.enabled):
        alerts.append(
            {
                "level": "info",
                "code": "patrol_disabled",
                "title": "定时巡检未开启",
                "detail": "可在全自动巡检页启用时间窗调度",
                "href": "/geo/visibility/patrol",
            }
        )

    # ---- content todos ----
    blocked_n = int(
        await session.scalar(
            select(func.count())
            .select_from(GeoContentTask)
            .where(
                GeoContentTask.tenant_id == tenant_id,
                GeoContentTask.status.notin_(("published", "archived")),
                GeoContentTask.blocked_reason.isnot(None),
                GeoContentTask.blocked_reason != "",
            )
        )
        or 0
    )
    if blocked_n:
        alerts.append(
            {
                "level": "warning",
                "code": "tasks_blocked",
                "title": f"{blocked_n} 篇优化文章被规则阻断",
                "detail": "请到优化文章列表处理补丁/审校",
                "href": "/geo/tasks",
            }
        )

    # ---- social credentials ----
    accounts = list(
        await session.scalars(
            select(GeoChannelAccount).where(
                GeoChannelAccount.tenant_id == tenant_id,
                GeoChannelAccount.status == "active",
            )
        )
    )
    expiring = 0
    expired = 0
    oauth_pending = 0
    for acc in accounts:
        if not acc.credentials_encrypted:
            continue
        if str(acc.auth_type or "") not in {"social_api", "oauth2", "api_key"}:
            continue
        try:
            creds = decrypt_credentials_json(acc.credentials_encrypted)
        except Exception:  # noqa: BLE001
            continue
        health = account_token_health(creds)
        if health["token_expired"]:
            expired += 1
            alerts.append(
                {
                    "level": "error",
                    "code": "token_expired",
                    "title": f"账号「{acc.display_name}」token 已过期",
                    "detail": "请刷新 OAuth 或重新校验微信凭证",
                    "href": "/geo/publishing",
                    "account_id": acc.id,
                }
            )
        elif health["token_expiring_soon"]:
            expiring += 1
            alerts.append(
                {
                    "level": "warning",
                    "code": "token_expiring",
                    "title": f"账号「{acc.display_name}」token 将在 48h 内过期",
                    "detail": health.get("token_expires_at") or "",
                    "href": "/geo/publishing",
                    "account_id": acc.id,
                }
            )
        if str(acc.auth_type) == "oauth2" or str(creds.get("provider")) == "oauth2":
            if not creds.get("access_token"):
                oauth_pending += 1
                alerts.append(
                    {
                        "level": "warning",
                        "code": "oauth_pending",
                        "title": f"账号「{acc.display_name}」未完成 OAuth 授权",
                        "detail": "在发布渠道页点「去授权」",
                        "href": "/geo/publishing",
                        "account_id": acc.id,
                    }
                )

    # ---- multi-media config ----
    try:
        matrix = await tenant_auto_push_matrix(session, tenant_id=tenant_id)
        rows = matrix.get("items") or matrix.get("rows") or []
        not_ready = [r for r in rows if r.get("config_ready") is False]
        if not_ready:
            names = "、".join(
                str(r.get("name") or r.get("channel_type") or "?") for r in not_ready[:5]
            )
            alerts.append(
                {
                    "level": "info",
                    "code": "push_config_incomplete",
                    "title": f"{len(not_ready)} 路多媒推送配置未就绪",
                    "detail": names,
                    "href": "/geo/publishing",
                }
            )
    except Exception:  # noqa: BLE001
        chs = list(
            await session.scalars(
                select(GeoPublishingChannel).where(
                    GeoPublishingChannel.tenant_id == tenant_id,
                    GeoPublishingChannel.enabled.is_(True),
                    GeoPublishingChannel.publish_mode == "auto_publish",
                )
            )
        )
        by_ch: dict[int, int] = {}
        for a in accounts:
            if a.credentials_encrypted and a.status == "active":
                by_ch[int(a.channel_id)] = by_ch.get(int(a.channel_id), 0) + 1
        missing = [c for c in chs if not by_ch.get(int(c.id))]
        if missing:
            alerts.append(
                {
                    "level": "info",
                    "code": "push_config_incomplete",
                    "title": f"{len(missing)} 个 auto_publish 渠道缺凭证",
                    "detail": "、".join(c.name for c in missing[:5]),
                    "href": "/geo/publishing",
                }
            )

    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for a in alerts:
        key = f"{a.get('code')}:{a.get('title')}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)

    level_rank = {"error": 0, "warning": 1, "info": 2}
    uniq.sort(key=lambda x: level_rank.get(str(x.get("level")), 9))

    return {
        "tenant_id": tenant_id,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "summary": {
            "total": len(uniq),
            "error": sum(1 for a in uniq if a.get("level") == "error"),
            "warning": sum(1 for a in uniq if a.get("level") == "warning"),
            "info": sum(1 for a in uniq if a.get("level") == "info"),
            "tokens_expired": expired,
            "tokens_expiring_soon": expiring,
            "oauth_pending": oauth_pending,
            "patrol_quota_used": used,
            "patrol_quota_max": day_limit,
        },
        "alerts": uniq,
    }
