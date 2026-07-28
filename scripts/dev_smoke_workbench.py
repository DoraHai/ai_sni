"""关键词工作台接口冒烟：列表（分页/筛选/排序/7 天指标/系数预警）+ 批量改分级。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_workbench.py
"""
import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.database import async_session_factory, engine
from app.models import (
    Adgroup,
    BaiduAccount,
    Campaign,
    Keyword,
    KwReportSnapshot,
    Tenant,
)
from app.security.crypto import encrypt

CAMP_NORMAL, CAMP_HOT = 9101, 9102  # HOT：时段 2.0 × 地域 1.5 × 移动 2.0 = 6.0 红色
CAMP_SLOT, CAMP_PAUSED = 9103, 9104  # SLOT：只投非当前时段；PAUSED：计划暂停
ADG_NORMAL, ADG_HOT = 9201, 9202
ADG_PAUSED, ADG_SLOT, ADG_IN_PAUSED = 9203, 9204, 9205

# serving 判定按北京时间当前 timeId（跨整点瞬间跑可能差 1 小时，重跑即可）
_now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))
TIME_ID_NOW = _now_cn.isoweekday() * 100 + _now_cn.hour
TIME_ID_OTHER = _now_cn.isoweekday() * 100 + (_now_cn.hour + 2) % 24


