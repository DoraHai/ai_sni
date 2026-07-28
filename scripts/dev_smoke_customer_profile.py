"""客户画像冒烟：6 维聚合 + brief + AI 总结缓存/降级 + 接口 GET/PATCH。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_customer_profile.py
"""
import asyncio
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import delete, select

from app.ai.customer_profile import build_customer_brief, gather_profile, generate_summary, profile_brief
from app.ai.deepseek import DeepSeekError
from app.database import async_session_factory, engine
from app.models import Adgroup, Campaign, Keyword, KwReportSnapshot, OperationRecord, Suggestion, Tenant

failed = False


def check(label, cond, detail=""):
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


async def fake_chat_json(system, user, timeout=30.0):
    return {"summary": "该客户偏工业泵场景、出价略高于指导价、移动占比适中，建议关注质量度。"}


async def main():
    async with async_session_factory() as s:
        t = await s.scalar(select(Tenant).where(Tenant.name == "画像冒烟租户"))
        if t is None:
            t = Tenant(name="画像冒烟租户", strategy="lead", monthly_budget=Decimal("10000"), brand_terms=["冒烟泵"])
            s.add(t)
            await s.flush()
        t.industry = "工业泵"
        t.business_desc = None
        t.profile_summary = None
        t.profile_generated_at = None
        tid = t.id
        for M in (Keyword, KwReportSnapshot, Campaign, Adgroup, OperationRecord, Suggestion):
            await s.execute(delete(M).where(M.tenant_id == tid))

        # keywords：3 词，含出价/指导价/质量度
        s.add_all([
            Keyword(tenant_id=tid, keyword_id=1, keyword="多级泵", category="focus", price=Decimal("10"), left_price_guide=Decimal("8"), quality=7, pause=False),
            Keyword(tenant_id=tid, keyword_id=2, keyword="泵阀", category="normal", price=Decimal("5"), left_price_guide=Decimal("6"), quality=5, pause=False),
            Keyword(tenant_id=tid, keyword_id=3, keyword="新词", category="new", price=Decimal("3"), quality=None, pause=False),
        ])
        s.add_all([
            Campaign(tenant_id=tid, campaign_id=901, campaign_name="C1"),
            Campaign(tenant_id=tid, campaign_id=902, campaign_name="C2"),
            Adgroup(tenant_id=tid, adgroup_id=801, adgroup_name="U1", campaign_id=901),
            Adgroup(tenant_id=tid, adgroup_id=802, adgroup_name="U2", campaign_id=901),
            Adgroup(tenant_id=tid, adgroup_id=803, adgroup_name="U3", campaign_id=902),
        ])
        # 近 30 天快照：PC 100 / 移动 50
        today = date.today()
        def snap(kw, dev, cost, click, imp, rank):
            return KwReportSnapshot(tenant_id=tid, report_date=today, keyword_id=kw, device=dev,
                                    cost=Decimal(str(cost)), click=click, impression=imp,
                                    avg_rank=Decimal(str(rank)), fetched_at=datetime.utcnow())
        s.add_all([snap(1, 0, 100, 10, 200, 2.0), snap(1, 1, 50, 5, 300, 3.0)])
        # 调价记录：+50%(超限,加价) / -5%(降价)
        s.add_all([
            OperationRecord(tenant_id=tid, opt_time=datetime.utcnow(), opt_level=5, old_value="1.00", new_value="1.50", dedup_key="cp1"),
            OperationRecord(tenant_id=tid, opt_time=datetime.utcnow(), opt_level=5, old_value="2.00", new_value="1.90", dedup_key="cp2"),
        ])
        # 建议采纳：adopted×2 / ignored×1 / pending×1
        for i, st in enumerate(["adopted", "adopted", "ignored", "pending"]):
            s.add(Suggestion(tenant_id=tid, rule_code="R", suggestion_type="raise", priority="P2",
                             confidence="high", reason="r", report_date=today, status=st, keyword_id=100 + i))
        await s.commit()

        # ===== 聚合 =====
        p = await gather_profile(s, t)
        check("基础：行业/预算", p["basics"]["industry"] == "工业泵" and p["basics"]["monthly_budget"] == 10000.0)
        check("结构：3词2计划3单元",
              p["structure"]["keywords"] == 3 and p["structure"]["campaigns"] == 2 and p["structure"]["adgroups"] == 3,
              str((p["structure"]["keywords"], p["structure"]["campaigns"], p["structure"]["adgroups"])))
        check("分级分布 focus/normal/new", {c["category"] for c in p["structure"]["category_dist"]} == {"focus", "normal", "new"})
        bh = p["bid_habits"]
        check("出价 vs 指导价 +0.5 / 高于占比 50%", bh["avg_diff_vs_guide"] == 0.5 and bh["above_guide_pct"] == 50.0, str(bh))
        check("分级均价 focus=10", any(a["label"] == "重点词" and a["avg_price"] == 10.0 for a in bh["avg_price_by_category"]))
        perf = p["performance"]
        check("效果 cpc=10 排名2.5", perf["kpi"]["cpc"] == 10.0 and perf["kpi"]["avg_rank"] == 2.5, str(perf["kpi"]))
        dev = {d["device"]: d["cost_share_pct"] for d in perf["device_split"]}
        check("设备占比 PC66.7/移动33.3", dev.get("PC") == 66.7 and dev.get("移动") == 33.3, str(dev))
        check("平均质量度 6.0", perf["avg_quality"] == 6.0, str(perf["avg_quality"]))
        adj = p["adjust_behavior"]
        check("调价 总2/均27.5/超1/加1降1",
              adj["total"] == 2 and adj["avg_abs_pct"] == 27.5 and adj["over_limit"] == 1
              and adj["raise_count"] == 1 and adj["lower_count"] == 1, str(adj))
        check("采纳率 66.7%", p["adoption"]["adopt_rate_pct"] == 66.7, str(p["adoption"]))

        # ===== brief =====
        brief = profile_brief(p)
        check("brief 含行业/词数/采纳率", "工业泵" in brief and "3 词" in brief and "采纳率 66.7%" in brief, brief[:80])

        # ===== AI 总结 + 缓存 =====
        with patch("app.ai.customer_profile.is_enabled", lambda: True), \
             patch("app.ai.customer_profile.chat_json", fake_chat_json):
            sm = await generate_summary(s, t, p)
        check("AI 总结生成", sm and sm.startswith("该客户偏工业泵"))
        check("总结落库缓存", t.profile_summary == sm and t.profile_generated_at is not None)

        async def boom(system, user, timeout=30.0):
            raise DeepSeekError("不该被调用")
        with patch("app.ai.customer_profile.is_enabled", lambda: True), \
             patch("app.ai.customer_profile.chat_json", boom):
            sm2 = await generate_summary(s, t, p)
        check("缓存命中不重调 AI", sm2 == sm)

        # 未配 key 降级
        with patch("app.ai.customer_profile.is_enabled", lambda: False):
            sm3 = await generate_summary(s, t, p, force=True)
        check("未配 key 返回 None", sm3 is None)

        # build_customer_brief（喂调价建议）
        cb = await build_customer_brief(s, t)
        check("build_customer_brief 含客户名", "画像冒烟租户" in cb)
    await engine.dispose()

    # ===== 接口 =====
    from fastapi.testclient import TestClient
    from app.config import get_settings
    from app.main import app

    auth = {"X-API-Key": get_settings().admin_api_key}
    with patch("app.ai.customer_profile.is_enabled", lambda: True), \
         patch("app.ai.customer_profile.chat_json", fake_chat_json), \
         patch("app.api.customer_profile.ai_enabled", lambda: True), \
         TestClient(app) as client:
        r = client.get("/api/v1/customer-profile", params={"tenant_id": tid}, headers=auth)
        check("接口 200 + 含 profile/summary", r.status_code == 200 and r.json()["profile"]["structure"]["keywords"] == 3
              and r.json()["summary"], r.text[:80])
        check("接口 ai_enabled True", r.json()["ai_enabled"] is True)

        # PATCH 改行业/业务 → 清总结缓存
        r = client.patch("/api/v1/customer-profile", params={"tenant_id": tid},
                         json={"industry": "工业泵 / 分离技术", "business_desc": "高端工业泵代运营"}, headers=auth)
        check("PATCH 200", r.status_code == 200)
        r2 = client.get("/api/v1/customer-profile", params={"tenant_id": tid}, headers=auth)
        check("改后行业更新", r2.json()["profile"]["basics"]["industry"] == "工业泵 / 分离技术")
        check("改后业务描述更新", r2.json()["profile"]["basics"]["business_desc"] == "高端工业泵代运营")

        r = client.get("/api/v1/customer-profile", params={"tenant_id": tid + 99999}, headers=auth)
        check("跨租户 404", r.status_code == 404)


asyncio.run(main())
print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
