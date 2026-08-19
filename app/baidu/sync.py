"""百度数据 → 本地 DB 的同步逻辑。

每个函数接 SQLAlchemy session + 业务参数，负责调百度 API + bulk upsert。
APScheduler 和手动触发接口都走这里。
"""
import hashlib
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.client import BaiduAPIClient, BaiduAPIError
from app.baidu.services.account import AccountService
from app.baidu.services.adgroup import AdgroupService
from app.baidu.services.campaign import CampaignService
from app.baidu.services.ocpc import OcpcService
from app.baidu.services.keyword import KeywordService
from app.baidu.services.planner import KeywordPlannerService
from app.baidu.services.report import ReportService
from app.baidu.services.strategy import PriceStrategyService
from app.baidu.services.toolkit import WHITELISTED_CONTENTS, ToolkitService
from app.expansion import (
    is_cold_pv_candidate,
    is_cold_query_candidate,
    parse_query_status,
    score_planner_candidate,
    score_query_candidate,
    suggest_category,
)
from app.urlwords import UrlFetchError, extract_words, fetch_page_text
from app.models import (
    Adgroup,
    BaiduAccount,
    Campaign,
    Keyword,
    KeywordCandidate,
    KeywordHourlyReport,
    KeywordRegionReport,
    KwRegionSnapshot,
    KwReportSnapshot,
    Lead,
    OcpcPackage,
    OperationRecord,
    PriceStrategy,
    SearchTermReport,
    Tenant,
)
from app.security.crypto import decrypt

logger = logging.getLogger(__name__)


def _to_int(v: Any) -> int | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _to_float(v: Any) -> float | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# 百度报告 device 返回的是中文 value（文档 0299：查询用 key、数据返回 value）。
# 新版口径 计算机=0 / 移动设备=1，与旧版数字不一致。落库统一存 int。
_DEVICE_VALUE_TO_INT = {"计算机": 0, "移动设备": 1}


def _device_to_int(v: Any) -> int | None:
    """device 兼容中文 value（计算机/移动设备）与数字 key 两种返回形态。"""
    if v is None:
        return None
    if isinstance(v, str) and v in _DEVICE_VALUE_TO_INT:
        return _DEVICE_VALUE_TO_INT[v]
    return _to_int(v)


def _row_to_record(
    row: dict[str, Any], tenant_id: int, baidu_account_id: int, report_date: date
) -> dict[str, Any]:
    """把百度 row 转成 KwReportSnapshot 的 insert 字典。"""
    return {
        "tenant_id": tenant_id,
        "baidu_account_id": baidu_account_id,
        "report_date": report_date,
        "user_id": _to_int(row.get("userId")),
        "campaign_id": _to_int(row.get("campaignId")),
        "campaign_name": row.get("campaignName") or row.get("campaignNameStatus"),
        "adgroup_id": _to_int(row.get("adGroupId")),
        "adgroup_name": row.get("adGroupName") or row.get("adGroupNameStatus"),
        "keyword_id": _to_int(row.get("wInfoId")),
        "keyword": row.get("wInfoNameStatus"),
        "match_type": _to_int(row.get("mixWmatchEnum")),
        "device": _device_to_int(row.get("device")),
        "impression": _to_int(row.get("impression")) or 0,
        "click": _to_int(row.get("click")) or 0,
        "cost": _to_float(row.get("cost")) or 0,
        "cpc": _to_float(row.get("cpc")),
        "ctr": _to_float(row.get("ctr")),
        "avg_rank": _to_float(row.get("avgRank")),
        "conversions": _to_int(row.get("ocpcConversionsDetail2")) or 0,
        "quality_enum": _to_int(row.get("qualityEnum")),
        "estimated_click_rate": _to_int(row.get("estimatedClickRate")),
        "business_relationship": _to_int(row.get("businessRelationship")),
        "land_page_experience": _to_int(row.get("landPageExperience")),
        "top_pageviews": _to_int(row.get("topPageViews")),
        "top_pclicks": _to_int(row.get("topPClicks")),
        "top_pay": _to_float(row.get("topPay")),
        "top_pv_win_a": _to_float(row.get("topPvWinA")),
        "top_first_pv_win_a": _to_float(row.get("topFirstPvWinA")),
        "bid_new": _to_float(row.get("bidNew")),
        "raw_metrics": row,
        "fetched_at": datetime.utcnow(),
    }


