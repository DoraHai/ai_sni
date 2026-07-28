"""5 类分级本地冒烟：维度表 + 自动分类 + 人工覆盖 + R-14 按分级过滤。

百度 getWord 本地调不了，keywords 行直接造（等价于同步落库后的状态）。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_classify.py
"""
import asyncio
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.classification import reclassify_keywords
from app.database import async_session_factory, engine
from app.models import Alert, Keyword, KwReportSnapshot, Tenant
from app.rules.engine import run_rules_for_tenant

YESTERDAY = date.today() - timedelta(days=1)

# (keyword_id, 字面, tabs, 累计展现, 期望分类)
CASES = [
    (71001, "冒烟测试租户 官网", None, 100, "brand"),
    (71002, "工业泵 维修", [31], 50, "focus"),
    (71003, "离心泵 价格", None, 5, "new"),
    (71004, "化工泵 厂家", None, 80, "normal"),
]


async def main() -> None:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "冒烟测试租户"))
        assert tenant, "先跑 dev_smoke_keyword_detail.py 建租户"

        for table in (KwReportSnapshot, Alert, Keyword):
            await session.execute(delete(table).where(table.tenant_id == tenant.id))

        for kw_id, text, tabs, imp, _ in CASES:
            session.add(
                KwReportSnapshot(
                    tenant_id=tenant.id,
                    report_date=YESTERDAY,
                    campaign_id=2001,
                    campaign_name="分级冒烟",
                    keyword_id=kw_id,
                    keyword=text,
                    device=1,
                    impression=imp,
                    click=5,
                    cost=20.0,
                    avg_rank=2.0,  # 全部排名失守，验证 R-14 只对 brand 触发
                    fetched_at=datetime.utcnow(),
                )
            )
            session.add(
                Keyword(
                    tenant_id=tenant.id,
                    keyword_id=kw_id,
                    keyword=text,
                    campaign_id=2001,
                    tabs=tabs,
                    price=10.0,
                    pause=False,
                    synced_at=datetime.utcnow(),
                )
            )
        await session.commit()

        # ===== 自动分类 =====
        counts = await reclassify_keywords(session, tenant)
        print("分类计数:", counts)
        for kw_id, _, _, _, expected in CASES:
            kw = await session.scalar(
                select(Keyword).where(
                    Keyword.tenant_id == tenant.id, Keyword.keyword_id == kw_id
                )
            )
            assert kw.category == expected, f"{kw.keyword} 期望 {expected} 实际 {kw.category}"
            print(f"  {kw.keyword}: {kw.category} ✓ (展现 {kw.total_impression})")

        # ===== 人工覆盖：normal → longtail，重算不被翻回 =====
        kw = await session.scalar(
            select(Keyword).where(
                Keyword.tenant_id == tenant.id, Keyword.keyword_id == 71004
            )
        )
        kw.category = "longtail"
        kw.category_source = "manual"
        await session.commit()
        await reclassify_keywords(session, tenant)
        await session.refresh(kw)
        assert kw.category == "longtail" and kw.category_source == "manual", "人工分级被自动重算覆盖"
        print("人工标长尾精准词后重算: 保持 longtail ✓")

        # ===== R-14 按分级过滤：4 词全部排名失守，只有 brand 触发 =====
        await run_rules_for_tenant(session, tenant, YESTERDAY)
        alerts = (
            await session.scalars(
                select(Alert).where(
                    Alert.tenant_id == tenant.id, Alert.rule_code == "R-14"
                )
            )
        ).all()
        assert len(alerts) == 1 and alerts[0].keyword_id == 71001, (
            f"R-14 应只对品牌词触发，实际 {[(a.keyword, a.keyword_id) for a in alerts]}"
        )
        print(f"R-14 按分级过滤: 只触发「{alerts[0].keyword}」✓")

        print("✅ 5 类分级冒烟全部通过")

    await engine.dispose()


asyncio.run(main())
