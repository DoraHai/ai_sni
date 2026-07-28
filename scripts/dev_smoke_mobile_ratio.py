"""出价系数移动比例层本地冒烟：铺计划/单元维度（含 priceRatio），验证 5 层叠加。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      .venv/bin/python scripts/dev_smoke_mobile_ratio.py

验证 4 个 case：
  1. 计划级 priceRatio=0.8（单元未设置）→ source=campaign，下限 ×0.8、上限 ×1.0
  2. 单元级 priceRatio=5.0 覆盖计划级 → source=adgroup，上限 ×5.0
  3. 两级都没有 → missing_layers 含「移动比例」，按 1.0 计
  4. 计划级 priceRatio=0（仅计算机计划，苏尔寿 EO/PS 实测）→ ratio=0 透传、
     missing_layers 空、生效区间不受影响（移动端无流量）
"""
import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.database import async_session_factory, engine
from app.models import Adgroup, BaiduAccount, Campaign, KwReportSnapshot, Tenant
from app.security.crypto import encrypt

KW_CAMP_RATIO = 62001  # case 1：吃计划级移动比例
KW_ADG_RATIO = 62002  # case 2：单元级覆盖
KW_NO_RATIO = 62003  # case 3：两级都没有
KW_PC_ONLY = 62004  # case 4：计划级比例 0（仅计算机投放）

CAMP_A, CAMP_B, CAMP_C, CAMP_D = 7001, 7002, 7003, 7004
ADG_A, ADG_B, ADG_C, ADG_D = 8001, 8002, 8003, 8004


def _now_time_id() -> int:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return now.isoweekday() * 100 + now.hour


async def seed() -> int:
    time_id = _now_time_id()
    sched = [{"timeId": time_id, "priceFactor": 1.2}]
    region = [
        {"regionId": 1, "priceFactor": 0.9},
        {"regionId": 2, "priceFactor": 1.5},
    ]
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "移动比例冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="移动比例冒烟租户", strategy="lead", monthly_budget=10000)
            session.add(tenant)
            await session.flush()
        acc = await session.scalar(
            select(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id)
        )
        if acc is None:
            session.add(
                BaiduAccount(
                    tenant_id=tenant.id,
                    baidu_username="移动比例冒烟账户",
                    baidu_ucid=99999998,
                    access_token_encrypted=encrypt("fake-token"),
                    expires_at=datetime(2026, 9, 1),
                    auth_mode="self",
                    status="active",
                )
            )
        for model in (KwReportSnapshot, Campaign, Adgroup):
            await session.execute(delete(model).where(model.tenant_id == tenant.id))

        camp_common = dict(
            tenant_id=tenant.id,
            schedule_price_factors=sched,
            region_price_factor=region,
            synced_at=datetime.utcnow(),
        )
        session.add_all(
            [
                Campaign(campaign_id=CAMP_A, campaign_name="计划级比例", price_ratio=0.8, **camp_common),
                Campaign(campaign_id=CAMP_B, campaign_name="单元级覆盖", price_ratio=0.8, **camp_common),
                Campaign(campaign_id=CAMP_C, campaign_name="无比例", price_ratio=None, **camp_common),
                Campaign(campaign_id=CAMP_D, campaign_name="仅PC", price_ratio=0, **camp_common),
                Adgroup(tenant_id=tenant.id, adgroup_id=ADG_A, campaign_id=CAMP_A, price_ratio=None),
                Adgroup(tenant_id=tenant.id, adgroup_id=ADG_B, campaign_id=CAMP_B, price_ratio=5.0),
                Adgroup(tenant_id=tenant.id, adgroup_id=ADG_C, campaign_id=CAMP_C, price_ratio=-1),  # -1=继承
                Adgroup(tenant_id=tenant.id, adgroup_id=ADG_D, campaign_id=CAMP_D, price_ratio=-1),
            ]
        )

        d = date.today() - timedelta(days=1)
        for kw_id, camp_id, adg_id, name in (
            (KW_CAMP_RATIO, CAMP_A, ADG_A, "计划比例词"),
            (KW_ADG_RATIO, CAMP_B, ADG_B, "单元覆盖词"),
            (KW_NO_RATIO, CAMP_C, ADG_C, "无比例词"),
            (KW_PC_ONLY, CAMP_D, ADG_D, "仅PC词"),
        ):
            session.add(
                KwReportSnapshot(
                    tenant_id=tenant.id,
                    report_date=d,
                    campaign_id=camp_id,
                    adgroup_id=adg_id,
                    keyword_id=kw_id,
                    keyword=name,
                    device=1,
                    impression=100,
                    click=10,
                    cost=50.0,
                    avg_rank=1.5,
                    bid_new=10.0,
                    fetched_at=datetime.utcnow(),
                )
            )
        await session.commit()
        tid = tenant.id
    await engine.dispose()
    return tid