def _parse_report_hour(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v.replace(minute=0, second=0, microsecond=0)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    text = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:00", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(minute=0, second=0, microsecond=0)
        except ValueError:
            continue
    return None


def _row_to_region_record(
    row: dict[str, Any], tenant_id: int, baidu_account_id: int, report_date: date
) -> dict[str, Any] | None:
    region_name = row.get("provinceCityName") or row.get("provinceName")
    keyword_id = _to_int(row.get("wInfoId"))
    if keyword_id is None or not region_name:
        return None
    return {
        "tenant_id": tenant_id,
        "baidu_account_id": baidu_account_id,
        "report_date": report_date,
        "user_id": _to_int(row.get("userId")),
        "campaign_id": _to_int(row.get("campaignId")),
        "campaign_name": row.get("campaignName") or row.get("campaignNameStatus"),
        "adgroup_id": _to_int(row.get("adGroupId")),
        "adgroup_name": row.get("adGroupName") or row.get("adGroupNameStatus"),
        "keyword_id": keyword_id,
        "keyword": row.get("wInfoNameStatus"),
        "device": _device_to_int(row.get("device")),
        "region_name": str(region_name),
        "region_level": "city" if row.get("provinceCityName") else "province",
        "impression": _to_int(row.get("impression")) or 0,
        "click": _to_int(row.get("click")) or 0,
        "cost": _to_float(row.get("cost")) or 0,
        "cpc": _to_float(row.get("cpc")),
        "ctr": _to_float(row.get("ctr")),
        "raw_metrics": row,
        "fetched_at": datetime.utcnow(),
    }


def _row_to_hourly_record(
    row: dict[str, Any], tenant_id: int, baidu_account_id: int
) -> dict[str, Any] | None:
    report_dt = _parse_report_hour(row.get("date"))
    keyword_id = _to_int(row.get("wInfoId"))
    if keyword_id is None or report_dt is None:
        return None
    return {
        "tenant_id": tenant_id,
        "baidu_account_id": baidu_account_id,
        "report_datetime": report_dt,
        "report_date": report_dt.date(),
        "hour": report_dt.hour,
        "user_id": _to_int(row.get("userId")),
        "campaign_id": _to_int(row.get("campaignId")),
        "campaign_name": row.get("campaignName") or row.get("campaignNameStatus"),
        "adgroup_id": _to_int(row.get("adGroupId")),
        "adgroup_name": row.get("adGroupName") or row.get("adGroupNameStatus"),
        "keyword_id": keyword_id,
        "keyword": row.get("wInfoNameStatus"),
        "device": _device_to_int(row.get("device")),
        "impression": _to_int(row.get("impression")) or 0,
        "click": _to_int(row.get("click")) or 0,
        "cost": _to_float(row.get("cost")) or 0,
        "cpc": _to_float(row.get("cpc")),
        "ctr": _to_float(row.get("ctr")),
        "raw_metrics": row,
        "fetched_at": datetime.utcnow(),
    }


def _row_region_date(row: dict[str, Any], fallback: date) -> date:
    parsed = _parse_report_hour(row.get("date"))
    return parsed.date() if parsed is not None else fallback


def _province_name(row: dict[str, Any]) -> str:
    province = row.get("provinceName")
    if province is None or str(province).strip() in ("", "-"):
        return "未知"
    return str(province).strip()


async def sync_keyword_report_for_account(
    session: AsyncSession,
    baidu_account: BaiduAccount,
    target_date: date,
) -> int:
    """拉某账户某天的关键词报告，upsert 到 kw_report_snapshots。返回写入条数。"""
    client = BaiduAPIClient(
        username=baidu_account.baidu_username,
        access_token=decrypt(baidu_account.access_token_encrypted),
    )
    svc = ReportService(client)

    iso_date = target_date.isoformat()
    rows = await svc.get_keyword_report(start_date=iso_date, end_date=iso_date)

    if not rows:
        logger.info(
            "账户 %s %s 关键词报告无数据", baidu_account.baidu_username, iso_date
        )
        return 0

    records = [
        _row_to_record(r, baidu_account.tenant_id, baidu_account.id, target_date)
        for r in rows
    ]

    # 跳过没有 keyword_id 的行（upsert 键含 keyword_id，None 会触发约束问题）
    records = [r for r in records if r["keyword_id"] is not None]
    if not records:
        return 0

    stmt = pg_insert(KwReportSnapshot).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "report_date", "keyword_id", "device"],
        set_={
            "impression": stmt.excluded.impression,
            "click": stmt.excluded.click,
            "cost": stmt.excluded.cost,
            "cpc": stmt.excluded.cpc,
            "ctr": stmt.excluded.ctr,
            "avg_rank": stmt.excluded.avg_rank,
            "conversions": stmt.excluded.conversions,
            "quality_enum": stmt.excluded.quality_enum,
            "estimated_click_rate": stmt.excluded.estimated_click_rate,
            "business_relationship": stmt.excluded.business_relationship,
            "land_page_experience": stmt.excluded.land_page_experience,
            "top_pageviews": stmt.excluded.top_pageviews,
            "top_pclicks": stmt.excluded.top_pclicks,
            "top_pay": stmt.excluded.top_pay,
            "top_pv_win_a": stmt.excluded.top_pv_win_a,
            "top_first_pv_win_a": stmt.excluded.top_first_pv_win_a,
            "bid_new": stmt.excluded.bid_new,
            "raw_metrics": stmt.excluded.raw_metrics,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )
    await session.execute(stmt)
    await session.commit()

    logger.info(
        "账户 %s %s 关键词报告 upsert %d 条",
        baidu_account.baidu_username,
        iso_date,
        len(records),
    )
    return len(records)


async def sync_keyword_dimension_reports_for_account(
    session: AsyncSession,
    baidu_account: BaiduAccount,
    target_date: date,
) -> dict[str, int]:
    """拉某账户某天关键词地域/小时效果报告。"""
    client = BaiduAPIClient(
        username=baidu_account.baidu_username,
        access_token=decrypt(baidu_account.access_token_encrypted),
    )
    svc = ReportService(client)
    iso_date = target_date.isoformat()

    region_rows = await svc.get_keyword_region_report(start_date=iso_date, end_date=iso_date)
    region_records = [
        rec for row in region_rows
        if (rec := _row_to_region_record(row, baidu_account.tenant_id, baidu_account.id, target_date))
    ]
    if region_records:
        await _chunked_upsert(
            session,
            KeywordRegionReport,
            region_records,
            "uq_kw_region_report_tenant_date_kw_region_device",
            {
                "tenant_id",
                "report_date",
                "keyword_id",
                "region_name",
                "region_level",
                "device",
            },
        )

    hourly_rows = await svc.get_keyword_hourly_report(start_date=iso_date, end_date=iso_date)
    hourly_records = [
        rec for row in hourly_rows
        if (rec := _row_to_hourly_record(row, baidu_account.tenant_id, baidu_account.id))
    ]
    if hourly_records:
        await _chunked_upsert(
            session,
            KeywordHourlyReport,
            hourly_records,
            "uq_kw_hourly_report_tenant_dt_kw_device",
            {"tenant_id", "report_datetime", "keyword_id", "device"},
        )

    logger.info(
        "账户 %s %s 关键词维度报告 upsert 地域 %d 条、小时 %d 条",
        baidu_account.baidu_username,
        iso_date,
        len(region_records),
        len(hourly_records),
    )
    return {"region": len(region_records), "hourly": len(hourly_records)}