async def seed() -> int:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "工作台冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="工作台冒烟租户", strategy="lead", monthly_budget=10000)
            session.add(tenant)
            await session.flush()
        if await session.scalar(
            select(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id)
        ) is None:
            session.add(
                BaiduAccount(
                    tenant_id=tenant.id,
                    baidu_username="工作台冒烟账户",
                    baidu_ucid=99999997,
                    access_token_encrypted=encrypt("fake-token"),
                    expires_at=datetime(2026, 9, 1),
                    auth_mode="self",
                    status="active",
                )
            )
        for model in (KwReportSnapshot, Keyword, Campaign, Adgroup):
            await session.execute(delete(model).where(model.tenant_id == tenant.id))

        session.add_all(
            [
                Campaign(
                    tenant_id=tenant.id, campaign_id=CAMP_NORMAL, campaign_name="普通计划",
                    schedule_price_factors=[{"timeId": TIME_ID_NOW, "priceFactor": 1.0}],
                    region_price_factor=[{"regionId": 1, "priceFactor": 1.0}],
                ),
                Campaign(
                    tenant_id=tenant.id, campaign_id=CAMP_HOT, campaign_name="高系数计划",
                    schedule_price_factors=[{"timeId": TIME_ID_NOW, "priceFactor": 2.0}],
                    region_price_factor=[{"regionId": 1, "priceFactor": 1.5}],
                ),
                Campaign(
                    tenant_id=tenant.id, campaign_id=CAMP_SLOT, campaign_name="非当前时段计划",
                    schedule_price_factors=[{"timeId": TIME_ID_OTHER, "priceFactor": 1.0}],
                ),
                Campaign(
                    tenant_id=tenant.id, campaign_id=CAMP_PAUSED, campaign_name="暂停计划",
                    pause=True,
                ),
                Adgroup(tenant_id=tenant.id, adgroup_id=ADG_NORMAL, campaign_id=CAMP_NORMAL,
                        adgroup_name="普通单元"),
                Adgroup(tenant_id=tenant.id, adgroup_id=ADG_HOT, campaign_id=CAMP_HOT,
                        adgroup_name="高系数单元", price_ratio=2.0),
                Adgroup(tenant_id=tenant.id, adgroup_id=ADG_PAUSED, campaign_id=CAMP_NORMAL,
                        adgroup_name="暂停单元", pause=True),
                Adgroup(tenant_id=tenant.id, adgroup_id=ADG_SLOT, campaign_id=CAMP_SLOT,
                        adgroup_name="非当前时段单元"),
                Adgroup(tenant_id=tenant.id, adgroup_id=ADG_IN_PAUSED, campaign_id=CAMP_PAUSED,
                        adgroup_name="暂停计划内单元"),
            ]
        )

        # 关键词：品牌×1（高系数计划）、一般×2（其中 1 个暂停）、新词×1
        # + serving 三种未投场景：单元暂停 / 计划非当前时段 / 计划暂停
        kws = [
            # (kw_id, text, camp, adg, category, price, pause, impressions)
            (63001, "工作台冒烟租户 官网", CAMP_HOT, ADG_HOT, "brand", 20.0, False, 900),
            (63002, "离心泵 价格", CAMP_NORMAL, ADG_NORMAL, "normal", 8.0, False, 500),
            (63003, "离心泵 维修", CAMP_NORMAL, ADG_NORMAL, "normal", 6.0, True, 300),
            (63004, "磁力泵 翻新", CAMP_NORMAL, ADG_NORMAL, "new", 4.0, False, 10),
            (63005, "单元暂停词", CAMP_NORMAL, ADG_PAUSED, "new", 3.0, False, 8),
            (63006, "时段外词", CAMP_SLOT, ADG_SLOT, "new", 3.0, False, 6),
            (63007, "计划暂停词", CAMP_PAUSED, ADG_IN_PAUSED, "new", 3.0, False, 4),
        ]
        for kw_id, text, camp, adg, cat, price, pause, imp in kws:
            session.add(
                Keyword(
                    tenant_id=tenant.id, keyword_id=kw_id, keyword=text,
                    campaign_id=camp, adgroup_id=adg, match_type=48,
                    price=price, pause=pause, quality=7,
                    total_impression=imp, category=cat, category_source="auto",
                )
            )

        # 快照：63001/63002 最近 3 天有数据（落在 7 天窗口），63002 点击更高
        today = date.today()
        for offset in range(3):
            d = today - timedelta(days=offset + 1)
            for kw_id, camp, adg, click, cost in (
                (63001, CAMP_HOT, ADG_HOT, 10, 100.0),
                (63002, CAMP_NORMAL, ADG_NORMAL, 30, 90.0),
            ):
                session.add(
                    KwReportSnapshot(
                        tenant_id=tenant.id, report_date=d,
                        campaign_id=camp, adgroup_id=adg, keyword_id=kw_id,
                        device=1, impression=200, click=click, cost=cost,
                        avg_rank=1.4, fetched_at=datetime.utcnow(),
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
    def fetch(**params) -> dict:
        r = client.get("/api/v1/keywords", params={"tenant_id": tenant_id, **params}, headers=auth)
        assert r.status_code == 200, r.text
        return r.json()

    # 基础：总数 / 分页 / totals
    b = fetch(page_size=2)
    check("总数 7", b["total"] == 7, str(b["total"]))
    check("分页 2 条", len(b["keywords"]) == 2)
    check(
        "totals",
        {k: b["totals"][k] for k in ("campaigns", "adgroups", "keywords")}
        == {"campaigns": 4, "adgroups": 5, "keywords": 7},
        str(b["totals"]),
    )
    check("分类计数", b["category_counts"].get("normal") == 2 and b["category_counts"].get("brand") == 1)
    check("计划下拉 4 项", len(b["campaign_options"]) == 4)
    check("默认按累计展现降序", b["keywords"][0]["keyword_id"] == 63001)

    # 7 天指标 + 系数
    row = b["keywords"][0]  # 63001 高系数：2.0×1.5×2.0=6.0 红
    check("7天点击 30", row["metrics_7d"]["click"] == 30, str(row["metrics_7d"]))
    check("CPC 10", row["metrics_7d"]["cpc"] == 10.0)
    check("峰值系数 6.0 红", row["effective"]["multiplier"] == 6.0 and row["effective"]["warning"] == "red",
          str(row["effective"]))
    check("生效出价 120", row["effective"]["price"] == 120.0)

    # 筛选
    check("分级筛选", fetch(category="normal")["total"] == 2)
    check("计划筛选", fetch(campaign_id=CAMP_HOT)["total"] == 1)
    check("暂停筛选", fetch(pause=True)["total"] == 1)
    check("搜索", fetch(q="维修")["total"] == 1)
    red = fetch(coef_warning="red")
    check("红色预警筛选", red["total"] == 1 and red["keywords"][0]["keyword_id"] == 63001, str(red["total"]))
    check("正常档筛选", fetch(coef_warning="normal")["total"] == 6)

    # ===== 当前时间是否投放（词/单元/计划暂停 + 计划分时段） =====
    check("totals 当前在投 3 + 时段标签", b["totals"]["serving_now"] == 3
          and bool(b["totals"]["current_slot"]), str(b["totals"]))
    check("首行投放中", b["keywords"][0]["serving"] == {"now": True, "reason": "投放中"})
    sv_on = fetch(serving=True)
    check("在投筛选 3 条", sv_on["total"] == 3
          and {k["keyword_id"] for k in sv_on["keywords"]} == {63001, 63002, 63004},
          str([k["keyword_id"] for k in sv_on["keywords"]]))
    sv_off = fetch(serving=False)
    reasons = {k["keyword_id"]: k["serving"]["reason"] for k in sv_off["keywords"]}
    check("未投筛选 4 条", sv_off["total"] == 4, str(reasons))
    check("未投原因正确", reasons.get(63003) == "关键词已暂停"
          and reasons.get(63005) == "单元已暂停"
          and reasons.get(63006) == "当前时段不投放"
          and reasons.get(63007) == "计划已暂停", str(reasons))

    # 排序：7 天点击降序 → 63002 第一
    s = fetch(sort_by="clicks_7d", order="desc")
    check("按 7 天点击排序", s["keywords"][0]["keyword_id"] == 63002, str([k["keyword_id"] for k in s["keywords"]]))

    # 批量改分级 → manual；再恢复 auto
    r = client.post("/api/v1/keywords/batch-category",
                    json={"tenant_id": tenant_id, "keyword_ids": [63002, 63003, 99999], "category": "longtail"},
                    headers=auth)
    check("批量标长尾", r.status_code == 200 and r.json()["updated"] == 2 and r.json()["missing"] == [99999],
          r.text[:120])
    after = fetch(category="longtail")
    check("批量后 longtail=2 且人工", after["total"] == 2
          and all(k["category"]["source"] == "manual" for k in after["keywords"]))
    r2 = client.post("/api/v1/keywords/batch-category",
                     json={"tenant_id": tenant_id, "keyword_ids": [63002, 63003], "category": "auto"},
                     headers=auth)
    check("批量恢复自动", r2.status_code == 200 and r2.json()["updated"] == 2)
    check("恢复后 normal=2", fetch(category="normal")["total"] == 2)

    # 非法分级 400
    rbad = client.post("/api/v1/keywords/batch-category",
                       json={"tenant_id": tenant_id, "keyword_ids": [63002], "category": "vip"}, headers=auth)
    check("非法分级 400", rbad.status_code == 400)

print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
