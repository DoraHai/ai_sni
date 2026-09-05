"""建议引擎：聚合每个关键词画像 → 跑规则 → 护栏 → upsert suggestions。

幂等：同 (tenant_id, rule_code, keyword_id, report_date) 重跑只刷新建议值/理由，
不覆盖人工 status（adopted/ignored）。report_date = 窗口锚定日（最近有数据日）。

第 3 步产「规则版」建议（reason 是模板文案）；第 4 步 AI 层会接收这些 draft +
全维 signals，替换 reason 为判断理由并做跨规则仲裁。
"""
import logging
from datetime import timedelta

from sqlalchemy import BigInteger, all_, any_, bindparam, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Keyword, KwReportSnapshot, Suggestion, Tenant
from app.database import async_session_factory
from app.module_scope import list_active_module_tenants
from app.suggestions.base import KeywordProfile, SuggestionContext
from app.suggestions.guardrails import apply_guardrails
from app.suggestions.rules import ALL_RULES

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _keyword_ids_parameter(ids):
    # PostgreSQL array is ONE bind, unlike an expanding IN/NOT IN list.
    return bindparam("keyword_ids", value=list(ids), type_=ARRAY(BigInteger))


async def _persist_suggestions(
    session: AsyncSession, tenant_id: int, target_date, records: list[dict],
    *, evaluated_keyword_ids=None,
) -> None:
    """Batch writes and stale cleanup share a transaction; never overwrite human state."""
    evaluated_ids = None if evaluated_keyword_ids is None else list(evaluated_keyword_ids)
    if not records and not evaluated_ids:
        return
    # Include implicit column defaults in the budget, not just explicit record keys.
    chunk_size = min(1000, 30000 // len(Suggestion.__table__.columns))
    try:
        for start in range(0, len(records), chunk_size):
            stmt = pg_insert(Suggestion).values(records[start:start + chunk_size])
            stmt = stmt.on_conflict_do_update(
                constraint="uq_suggestions_tenant_kw_date",
                set_={
                    "rule_code": stmt.excluded.rule_code,
                    "suggestion_type": stmt.excluded.suggestion_type,
                    "priority": stmt.excluded.priority,
                    "confidence": stmt.excluded.confidence,
                    "current_bid": stmt.excluded.current_bid,
                    "suggested_bid": stmt.excluded.suggested_bid,
                    "change_pct": stmt.excluded.change_pct,
                    "reason": stmt.excluded.reason,
                    "signals": stmt.excluded.signals,
                    # Only reactivate system-expired results; preserve human decisions.
                    "status": case(
                        (Suggestion.status == "expired", "pending"),
                        else_=Suggestion.status,
                    ),
                    # 不动 adopted_at 或内部协作状态。
                },
            )
            await session.execute(stmt)

        # 不对 NOT IN 分块执行：那会把其他批次的新建议错误标记为过期。
        cleanup = (
            update(Suggestion)
            .where(
                Suggestion.tenant_id == tenant_id,
                Suggestion.status == "pending",
                Suggestion.report_date <= target_date,
                or_(
                    Suggestion.report_date != target_date,
                    Suggestion.keyword_id != all_(
                        _keyword_ids_parameter(r["keyword_id"] for r in records)
                    ),
                ),
            )
            .values(status="expired")
            .execution_options(synchronize_session=False)
        )
        if evaluated_ids is not None:
            # Missing reports/assets are not evidence that an old suggestion is invalid.
            cleanup = cleanup.where(Suggestion.keyword_id == any_(bindparam(
                "evaluated_keyword_ids", value=evaluated_ids, type_=ARRAY(BigInteger)
            )))
        await session.execute(cleanup)
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def run_suggestions_for_tenant(
    session: AsyncSession, tenant: Tenant, window_days: int = WINDOW_DAYS
) -> int:
    """对单租户跑建议引擎，返回写入/刷新的建议条数。"""
    # 窗口锚定：最近有数据日往前 window_days 天
    latest = await session.scalar(
        select(func.max(KwReportSnapshot.report_date)).where(
            KwReportSnapshot.tenant_id == tenant.id
        )
    )
    if latest is None:
        return 0
    window_start = latest - timedelta(days=window_days - 1)

    # 窗口指标聚合（跨天 + 跨设备合并到关键词）
    metric_rows = (
        await session.execute(
            select(
                KwReportSnapshot.keyword_id,
                func.max(KwReportSnapshot.campaign_name),
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
                func.sum(KwReportSnapshot.conversions),
                func.avg(KwReportSnapshot.avg_rank),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant.id,
                KwReportSnapshot.report_date >= window_start,
                KwReportSnapshot.report_date <= latest,
                KwReportSnapshot.keyword_id.isnot(None),
            )
            .group_by(KwReportSnapshot.keyword_id)
        )
    ).all()
    if not metric_rows:
        return 0

    metrics: dict[int, dict] = {}
    tot_click = tot_imp = 0
    tot_cost = 0.0
    for kw_id, camp_name, cost, click, imp, conv, rank in metric_rows:
        cost_f = _f(cost) or 0.0
        click_i = int(click or 0)
        imp_i = int(imp or 0)
        conv_i = int(conv or 0)
        metrics[kw_id] = {
            "campaign_name": camp_name,
            "cost": cost_f,
            "click": click_i,
            "impression": imp_i,
            "conversions": conv_i,
            "ctr": (click_i / imp_i) if imp_i else None,
            "cpc": (cost_f / click_i) if click_i else None,
            "avg_rank": _f(rank),
        }
        tot_click += click_i
        tot_imp += imp_i
        tot_cost += cost_f

    ctx = SuggestionContext(
        target_date=latest,
        avg_ctr=(tot_click / tot_imp) if tot_imp else None,
        avg_cpc=(tot_cost / tot_click) if tot_click else None,
    )

    # 关键词属性（未暂停的；已暂停词不产调价建议）
    kw_rows = (
        await session.scalars(
            select(Keyword).where(
                Keyword.tenant_id == tenant.id,
                Keyword.keyword_id == any_(_keyword_ids_parameter(metrics.keys())),
                Keyword.pause.isnot(True),
            )
        )
    ).all()

    if not kw_rows or not ALL_RULES:
        return 0  # no usable assets/rules: do not treat missing input as a rejection
    drafts = []
    evaluation_failed = False
    profiles: dict[int, KeywordProfile] = {}
    for kw in kw_rows:
        m = metrics.get(kw.keyword_id)
        if not m:
            continue
        p = KeywordProfile(
            keyword_id=kw.keyword_id,
            keyword=kw.keyword,
            campaign_id=kw.campaign_id,
            campaign_name=m["campaign_name"],
            adgroup_id=kw.adgroup_id,
            category=kw.category,
            price=_f(kw.price),
            quality=kw.quality,
            left_price_guide=_f(kw.left_price_guide),
            m_price_guide=_f(kw.m_price_guide),
            impression=m["impression"],
            click=m["click"],
            cost=m["cost"],
            conversions=m["conversions"],
            ctr=m["ctr"],
            cpc=m["cpc"],
            avg_rank=m["avg_rank"],
        )
        profiles[kw.keyword_id] = p
        for rule in ALL_RULES:
            try:
                d = rule(p, ctx)
            except Exception:  # noqa: BLE001
                evaluation_failed = True
                logger.exception(
                    "建议规则 %s 对词 %s 执行失败", rule.__name__, kw.keyword_id
                )
                continue
            if d is None:
                continue
            d = apply_guardrails(d, p)
            if d is not None:
                drafts.append(d)

    if evaluation_failed:
        # A partial rule pass is not an authoritative replacement of previous results.
        raise RuntimeError("建议规则评估未完整完成，已保留原有建议，请重试")
    if not drafts:
        await _persist_suggestions(
            session, tenant.id, ctx.target_date, [], evaluated_keyword_ids=profiles.keys()
        )
        return 0

    # 同词仲裁：一个关键词只留一条主建议（优先级最高，同级取置信度高）。
    # 这是规则版兜底仲裁；第 4 步 AI 层会做更聪明的综合仲裁（如高耗 vs 扩量冲突）。
    conf_rank = {"high": 0, "mid": 1, "low": 2}
    by_kw: dict[int, object] = {}
    for d in drafts:
        cur = by_kw.get(d.keyword_id)
        if cur is None or (d.priority, conf_rank.get(d.confidence, 9)) < (
            cur.priority,
            conf_rank.get(cur.confidence, 9),
        ):
            by_kw[d.keyword_id] = d
    drafts = list(by_kw.values())

    # AI 判断层（第 4 步）：配了 DEEPSEEK_API_KEY 就逐条做 AI 判断 / 仲裁 / 理由，
    # 否则原样用规则版。AI 否决的剔除；调用失败在 enhance_draft 内降级保留规则版。
    from app.ai.customer_profile import build_customer_brief
    from app.ai.judge import enhance_draft

    # 客户画像：每次跑算一次，喂给每条建议的 AI 判断（让 AI 懂这个客户）
    customer_brief = await build_customer_brief(session, tenant)

    final = []
    for d in drafts:
        nd = await enhance_draft(profiles.get(d.keyword_id), d, customer_brief)
        if nd is not None:
            final.append(nd)
    drafts = final

    records = [
        {
            "tenant_id": tenant.id,
            "rule_code": d.rule_code,
            "suggestion_type": d.suggestion_type,
            "priority": d.priority,
            "confidence": d.confidence,
            "current_bid": d.current_bid,
            "suggested_bid": d.suggested_bid,
            "change_pct": d.change_pct,
            "reason": d.reason,
            "signals": d.signals,
            "report_date": ctx.target_date,
            "keyword_id": d.keyword_id,
            "keyword": d.keyword,
            "campaign_id": d.campaign_id,
            "campaign_name": d.campaign_name,
            "adgroup_id": d.adgroup_id,
        }
        for d in drafts
    ]
    await _persist_suggestions(
        session, tenant.id, ctx.target_date, records, evaluated_keyword_ids=profiles.keys()
    )

    logger.info(
        "租户 %s 建议引擎产出 %d 条（窗口 %s ~ %s）",
        tenant.id,
        len(records),
        window_start,
        latest,
    )
    return len(records)


async def run_suggestions_for_all_tenants(
    session: AsyncSession, window_days: int = WINDOW_DAYS
) -> dict[str, int]:
    """对所有租户跑建议引擎（每日同步后调用）。返回 {租户名: 条数}。"""
    tenants = await list_active_module_tenants(session, "sem")
    tenant_refs = [(tenant.id, tenant.name) for tenant in tenants]
    result: dict[str, int] = {}
    for tenant_id, tenant_name in tenant_refs:
        try:
            async with async_session_factory() as tenant_session:
                tenant = await tenant_session.get(Tenant, tenant_id)
                if tenant is None:
                    continue
                result[tenant_name] = await run_suggestions_for_tenant(tenant_session, tenant, window_days)
        except Exception:  # noqa: BLE001
            logger.exception("租户 %s 建议引擎失败", tenant_name)
            result[tenant_name] = -1
    return result
