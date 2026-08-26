"""数据看板接口。

对应原型 02-monitor/01-dashboard.html。
M1 Day 2 范围：时段 KPI（含环比）+ 7 天趋势 + 设备维度 + 计划消费分布 + 实时余额。

数据口径：
  - 效果指标（消费/点击/展现/CPC/CTR）聚合自 kw_report_snapshots（每天 02:00 同步昨日）
  - 账户余额 / 累计消费 / 日预算实时调百度 getAccountInfo，调用失败时降级返回错误说明，不影响其余数据
  - 线索 / CPL 依赖转化数据（爱番番 / ocpc 转化列），M2 接入前返回 null
"""
import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu import BaiduAPIClient, BaiduAPIError
from app.baidu.services import AccountService
from app.database import get_session
from app.models import (
    Adgroup, Alert, BaiduAccount, Campaign, Keyword, KwReportSnapshot, Lead,
    SearchTermReport, Tenant,
)
from app.security.auth import AuthContext, require_scoped_auth
from app.security.crypto import decrypt

logger = logging.getLogger(__name__)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["数据看板"],
    dependencies=[Depends(require_scoped_auth)],
)

# 百度报告 device 落库为 int（见 sync._device_to_int）：0=计算机 1=移动设备
# 文档 0299 新版口径，与旧版数字不一致；返回中文 value 在同步层已转 int
DEVICE_LABELS = {0: "PC", 1: "移动"}


def _f(v: Any) -> float:
    """Decimal/None → float，金额统一保留 2 位。"""
    return round(float(v), 2) if v is not None else 0.0


def _derive(
    cost: float, click: int, impression: int, conversions: int | None = None
) -> dict[str, Any]:
    """由基础量算 CPC / CTR；传了 conversions 再算转化成本 / 转化率。除零返回 None。"""
    out = {
        "cost": round(cost, 2),
        "click": click,
        "impression": impression,
        "cpc": round(cost / click, 2) if click else None,
        "ctr": round(click / impression, 4) if impression else None,
    }
    if conversions is not None:
        out["conversions"] = conversions
        out["conv_cost"] = round(cost / conversions, 2) if conversions else None  # 转化成本（电话点击）
        out["cvr"] = round(conversions / click, 4) if click else None  # 转化率
    return out


def _change_pct(cur: float | None, prev: float | None) -> float | None:
    """环比变化百分比。上期为 0 或缺失时无法计算，返回 None。"""
    if cur is None or not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


async def _period_kpi(
    session: AsyncSession, tenant_id: int, start: date, end: date
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(KwReportSnapshot.cost), 0),
                func.coalesce(func.sum(KwReportSnapshot.click), 0),
                func.coalesce(func.sum(KwReportSnapshot.impression), 0),
            ).where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
        )
    ).one()
    return _derive(_f(row[0]), int(row[1]), int(row[2]))


async def _fetch_account_realtime(
    session: AsyncSession, tenant_id: int
) -> dict[str, Any]:
    """实时调百度 getAccountInfo 拿余额/累计消费/日预算。失败降级，不抛出。"""
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        return {"status": "error", "message": "该租户没有生效的百度账户授权"}

    try:
        # decrypt 也要在降级保护内：主密钥轮换后旧密文解不开（InvalidTag），
        # 不能让整个看板 500（生产 2026-06-11 轮换过一次密钥）
        client = BaiduAPIClient(
            username=acc.baidu_username,
            access_token=decrypt(acc.access_token_encrypted),
        )
        data = await AccountService(client).get_account_info(
            fields=["userId", "balance", "cost", "budget", "budgetType"]
        )
    except BaiduAPIError as e:
        logger.warning("tenant_id=%s 实时账户信息获取失败: %s", tenant_id, e.message)
        return {
            "status": "error",
            "message": f"百度账户信息暂时无法获取（{e.message}），效果数据不受影响",
        }
    except Exception as e:  # noqa: BLE001  网络/超时等基础设施异常同样降级
        logger.warning("tenant_id=%s 实时账户信息获取异常: %s", tenant_id, e)
        return {
            "status": "error",
            "message": "百度账户信息暂时无法获取（网络异常），效果数据不受影响",
        }

    info = data.get("data") or {}
    if isinstance(info, list):
        info = info[0] if info else {}
    return {
        "status": "ok",
        "baidu_username": acc.baidu_username,
        "balance": _f(info.get("balance")),
        "cost_total": _f(info.get("cost")),
        "daily_budget": _f(info.get("budget")),
        "token_expires_at": acc.expires_at.isoformat(),
    }


