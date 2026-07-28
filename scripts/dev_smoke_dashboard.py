"""dashboard/today 本地冒烟：建租户 + 塞两天假快照 + TestClient 调接口。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      .venv/bin/python scripts/dev_smoke_dashboard.py
"""
import asyncio
import json
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.database import async_session_factory, engine
from app.models import BaiduAccount, KwReportSnapshot, Tenant
from app.security.crypto import encrypt


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
        today = date.today()
        rows = []
        for offset, (cost, click, imp) in enumerate(
            [(120.5, 30, 800), (98.0, 22, 650), (150.0, 41, 1100)]
        ):
            d = today - timedelta(days=offset + 1)
            for device, share in ((1, 0.6), (2, 0.4)):
                rows.append(
                    KwReportSnapshot(
                        tenant_id=tenant.id,
                        report_date=d,
                        campaign_id=1001 + offset % 2,
                        campaign_name=f"测试计划-{1001 + offset % 2}",
                        keyword_id=50000 + offset * 10 + device,
                        keyword=f"测试词{offset}",
                        device=device,
                        impression=int(imp * share),
                        click=int(click * share),
                        cost=round(cost * share, 2),
                        fetched_at=datetime.utcnow(),
                    )
                )
        session.add_all(rows)
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
    r = client.get(f"/api/v1/dashboard/today?tenant_id={tenant_id}", headers=auth)
    print("HTTP", r.status_code)
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))

    r404 = client.get("/api/v1/dashboard/today?tenant_id=99999", headers=auth)
    print("HTTP(不存在租户)", r404.status_code, r404.json())

    rbad = client.get(
        f"/api/v1/dashboard/today?tenant_id={tenant_id}"
        "&start_date=2026-06-09&end_date=2026-06-01",
        headers=auth,
    )
    print("HTTP(日期倒置)", rbad.status_code, rbad.json())

    rnokey = client.get(f"/api/v1/dashboard/today?tenant_id={tenant_id}")
    print("HTTP(无 API Key)", rnokey.status_code, rnokey.json())

    rwrong = client.get(
        f"/api/v1/dashboard/today?tenant_id={tenant_id}",
        headers={"X-API-Key": "wrong-key"},
    )
    print("HTTP(错误 API Key)", rwrong.status_code, rwrong.json())

    rquery = client.get(
        f"/api/v1/dashboard/today?tenant_id={tenant_id}"
        f"&key={get_settings().admin_api_key}"
    )
    print("HTTP(查询参数携带 Key)", rquery.status_code)
