"""同词归并本地冒烟：品牌词连续 3 天排名失守 → 引擎逐日跑 → 验证只剩最新一条 open。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_alert_merge.py
"""
import asyncio
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.database import async_session_factory, engine
from app.models import Alert, Keyword, KwReportSnapshot, Tenant
from app.rules.engine import run_rules_for_tenant

KW_ID = 62001
TODAY = date.today()
DAYS = [TODAY - timedelta(days=3), TODAY - timedelta(days=2), TODAY - timedelta(days=1)]


async def main() -> None:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "冒烟测试租户"))
        assert tenant, "先跑 dev_smoke_keyword_detail.py 建租户"

        await session.execute(
            delete(KwReportSnapshot).where(KwReportSnapshot.tenant_id == tenant.id)
        )
        await session.execute(delete(Alert).where(Alert.tenant_id == tenant.id))
        # R-14 已切按 keywords.category='brand' 过滤——给冒烟快照补对应维度行
        # （此前只造快照不造维度行，分级切换后引擎一条不触发，2026-06-13 修）
        await session.execute(
            delete(Keyword).where(
                Keyword.tenant_id == tenant.id, Keyword.keyword_id.in_([KW_ID, KW_ID + 1])
            )
        )
        session.add_all([
            Keyword(tenant_id=tenant.id, keyword_id=KW_ID, keyword="冒烟测试租户 官网",
                    category="brand", category_source="auto"),
            Keyword(tenant_id=tenant.id, keyword_id=KW_ID + 1, keyword="冒烟测试租户 配件",
                    category="brand", category_source="auto"),
        ])

        # 品牌词连续 3 天 avg_rank=2.0（> 1.5 阈值），每天都会触发 R-14
        for d in DAYS:
            session.add(
                KwReportSnapshot(
                    tenant_id=tenant.id,
                    report_date=d,
                    campaign_id=2001,
                    campaign_name="品牌词-归并冒烟",
                    keyword_id=KW_ID,
                    keyword="冒烟测试租户 官网",
                    device=1,
                    impression=100,
                    click=10,
                    cost=50.0,
                    avg_rank=2.0,
                    fetched_at=datetime.utcnow(),
                )
            )
        # 低展现品牌词：排名同样失守但展现 < 5，不应触发 R-14（最小展现门槛）
        session.add(
            KwReportSnapshot(
                tenant_id=tenant.id,
                report_date=DAYS[2],
                campaign_id=2001,
                campaign_name="品牌词-归并冒烟",
                keyword_id=KW_ID + 1,
                keyword="冒烟测试租户 配件",
                device=1,
                impression=2,
                click=0,
                cost=0,
                avg_rank=4.0,
                fetched_at=datetime.utcnow(),
            )
        )
        await session.commit()

        async def status_map() -> dict[str, str]:
            rows = (
                await session.scalars(
                    select(Alert).where(
                        Alert.tenant_id == tenant.id, Alert.keyword_id == KW_ID
                    )
                )
            ).all()
            for a in rows:
                session.expire(a)
            rows = (
                await session.scalars(
                    select(Alert).where(
                        Alert.tenant_id == tenant.id, Alert.keyword_id == KW_ID
                    )
                )
            ).all()
            return {a.report_date.isoformat(): a.status for a in rows}

        # 逐日跑（正序）
        for d in DAYS:
            await run_rules_for_tenant(session, tenant, d)
        m = await status_map()
        print("正序跑 3 天:", m)
        assert m[DAYS[2].isoformat()] == "open", "最新一天应保持 open"
        assert m[DAYS[0].isoformat()] == "merged" and m[DAYS[1].isoformat()] == "merged", "旧告警应归并"

        # 乱序回灌最早一天，归并状态不应翻回
        await run_rules_for_tenant(session, tenant, DAYS[0])
        m = await status_map()
        print("回灌最早一天:", m)
        assert m[DAYS[0].isoformat()] == "merged", "回灌后旧告警仍应是 merged"
        assert m[DAYS[2].isoformat()] == "open", "最新一条不受影响"

        # 人工处理最新一条后再回灌：不应有新 open 冒出来
        latest = await session.scalar(
            select(Alert).where(
                Alert.tenant_id == tenant.id,
                Alert.keyword_id == KW_ID,
                Alert.status == "open",
            )
        )
        latest.status = "resolved"
        latest.resolved_at = datetime.utcnow()
        await session.commit()
        await run_rules_for_tenant(session, tenant, DAYS[1])
        m = await status_map()
        print("处理最新后回灌:", m)
        assert m[DAYS[2].isoformat()] == "resolved", "人工 resolved 不能被覆盖"
        assert "open" not in m.values(), "全组不应再有 open"

        low_imp = await session.scalar(
            select(Alert).where(
                Alert.tenant_id == tenant.id, Alert.keyword_id == KW_ID + 1
            )
        )
        assert low_imp is None, "展现 < 5 的品牌词不应触发 R-14"
        print("✅ 同词归并 + 最小展现门槛冒烟全部通过")

    await engine.dispose()


asyncio.run(main())