async def sync_region_snapshot(
    session: AsyncSession,
    tenant: Tenant | None,
    baidu_account: BaiduAccount,
    start_date: date,
    end_date: date,
) -> int:
    """按省汇总关键词报表地域数据，upsert 进 kw_region_snapshots。"""
    client = BaiduAPIClient(
        username=baidu_account.baidu_username,
        access_token=decrypt(baidu_account.access_token_encrypted),
    )
    svc = ReportService(client)
    rows = await svc.get_keyword_province_report(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )

    agg: dict[tuple[int, date, str], dict[str, Any]] = {}
    fetched_at = datetime.utcnow()
    for row in rows:
        province = _province_name(row)
        report_date = _row_region_date(row, start_date)
        tenant_id = tenant.id if tenant is not None else baidu_account.tenant_id
        key = (baidu_account.tenant_id, report_date, province)
        item = agg.setdefault(
            key,
            {
                "tenant_id": tenant_id,
                "baidu_account_id": baidu_account.id,
                "report_date": report_date,
                "province": province,
                "cost": 0.0,
                "click": 0,
                "impression": 0,
                "fetched_at": fetched_at,
            },
        )
        item["cost"] += _to_float(row.get("cost")) or 0.0
        item["click"] += _to_int(row.get("click")) or 0
        item["impression"] += _to_int(row.get("impression")) or 0

    records = [
        {**item, "cost": round(float(item["cost"]), 2)}
        for item in agg.values()
    ]
    if records:
        await _chunked_upsert(
            session,
            KwRegionSnapshot,
            records,
            "uq_kw_region_snapshot",
            {"tenant_id", "report_date", "province"},
        )

    logger.info(
        "账户 %s %s~%s 省级地域汇总 upsert %d 条",
        baidu_account.baidu_username,
        start_date,
        end_date,
        len(records),
    )
    return len(records)


async def sync_keyword_region_snapshots_for_account(
    session: AsyncSession,
    baidu_account: BaiduAccount,
    target_date: date,
) -> int:
    """兼容旧调用：同步单日省级地域汇总。"""
    return await sync_region_snapshot(
        session, None, baidu_account, target_date, target_date
    )


def _parse_baidu_time(v: Any) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("T", " ").split(".")[0])
    except ValueError:
        return None


def _account_client(baidu_account: BaiduAccount) -> BaiduAPIClient:
    return BaiduAPIClient(
        username=baidu_account.baidu_username,
        access_token=decrypt(baidu_account.access_token_encrypted),
    )


# asyncpg 单条语句绑定参数上限 32767；按"行数 × 列数"留余量分批
UPSERT_CHUNK = 1000


async def _chunked_upsert(
    session: AsyncSession, model, records: list[dict], constraint: str, skip_keys: set[str]
) -> None:
    """大批量 upsert 分批执行，避免超 asyncpg 32767 参数上限（生产实测 2026-06-11）。"""
    for i in range(0, len(records), UPSERT_CHUNK):
        chunk = records[i : i + UPSERT_CHUNK]
        stmt = pg_insert(model).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint=constraint,
            set_={k: getattr(stmt.excluded, k) for k in chunk[0] if k not in skip_keys},
        )
        await session.execute(stmt)
    await session.commit()


async def sync_campaigns_for_account(
    session: AsyncSession, baidu_account: BaiduAccount
) -> int:
    """同步推广计划维度（getCampaign，全账户）。返回写入条数。"""
    campaigns = await CampaignService(_account_client(baidu_account)).get_all_campaigns()
    if not campaigns:
        return 0

    now = datetime.utcnow()
    records = []
    for c in campaigns:
        camp_id = _to_int(c.get("campaignId"))
        if camp_id is None:
            continue
        records.append(
            {
                "tenant_id": baidu_account.tenant_id,
                "baidu_account_id": baidu_account.id,
                "campaign_id": camp_id,
                "campaign_name": c.get("campaignName"),
                "budget": _to_float(c.get("budget")),
                "pause": c.get("pause") if isinstance(c.get("pause"), bool) else None,
                "status": _to_int(c.get("status")),
                "equipment_type": _to_int(c.get("equipmentType")),
                "region_target": c.get("regionTarget"),
                "geo_location_status": _to_int(c.get("geoLocationStatus")),
                "schedule": c.get("schedule"),
                "region_price_factor": c.get("regionPriceFactor"),
                "schedule_price_factors": c.get("schedulePriceFactors"),
                "price_ratio": _to_float(c.get("priceRatio")),
                "negative_words": c.get("negativeWords"),
                "exact_negative_words": c.get("exactNegativeWords"),
                "baidu_create_time": _parse_baidu_time(c.get("createTime")),
                "synced_at": now,
            }
        )
    if not records:
        return 0

    await _chunked_upsert(
        session, Campaign, records, "uq_campaigns_tenant_camp", {"tenant_id", "campaign_id"}
    )
    logger.info("账户 %s 计划维度 upsert %d 条", baidu_account.baidu_username, len(records))
    return len(records)


async def sync_adgroups_for_account(
    session: AsyncSession, baidu_account: BaiduAccount
) -> int:
    """同步推广单元维度（getAdgroup，按本地 campaigns 表的计划枚举）。返回写入条数。"""
    campaign_ids = (
        await session.scalars(
            select(Campaign.campaign_id).where(
                Campaign.tenant_id == baidu_account.tenant_id
            )
        )
    ).all()
    if not campaign_ids:
        return 0

    adgroups = await AdgroupService(_account_client(baidu_account)).get_adgroups_by_campaign_ids(
        list(campaign_ids)
    )
    if not adgroups:
        return 0

    now = datetime.utcnow()
    records = []
    for a in adgroups:
        adg_id = _to_int(a.get("adgroupId"))
        if adg_id is None:
            continue
        records.append(
            {
                "tenant_id": baidu_account.tenant_id,
                "baidu_account_id": baidu_account.id,
                "adgroup_id": adg_id,
                "campaign_id": _to_int(a.get("campaignId")),
                "adgroup_name": a.get("adgroupName"),
                "max_price": _to_float(a.get("maxPrice")),
                "pause": a.get("pause") if isinstance(a.get("pause"), bool) else None,
                "status": _to_int(a.get("status")),
                "price_ratio": _to_float(a.get("priceRatio")),
                "negative_words": a.get("negativeWords"),
                "exact_negative_words": a.get("exactNegativeWords"),
                "pc_final_url": a.get("pcFinalUrl"),
                "mobile_final_url": a.get("mobileFinalUrl"),
                "pc_track_param": a.get("pcTrackParam"),
                "mobile_track_param": a.get("mobileTrackParam"),
                "pc_track_template": a.get("pcTrackTemplate"),
                "mobile_track_template": a.get("mobileTrackTemplate"),
                "synced_at": now,
            }
        )
    if not records:
        return 0

    await _chunked_upsert(
        session, Adgroup, records, "uq_adgroups_tenant_adg", {"tenant_id", "adgroup_id"}
    )
    logger.info("账户 %s 单元维度 upsert %d 条", baidu_account.baidu_username, len(records))
    return len(records)


