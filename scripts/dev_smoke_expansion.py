"""拓词本地冒烟：打分/建议分类纯函数 + 同步幂等（mock 百度）+ 候选接口（筛选/状态/导出）。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_expansion.py
"""
import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import delete, func, select

from app.baidu.sync import (
    sync_planner_candidates_for_account,
    sync_query_candidates_for_account,
)
from app.database import async_session_factory, engine
from app.expansion import (
    parse_query_status,
    score_planner_candidate,
    score_query_candidate,
    suggest_category,
)
from app.models import BaiduAccount, Keyword, KeywordCandidate, Tenant
from app.security.crypto import encrypt

failed = False


def check(label: str, cond: bool, detail: str = "") -> None:
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


# ===== 纯函数：打分 / 建议分类 / queryStatus 解析 =====
s_high = score_planner_candidate(43616, 1, ["高频热搜词"])
check("规划师高 PV 低竞争 ≥8", s_high >= 8, str(s_high))
s_low = score_planner_candidate(80, 3, None)
check("规划师低 PV 高竞争落长尾档", 3 <= s_low < 5, str(s_low))
check("转化潜力标签加分", score_planner_candidate(1000, 2, ["转化潜力词"]) > score_planner_candidate(1000, 2, None))
sq = score_query_candidate(680, 12)
check("搜索词源有点击高分", sq >= 8, str(sq))
check("搜索词源零流量低分", score_query_candidate(3, 0) < 3, str(score_query_candidate(3, 0)))
check("品牌词根优先", suggest_category("冒烟泵业 招聘", "query", 1.0, ["冒烟泵业"]) == "brand")
check("低分 query 建议否定", suggest_category("某词", "query", 1.0, []) == "negative")
check("低分 planner 新词观察", suggest_category("某词", "planner", 1.0, []) == "observe")
check("queryStatus 数字 key", parse_query_status("1") == 1)
check("queryStatus 中文 value", parse_query_status("未添加") == 1)
check("queryStatus 非法 None", parse_query_status("???") is None)

FAKE_PLANNER_SEED = [
    {"word": "多级离心泵 选型", "competition": 2, "PV": 2400, "pcPV": 1500, "mobilePV": 900,
     "showReasons": ["转化潜力词"], "recommendPricePc": 8.2, "recommendPriceMobile": 5.1},
    {"word": "已购冒烟词", "competition": 1, "PV": 999},  # 已在 keywords 表 → 应跳过
    {"word": "立式多级泵 厂家", "competition": 1, "PV": 320, "recommendPricePc": 4.2},
]
FAKE_PLANNER_CUSTOM = [
    {"word": "化工分离塔 设计", "competition": 1, "PV": 280, "recommendPricePc": 5.5},
]
FAKE_QUERY_ROWS = [
    # 未添加 + 两个触发词 → 聚合为一条，matched_keyword 取展现高的
    {"queryWord": "磁力泵 价格", "queryStatusName": "未添加", "wInfoNameStatus": "磁力泵",
     "impression": 600, "click": 10, "cost": 96.0},
    {"queryWord": "磁力泵 价格", "queryStatusName": "1", "wInfoNameStatus": "泵 价格",
     "impression": 60, "click": 2, "cost": 9.0},
    # 已添加 → 过滤
    {"queryWord": "冒烟泵业 官网", "queryStatusName": "已添加", "wInfoNameStatus": "冒烟泵业",
     "impression": 100, "click": 5, "cost": 50.0},
    # 低流量未添加 → 建议否定
    {"queryWord": "冒烟泵业 招聘", "queryStatusName": "未添加", "wInfoNameStatus": "冒烟泵业",
     "impression": 3, "click": 0, "cost": 0.0},
]


