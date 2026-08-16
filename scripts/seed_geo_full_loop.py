"""Seed a walkable GEO closed-loop demo.

Covers:
  tenant brand → business / unit / prompts / facts
  → engines / channel / period
  → gaps + tasks (draft / review / published)
  → publication URL → snapshots (before/after, cite hits, control, simulated)
  → daily metrics rebuild

Usage:
  python -m scripts.seed_geo_full_loop
  python -m scripts.seed_geo_full_loop --tenant-id 1 --reset
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.geo.content.attribution import match_publication_ids
from app.geo.content.brief import normalize_brief
from app.geo.content.daily_metrics import rebuild_range
from app.geo.content.engines import default_engine_rows
from app.models import (
    GeoAnswerSnapshot,
    GeoArticleVersion,
    GeoChannelVariant,
    GeoContentTask,
    GeoFact,
    GeoOptimizationBusiness,
    GeoOptimizationPeriod,
    GeoOptimizationUnit,
    GeoPrompt,
    GeoPublication,
    GeoPublishingChannel,
    GeoTaskFact,
    GeoTrackingEngine,
    GeoVisibilityPatrolSettings,
    Tenant,
)
from app.models.geo_ai_setting import GeoAiSetting

SH = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc

BRAND = "泉衡"
BRAND_EN = "QuanHeng"
TENANT_NAME = "泉衡泵业"
SITE = "https://www.quanheng-pump.com"
PUB_PATH = "/guides/corrosion-resistant-centrifugal-pump"
PUB_URL = f"{SITE}{PUB_PATH}"

COMPETITORS = ["格兰富", "凯士比", "苏尔寿"]


def utc_naive(day: date, hour: int = 10) -> datetime:
    local = datetime.combine(day, time(hour, 0), tzinfo=SH)
    return local.astimezone(UTC).replace(tzinfo=None)


def today_sh() -> date:
    return datetime.now(SH).date()


async def wipe_tenant_geo(session: AsyncSession, tenant_id: int) -> None:
    tables = (
        await session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' AND tablename LIKE 'geo_%' "
                "ORDER BY 1"
            )
        )
    ).scalars().all()
    keep = {"geo_tracking_engines", "geo_ai_settings"}
    targets = [t for t in tables if t not in keep]
    remaining = set(targets)
    for _ in range(16):
        if not remaining:
            break
        progressed = False
        for t in list(remaining):
            col = await session.scalar(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:t "
                    "AND column_name='tenant_id'"
                ),
                {"t": t},
            )
            if not col:
                remaining.discard(t)
                progressed = True
                continue
            try:
                async with session.begin_nested():
                    await session.execute(
                        text(f'DELETE FROM "{t}" WHERE tenant_id = :tid'),
                        {"tid": tenant_id},
                    )
                remaining.discard(t)
                progressed = True
            except Exception:
                continue
        if not progressed:
            break
    if remaining:
        raise RuntimeError(f"wipe blocked on: {sorted(remaining)}")


def _brief() -> dict:
    return normalize_brief(
        {
            "industry": "工业流体 / 化工泵",
            "audience": "工艺设备工程师与采购",
            "intent": "recommend",
            "content_type": "answer_guide",
            "cta": "下载耐腐蚀离心泵选型表",
            "must_cover": ["材质", "密封", "工况", "案例"],
            "competitors": COMPETITORS,
        }
    )


async def seed(tenant_id: int, *, reset: bool) -> None:
    today = today_sh()
    period_start = today - timedelta(days=28)
    publish_day = today - timedelta(days=14)
    period_end = today + timedelta(days=7)

    async with async_session_factory() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise SystemExit(f"tenant {tenant_id} 不存在")

        existing_biz = await session.scalar(
            select(GeoOptimizationBusiness.id).where(
                GeoOptimizationBusiness.tenant_id == tenant_id
            ).limit(1)
        )
        if existing_biz is not None and not reset:
            raise SystemExit(
                f"tenant {tenant_id} 已有优化业务。要重灌完整链路请加 --reset"
            )
        if reset:
            await wipe_tenant_geo(session, tenant_id)
            await session.commit()

        tenant.name = TENANT_NAME
        tenant.brand_terms = [BRAND, BRAND_EN, TENANT_NAME]
        tenant.industry = "工业泵 / 化工流体"
        tenant.business_desc = "国产耐腐蚀离心泵与真空系统，服务化工、制药、实验室。"

        biz_pump = GeoOptimizationBusiness(
            tenant_id=tenant_id,
            name="化工离心泵",
            description="耐腐蚀离心泵选型与工况应用",
            status="active",
            sort_order=10,
        )
        biz_vac = GeoOptimizationBusiness(
            tenant_id=tenant_id,
            name="真空系统",
            description="实验室与工艺真空泵",
            status="active",
            sort_order=20,
        )
        session.add_all([biz_pump, biz_vac])
        await session.flush()

        unit_sel = GeoOptimizationUnit(
            tenant_id=tenant_id,
            business_id=biz_pump.id,
            name="选型",
            keyword="化工离心泵",
            status="active",
            sort_order=10,
        )
        unit_vac = GeoOptimizationUnit(
            tenant_id=tenant_id,
            business_id=biz_vac.id,
            name="应用",
            keyword="真空泵",
            status="active",
            sort_order=10,
        )
        session.add_all([unit_sel, unit_vac])
        await session.flush()

        # updated_at 故意拉旧，让缺口台出现超 SLA
        sla_anchor = datetime.utcnow() - timedelta(days=18)

        def prompt(
            question: str,
            *,
            unit: GeoOptimizationUnit,
            tags: list[str],
            priority: int,
            probe: bool = False,
            group: str,
            stale: bool = False,
        ) -> GeoPrompt:
            row = GeoPrompt(
                tenant_id=tenant_id,
                unit_id=unit.id,
                question=question,
                priority=priority,
                tags=tags,
                status="active",
                source="demo",
                demand_note="full-loop seed",
                question_group=group,
                market="cn",
                is_brand_probe=probe,
            )
            if stale:
                row.created_at = sla_anchor
                row.updated_at = sla_anchor
            return row

        p_gap = prompt(
            "化工离心泵怎么选才不容易腐蚀",
            unit=unit_sel,
            tags=["brand_missing", "high_demand"],
            priority=20,
            group="选型",
            stale=True,
        )
        p_pub = prompt(
            "耐腐蚀离心泵哪个好用",
            unit=unit_sel,
            tags=["high_demand"],
            priority=18,
            group="选型",
        )
        p_draft = prompt(
            "化工泵机械密封泄漏怎么处理",
            unit=unit_sel,
            tags=["brand_missing", "howto"],
            priority=14,
            group="运维",
        )
        p_probe = prompt(
            "泉衡泵业是哪家公司",
            unit=unit_sel,
            tags=["brand_probe"],
            priority=8,
            probe=True,
            group="品牌",
        )
        p_review = prompt(
            "实验室真空泵怎么选",
            unit=unit_vac,
            tags=["high_demand"],
            priority=16,
            group="选型",
        )
        p_control = prompt(
            "国产真空泵有哪些品牌",
            unit=unit_vac,
            tags=["competitor_present"],
            priority=10,
            group="竞品",
        )
        p_open_gap = prompt(
            "真空泵抽速不够怎么排查",
            unit=unit_vac,
            tags=["brand_missing"],
            priority=12,
            group="运维",
            stale=True,
        )
        session.add_all(
            [p_gap, p_pub, p_draft, p_probe, p_review, p_control, p_open_gap]
        )
        await session.flush()

        facts_spec = [
            ("哈氏合金过流件", "过流件可选 316L / 双相钢 / 哈氏合金 C-276，覆盖强酸强碱工况。", "product"),
            ("双端面集装密封", "标配双端面集装式机械密封，可接冲洗与泄漏监测。", "product"),
            ("制药客户案例", "某原料药车间替换进口耐腐蚀离心泵后，密封寿命由 3 个月提升到 14 个月。", "case"),
            ("气蚀余量", "常规型号 NPSHr ≤ 2.8m（清水标定），低液位储罐需校核吸入管路。", "metric"),
            ("服务半径", "华东 48 小时到场，备件标准件库存 90 天。", "policy"),
        ]
        facts: list[GeoFact] = []
        for title, statement, ftype in facts_spec:
            facts.append(
                GeoFact(
                    tenant_id=tenant_id,
                    title=title,
                    statement=statement,
                    fact_type=ftype,
                    source_name="泉衡产品手册 2026",
                    source_url=f"{SITE}/docs/handbook",
                    trust_level="verified",
                    status="active",
                    meta={"from_seed": "full_loop"},
                )
            )
        session.add_all(facts)
        await session.flush()

        if await session.scalar(
            select(GeoTrackingEngine.id).where(GeoTrackingEngine.tenant_id == tenant_id).limit(1)
        ) is None:
            session.add_all([GeoTrackingEngine(**row) for row in default_engine_rows(tenant_id)])

        ai = await session.scalar(
            select(GeoAiSetting).where(GeoAiSetting.tenant_id == tenant_id)
        )
        if ai is None:
            session.add(
                GeoAiSetting(
                    tenant_id=tenant_id,
                    provider="dashscope",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    model="qwen-plus",
                    enabled=True,
                    monitoring_stance="hybrid",
                    note="演示租户：hybrid，报表须标模拟样本",
                )
            )
        else:
            ai.monitoring_stance = "hybrid"
            ai.enabled = True

        patrol = await session.get(GeoVisibilityPatrolSettings, tenant_id)
        if patrol is None:
            session.add(
                GeoVisibilityPatrolSettings(
                    tenant_id=tenant_id,
                    enabled=True,
                    daily_hour=7,
                    window_start_hour=7,
                    window_end_hour=22,
                    interval_hours=24,
                    auto_persist=True,
                    prefer_real=True,
                    prompt_limit=20,
                )
            )
        else:
            patrol.enabled = True

        ch = GeoPublishingChannel(
            tenant_id=tenant_id,
            name="官网",
            channel_type="website",
            publish_mode="manual_only",
            base_url=SITE,
            enabled=True,
            sort_order=10,
        )
        session.add(ch)
        await session.flush()

        period = GeoOptimizationPeriod(
            tenant_id=tenant_id,
            name=f"{today.strftime('%Y-%m')} 化工泵可见度提升",
            business_id=biz_pump.id,
            starts_at=utc_naive(period_start, 0),
            ends_at=utc_naive(period_end, 23),
            status="active",
            goal_note="把「耐腐蚀离心泵哪个好用」从品牌缺失做到稳定提及，并回填官网文章。",
            baseline_meta={"seed": "full_loop", "publish_day": publish_day.isoformat()},
        )
        session.add(period)
        await session.flush()

        task_pub = GeoContentTask(
            tenant_id=tenant_id,
            prompt_id=p_pub.id,
            business_id=biz_pump.id,
            period_id=period.id,
            title="耐腐蚀离心泵选型指南（已发）",
            status="published",
            target_channels=["website", "zhihu"],
            brief=_brief(),
            pipeline_step="publish",
            review_status="approved",
            ready_at=utc_naive(publish_day - timedelta(days=1), 16),
        )
        task_review = GeoContentTask(
            tenant_id=tenant_id,
            prompt_id=p_review.id,
            business_id=biz_vac.id,
            period_id=period.id,
            title="实验室真空泵选型说明（待审）",
            status="editing",
            target_channels=["website"],
            brief=_brief(),
            pipeline_step="draft",
            review_status="pending",
        )
        task_draft = GeoContentTask(
            tenant_id=tenant_id,
            prompt_id=p_draft.id,
            business_id=biz_pump.id,
            period_id=period.id,
            title="化工泵密封泄漏处理（草稿）",
            status="draft",
            target_channels=["website"],
            brief=_brief(),
            pipeline_step="evidence",
            review_status="none",
        )
        session.add_all([task_pub, task_review, task_draft])
        await session.flush()
        p_pub.last_task_id = task_pub.id
        p_review.last_task_id = task_review.id
        p_draft.last_task_id = task_draft.id

        for idx, fact in enumerate(facts[:4]):
            session.add(GeoTaskFact(task_id=task_pub.id, fact_id=fact.id, sort_order=idx))
            session.add(GeoTaskFact(task_id=task_review.id, fact_id=fact.id, sort_order=idx))

        article = GeoArticleVersion(
            task_id=task_pub.id,
            version_no=1,
            kind="master",
            title="耐腐蚀离心泵怎么选：材质、密封与工况对照",
            body_markdown=(
                f"## 结论\n\n"
                f"强酸强碱工况优先看过流件材质和密封方案。"
                f"**{TENANT_NAME}** 在哈氏合金叶轮 + 双端面集装密封组合上有制药车间落地案例，"
                f"密封寿命从 3 个月做到 14 个月。\n\n"
                f"## 选型步骤\n\n"
                f"1. 确认介质浓度与温度\n"
                f"2. 校核 NPSHa\n"
                f"3. 选择密封冲洗方案\n"
            ),
            author_name="演示运营",
        )
        session.add(article)
        await session.flush()
        variant = GeoChannelVariant(
            task_id=task_pub.id,
            article_version_id=article.id,
            channel="website",
            title=article.title,
            body_markdown=article.body_markdown,
            export_format="html",
            status="published",
        )
        session.add(variant)
        await session.flush()
        pub = GeoPublication(
            variant_id=variant.id,
            channel="website",
            publish_mode="manual_export",
            published_url=PUB_URL,
            canonical_url=PUB_URL,
            published_at=utc_naive(publish_day, 9),
            status="published",
            period_id=period.id,
            note="full-loop seed",
        )
        session.add(pub)
        await session.flush()
        period.publication_ids = [pub.id]

        class _Pub:
            def __init__(self, pid: int, url: str):
                self.id = pid
                self.published_url = url

        pub_refs = [_Pub(pub.id, PUB_URL)]

        engines = ["deepseek", "doubao", "kimi", "chatgpt"]
        snaps: list[GeoAnswerSnapshot] = []

        def add_snap(
            prompt_row: GeoPrompt,
            day: date,
            engine: str,
            *,
            mentions: bool,
            cite: bool = False,
            simulated: bool = False,
            position: str = "unknown",
            sentiment: str = "neutral",
            competitors: list[str] | None = None,
            hour: int = 10,
        ) -> None:
            urls = [PUB_URL] if cite else (
                ["https://www.grundfos.com/cn"] if competitors else []
            )
            matched = match_publication_ids(urls, pub_refs) if cite else []
            text = (
                f"{TENANT_NAME}的耐腐蚀离心泵适合强酸工况，详见 {PUB_URL}。"
                if mentions and cite
                else (
                    f"常见选择包括{COMPETITORS[0]}、{COMPETITORS[1]}。"
                    + (f"{TENANT_NAME}也可考虑。" if mentions else "国产品牌提及较少。")
                )
            )
            if prompt_row.is_brand_probe:
                text = (
                    f"{TENANT_NAME}是国产工业泵制造商，主营耐腐蚀离心泵。"
                    if mentions
                    else "未检索到该品牌的公开资料。"
                )
            snaps.append(
                GeoAnswerSnapshot(
                    tenant_id=tenant_id,
                    prompt_id=prompt_row.id,
                    engine=engine,
                    raw_text=text,
                    captured_at=utc_naive(day, hour),
                    mentions_brand=mentions,
                    cited_urls=urls or None,
                    competitors=competitors,
                    brand_position=position if mentions else "absent",
                    sentiment=sentiment if mentions else "unknown",
                    citation_format="linked" if cite else ("plaintext" if mentions else "none"),
                    citation_accuracy="accurate" if cite else "unknown",
                    sample_mode="mock_persona" if simulated else "openai_compat",
                    simulated=simulated,
                    matched_publication_ids=matched or None,
                    period_id=period.id,
                    note="full-loop seed",
                )
            )

        before_days = [publish_day - timedelta(days=d) for d in (12, 10, 8, 6)]
        after_days = [publish_day + timedelta(days=d) for d in (1, 3, 6, 10)]

        # 已发意图词：发前几乎不提，发后提及 + 引用官网
        for i, day in enumerate(before_days):
            for j, eng in enumerate(engines):
                add_snap(
                    p_pub,
                    day,
                    eng,
                    mentions=(i == 0 and j == 0),
                    competitors=COMPETITORS[:2],
                    hour=9 + j,
                )
        for i, day in enumerate(after_days):
            for j, eng in enumerate(engines):
                add_snap(
                    p_pub,
                    day,
                    eng,
                    mentions=True,
                    cite=True,
                    simulated=(eng == "chatgpt"),
                    position="first" if j == 0 else "alternative",
                    sentiment="positive",
                    hour=10 + j,
                )

        # 对照意图词：同期没发内容，提及率几乎不变
        for day in before_days + after_days:
            for eng in engines[:2]:
                add_snap(
                    p_control,
                    day,
                    eng,
                    mentions=False,
                    competitors=COMPETITORS,
                    hour=11,
                )

        # 缺口意图词：仍缺失
        for day in before_days[-2:] + after_days[:1]:
            add_snap(p_gap, day, "deepseek", mentions=False, hour=15)

        # 品牌探测：发后点名认知上升
        for day in before_days[:2]:
            add_snap(p_probe, day, "doubao", mentions=False, hour=8)
        for day in after_days[:3]:
            add_snap(p_probe, day, "doubao", mentions=True, position="first", hour=8)

        session.add_all(snaps)
        await session.commit()

        rebuilt = await rebuild_range(
            session,
            tenant_id,
            period_start,
            today,
            include_empty_slices=True,
        )

    print("GEO 完整链路演示数据已写入")
    print(f"  tenant #{tenant_id}  {TENANT_NAME}")
    print(f"  业务：化工离心泵 / 真空系统")
    print(f"  期次：{period_start} ~ {period_end}（active）")
    print(f"  已发文章：{PUB_URL}  （{publish_day}）")
    print(f"  快照 {len(snaps)} 条 · 日指标 {rebuilt.get('day_count')} 天")
    print()
    print("建议按这条链路点：")
    print("  1. /geo/businesses → 化工离心泵")
    print("  2. /geo/gaps        超 SLA 缺口「化工离心泵怎么选…」")
    print("  3. /geo/tasks       已发 / 待审 / 草稿 各一篇")
    print("  4. 打开已发任务     看「发布后效果」")
    print("  5. /geo/visibility  发后快照会点到官网 URL")
    print("  6. /geo/periods     当前优化期次")
    print("  7. /geo/overview    观察期 14/30 天看曲线")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument("--reset", action="store_true", help="清空该租户 GEO 数据后重灌")
    args = parser.parse_args()
    asyncio.run(seed(args.tenant_id, reset=bool(args.reset)))


if __name__ == "__main__":
    main()