async def sync_price_strategies_for_account(
    session: AsyncSession, baidu_account: BaiduAccount
) -> int:
    """同步优化排名出价策略（getPriceStrategy，全账户）。返回写入条数。"""
    strategies = await PriceStrategyService(
        _account_client(baidu_account)
    ).get_ranking_strategies()
    if not strategies:
        return 0

    now = datetime.utcnow()
    records = []
    for s in strategies:
        strat_id = _to_int(s.get("strategyId"))
        if strat_id is None:
            continue
        records.append(
            {
                "tenant_id": baidu_account.tenant_id,
                "baidu_account_id": baidu_account.id,
                "strategy_id": strat_id,
                "strategy_name": s.get("strategyName"),
                "strategy_type": _to_int(s.get("strategyType")),
                "target_rank": _to_int(s.get("targetRank")),
                "price_factor": _to_float(s.get("priceFactor")),
                "is_pause": s.get("isPause") if isinstance(s.get("isPause"), bool) else None,
                "campaign_bindings": s.get("priceStrategyCampaignTypes"),
                "synced_at": now,
            }
        )
    if not records:
        return 0

    await _chunked_upsert(
        session,
        PriceStrategy,
        records,
        "uq_price_strategies_tenant_strat",
        {"tenant_id", "strategy_id"},
    )
    logger.info(
        "账户 %s 出价策略 upsert %d 条", baidu_account.baidu_username, len(records)
    )
    return len(records)


async def sync_ocpc_packages_for_account(
    session: AsyncSession, baidu_account: BaiduAccount
) -> int:
    """同步 oCPC 出价策略（getTargetPackageList，level=1 全账户）。返回写入条数。

    level=1 需传 userId（推广账户 ID，与 ucid 不一定相同），先 getAccountInfo 取。
    🚫 只读同步，不写回。账户没开 OCPC 时返回空，本地存量不动（不清表）。
    """
    client = _account_client(baidu_account)
    resp = await AccountService(client).get_account_info(["userId"])
    info = resp.get("data") or {}
    if isinstance(info, list):  # getAccountInfo 的 data 可能是 list（见 dashboard 实测）
        info = info[0] if info else {}
    user_id = _to_int(info.get("userId"))
    if user_id is None:
        logger.warning("账户 %s getAccountInfo 未返回 userId，跳过 OCPC 同步", baidu_account.baidu_username)
        return 0

    packages = await OcpcService(client).get_target_packages(user_id)
    if not packages:
        logger.info("账户 %s 无 oCPC 出价策略", baidu_account.baidu_username)
        return 0

    now = datetime.utcnow()
    records = []
    for p in packages:
        pkg_id = _to_int(p.get("targetPackageId"))
        if pkg_id is None:
            continue
        records.append(
            {
                "tenant_id": baidu_account.tenant_id,
                "baidu_account_id": baidu_account.id,
                "package_id": pkg_id,
                "package_name": p.get("targetPackageName"),
                "ocpc_bid_type": _to_int(p.get("ocpcBidType")),
                "ocpc_bid": _to_float(p.get("ocpcBid")),
                "package_status": _to_int(p.get("packageStatus")),
                "ocpc_deep_cpa": _to_float(p.get("ocpcDeepCpa")),
                "deep_trans_type_mode": _to_int(p.get("deepTransTypeMode")),
                "scope": p.get("scope") if isinstance(p.get("scope"), list) else None,
                "data_flow_data": p.get("dataFlowData") if isinstance(p.get("dataFlowData"), list) else None,
                "assist_trans_types": p.get("assistTransTypes") if isinstance(p.get("assistTransTypes"), list) else None,
                "raw": p,
                "synced_at": now,
            }
        )
    if not records:
        return 0

    await _chunked_upsert(
        session, OcpcPackage, records, "uq_ocpc_packages_tenant_pkg", {"tenant_id", "package_id"}
    )
    logger.info("账户 %s oCPC 策略 upsert %d 条", baidu_account.baidu_username, len(records))
    return len(records)


async def sync_keywords_for_account(
    session: AsyncSession, baidu_account: BaiduAccount
) -> int:
    """同步关键词维度（getWord）到 keywords 表。返回写入条数。

    优先按本地 adgroups 表全量枚举（idType=5，零展现词也覆盖）；
    单元维度还没同步过时回退"按 snapshots 出现过的 keyword_id 反查"。
    """
    span_rows = (
        await session.execute(
            select(
                KwReportSnapshot.keyword_id,
                func.min(KwReportSnapshot.report_date),
            )
            .where(
                KwReportSnapshot.tenant_id == baidu_account.tenant_id,
                KwReportSnapshot.keyword_id.isnot(None),
            )
            .group_by(KwReportSnapshot.keyword_id)
        )
    ).all()
    first_seen = {kw_id: d for kw_id, d in span_rows}

    svc = KeywordService(_account_client(baidu_account))
    adgroup_ids = (
        await session.scalars(
            select(Adgroup.adgroup_id).where(
                Adgroup.tenant_id == baidu_account.tenant_id
            )
        )
    ).all()
    if adgroup_ids:
        words = await svc.get_words_by_adgroup_ids(list(adgroup_ids))
    elif first_seen:
        words = await svc.get_words_by_ids(list(first_seen))
    else:
        return 0
    if not words:
        logger.info("账户 %s getWord 无返回", baidu_account.baidu_username)
        return 0

    now = datetime.utcnow()
    records = []
    for w in words:
        kw_id = _to_int(w.get("keywordId"))
        if kw_id is None:
            continue
        records.append(
            {
                "tenant_id": baidu_account.tenant_id,
                "baidu_account_id": baidu_account.id,
                "keyword_id": kw_id,
                "keyword": w.get("keyword"),
                "campaign_id": _to_int(w.get("campaignId")),
                "adgroup_id": _to_int(w.get("adgroupId")),
                "match_type": _to_int(w.get("matchType")),
                "phrase_type": _to_int(w.get("phraseType")),
                "price": _to_float(w.get("price")),
                "pause": w.get("pause") if isinstance(w.get("pause"), bool) else None,
                "status": _to_int(w.get("status")),
                "tabs": w.get("tabs") if isinstance(w.get("tabs"), list) else None,
                "quality": _to_int(w.get("quality")),
                "left_price_guide": _to_float(w.get("leftPriceGuide")),  # "-" → None
                "m_price_guide": _to_float(w.get("mPriceGuide")),
                "baidu_create_time": _parse_baidu_time(w.get("createTime")),
                "first_seen_date": first_seen.get(kw_id),
                "synced_at": now,
            }
        )
    if not records:
        return 0

    # set_ 不含 category / category_source：人工分级与自动重算分离
    await _chunked_upsert(
        session, Keyword, records, "uq_keywords_tenant_kw", {"tenant_id", "keyword_id"}
    )

    logger.info(
        "账户 %s 关键词维度 upsert %d 条", baidu_account.baidu_username, len(records)
    )
    return len(records)


