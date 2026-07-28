"""月度分析报告冒烟（AI 应用路线 ③）：数据聚合 + AI 叙述缓存/降级 + 接口。

覆盖：KPI+月环比、投放天数、分类报告、TOP消费词、设备分布、异常处置、本月操作统计；
AI 叙述生成+缓存（命中不重调）、force 重算、未配 key 降级（数据照出叙述空）、接口 + available-months。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_monthly_report.py
"""
import asyncio
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import delete, select

from app.ai.deepseek import DeepSeekError
from app.ai.monthly_report import gather_report_data, get_monthly_report
from app.database import async_session_factory, engine
from app.models import (
    Alert,
    BaiduAccount,
    Keyword,
    KwReportSnapshot,
    MonthlyReport,
    OperationRecord,
    Suggestion,
    Tenant,
)
from app.security.crypto import encrypt

failed = False


def check(label: str, cond: bool, detail: str = "") -> None:
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


FAKE_NARRATIVE = {
    "summary": "5 月投放平稳，消费环比上升，重点词占比健康。",
    "module_comments": {
        "overview": "消费环比 +125%，需关注预算节奏。",
        "by_category": "重点词主导消费，结构合理。",
        "top_keywords": "头部集中在多级泵，建议关注转化。",
        "device": "PC 为主，移动占比近三成。",
        "alerts": "异常处置及时。",
        "operations": "本月操作克制，1 次超上限需复盘。",
    },
    "next_month_plan": ["优化移动端落地页", "复盘超上限调价", "扩展重点词长尾"],
}


async def fake_chat_json(system: str, user: str, timeout: float = 30.0) -> dict:
    return dict(FAKE_NARRATIVE)


def snap(tenant_id, acc_id, d, kw_id, kw, device, cost, click, imp, rank):
    return KwReportSnapshot(
        tenant_id=tenant_id, baidu_account_id=acc_id, report_date=d,
        keyword_id=kw_id, keyword=kw, device=device,
        cost=Decimal(str(cost)), click=click, impression=imp,
        avg_rank=Decimal(str(rank)), fetched_at=datetime.utcnow(),
    )


