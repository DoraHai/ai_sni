"""拓词二期冒烟：URL 提词 / SSRF 防护 / kwc 翻转 / 冷门词两路口径（mock 百度与抓页）。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_url_cold.py
"""
import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import delete, select

from app.baidu.sync import (
    sync_planner_candidates_for_account,
    sync_query_candidates_for_account,
    sync_url_candidates_for_account,
)
from app.database import async_session_factory, engine
from app.expansion import is_cold_pv_candidate, is_cold_query_candidate
from app.models import BaiduAccount, Keyword, KeywordCandidate, Tenant
from app.security.crypto import encrypt
from app.urlwords import UrlFetchError, extract_words, validate_url

failed = False


def check(label: str, cond: bool, detail: str = "") -> None:
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


# ===== 纯函数：SSRF 防护 / 提词 / 冷门口径 =====
def raises_fetch_error(url: str) -> bool:
    try:
        validate_url(url)
        return False
    except UrlFetchError:
        return True


check("拒绝 file://", raises_fetch_error("file:///etc/passwd"))
check("拒绝 localhost", raises_fetch_error("http://localhost:8000/admin"))
check("拒绝内网 IP", raises_fetch_error("http://192.168.1.1/"))
check("拒绝 169.254 元数据段", raises_fetch_error("http://169.254.169.254/"))
check("放行公网 https", not raises_fetch_error("https://www.sulzer.com/zh-cn"))

TITLE = "工业泵选型指南-多级离心泵厂家|冒烟泵业"
TEXT = (
    "多级离心泵 选型 多级离心泵 厂家 立式多级泵 参数 立式多级泵 规格 "
    "化工流程泵 耐腐蚀泵 磁力驱动泵 HDPE 储罐 多级离心泵 应用 案例 "
) * 10
words = extract_words(TITLE, TEXT)
check("标题短语优先提取", words[0] == "工业泵选型指南", str(words[:3]))
check("提词含核心产品词", any("多级离心泵" in w for w in words), str(words[:6]))
check("英文型号词保留", any(w.upper() == "HDPE" for w in words))
check("单 URL 上限 30", len(words) <= 30, str(len(words)))

check("冷门①低 PV+意图后缀", is_cold_pv_candidate("立式泵 价格", 320, None))
check("冷门①低 PV+转化标签", is_cold_pv_candidate("某产品词", 100, ["转化潜力词"]))
check("冷门①PV 达标不算", not is_cold_pv_candidate("立式泵 价格", 800, None))
check("冷门①PV 未知不算", not is_cold_pv_candidate("立式泵 价格", None, ["转化潜力词"]))
check("冷门②低展现有点击", is_cold_query_candidate(30, 2))
check("冷门②无点击不算", not is_cold_query_candidate(30, 0))

FAKE_PAGES = {
    "https://ok.example.com/pumps": (TITLE, TEXT),
}
FAKE_PV_ROWS = [
    # kwc=1（百度口径=高竞争）→ 入库 competition 应翻转为 3
    {"keywordName": "工业泵选型指南", "averageMonthPv": 2400, "kwc": 1,
     "pcPrice": 8.0, "mobilePrice": 5.0, "showReasons": []},
    # 低 PV + 意图后缀（标题短语"多级离心泵厂家"含"厂家"）→ 归 cold
    {"keywordName": "多级离心泵厂家", "averageMonthPv": 200, "kwc": 3,
     "pcPrice": 4.0, "mobilePrice": 2.5, "showReasons": []},
]
FAKE_PLANNER_ROWS = [
    # 低 PV + 转化潜力词标签 → 冷门①，归 cold
    {"word": "耐腐蚀泵 定制", "competition": 1, "PV": 150, "showReasons": ["转化潜力词"]},
    # 正常规划师候选
    {"word": "化工流程泵 选型", "competition": 2, "PV": 1200, "showReasons": []},
]
FAKE_QUERY_ROWS = [
    # 冷门②：低展现有点击
    {"queryWord": "卧式多级泵 维修点", "queryStatusName": "未添加",
     "wInfoNameStatus": "多级泵", "impression": 20, "click": 2, "cost": 15.0},
    # 正常搜索词候选
    {"queryWord": "离心泵 价格表", "queryStatusName": "未添加",
     "wInfoNameStatus": "离心泵", "impression": 300, "click": 6, "cost": 80.0},
]