# getOperationRecord 的 optTime 是英文本地化格式（实测样例 "Sep 2, 2021 11:54:00 PM"）
_OPT_TIME_FORMATS = ("%b %d, %Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S")


def _parse_opt_time(v: Any) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    for fmt in _OPT_TIME_FORMATS:
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return _parse_baidu_time(v)


async def sync_operation_records_for_account(
    session: AsyncSession,
    baidu_account: BaiduAccount,
    start_date: date,
    end_date: date,
) -> int:
    """同步百度操作记录（调价台账数据源，只读）。返回本次拉到的条数。

    百度不给记录 ID，幂等靠 dedup_key（全字段 md5）+ on_conflict_do_nothing，
    重叠窗口重复拉取不会产生重复行。
    """
    svc = ToolkitService(_account_client(baidu_account))
    raw = await svc.get_operation_records(start_date.isoformat(), end_date.isoformat())
    if not raw:
        logger.info(
            "账户 %s %s~%s 无操作记录", baidu_account.baidu_username, start_date, end_date
        )
        return 0

    now = datetime.utcnow()
    records = []
    seen: set[str] = set()
    for r in raw:
        # 白名单过滤：百度对 optContents 过滤不严格，挡掉 shelveIdea/空内容等台账无关噪音
        if r.get("optContent") not in WHITELISTED_CONTENTS:
            continue
        opt_time = _parse_opt_time(r.get("optTime"))
        if opt_time is None:
            logger.warning("操作记录 optTime 解析失败，跳过: %r", r.get("optTime"))
            continue
        opt_level = _to_int(r.get("optLevel")) or r.get("_optLevel")
        fields = (
            opt_time.isoformat(),
            str(opt_level),
            str(r.get("optType")),
            r.get("optContent") or "",
            r.get("optObj") or "",
            str(r.get("oldValue")),
            str(r.get("newValue")),
            str(r.get("planId")),
            str(r.get("unitId")),
        )
        dedup = hashlib.md5("|".join(fields).encode("utf-8")).hexdigest()
        if dedup in seen:  # 同批内完全相同的行（同秒同操作），无法区分，保留一条
            continue
        seen.add(dedup)
        records.append(
            {
                "tenant_id": baidu_account.tenant_id,
                "baidu_account_id": baidu_account.id,
                "opt_time": opt_time,
                "opt_type": _to_int(r.get("optType")),
                "opt_level": _to_int(opt_level),
                "opt_content": r.get("optContent"),
                "opt_obj": r.get("optObj"),
                "old_value": str(r.get("oldValue")) if r.get("oldValue") is not None else None,
                "new_value": str(r.get("newValue")) if r.get("newValue") is not None else None,
                "plan_id": _to_int(r.get("planId")),
                "unit_id": _to_int(r.get("unitId")),
                "dedup_key": dedup,
                "synced_at": now,
            }
        )
    if not records:
        return 0

    for i in range(0, len(records), UPSERT_CHUNK):
        chunk = records[i : i + UPSERT_CHUNK]
        stmt = pg_insert(OperationRecord).values(chunk)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_operation_records_tenant_dedup"
        )
        await session.execute(stmt)
    await session.commit()

    logger.info(
        "账户 %s 操作记录 %s~%s 拉到 %d 条（幂等去重后入库）",
        baidu_account.baidu_username, start_date, end_date, len(records),
    )
    return len(records)


# ============================================================
# 拓词候选（🚫 红线：只聚合展示，不写回百度）
# ============================================================


async def _tenant_brand_terms(session: AsyncSession, tenant_id: int) -> list[str]:
    tenant = await session.get(Tenant, tenant_id)
    terms = [t.strip() for t in (tenant.brand_terms or []) if t and t.strip()] if tenant else []
    if not terms and tenant and tenant.name:
        terms = [tenant.name.strip()]
    return terms


async def _existing_keyword_texts(session: AsyncSession, tenant_id: int) -> set[str]:
    """租户已购词字面集合（小写），候选去重用——已在投的词不算拓词候选。"""
    texts = (
        await session.scalars(
            select(Keyword.keyword).where(
                Keyword.tenant_id == tenant_id, Keyword.keyword.isnot(None)
            )
        )
    ).all()
    return {t.strip().lower() for t in texts if t and t.strip()}


async def _upsert_candidates(session: AsyncSession, records: list[dict]) -> None:
    """候选词幂等 upsert：刷新指标列，status/status_updated_at 人工字段不碰。"""
    for i in range(0, len(records), UPSERT_CHUNK):
        chunk = records[i : i + UPSERT_CHUNK]
        stmt = pg_insert(KeywordCandidate).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_kw_candidates_tenant_word_src",
            set_={
                k: getattr(stmt.excluded, k)
                for k in chunk[0]
                if k not in {"tenant_id", "word", "source"}
            },
        )
        await session.execute(stmt)
    await session.commit()