async def main() -> None:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "月报冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="月报冒烟租户", strategy="lead", monthly_budget=10000)
            session.add(tenant)
            await session.flush()
        acc = await session.scalar(select(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id))
        if acc is None:
            acc = BaiduAccount(
                tenant_id=tenant.id, baidu_username="月报冒烟账户", baidu_ucid=99999993,
                access_token_encrypted=encrypt("fake"), expires_at=datetime(2026, 9, 1),
                auth_mode="self", status="active",
            )
            session.add(acc)
            await session.flush()
        tid = tenant.id
        # 清旧数据
        for M in (KwReportSnapshot, Keyword, Alert, OperationRecord, Suggestion, MonthlyReport):
            await session.execute(delete(M).where(M.tenant_id == tid))

        # keywords（分类 join 用）
        session.add_all([
            Keyword(tenant_id=tid, baidu_account_id=acc.id, keyword_id=1, keyword="多级离心泵", category="focus"),
            Keyword(tenant_id=tid, baidu_account_id=acc.id, keyword_id=2, keyword="泵阀", category="normal"),
        ])
        # 5 月快照：kw1 PC+移动，kw2 PC；4 月快照（环比）
        session.add_all([
            snap(tid, acc.id, date(2026, 5, 10), 1, "多级离心泵", 0, 100, 10, 200, 2.0),
            snap(tid, acc.id, date(2026, 5, 10), 1, "多级离心泵", 1, 50, 8, 300, 3.0),
            snap(tid, acc.id, date(2026, 5, 11), 2, "泵阀", 0, 30, 3, 100, 1.5),
            snap(tid, acc.id, date(2026, 4, 15), 1, "多级离心泵", 0, 80, 5, 100, 2.0),
        ])
        # 异常 / 操作 / 建议
        session.add_all([
            Alert(tenant_id=tid, rule_code="R-14", priority="P0", title="t", message="m",
                  report_date=date(2026, 5, 12), status="resolved"),
            Alert(tenant_id=tid, rule_code="R-02", priority="P1", title="t", message="m",
                  report_date=date(2026, 5, 13), status="open"),
            OperationRecord(tenant_id=tid, opt_time=datetime(2026, 5, 5), opt_level=5,
                            old_value="1.00", new_value="2.00", dedup_key="smoke-op-1"),
            Suggestion(tenant_id=tid, rule_code="R-01", suggestion_type="raise", priority="P2",
                       confidence="high", reason="r", report_date=date(2026, 5, 6),
                       status="adopted", adopted_at=datetime(2026, 5, 6)),
        ])
        await session.commit()

        # ===== 数据聚合 =====
        d = await gather_report_data(session, tenant, 2026, 5)
        check("KPI 消费 180", d["kpi"]["cost"]["current"] == 180.0, str(d["kpi"]["cost"]["current"]))
        check("月环比 +125%", d["kpi"]["cost"]["change_pct"] == 125.0, str(d["kpi"]["cost"]["change_pct"]))
        check("投放天数 2", d["period"]["active_days"] == 2, str(d["period"]["active_days"]))
        check("预算耗用 1.8%", d["budget"]["usage_pct"] == 1.8, str(d["budget"]["usage_pct"]))
        cat = {c["category"]: c for c in d["by_category"]}
        check("分类 focus 150 / normal 30",
              cat["focus"]["cost"] == 150.0 and cat["normal"]["cost"] == 30.0,
              f"{cat['focus']['cost']}/{cat['normal']['cost']}")
        check("分类按消费降序（focus 首）", d["by_category"][0]["category"] == "focus")
        check("TOP 词首位多级离心泵 150",
              d["top_keywords"][0]["keyword"] == "多级离心泵" and d["top_keywords"][0]["cost"] == 150.0)
        dev = {x["device"]: x for x in d["device_split"]}
        check("设备 PC 130 / 移动 50", dev["PC"]["cost"] == 130.0 and dev["移动"]["cost"] == 50.0,
              f"{dev['PC']['cost']}/{dev['移动']['cost']}")
        check("PC 占比 72.2%", dev["PC"]["cost_share_pct"] == 72.2, str(dev["PC"]["cost_share_pct"]))
        check("异常 open1 resolved1",
              d["alerts_review"].get("open") == 1 and d["alerts_review"].get("resolved") == 1,
              str(d["alerts_review"]))
        op = d["operations"]
        check("操作 总1 超限1 关键词级1 AI采纳1",
              op["total"] == 1 and op["over_limit"] == 1 and op["by_level"].get("关键词") == 1
              and op["ai_suggestions_adopted"] == 1, str(op))
        check("待接入模块占位完整", set(d["pending_modules"]) == {"conversion", "hourly", "region", "competitor"})
        # 趋势补满整月（5 月 31 天），仅 2 天有消费（05-10/05-11）
        check("日趋势补满整月 31 天", len(d["trend"]) == 31, str(len(d["trend"])))
        check("趋势仅 2 天有消费", sum(1 for t in d["trend"] if t["cost"] > 0) == 2,
              str(sum(1 for t in d["trend"] if t["cost"] > 0)))

        # ===== AI 叙述生成 + 缓存 =====
        with patch("app.ai.monthly_report.is_enabled", lambda: True), \
             patch("app.ai.monthly_report.chat_json", fake_chat_json):
            r1 = await get_monthly_report(session, tenant, 2026, 5)
        check("AI 叙述生成", r1["narrative"]["summary"].startswith("5 月投放平稳"))
        check("模块点评回填", r1["narrative"]["module_comments"].get("overview", "").startswith("消费环比"))
        check("下月计划 3 条", len(r1["narrative"]["next_month_plan"]) == 3)
        check("ai_enabled True", r1["ai_enabled"] is True)
        cached = await session.scalar(select(MonthlyReport).where(
            MonthlyReport.tenant_id == tid, MonthlyReport.year == 2026, MonthlyReport.month == 5))
        check("叙述落库缓存", cached is not None and cached.summary.startswith("5 月"))

        # 缓存命中：即便 AI 会抛错也用缓存（不重调）
        async def boom(system, user, timeout=30.0):
            raise DeepSeekError("不该被调用")

        with patch("app.ai.monthly_report.is_enabled", lambda: True), \
             patch("app.ai.monthly_report.chat_json", boom):
            r2 = await get_monthly_report(session, tenant, 2026, 5)
        check("缓存命中不重调 AI", r2["narrative"]["summary"].startswith("5 月投放平稳"))

        # force 重算（mock 恢复正常）
        with patch("app.ai.monthly_report.is_enabled", lambda: True), \
             patch("app.ai.monthly_report.chat_json", fake_chat_json):
            r3 = await get_monthly_report(session, tenant, 2026, 5, force=True)
        check("force 重算成功", r3["narrative"] is not None and r3["generated_at"] is not None)

        # ===== 降级：未配 key → 数据在、叙述空 =====
        await session.execute(delete(MonthlyReport).where(MonthlyReport.tenant_id == tid))
        await session.commit()
        with patch("app.ai.monthly_report.is_enabled", lambda: False):
            r4 = await get_monthly_report(session, tenant, 2026, 5)
        check("未配 key 数据仍在", r4["data"]["kpi"]["cost"]["current"] == 180.0)
        check("未配 key 叙述空 + ai_enabled False",
              r4["narrative"] is None and r4["ai_enabled"] is False)
    await engine.dispose()

    # ===== 接口 =====
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    auth = {"X-API-Key": get_settings().admin_api_key}
    with patch("app.ai.monthly_report.is_enabled", lambda: True), \
         patch("app.ai.monthly_report.chat_json", fake_chat_json), \
         TestClient(app) as client:
        r = client.get("/api/v1/reports/monthly",
                       params={"tenant_id": tid, "year": 2026, "month": 5}, headers=auth)
        check("月报接口 200", r.status_code == 200, r.text[:120])
        body = r.json()
        check("接口含数据 + 叙述",
              body["data"]["kpi"]["cost"]["current"] == 180.0 and body["narrative"]["summary"],
              str(body.get("generated_at")))

        r = client.get("/api/v1/reports/monthly/available-months",
                       params={"tenant_id": tid}, headers=auth)
        am = r.json()
        check("可用月份含 2026-5 / 2026-4",
              any(m["year"] == 2026 and m["month"] == 5 for m in am["months"])
              and any(m["month"] == 4 for m in am["months"]), str([m["label"] for m in am["months"]]))
        check("默认月 2026-5（最近有消费）",
              am["default"]["year"] == 2026 and am["default"]["month"] == 5, str(am["default"]))

        r = client.get("/api/v1/reports/monthly",
                       params={"tenant_id": tid + 99999, "year": 2026, "month": 5}, headers=auth)
        check("跨租户 404", r.status_code == 404)


asyncio.run(main())
print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
