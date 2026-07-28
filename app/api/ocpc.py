"""oCPC 投放管理（查看层，只读）。

展示 OcpcService/getTargetPackageList 同步下来的目标转化包：目标转化出价、学习状态、
绑定计划、转化口径（数据来源 + 目标转化类型），并结合本地已落库的电话转化量给出
「数据够不够喂 OCPC」的判断。本路由不写回百度。
"""
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard import _f
from app.database import get_session
from app.models import (
    DATA_FLOW_LABELS,
    OCPC_BID_TYPE_LABELS,
    PACKAGE_STATUS_LABELS,
    TRANS_TYPE_LABELS,
    Campaign,
    KwReportSnapshot,
    OcpcPackage,
)
from app.security.auth import require_scoped_auth

router = APIRouter(
    prefix="/api/v1/ocpc",
    tags=["oCPC 投放"],
    dependencies=[Depends(require_scoped_auth)],
)

# OCPC 学习的经验门槛（每周转化量）。百度未公开硬阈值，业内常用 ~15/周 作二阶段下限参考。
# 仅用于前端提示「数据够不够」，不是百度官方口径。
LEARN_WEEKLY_MIN = 15


def _conv_window(tenant_id: int, max_date, days: int):
    """近 N 天电话转化量/消费按计划聚合的查询语句。"""
    start = max_date - timedelta(days=days - 1)
    return (
        select(
            KwReportSnapshot.campaign_id,
            func.sum(KwReportSnapshot.conversions),
            func.sum(KwReportSnapshot.cost),
        )
        .where(
            KwReportSnapshot.tenant_id == tenant_id,
            KwReportSnapshot.report_date >= start,
            KwReportSnapshot.report_date <= max_date,
        )
        .group_by(KwReportSnapshot.campaign_id)
    )


@router.get("/packages")
async def list_ocpc_packages(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """oCPC 出价策略列表 + 转化口径 + 数据是否喂得饱（近 7/30 天电话转化量）。"""
    packages = (
        await session.scalars(
            select(OcpcPackage).where(OcpcPackage.tenant_id == tenant_id)
        )
    ).all()

    camp_names = {
        c.campaign_id: c.campaign_name
        for c in (
            await session.scalars(select(Campaign).where(Campaign.tenant_id == tenant_id))
        ).all()
    }

    # 近 7/30 天转化量按计划聚合（电话转化 = kw_report_snapshots.conversions / Detail2）
    max_date = await session.scalar(
        select(func.max(KwReportSnapshot.report_date)).where(
            KwReportSnapshot.tenant_id == tenant_id
        )
    )
    conv7: dict[int, dict] = {}
    conv30: dict[int, dict] = {}
    if max_date is not None:
        for row in (await session.execute(_conv_window(tenant_id, max_date, 7))).all():
            if row[0] is not None:
                conv7[int(row[0])] = {"conv": int(row[1] or 0), "cost": _f(row[2])}
        for row in (await session.execute(_conv_window(tenant_id, max_date, 30))).all():
            if row[0] is not None:
                conv30[int(row[0])] = {"conv": int(row[1] or 0), "cost": _f(row[2])}

    acct_conv7 = sum(v["conv"] for v in conv7.values())
    acct_conv30 = sum(v["conv"] for v in conv30.values())

    def dataflows_view(pkg: OcpcPackage) -> list[dict]:
        out = []
        for df in pkg.data_flow_data or []:
            tts = df.get("transType") or []
            out.append(
                {
                    "data_flow": df.get("dataFlow"),
                    "data_flow_label": DATA_FLOW_LABELS.get(df.get("dataFlow"), f"#{df.get('dataFlow')}"),
                    "trans_types": [
                        {"code": t, "label": TRANS_TYPE_LABELS.get(t, f"#{t}")} for t in tts
                    ],
                }
            )
        return out

    rows: list[dict[str, Any]] = []
    for p in packages:
        bound_ids = p.bound_campaign_ids()
        bound = [{"campaign_id": cid, "campaign_name": camp_names.get(cid)} for cid in bound_ids]
        # 包级转化口径：是否覆盖电话（2 电话按钮点击 / 30 电话拨通）
        all_trans = {t for df in (p.data_flow_data or []) for t in (df.get("transType") or [])}
        covers_phone = bool(all_trans & {2, 30})
        # 包级近 7/30 天转化量 = 绑定计划合计（未绑定计划的包按账户口径无法归集，给 None）
        pkg_conv7 = sum(conv7.get(cid, {}).get("conv", 0) for cid in bound_ids) if bound_ids else None
        pkg_conv30 = sum(conv30.get(cid, {}).get("conv", 0) for cid in bound_ids) if bound_ids else None
        rows.append(
            {
                "package_id": p.package_id,
                "package_name": p.package_name,
                "ocpc_bid_type": p.ocpc_bid_type,
                "ocpc_bid_type_label": OCPC_BID_TYPE_LABELS.get(p.ocpc_bid_type, "—"),
                "ocpc_bid": _f(p.ocpc_bid) if p.ocpc_bid is not None else None,
                "package_status": p.package_status,
                "package_status_label": PACKAGE_STATUS_LABELS.get(p.package_status, "—"),
                "ocpc_deep_cpa": _f(p.ocpc_deep_cpa) if p.ocpc_deep_cpa is not None else None,
                "bound_campaigns": bound,
                "dataflows": dataflows_view(p),
                "covers_phone": covers_phone,
                "conv_7d": pkg_conv7,
                "conv_30d": pkg_conv30,
                "assist_trans_types": [
                    TRANS_TYPE_LABELS.get(t, f"#{t}") for t in (p.assist_trans_types or [])
                ],
                "synced_at": p.synced_at.isoformat() if p.synced_at else None,
            }
        )

    # 数据充足度判断（账户口径，advisory）：近 7 天电话转化是否够喂学习
    adequacy = "sufficient" if acct_conv7 >= LEARN_WEEKLY_MIN else ("low" if acct_conv7 > 0 else "none")

    return {
        "total": len(rows),
        "packages": rows,
        "summary": {
            "account_conv_7d": acct_conv7,
            "account_conv_30d": acct_conv30,
            "learn_weekly_min": LEARN_WEEKLY_MIN,
            "adequacy": adequacy,  # sufficient / low / none
            "data_until": max_date.isoformat() if max_date else None,
            "status_counts": _status_counts(packages),
        },
    }


def _status_counts(packages) -> dict[str, int]:
    c: dict[str, int] = {}
    for p in packages:
        label = PACKAGE_STATUS_LABELS.get(p.package_status, "未知")
        c[label] = c.get(label, 0) + 1
    return c