@router.get("/today")
async def dashboard_today(
    tenant_id: int = Query(..., description="本地租户 ID"),
    start_date: date | None = Query(None, description="统计起始日期，默认本月 1 日"),
    end_date: date | None = Query(None, description="统计截止日期，默认今天"),
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """看板核心数据：时段 KPI + 环比 + 完整时段趋势 + 设备维度 + 计划分布。

    苏尔寿 6 月起停投，演示时传 start_date=2026-05-01&end_date=2026-05-31 看 5 月数据。
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    ctx.ensure_tenant(tenant_id)

    end = end_date or datetime.now(_SHANGHAI_TZ).date()
    start = start_date or end.replace(day=1)
    if start > end:
        raise HTTPException(400, "统计起始日期不能晚于截止日期")

    # ===== 时段 KPI + 上一等长时段环比 =====
    kpi = await _period_kpi(session, tenant_id, start, end)
    period_days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    prev_kpi = await _period_kpi(session, tenant_id, prev_start, prev_end)

    kpi_compare = {
        k: {
            "current": kpi[k],
            "previous": prev_kpi[k],
            "change_pct": _change_pct(kpi[k], prev_kpi[k]),
        }
        for k in ("cost", "click", "impression", "cpc", "ctr")
    }

    # ===== 真线索 / 线索成本 CPL（leads 表，按 lead_time 落在时段内，含环比） =====
    async def _lead_count(s: date, e: date) -> int:
        return int(
            await session.scalar(
                select(func.count()).select_from(Lead).where(
                    Lead.tenant_id == tenant_id,
                    Lead.lead_time >= s,
                    Lead.lead_time <= e,
                    Lead.status != "invalid",
                )
            ) or 0
        )

    lead_cnt = await _lead_count(start, end)
    prev_lead_cnt = await _lead_count(prev_start, prev_end)
    cpl_cur = round(kpi["cost"] / lead_cnt, 2) if lead_cnt else None
    cpl_prev = round(prev_kpi["cost"] / prev_lead_cnt, 2) if prev_lead_cnt else None
    lead_compare = {
        "current": lead_cnt, "previous": prev_lead_cnt,
        "change_pct": _change_pct(lead_cnt, prev_lead_cnt),
    }
    cpl_compare = {
        "current": cpl_cur, "previous": cpl_prev,
        "change_pct": _change_pct(cpl_cur, cpl_prev),
    }

    # ===== 月预算耗用（按 end_date 所在月） =====
    month_start = end.replace(day=1)
    month_end = end.replace(day=calendar.monthrange(end.year, end.month)[1])
    month_kpi = await _period_kpi(session, tenant_id, month_start, month_end)
    monthly_budget = _f(tenant.monthly_budget) if tenant.monthly_budget else None
    budget = {
        "monthly_budget": monthly_budget,
        "month_cost": month_kpi["cost"],
        "usage_pct": (
            round(month_kpi["cost"] / monthly_budget * 100, 1)
            if monthly_budget
            else None
        ),
    }

    # ===== 时段趋势（完整选定区间，缺数据的日期补 0） =====
    trend_start = start
    trend_rows = (
        await session.execute(
            select(
                KwReportSnapshot.report_date,
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.report_date >= trend_start,
                KwReportSnapshot.report_date <= end,
            )
            .group_by(KwReportSnapshot.report_date)
        )
    ).all()
    by_date = {r[0]: r for r in trend_rows}
    trend = []
    for i in range(period_days):
        d = trend_start + timedelta(days=i)
        r = by_date.get(d)
        trend.append(
            {
                "date": d.isoformat(),
                "cost": _f(r[1]) if r else 0.0,
                "click": int(r[2]) if r else 0,
                "impression": int(r[3]) if r else 0,
            }
        )

    # ===== 设备维度 =====
    device_rows = (
        await session.execute(
            select(
                KwReportSnapshot.device,
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
            .group_by(KwReportSnapshot.device)
        )
    ).all()
    total_device_cost = sum(_f(r[1]) for r in device_rows) or None
    device_split = [
        {
            "device": DEVICE_LABELS.get(r[0], "其他"),
            **_derive(_f(r[1]), int(r[2]), int(r[3])),
            "cost_share_pct": (
                round(_f(r[1]) / total_device_cost * 100, 1)
                if total_device_cost
                else None
            ),
        }
        for r in device_rows
    ]

    # ===== 计划消费分布（前 6，按消费降序） =====
    campaign_rows = (
        await session.execute(
            select(
                KwReportSnapshot.campaign_id,
                func.max(KwReportSnapshot.campaign_name),
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
            .group_by(KwReportSnapshot.campaign_id)
            .order_by(func.sum(KwReportSnapshot.cost).desc())
            .limit(6)
        )
    ).all()
    top_campaigns = [
        {
            "campaign_id": r[0],
            "campaign_name": r[1],
            **_derive(_f(r[2]), int(r[3]), int(r[4])),
        }
        for r in campaign_rows
    ]

    # ===== 未处理告警计数（看板顶部异常卡） =====
    alert_rows = (
        await session.execute(
            select(Alert.priority, func.count())
            .where(Alert.tenant_id == tenant_id, Alert.status == "open")
            .group_by(Alert.priority)
        )
    ).all()
    alert_counts = {p: int(n) for p, n in alert_rows}

    # ===== 实时账户信息（失败降级） =====
    account = await _fetch_account_realtime(session, tenant_id)

    # ===== 报告数据新鲜度 =====
    latest_report_date_query = (
        select(func.max(KwReportSnapshot.report_date))
        .where(KwReportSnapshot.tenant_id == tenant_id)
        .scalar_subquery()
    )
    latest_report_date, last_synced_at = (
        await session.execute(
            select(
                latest_report_date_query,
                func.max(KwReportSnapshot.fetched_at),
            ).where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.report_date == latest_report_date_query,
            )
        )
    ).one()

    active_accounts = list((await session.scalars(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id,
            BaiduAccount.status == "active",
        )
    )).all())
    asset_counts = {}
    for key, model in (
        ("campaigns", Campaign), ("adgroups", Adgroup),
        ("keywords", Keyword), ("search_terms", SearchTermReport),
    ):
        asset_counts[key] = int(await session.scalar(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
        ) or 0)

    latest_account_sync = max(
        (row.last_synced_at for row in active_accounts if row.last_synced_at),
        default=None,
    )
    if not active_accounts:
        connection_state = "not_connected"
        connection_message = "当前客户尚未连接百度推广账户"
    elif any(row.sync_status == "failed" for row in active_accounts):
        connection_state = "sync_failed"
        connection_message = "账户已连接，最近一次资产同步失败"
    elif any(row.sync_status in {"pending", "syncing"} for row in active_accounts):
        connection_state = "syncing"
        connection_message = "账户已连接，资产正在同步"
    elif not latest_account_sync or not any(asset_counts.values()):
        connection_state = "not_synced"
        connection_message = "账户已连接，但计划、单元和关键词资产尚未同步"
    elif asset_counts["campaigns"] and (
        not asset_counts["adgroups"] or not asset_counts["keywords"]
    ):
        connection_state = "partial"
        connection_message = "账户已连接，资产同步不完整"
    else:
        connection_state = "ready"
        connection_message = "账户已连接，资产数据已同步"

    requested_data_complete = bool(latest_report_date and latest_report_date >= end)
    if not requested_data_complete:
        # 缺失的报表日不是 0 消费，禁止计算为下降 100%。
        for item in kpi_compare.values():
            item["change_pct"] = None
        lead_compare["change_pct"] = None
        cpl_compare["change_pct"] = None

    return {
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "strategy": tenant.strategy,
        },
        "period": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days": period_days,
        },
        "kpi": kpi_compare,
        # 真线索 / 线索成本：来自 leads 表（手动录入 + 百度基木鱼同步），按 lead_time 时段统计
        "lead": lead_compare,
        "cpl": cpl_compare,
        "budget": budget,
        "alert_counts": alert_counts,
        "trend": trend,
        # 兼容旧前端；下一版客户端应读取 trend（完整选定区间）。
        "trend_7d": trend,
        "device_split": device_split,
        "top_campaigns": top_campaigns,
        "account": account,
        "freshness": {
            "latest_report_date": (
                latest_report_date.isoformat() if latest_report_date else None
            ),
            "last_synced_at": (
                last_synced_at.replace(tzinfo=timezone.utc)
                .astimezone(_SHANGHAI_TZ)
                .isoformat()
                if last_synced_at
                else None
            ),
            "sync_interval_minutes": 15,
            "requested_data_complete": requested_data_complete,
        },
        "connection": {
            "state": connection_state,
            "message": connection_message,
            "active_accounts": len(active_accounts),
            "last_account_synced_at": (
                latest_account_sync.replace(tzinfo=timezone.utc)
                .astimezone(_SHANGHAI_TZ).isoformat()
                if latest_account_sync else None
            ),
            "asset_counts": asset_counts,
        },
    }
