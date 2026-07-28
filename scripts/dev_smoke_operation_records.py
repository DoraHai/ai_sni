"""调价台账本地冒烟：同步幂等（mock 百度返回）+ 台账接口（筛选/统计/超 20% 标记）。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_operation_records.py
"""
import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import delete, func, select

from app.baidu.sync import _parse_opt_time, sync_operation_records_for_account
from app.database import async_session_factory, engine
from app.models import BaiduAccount, Keyword, OperationRecord, Tenant
from app.security.crypto import encrypt

failed = False


def check(label: str, cond: bool, detail: str = "") -> None:
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


# ===== 纯函数：optTime 解析 =====
check("英文格式解析", _parse_opt_time("Sep 2, 2021 11:54:00 PM") == datetime(2021, 9, 2, 23, 54))
check("ISO 格式解析", _parse_opt_time("2026-06-10 09:30:00") == datetime(2026, 6, 10, 9, 30))
check("非法值返回 None", _parse_opt_time("garbage") is None)

FAKE_RECORDS = [
    # 关键词出价 +12%（正常幅度）。对象名带方括号（百度出价记录的格式），测试归一化匹配
    {"optTime": "Jun 10, 2026 09:42:00 AM", "optType": 1, "optLevel": 5,
     "optContent": "bidPriceWord", "optObj": "[苏尔寿 中国]",
     "oldValue": "18.50", "newValue": "20.72", "planId": 2001, "unitId": 3001},
    # 关键词出价 +30%（超 20% 上限）
    {"optTime": "Jun 9, 2026 04:24:00 PM", "optType": 1, "optLevel": 5,
     "optContent": "bidPriceWord", "optObj": "苏尔寿 工业泵",
     "oldValue": "15.00", "newValue": "19.50", "planId": 2001, "unitId": 3001},
    # 暂停关键词（非数值，无幅度）
    {"optTime": "Jun 9, 2026 10:00:00 AM", "optType": 5, "optLevel": 5,
     "optContent": "shelveWord", "optObj": "磁力泵 价格",
     "oldValue": "启用", "newValue": "暂停", "planId": 2001, "unitId": 3001},
    # 计划级时段系数
    {"optTime": "Jun 8, 2026 02:32:00 PM", "optType": 4, "optLevel": 2,
     "optContent": "campaignCycPriceFactor", "optObj": "品牌词-冒烟",
     "oldValue": "1.3", "newValue": "1.5", "planId": 2001, "unitId": 0},
    # 噪音：创意暂停（订阅外，百度宽松返回）→ 白名单应过滤掉
    {"optTime": "Jun 8, 2026 10:00:00 AM", "optType": 5, "optLevel": 4,
     "optContent": "shelveIdea", "optObj": "某创意", "oldValue": "无", "newValue": "无"},
    # 噪音：opt_content 为空 → 过滤
    {"optTime": "Jun 8, 2026 09:00:00 AM", "optType": 4, "optLevel": 5,
     "optContent": None, "optObj": "脏数据", "oldValue": "x", "newValue": "y"},
]


async def main() -> None:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "台账冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="台账冒烟租户", strategy="lead", monthly_budget=10000)
            session.add(tenant)
            await session.flush()
        acc = await session.scalar(
            select(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id)
        )
        if acc is None:
            acc = BaiduAccount(
                tenant_id=tenant.id, baidu_username="台账冒烟账户", baidu_ucid=99999996,
                access_token_encrypted=encrypt("fake-token"),
                expires_at=datetime(2026, 9, 1), auth_mode="self", status="active",
            )
            session.add(acc)
            await session.flush()
        await session.execute(
            delete(OperationRecord).where(OperationRecord.tenant_id == tenant.id)
        )
        # 关键词级记录跳转用：「苏尔寿 中国」造 2 个同名词（不同展现），台账应解析到展现高的；
        # 「苏尔寿 工业泵」不建词 → 解析为 None（前端不可点）
        await session.execute(delete(Keyword).where(Keyword.tenant_id == tenant.id))
        session.add_all([
            Keyword(tenant_id=tenant.id, baidu_account_id=acc.id, keyword_id=700001,
                    keyword="苏尔寿 中国", total_impression=50),
            Keyword(tenant_id=tenant.id, baidu_account_id=acc.id, keyword_id=700002,
                    keyword="苏尔寿 中国", total_impression=999),
        ])
        await session.commit()

        # ===== 同步 + 幂等（mock ToolkitService.get_operation_records） =====
        async def fake_get(self, start_date, end_date):
            return [dict(r) for r in FAKE_RECORDS]

        with patch(
            "app.baidu.services.toolkit.ToolkitService.get_operation_records", fake_get
        ):
            n1 = await sync_operation_records_for_account(
                session, acc, date.today() - timedelta(days=3), date.today()
            )
            n2 = await sync_operation_records_for_account(
                session, acc, date.today() - timedelta(days=3), date.today()
            )
        total = await session.scalar(
            select(func.count()).select_from(OperationRecord).where(
                OperationRecord.tenant_id == tenant.id
            )
        )
        check("首次同步 4 条（白名单过滤掉 2 条噪音）", n1 == 4, str(n1))
        check("重复同步幂等（库里仍 4 条）", total == 4, str(total))

        tid = tenant.id
    await engine.dispose()

    # ===== 台账接口 =====
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    auth = {"X-API-Key": get_settings().admin_api_key}
    with TestClient(app) as client:
        def fetch(**params):
            r = client.get("/api/v1/operation-records",
                           params={"tenant_id": tid, **params}, headers=auth)
            assert r.status_code == 200, r.text
            return r.json()

        b = fetch()
        check("台账总数 4", b["total"] == 4, str(b["total"]))
        check("本月统计", b["summary"]["month_total"] == 4
              and b["summary"]["month_keyword_level"] == 3
              and b["summary"]["month_coef_level"] == 1, str(b["summary"]))
        check("超上限计数 1", b["summary"]["month_over_limit"] == 1)

        first = b["records"][0]  # 倒序，最新 = 苏尔寿 中国 +12%
        check("倒序首条（对象名保留原括号）", first["opt_obj"] == "[苏尔寿 中国]")
        check("带括号对象名归一化后解析到展现最高 keyword_id", first["keyword_id"] == 700002,
              str(first["keyword_id"]))
        pump = next(r for r in b["records"] if r["opt_obj"] == "苏尔寿 工业泵")
        check("无匹配词 keyword_id 为 None", pump["keyword_id"] is None, str(pump["keyword_id"]))
        plan_lvl = next(r for r in b["records"] if r["opt_level"] == 2)
        check("非关键词级不给 keyword_id", plan_lvl["keyword_id"] is None)
        check("幅度 +12%", first["change"] == {"pct": 12.0, "over_limit": False}, str(first["change"]))
        check("内容标签", first["content_label"] == "关键词出价")

        over = fetch(over_limit=True)
        check("只看超上限", over["total"] == 1
              and over["records"][0]["change"]["over_limit"] is True
              and over["records"][0]["change"]["pct"] == 30.0, str(over["total"]))

        check("层级筛选 计划", fetch(opt_level=2)["total"] == 1)
        check("内容筛选 shelveWord", fetch(opt_content="shelveWord")["total"] == 1)
        check("对象搜索", fetch(q="工业泵")["total"] == 1)
        shelve = fetch(opt_content="shelveWord")["records"][0]
        check("非数值变更无幅度", shelve["change"] is None and "启用 → 暂停" in f"{shelve['old_value']} → {shelve['new_value']}")


asyncio.run(main())
print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