tenant_id = asyncio.run(seed())

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

auth = {"X-API-Key": get_settings().admin_api_key}
failed = False


def check(label: str, cond: bool, detail: str = "") -> None:
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


with TestClient(app) as client:
    def coef(kw_id: int) -> dict:
        r = client.get(f"/api/v1/keywords/{kw_id}?tenant_id={tenant_id}", headers=auth)
        assert r.status_code == 200, r.text
        return r.json()["bid_coefficients"]

    # case 1：计划级 0.8。base=10，时段 1.2，地域 0.9~1.5
    c1 = coef(KW_CAMP_RATIO)
    check("case1 source=campaign", c1["mobile"]["source"] == "campaign", str(c1["mobile"]))
    check("case1 ratio=0.8", c1["mobile"]["ratio"] == 0.8)
    check("case1 missing_layers 空", c1["missing_layers"] == [])
    # 下限 10×1.2×0.9×0.8=8.64；上限 10×1.2×1.5×1.0=18.0
    check("case1 区间", (c1["effective"]["current_min"], c1["effective"]["current_max"]) == (8.64, 18.0),
          str(c1["effective"]))
    check("case1 max_multiplier=1.8", c1["effective"]["max_multiplier"] == 1.8)

    # case 2：单元级 5.0 覆盖。上限 10×1.2×1.5×5=90，倍数 9（>4 红色预警）
    c2 = coef(KW_ADG_RATIO)
    check("case2 source=adgroup", c2["mobile"]["source"] == "adgroup", str(c2["mobile"]))
    check("case2 ratio=5.0", c2["mobile"]["ratio"] == 5.0)
    check("case2 区间", (c2["effective"]["current_min"], c2["effective"]["current_max"]) == (10.8, 90.0),
          str(c2["effective"]))
    check("case2 max_multiplier=9.0", c2["effective"]["max_multiplier"] == 9.0)

    # case 3：两级都没有（单元 -1=继承、计划 None）→ 缺层按 1.0
    c3 = coef(KW_NO_RATIO)
    check("case3 ratio=None", c3["mobile"]["ratio"] is None, str(c3["mobile"]))
    check("case3 missing_layers 含移动比例", c3["missing_layers"] == ["移动比例"])
    check("case3 区间不受影响", (c3["effective"]["current_min"], c3["effective"]["current_max"]) == (10.8, 18.0),
          str(c3["effective"]))

    # case 4：计划级 0（仅 PC，单元 -1 继承）→ ratio=0 透传、不算缺层、区间不受影响
    c4 = coef(KW_PC_ONLY)
    check("case4 ratio=0 source=campaign", c4["mobile"] == {"ratio": 0.0, "source": "campaign"}, str(c4["mobile"]))
    check("case4 missing_layers 空", c4["missing_layers"] == [])
    check("case4 区间不受影响", (c4["effective"]["current_min"], c4["effective"]["current_max"]) == (10.8, 18.0),
          str(c4["effective"]))

print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