def _planner_row_to_record(
    row: dict[str, Any],
    baidu_account: BaiduAccount,
    seed: str | None,
    brand_terms: list[str],
    now: datetime,
) -> dict[str, Any] | None:
    word = (row.get("word") or "").strip()
    if not word:
        return None
    pv = _to_int(row.get("PV"))
    competition = _to_int(row.get("competition"))
    reasons = row.get("showReasons") if isinstance(row.get("showReasons"), list) else None
    score = score_planner_candidate(pv, competition, reasons)
    # 命中冷门口径①的候选直接归 cold 源（拓词 4 源里的"冷门词识别"）
    source = "cold" if is_cold_pv_candidate(word, pv, reasons) else "planner"
    return {
        "tenant_id": baidu_account.tenant_id,
        "baidu_account_id": baidu_account.id,
        "word": word,
        "source": source,
        "seed_word": seed,
        "monthly_pv": pv,
        "pc_pv": _to_int(row.get("pcPV")),
        "mobile_pv": _to_int(row.get("mobilePV")),
        "competition": competition,
        "recommend_price_pc": _to_float(row.get("recommendPricePc")),
        "recommend_price_mobile": _to_float(row.get("recommendPriceMobile")),
        "show_reasons": reasons,
        "potential_score": score,
        "suggested_category": suggest_category(word, "planner", score, brand_terms),
        "raw": row,
        "synced_at": now,
    }


async def sync_planner_candidates_for_account(
    session: AsyncSession,
    baidu_account: BaiduAccount,
    seeds: list[str],
    max_num: int = 300,
) -> int:
    """百度规划师拓词：逐个种子词调 getKRByQuery + 一次账户主动推荐 getKRCustom。

    removeDuplicate 已让百度剔除账户内已购词，本地再按 keywords 表字面兜底去重。
    返回写入候选条数。
    """
    svc = KeywordPlannerService(_account_client(baidu_account))
    brand_terms = await _tenant_brand_terms(session, baidu_account.tenant_id)
    existing = await _existing_keyword_texts(session, baidu_account.tenant_id)

    now = datetime.utcnow()
    by_word: dict[str, dict] = {}  # 多种子词推同一词时保留最后一条（PV 类指标各种子一致）

    def collect(rows: list[dict], seed: str | None) -> None:
        for row in rows:
            rec = _planner_row_to_record(row, baidu_account, seed, brand_terms, now)
            if rec is None or rec["word"].lower() in existing:
                continue
            by_word[rec["word"]] = rec

    # 账户主动推荐失败不阻断种子词拓展（两接口权限独立演进，防御处理）
    try:
        collect(await svc.get_account_recommend_words(max_num), None)
    except BaiduAPIError as e:
        logger.warning("账户 %s 主动推荐词失败（跳过）: %s", baidu_account.baidu_username, e)
    for s in seeds:
        collect(await svc.get_words_by_seed(s, max_num), s)

    records = list(by_word.values())
    if records:
        await _upsert_candidates(session, records)
    logger.info(
        "账户 %s 规划师拓词：%d 种子词 → %d 候选",
        baidu_account.baidu_username, len(seeds), len(records),
    )
    return len(records)


async def sync_query_candidates_for_account(
    session: AsyncSession,
    baidu_account: BaiduAccount,
    start_date: date,
    end_date: date,
) -> int:
    """搜索词转拓词：搜索词报告里"已触发但未添加"的搜索词（窗口最大 91 天）。

    SUMMARY 汇总后同一搜索词仍可能多行（不同触发词），按词聚合，
    触发词取展现最高的一条。返回写入候选条数。
    """
    svc = ReportService(_account_client(baidu_account))
    rows = await svc.get_search_term_report(
        start_date.isoformat(), end_date.isoformat()
    )
    if not rows:
        logger.info("账户 %s 搜索词报告无数据", baidu_account.baidu_username)
        return 0

    brand_terms = await _tenant_brand_terms(session, baidu_account.tenant_id)
    existing = await _existing_keyword_texts(session, baidu_account.tenant_id)

    agg: dict[str, dict[str, Any]] = {}
    for row in rows:
        word = (row.get("queryWord") or "").strip()
        if not word or word.lower() in existing:
            continue
        # 只要"未添加"（1）。已添加不是拓词，不可添加加了也没用
        if parse_query_status(row.get("queryStatusName")) != 1:
            continue
        imp = _to_int(row.get("impression")) or 0
        item = agg.setdefault(
            word,
            {"impression": 0, "click": 0, "cost": 0.0, "matched_keyword": None, "_max_imp": -1,
             "raw": row},
        )
        item["impression"] += imp
        item["click"] += _to_int(row.get("click")) or 0
        item["cost"] += _to_float(row.get("cost")) or 0.0
        if imp > item["_max_imp"]:
            item["_max_imp"] = imp
            item["matched_keyword"] = row.get("wInfoNameStatus")

    now = datetime.utcnow()
    records = []
    for word, m in agg.items():
        score = score_query_candidate(m["impression"], m["click"])
        records.append(
            {
                "tenant_id": baidu_account.tenant_id,
                "baidu_account_id": baidu_account.id,
                "word": word,
                # 冷门口径②：低展现但有点击 → 归 cold 源
                "source": "cold" if is_cold_query_candidate(m["impression"], m["click"]) else "query",
                "seed_word": None,
                "impression": m["impression"],
                "click": m["click"],
                "cost": round(m["cost"], 2),
                "matched_keyword": m["matched_keyword"],
                "potential_score": score,
                "suggested_category": suggest_category(word, "query", score, brand_terms),
                "raw": m["raw"],
                "synced_at": now,
            }
        )
    if records:
        await _upsert_candidates(session, records)
    logger.info(
        "账户 %s 搜索词转拓词 %s~%s：%d 候选",
        baidu_account.baidu_username, start_date, end_date, len(records),
    )
    return len(records)


_SEARCH_TERM_REPORT_MAX_WINDOW_DAYS = 31


def _search_term_windows(start_date: date, end_date: date) -> list[tuple[date, date]]:
    """将百度搜索词报告日期范围切成不超过 31 天的闭区间。"""
    if start_date > end_date:
        raise ValueError("搜索词报告开始日期不能晚于结束日期")

    windows: list[tuple[date, date]] = []
    window_start = start_date
    while window_start <= end_date:
        window_end = min(
            window_start + timedelta(days=_SEARCH_TERM_REPORT_MAX_WINDOW_DAYS - 1),
            end_date,
        )
        windows.append((window_start, window_end))
        window_start = window_end + timedelta(days=1)
    return windows