async def main() -> None:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "拓词二期冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="拓词二期冒烟租户", strategy="lead", monthly_budget=10000,
                            brand_terms=["冒烟泵业"])
            session.add(tenant)
            await session.flush()
        acc = await session.scalar(
            select(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id)
        )
        if acc is None:
            acc = BaiduAccount(
                tenant_id=tenant.id, baidu_username="拓词二期冒烟账户", baidu_ucid=99999994,
                access_token_encrypted=encrypt("fake-token"),
                expires_at=datetime(2026, 9, 1), auth_mode="self", status="active",
            )
            session.add(acc)
            await session.flush()
        acc.access_token_encrypted = encrypt("fake-token")
        await session.execute(
            delete(KeywordCandidate).where(KeywordCandidate.tenant_id == tenant.id)
        )
        await session.execute(delete(Keyword).where(Keyword.tenant_id == tenant.id))
        await session.commit()

        async def fake_fetch(url):
            if url in FAKE_PAGES:
                return FAKE_PAGES[url]
            raise UrlFetchError(f"抓取失败 {url}: HTTP 404")

        async def fake_pv(self, words_):
            return [dict(r) for r in FAKE_PV_ROWS]

        async def fake_seed(self, seed, max_num=300):
            return [dict(r) for r in FAKE_PLANNER_ROWS]

        async def fake_custom(self, max_num=300):
            return []

        async def fake_report(self, start_date, end_date, columns=None,
                              time_unit="SUMMARY", page_size=10000):
            return [dict(r) for r in FAKE_QUERY_ROWS]

        with patch("app.baidu.sync.fetch_page_text", fake_fetch), \
             patch("app.baidu.services.planner.KeywordPlannerService.get_pv_search", fake_pv), \
             patch("app.baidu.services.planner.KeywordPlannerService.get_words_by_seed", fake_seed), \
             patch("app.baidu.services.planner.KeywordPlannerService.get_account_recommend_words", fake_custom), \
             patch("app.baidu.services.report.ReportService.get_search_term_report", fake_report):
            n_url, details = await sync_url_candidates_for_account(
                session, acc,
                ["https://ok.example.com/pumps", "https://dead.example.com/404"],
            )
            n_planner = await sync_planner_candidates_for_account(session, acc, ["离心泵"])
            n_query = await sync_query_candidates_for_account(
                session, acc, date.today() - timedelta(days=29), date.today()
            )

        check("URL 源入库（含失败 URL 容错）", n_url > 0, str(n_url))
        ok_detail = next(d for d in details if d["url"].startswith("https://ok"))
        bad_detail = next(d for d in details if d["url"].startswith("https://dead"))
        check("成功 URL 明细", ok_detail["error"] is None and ok_detail["extracted"] > 0)
        check("失败 URL 明细带原因", "404" in (bad_detail["error"] or ""))

        async def get(word):
            return await session.scalar(
                select(KeywordCandidate).where(
                    KeywordCandidate.tenant_id == tenant.id, KeywordCandidate.word == word
                )
            )

        c1 = await get("工业泵选型指南")
        check("kwc=1 翻转为 competition=3", c1 is not None and c1.competition == 3,
              str(c1.competition if c1 else None))
        check("URL 源 seed_word 存页面", c1.seed_word == "https://ok.example.com/pumps")
        check("URL 候选有 PV/指导价", c1.monthly_pv == 2400 and float(c1.recommend_price_pc) == 8.0)

        c2 = await get("多级离心泵厂家")
        check("URL 提词命中冷门①归 cold", c2 is not None and c2.source == "cold",
              str(c2.source if c2 else None))

        c3 = await get("耐腐蚀泵 定制")
        check("规划师命中冷门①归 cold", c3 is not None and c3.source == "cold")
        c4 = await get("化工流程泵 选型")
        check("规划师正常词仍归 planner", c4 is not None and c4.source == "planner")

        c5 = await get("卧式多级泵 维修点")
        check("搜索词命中冷门②归 cold", c5 is not None and c5.source == "cold")
        c6 = await get("离心泵 价格表")
        # "价格"是意图词但冷门②只看展现/点击；query 源不走口径①
        check("搜索词正常词仍归 query", c6 is not None and c6.source == "query")

        tid = tenant.id
    await engine.dispose()

    # ===== 接口：cold/url 源筛选与计数 =====
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    auth = {"X-API-Key": get_settings().admin_api_key}
    with TestClient(app) as client:
        r = client.get("/api/v1/expansion/candidates",
                       params={"tenant_id": tid, "source": "cold"}, headers=auth)
        assert r.status_code == 200, r.text
        b = r.json()
        check("cold 源筛选 3 条", b["total"] == 3, str(b["total"]))
        check("源卡计数含 url/cold",
              b["source_pending_counts"].get("cold") == 3
              and b["source_pending_counts"].get("url", 0) >= 1,
              str(b["source_pending_counts"]))

        r = client.post("/api/v1/admin/sync-url-words", headers=auth,
                        json={"tenant_id": tid, "urls": []})
        check("空 URL 列表 422", r.status_code == 422, str(r.status_code))
        r = client.post("/api/v1/admin/sync-url-words", headers=auth,
                        json={"tenant_id": tid, "urls": ["http://localhost/x"]})
        body = r.json()
        check("内网 URL 被拒（容错不写入）", r.status_code == 200
              and body["candidates_written"] == 0 and body["urls"][0]["error"], str(body)[:120])


asyncio.run(main())
print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
