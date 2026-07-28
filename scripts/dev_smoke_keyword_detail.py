"""keywords/{id} 详情接口本地冒烟：建租户 + 塞品牌词/非品牌词快照 + 告警 + TestClient 调接口。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      .venv/bin/python scripts/dev_smoke_keyword_detail.py
"""
import asyncio
import json
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.database import async_session_factory, engine
from app.models import Alert, BaiduAccount, KwReportSnapshot, Tenant
from app.security.crypto import encrypt

BRAND_KW_ID = 61001
NORMAL_KW_ID = 61002


async def seed() -> int:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "冒烟测试租户"))
        if tenant is None:
            tenant = Tenant(name="冒烟测试租户", strategy="lead", monthly_budget=10000)
            session.add(tenant)
            await session.flush()

        acc = await session.scalar(
            select(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id)
        )
        if acc is None:
            session.add(
                BaiduAccount(
                    tenant_id=tenant.id,
                    baidu_username="冒烟测试账户",
                    baidu_ucid=99999999,
                    access_token_encrypted=encrypt("fake-token"),
                    expires_at=datetime(2026, 9, 1),
                    auth_mode="self",
                    status="active",
                )
            )

        await session.execute(
            delete(KwReportSnapshot).where(KwReportSnapshot.tenant_id == tenant.id)
        )
        await session.execute(delete(Alert).where(Alert.tenant_id == tenant.id))

        # 品牌词（含租户名）10 天 × 2 设备，排名后 3 天恶化；非品牌词只给 3 天
        today = date.today()
        rows = []
        for offset in range(10):
            d = today - timedelta(days=offset + 1)
            rank = 1.2 if offset >= 3 else 1.8  # 最近 3 天排名失守
            for device, share in ((1, 0.6), (2, 0.4)):
                rows.append(
                    KwReportSnapshot(
                        tenant_id=tenant.id,
                        report_date=d,
                        campaign_id=2001,
                        campaign_name="品牌词-冒烟",
                        adgroup_id=3001,
                        adgroup_name="核心词单元",
                        keyword_id=BRAND_KW_ID,
                        keyword="冒烟测试租户 官网",
                        match_type=48,
                        device=device,
                        impression=int(500 * share),
                        click=int(40 * share),
                        cost=round(120.0 * share, 2),
                        avg_rank=rank,
                        quality_enum=8,
                        estimated_click_rate=3,
                        business_relationship=2,
                        land_page_experience=2,
                        bid_new=18.5,
                        fetched_at=datetime.utcnow(),
                    )
                )
        for offset in range(3):
            d = today - timedelta(days=offset + 1)
            rows.append(
                KwReportSnapshot(
                    tenant_id=tenant.id,
                    report_date=d,
                    campaign_id=2002,
                    campaign_name="通用词-冒烟",
                    keyword_id=NORMAL_KW_ID,
                    keyword="工业泵 维修",
                    match_type=17,
                    device=1,
                    impression=100,
                    click=5,
                    cost=30.0,
                    avg_rank=2.5,
                    fetched_at=datetime.utcnow(),
                )
            )
        session.add_all(rows)

        session.add(
            Alert(
                tenant_id=tenant.id,
                rule_code="R-14",
                priority="P0",
                title="品牌词排名失守",
                message="品牌词「冒烟测试租户 官网」平均排名 1.8，已跌出第一位。",
                report_date=today - timedelta(days=1),
                keyword_id=BRAND_KW_ID,
                keyword="冒烟测试租户 官网",
                campaign_id=2001,
                campaign_name="品牌词-冒烟",
                metrics={"平均排名": 1.8, "消费": 120.0, "展现": 500},
            )
        )
        await session.commit()
        tid = tenant.id
    # seed 跑在独立事件循环里，必须清掉连接池，否则 TestClient 的新循环会复用旧连接报错
    await engine.dispose()
    return tid


tenant_id = asyncio.run(seed())

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

auth = {"X-API-Key": get_settings().admin_api_key}

with TestClient(app) as client:
    r = client.get(
        f"/api/v1/keywords/{BRAND_KW_ID}?tenant_id={tenant_id}", headers=auth
    )
    print("HTTP(品牌词默认时段)", r.status_code)
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))

    r2 = client.get(
        f"/api/v1/keywords/{NORMAL_KW_ID}?tenant_id={tenant_id}", headers=auth
    )
    body = r2.json()
    print(
        "HTTP(非品牌词)", r2.status_code,
        "category:", body["keyword"]["category"],
        "match:", body["keyword"]["match_type_label"],
        "alerts:", len(body["alerts"]),
    )

    start = (date.today() - timedelta(days=4)).isoformat()
    end = (date.today() - timedelta(days=1)).isoformat()
    r3 = client.get(
        f"/api/v1/keywords/{BRAND_KW_ID}?tenant_id={tenant_id}"
        f"&start_date={start}&end_date={end}",
        headers=auth,
    )
    b3 = r3.json()
    print(
        "HTTP(指定 4 天时段)", r3.status_code,
        "days:", b3["period"]["days"],
        "trend_len:", len(b3["trend"]),
        "环比消费:", b3["kpi"]["cost"],
    )

    r404 = client.get(f"/api/v1/keywords/99999999?tenant_id={tenant_id}", headers=auth)
    print("HTTP(不存在关键词)", r404.status_code, r404.json())

    rt404 = client.get(f"/api/v1/keywords/{BRAND_KW_ID}?tenant_id=99999", headers=auth)
    print("HTTP(不存在租户)", rt404.status_code, rt404.json())

    rbad = client.get(
        f"/api/v1/keywords/{BRAND_KW_ID}?tenant_id={tenant_id}"
        "&start_date=2026-06-09&end_date=2026-06-01",
        headers=auth,
    )
    print("HTTP(日期倒置)", rbad.status_code, rbad.json())

    rnokey = client.get(f"/api/v1/keywords/{BRAND_KW_ID}?tenant_id={tenant_id}")
    print("HTTP(无 API Key)", rnokey.status_code, rnokey.json())