async def _fetch_search_term_rows(
    baidu_account: BaiduAccount,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """拉取一个百度允许的搜索词报告窗口，不写本地库。"""
    svc = ReportService(_account_client(baidu_account))
    return await svc.get_search_term_report(start_date.isoformat(), end_date.isoformat())


def _merge_search_term_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并分段 SUMMARY 报表，使同一搜索词维度在完整窗口中只保留一行。

    每段都是互不重叠的时间区间，不能简单选择消费最高的一段，否则 91 天指标会
    被低估。展现、点击、消费和转化按段累加；比率指标据合计值重算，名称和状态等
    非指标字段以较后拉取到的行覆盖。
    """
    merged: dict[tuple[str, int | None, int | None], dict[str, Any]] = {}
    totals: dict[tuple[str, int | None, int | None], dict[str, float]] = {}

    for row in rows:
        word = (row.get("queryWord") or "").strip()
        if not word:
            continue
        key = (word, _to_int(row.get("campaignId")), _to_int(row.get("adGroupId")))
        current = merged.get(key)
        if current is None:
            current = dict(row)
            current["queryWord"] = word
            merged[key] = current
            totals[key] = {"impression": 0.0, "click": 0.0, "cost": 0.0, "conversions": 0.0}
        else:
            # 后面的窗口更新名称、触发词、状态和匹配方式等非累加字段。
            current.update(row)
            current["queryWord"] = word

        total = totals[key]
        total["impression"] += _to_int(row.get("impression")) or 0
        total["click"] += _to_int(row.get("click")) or 0
        total["cost"] += _to_float(row.get("cost")) or 0.0
        total["conversions"] += _to_int(row.get("ocpcConversionsDetail2")) or 0

    for key, row in merged.items():
        total = totals[key]
        impression = int(total["impression"])
        click = int(total["click"])
        cost = total["cost"]
        conversions = int(total["conversions"])
        row["impression"] = impression
        row["click"] = click
        row["cost"] = cost
        row["ocpcConversionsDetail2"] = conversions
        row["cpc"] = cost / click if click else None
        row["ctr"] = click * 100 / impression if impression else None
        row["ocpcConversionsDetail2CVR"] = conversions * 100 / click if click else None

    return list(merged.values())


async def sync_search_terms_for_account(
    session: AsyncSession,
    baidu_account: BaiduAccount,
    start_date: date,
    end_date: date,
) -> int:
    """搜索词报告全量落库（含已添加词），支持自动分段和空结果保护。

    与 sync_query_candidates（只留未添加词转拓词）不同，本表存全量，供搜索词报告页 +
    关键词详情触发搜索词下钻 + 后续加否词/转拓词。每次成功同步覆盖该租户旧快照；
    百度全部窗口均无数据时保留旧快照。返回写入条数。
    """
    fetched_rows: list[dict[str, Any]] = []
    windows = _search_term_windows(start_date, end_date)
    for window_start, window_end in windows:
        rows = await _fetch_search_term_rows(baidu_account, window_start, window_end)
        fetched_rows.extend(rows)

    rows = _merge_search_term_rows(fetched_rows)

    if not rows:
        logger.warning(
            "账户 %s 搜索词报告 %s~%s 分 %d 段拉取后仍无数据，保留本地旧快照",
            baidu_account.baidu_username,
            start_date,
            end_date,
            len(windows),
        )
        return 0

    # 仅在全部窗口拉取并合并后存在数据时，才替换全量快照。
    await session.execute(
        delete(SearchTermReport).where(SearchTermReport.tenant_id == baidu_account.tenant_id)
    )
    now = datetime.utcnow()
    records = []
    for row in rows:
        word = (row.get("queryWord") or "").strip()
        if not word:
            continue
        status = parse_query_status(row.get("queryStatusName"))
        records.append(
            SearchTermReport(
                tenant_id=baidu_account.tenant_id,
                baidu_account_id=baidu_account.id,
                query_word=word,
                trigger_keyword=row.get("wInfoNameStatus"),
                query_status=status,
                campaign_id=_to_int(row.get("campaignId")),
                campaign_name=row.get("campaignName"),
                adgroup_id=_to_int(row.get("adGroupId")),
                adgroup_name=row.get("adGroupName"),
                match_id=_to_int(row.get("wMatchId")),
                impression=_to_int(row.get("impression")),
                click=_to_int(row.get("click")),
                cost=_to_float(row.get("cost")),
                ctr=_to_float(row.get("ctr")),
                cpc=_to_float(row.get("cpc")),
                conversions=_to_int(row.get("ocpcConversionsDetail2")),
                cvr=_to_float(row.get("ocpcConversionsDetail2CVR")),
                window_start=start_date,
                window_end=end_date,
                is_added=(status == 0),
                synced_at=now,
            )
        )
    session.add_all(records)
    await session.commit()
    logger.info(
        "账户 %s 搜索词报告 %s~%s（%d 段）：原始 %d 条，合并落库 %d 条",
        baidu_account.baidu_username,
        start_date,
        end_date,
        len(windows),
        len(fetched_rows),
        len(records),
    )
    return len(records)


async def sync_url_candidates_for_account(
    session: AsyncSession,
    baidu_account: BaiduAccount,
    urls: list[str],
) -> tuple[int, list[dict[str, Any]]]:
    """URL 爬取拓词：抓页面 → jieba 提词 → getPvSearch 流量回查 → 入库（source=url）。

    返回 (写入条数, 每个 URL 的结果明细)。单 URL 抓取失败不阻断其余 URL。
    ⚠️ getPvSearch 的 kwc 是 1高3低，入库前翻转成 competition 口径（1低3高）。
    """
    brand_terms = await _tenant_brand_terms(session, baidu_account.tenant_id)
    existing = await _existing_keyword_texts(session, baidu_account.tenant_id)

    word_to_url: dict[str, str] = {}
    details: list[dict[str, Any]] = []
    for url in urls:
        try:
            title, text = await fetch_page_text(url)
            words = extract_words(title, text)
        except UrlFetchError as e:
            details.append({"url": url, "extracted": 0, "error": str(e)})
            continue
        fresh = [
            w for w in words
            if w.lower() not in existing and w not in word_to_url
        ]
        for w in fresh:
            word_to_url[w] = url
        details.append({"url": url, "extracted": len(words), "new": len(fresh), "error": None})

    if not word_to_url:
        return 0, details

    # 流量回查：黄反/超限的词百度不返回，pv_map 里查不到的按无数据入库
    svc = KeywordPlannerService(_account_client(baidu_account))
    pv_rows = await svc.get_pv_search(list(word_to_url))
    pv_map = {r.get("keywordName"): r for r in pv_rows if r.get("keywordName")}

    now = datetime.utcnow()
    records = []
    for word, url in word_to_url.items():
        pv_row = pv_map.get(word) or {}
        pv = _to_int(pv_row.get("averageMonthPv"))
        kwc = _to_int(pv_row.get("kwc"))
        competition = (4 - kwc) if kwc in (1, 2, 3) else None  # kwc 1高3低 → 1低3高
        reasons = (
            pv_row.get("showReasons") if isinstance(pv_row.get("showReasons"), list) else None
        )
        score = score_planner_candidate(pv, competition, reasons)
        records.append(
            {
                "tenant_id": baidu_account.tenant_id,
                "baidu_account_id": baidu_account.id,
                "word": word,
                "source": "cold" if is_cold_pv_candidate(word, pv, reasons) else "url",
                "seed_word": url,  # url 源的 seed_word 存来源页面
                "monthly_pv": pv,
                "pc_pv": _to_int(pv_row.get("averageMonthPvPc")),
                "mobile_pv": _to_int(pv_row.get("averageMonthPvMobile")),
                "competition": competition,
                "recommend_price_pc": _to_float(pv_row.get("pcPrice")),
                "recommend_price_mobile": _to_float(pv_row.get("mobilePrice")),
                "show_reasons": reasons,
                "potential_score": score,
                "suggested_category": suggest_category(word, "url", score, brand_terms),
                "raw": pv_row or None,
                "synced_at": now,
            }
        )
    await _upsert_candidates(session, records)
    logger.info(
        "账户 %s URL 拓词：%d 个 URL → %d 候选",
        baidu_account.baidu_username, len(urls), len(records),
    )
    return len(records), details


async def sync_keyword_report_for_all_active_accounts(
    session: AsyncSession, target_date: date
) -> dict[str, int]:
    """拉所有 active baidu_accounts 的目标日报告。返回 {username: 写入条数}。"""
    accounts = (
        await session.scalars(
            select(BaiduAccount).where(BaiduAccount.status == "active")
        )
    ).all()

    result: dict[str, int] = {}
    for acc in accounts:
        try:
            n = await sync_keyword_report_for_account(session, acc, target_date)
            await sync_keyword_dimension_reports_for_account(session, acc, target_date)
            result[acc.baidu_username] = n
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "账户 %s 拉 %s 报告失败: %s", acc.baidu_username, target_date, e
            )
            result[acc.baidu_username] = -1
    return result


# 基木鱼线索组件类型（文档 0819）。苏尔寿实测只有 phone 有数据，全扫一遍兼容其余客户
LEAD_SOLUTION_TYPES = ["phone", "consult", "form", "wechat", "callback", "follow"]


async def sync_leads_for_account(
    session: AsyncSession,
    baidu_account: BaiduAccount,
    start_date: date,
    end_date: date,
) -> int:
    """从百度拉基木鱼营销通线索（LeadsNoticeService/getNoticeList）落 leads 表。

    幂等：按 clueId（external_id）去重，已存在的跳过——保住人工改过的状态/备注，只增不覆盖。
    词级归因（keyword/campaign）、接通状态（connect）一并落库。窗口 ≤30 天。返回新增条数。
    """
    client = _account_client(baidu_account)
    tenant_id = baidu_account.tenant_id

    # 已落库的 clueId，用于跨类型/跨次同步去重
    existing: set[str] = set(
        (
            await session.scalars(
                select(Lead.external_id).where(
                    Lead.tenant_id == tenant_id, Lead.external_id.isnot(None)
                )
            )
        ).all()
    )

    start_s = start_date.strftime("%Y-%m-%d 00:00:00")
    end_s = end_date.strftime("%Y-%m-%d 23:59:59")
    new_records: list[Lead] = []
    seen: set[str] = set()  # 本次批内去重

    for sol in LEAD_SOLUTION_TYPES:
        page_no = 1
        while True:
            body = {
                "solutionType": sol,
                "startDate": start_s,
                "endDate": end_s,
                "pageNo": page_no,
                "pageSize": 5000,
            }
            try:
                resp = await client.call("LeadsNoticeService", "getNoticeList", body)
            except BaiduAPIError as e:
                logger.warning(
                    "账户 %s 线索拉取失败 type=%s code=%s msg=%s",
                    baidu_account.baidu_username, sol, e.code, e.message,
                )
                break
            block = (resp.get("data") or [{}])[0]
            rows = block.get("noticeDetailList") or []
            for r in rows:
                clue_id = str(r.get("clueId") or "").strip()
                if not clue_id or clue_id in existing or clue_id in seen:
                    continue
                seen.add(clue_id)
                commit_dt = _parse_baidu_time(r.get("commitTime"))
                new_records.append(
                    Lead(
                        tenant_id=tenant_id,
                        contact_name=(r.get("userName") or None),
                        phone=(r.get("cluePhoneNumber") or None),
                        source_channel="baidu",
                        external_id=clue_id,
                        campaign_id=_to_int(r.get("campaignId")),
                        campaign_name=r.get("campaignName"),
                        keyword=r.get("keyword") or r.get("searchWord"),
                        connect=_to_int(r.get("connect")),
                        status="new",
                        lead_time=commit_dt.date() if commit_dt else None,
                        note=r.get("flowChannelName") or None,
                        operator_name="百度同步",
                    )
                )
            total = _to_int(block.get("totalNum")) or 0
            if len(rows) < 5000 or page_no * 5000 >= total:
                break
            page_no += 1

    if new_records:
        session.add_all(new_records)
        await session.commit()
    logger.info(
        "账户 %s 线索同步 %s~%s：新增 %d 条（已存在 %d 条跳过）",
        baidu_account.baidu_username, start_date, end_date, len(new_records), len(existing),
    )
    return len(new_records)