async def main() -> None:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "拓词冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="拓词冒烟租户", strategy="lead", monthly_budget=10000,
                            brand_terms=["冒烟泵业"])
            session.add(tenant)
            await session.flush()
        acc = await session.scalar(
            select(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id)
        )
        if acc is None:
            acc = BaiduAccount(
                tenant_id=tenant.id, baidu_username="拓词冒烟账户", baidu_ucid=99999995,
                access_token_encrypted=encrypt("fake-token"),
                expires_at=datetime(2026, 9, 1), auth_mode="self", status="active",
            )
            session.add(acc)
            await session.flush()
        # token 密文按当前 master key 重写，避免换 dev key 后 InvalidTag
        acc.access_token_encrypted = encrypt("fake-token")
        await session.execute(
            delete(KeywordCandidate).where(KeywordCandidate.tenant_id == tenant.id)
        )
        await session.execute(delete(Keyword).where(Keyword.tenant_id == tenant.id))
        session.add(Keyword(tenant_id=tenant.id, baidu_account_id=acc.id,
                            keyword_id=900001, keyword="已购冒烟词"))
        await session.commit()

        # ===== 同步 + 幂等（mock 规划师与搜索词报告） =====
        async def fake_seed(self, seed, max_num=300):
            return [dict(r) for r in FAKE_PLANNER_SEED]

        async def fake_custom(self, max_num=300):
            return [dict(r) for r in FAKE_PLANNER_CUSTOM]

        async def fake_report(self, start_date, end_date, columns=None,
                              time_unit="SUMMARY", page_size=10000):
            return [dict(r) for r in FAKE_QUERY_ROWS]

        with patch("app.baidu.services.planner.KeywordPlannerService.get_words_by_seed", fake_seed), \
             patch("app.baidu.services.planner.KeywordPlannerService.get_account_recommend_words", fake_custom), \
             patch("app.baidu.services.report.ReportService.get_search_term_report", fake_report):
            n_p1 = await sync_planner_candidates_for_account(session, acc, ["离心泵"])
            n_q1 = await sync_query_candidates_for_account(
                session, acc, date.today() - timedelta(days=29), date.today()
            )
            check("规划师 3 候选（剔除已购词）", n_p1 == 3, str(n_p1))
            check("搜索词 2 候选（剔除已添加，同词聚合）", n_q1 == 2, str(n_q1))

            # 标记一条已忽略后重复同步：status 不能被刷回 pending
            ignored = await session.scalar(
                select(KeywordCandidate).where(
                    KeywordCandidate.tenant_id == tenant.id,
                    KeywordCandidate.word == "磁力泵 价格",
                )
            )
            ignored.status = "ignored"
            ignored.status_updated_at = datetime.utcnow()
            await session.commit()

            n_p2 = await sync_planner_candidates_for_account(session, acc, ["离心泵"])
            n_q2 = await sync_query_candidates_for_account(
                session, acc, date.today() - timedelta(days=29), date.today()
            )
        total = await session.scalar(
            select(func.count()).select_from(KeywordCandidate).where(
                KeywordCandidate.tenant_id == tenant.id
            )
        )
        check("重复同步幂等（库里仍 5 条）", total == 5, str(total))
        await session.refresh(ignored)
        check("人工状态不被同步覆盖", ignored.status == "ignored", ignored.status)

        merged = await session.scalar(
            select(KeywordCandidate).where(
                KeywordCandidate.tenant_id == tenant.id,
                KeywordCandidate.word == "磁力泵 价格",
            )
        )
        check("同词聚合：展现 660 / 点击 12", merged.impression == 660 and merged.click == 12,
              f"{merged.impression}/{merged.click}")
        check("触发词取展现高者", merged.matched_keyword == "磁力泵", str(merged.matched_keyword))

        brand_cand = await session.scalar(
            select(KeywordCandidate).where(
                KeywordCandidate.tenant_id == tenant.id,
                KeywordCandidate.word == "冒烟泵业 招聘",
            )
        )
        check("品牌词根候选归 brand", brand_cand.suggested_category == "brand",
              str(brand_cand.suggested_category))

        tid = tenant.id
    await engine.dispose()

    # ===== 候选接口 =====
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    auth = {"X-API-Key": get_settings().admin_api_key}
    with TestClient(app) as client:
        def fetch(**params):
            r = client.get("/api/v1/expansion/candidates",
                           params={"tenant_id": tid, **params}, headers=auth)
            assert r.status_code == 200, r.text
            return r.json()

        b = fetch()
        check("全量 5 条", b["total"] == 5, str(b["total"]))
        check("默认潜力分降序", [c["potential_score"] for c in b["candidates"]]
              == sorted([c["potential_score"] for c in b["candidates"]], reverse=True))
        # 「立式多级泵 厂家」PV 320 + 意图词"厂家"→ 二期冷门口径①归 cold
        check("源卡待处理计数", b["source_pending_counts"].get("planner") == 2
              and b["source_pending_counts"].get("query") == 1
              and b["source_pending_counts"].get("cold") == 1, str(b["source_pending_counts"]))

        check("source 筛选", fetch(source="query")["total"] == 2)
        check("status 筛选", fetch(status="ignored")["total"] == 1)
        check("min_score 筛选", all(c["potential_score"] >= 5 for c in fetch(min_score=5)["candidates"]))
        check("候选词搜索", fetch(q="离心泵")["total"] == 1)

        cand_id = fetch(q="立式多级泵")["candidates"][0]["id"]
        r = client.patch(f"/api/v1/expansion/candidates/{cand_id}/status",
                         params={"tenant_id": tid, "status": "adopted"}, headers=auth)
        check("状态标记 adopted", r.status_code == 200 and r.json()["candidate_status"] == "adopted")
        r = client.patch(f"/api/v1/expansion/candidates/{cand_id}/status",
                         params={"tenant_id": tid, "status": "bogus"}, headers=auth)
        check("非法状态 400", r.status_code == 400)
        r = client.patch(f"/api/v1/expansion/candidates/{cand_id}/status",
                         params={"tenant_id": tid + 999, "status": "ignored"}, headers=auth)
        check("跨租户 404", r.status_code == 404)

        r = client.get("/api/v1/expansion/candidates/export",
                       params={"tenant_id": tid}, headers=auth)
        check("导出 CSV", r.status_code == 200 and r.text.startswith("\ufeff候选词")
              and "多级离心泵 选型" in r.text, str(r.status_code))


asyncio.run(main())
print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
