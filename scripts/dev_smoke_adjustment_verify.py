"""待验证调价冒烟：近7天出价调整筛选 + 调前/后效果 + AI研判缓存 + 标记验证 + 接口。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_adjustment_verify.py
"""
import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import delete, select

from app.ai.adjustment_verify import build_one, generate_verdict, list_pending
from app.database import async_session_factory, engine
from app.models import AdjustmentReview, Keyword, KwReportSnapshot, OperationRecord, Tenant

failed = False


def check(label, cond, detail=""):
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


async def fake_chat_json(system, user, timeout=30.0):
    return {"verdict": "achieved", "reason": "加价后排名前移、点击上升，达成抢量目的"}


async def main():
    today = date.today()
    async with async_session_factory() as s:
        t = await s.scalar(select(Tenant).where(Tenant.name == "验证冒烟租户"))
        if t is None:
            t = Tenant(name="验证冒烟租户", monthly_budget=Decimal("10000"))
            s.add(t)
            await s.flush()
        tid = t.id
        for M in (Keyword, KwReportSnapshot, OperationRecord, AdjustmentReview):
            await s.execute(delete(M).where(M.tenant_id == tid))
        s.add(Keyword(tenant_id=tid, keyword_id=1, keyword="多级泵", total_impression=999, pause=False))

        # 调价记录：A=近3天出价(+30%超限,加价)；B=10天前出价(降价,出7天外)；C=近期但非出价(排除)
        s.add_all([
            OperationRecord(tenant_id=tid, opt_time=datetime.utcnow() - timedelta(days=3), opt_level=5,
                            opt_content="bidPriceWord", opt_obj="多级泵", old_value="5.00", new_value="6.50", dedup_key="av1"),
            OperationRecord(tenant_id=tid, opt_time=datetime.utcnow() - timedelta(days=10), opt_level=5,
                            opt_content="bidPriceWord", opt_obj="多级泵", old_value="8.00", new_value="7.00", dedup_key="av2"),
            OperationRecord(tenant_id=tid, opt_time=datetime.utcnow() - timedelta(days=2), opt_level=5,
                            opt_content="shelveWord", opt_obj="多级泵", old_value="启用", new_value="暂停", dedup_key="av3"),
        ])

        def snap(d, rank, cost, click, imp):
            return KwReportSnapshot(tenant_id=tid, report_date=d, keyword_id=1, device=0,
                                    cost=Decimal(str(cost)), click=click, impression=imp,
                                    avg_rank=Decimal(str(rank)), fetched_at=datetime.utcnow())
        # A 的调价日=today-3。调价前[today-10..today-4]：today-6/today-5；调价后[today-3..latest]：today-2/today-1
        s.add_all([
            snap(today - timedelta(days=6), 5.0, 100, 10, 200),
            snap(today - timedelta(days=5), 4.0, 80, 8, 150),
            snap(today - timedelta(days=2), 2.0, 120, 15, 250),
            snap(today - timedelta(days=1), 1.5, 130, 18, 280),
        ])
        await s.commit()

        # ===== 7 天筛选 =====
        items7 = await list_pending(s, t, days=7)
        check("近7天只 1 条出价调整（排除7天外+非出价）", len(items7) == 1 and items7[0]["dedup_key"] == "av1",
              str([(i["dedup_key"], i["keyword"]) for i in items7]))
        a = items7[0]
        check("方向=加价 +30% 超限", a["direction"] == "raise" and a["change_pct"] == 30.0 and a["over_limit"] is True,
              f"{a['direction']}/{a['change_pct']}/{a['over_limit']}")
        check("关键词解析到 id", a["keyword_id"] == 1)
        check("调前效果 avg_rank=4.5", a["effect"]["before"] and a["effect"]["before"]["avg_rank"] == 4.5,
              str(a["effect"]["before"]))
        check("调后效果 avg_rank=1.75 / 2天", a["effect"]["after"] and a["effect"]["after"]["avg_rank"] == 1.75
              and a["effect"]["after"]["days"] == 2, str(a["effect"]["after"]))

        items14 = await list_pending(s, t, days=14)
        check("近14天含降价那条", len(items14) == 2 and any(i["dedup_key"] == "av2" and i["direction"] == "lower" for i in items14),
              str([(i["dedup_key"], i["direction"]) for i in items14]))

        # ===== AI 研判 + 缓存 =====
        with patch("app.ai.adjustment_verify.is_enabled", lambda: True), \
             patch("app.ai.adjustment_verify.chat_json", fake_chat_json):
            v = await generate_verdict(s, t, a)
        check("AI 研判 achieved", v and v["verdict"] == "achieved", str(v))
        rv = await s.scalar(select(AdjustmentReview).where(AdjustmentReview.tenant_id == tid, AdjustmentReview.dedup_key == "av1"))
        check("研判落库缓存", rv and rv.ai_verdict == "achieved")

        from app.ai.deepseek import DeepSeekError
        async def boom(system, user, timeout=30.0):
            raise DeepSeekError("不该被调用")
        with patch("app.ai.adjustment_verify.is_enabled", lambda: True), \
             patch("app.ai.adjustment_verify.chat_json", boom):
            v2 = await generate_verdict(s, t, a)
        check("缓存命中不重调 AI", v2["verdict"] == "achieved")

        with patch("app.ai.adjustment_verify.is_enabled", lambda: False):
            v3 = await generate_verdict(s, t, a, force=True)
        check("未配 key 返回 None", v3 is None)

        check("build_one 含效果", (await build_one(s, t, "av1"))["effect"]["before"]["avg_rank"] == 4.5)
    await engine.dispose()

    # ===== 接口 =====
    from fastapi.testclient import TestClient
    from app.config import get_settings
    from app.main import app

    auth = {"X-API-Key": get_settings().admin_api_key}
    with patch("app.ai.adjustment_verify.is_enabled", lambda: True), \
         patch("app.ai.adjustment_verify.chat_json", fake_chat_json), \
         patch("app.api.adjustments_verify.ai_enabled", lambda: True), \
         TestClient(app) as client:
        r = client.get("/api/v1/adjustment-verify", params={"tenant_id": tid, "days": 7}, headers=auth)
        b = r.json()
        check("接口 200 + 1 条 + summary", r.status_code == 200 and b["summary"]["total"] == 1
              and b["summary"]["pending"] == 1, r.text[:100])

        r = client.post("/api/v1/adjustment-verify/av1/ai", params={"tenant_id": tid}, headers=auth)
        check("AI 端点 200 + achieved", r.status_code == 200 and r.json()["ai"]["verdict"] == "achieved")

        r = client.patch("/api/v1/adjustment-verify/av1", params={"tenant_id": tid},
                         json={"verdict": "achieved", "note": "复盘OK"}, headers=auth)
        check("标记已验证 200", r.status_code == 200 and r.json()["review_status"] == "verified")
        b2 = client.get("/api/v1/adjustment-verify", params={"tenant_id": tid, "days": 7}, headers=auth).json()
        check("已验证计数 +1", b2["summary"]["verified"] == 1 and b2["items"][0]["review"]["verdict"] == "achieved")

        r = client.patch("/api/v1/adjustment-verify/av1", params={"tenant_id": tid}, json={"reopen": True}, headers=auth)
        check("改回待验证", r.status_code == 200 and r.json()["review_status"] == "pending")

        r = client.patch("/api/v1/adjustment-verify/av1", params={"tenant_id": tid}, json={"verdict": "bogus"}, headers=auth)
        check("非法判定 400", r.status_code == 400)

        r = client.get("/api/v1/adjustment-verify", params={"tenant_id": tid + 99999, "days": 7}, headers=auth)
        check("跨租户 404", r.status_code == 404)


asyncio.run(main())
print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
