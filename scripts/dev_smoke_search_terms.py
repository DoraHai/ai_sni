"""搜索词报告冒烟：全量落库查询（筛选/有点击/汇总）+ 关键词详情触发搜索词下钻（A）。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_search_terms.py
"""
import asyncio
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.database import async_session_factory, engine
from app.models import (
    Adgroup,
    BaiduAccount,
    KwReportSnapshot,
    SearchTermReport,
    Tenant,
    WritebackAction,
)
from app.security.crypto import encrypt

ADG = 8901


async def seed() -> int:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "搜索词冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="搜索词冒烟租户", strategy="lead", monthly_budget=10000)
            session.add(tenant)
            await session.flush()
        await session.execute(delete(WritebackAction).where(WritebackAction.tenant_id == tenant.id))
        await session.execute(delete(SearchTermReport).where(SearchTermReport.tenant_id == tenant.id))
        await session.execute(delete(KwReportSnapshot).where(KwReportSnapshot.tenant_id == tenant.id))
        await session.execute(delete(Adgroup).where(Adgroup.tenant_id == tenant.id))
        await session.execute(delete(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id))
        await session.flush()
        session.add(BaiduAccount(
            tenant_id=tenant.id, baidu_username="搜索词冒烟账户", baidu_ucid=99999995,
            access_token_encrypted=encrypt("fake-token"),
            expires_at=datetime(2026, 9, 1), auth_mode="self", status="active",
        ))
        session.add(Adgroup(
            tenant_id=tenant.id, adgroup_id=ADG, campaign_id=8801, adgroup_name="单元A",
            negative_words=[], exact_negative_words=[],
        ))

        win_s, win_e = date.today() - timedelta(days=29), date.today()
        now = datetime.utcnow()

        def st(word, trigger, status, imp, clk, cost):
            return SearchTermReport(
                tenant_id=tenant.id, baidu_account_id=None, query_word=word,
                trigger_keyword=trigger, query_status=status,
                campaign_id=8801, campaign_name="计划A", adgroup_id=ADG, adgroup_name="单元A",
                match_id=1, impression=imp, click=clk, cost=cost, ctr=None, cpc=None,
                window_start=win_s, window_end=win_e, is_added=(status == 0), synced_at=now,
            )

        session.add_all([
            st("离心泵 多少钱", "离心泵 价格", 1, 200, 12, 80.0),   # 未添加 有点击
            st("离心泵 报价", "离心泵 价格", 1, 150, 0, 0.0),        # 未添加 零点击
            st("离心泵 价格", "离心泵 价格", 0, 300, 20, 100.0),     # 已添加 有点击
            st("磁力泵 厂家", "磁力泵", 1, 50, 3, 10.0),            # 别的触发词
        ])
        # A 下钻需要详情接口能识别该关键词（KwReportSnapshot 提供 keyword 文本）
        session.add(KwReportSnapshot(
            tenant_id=tenant.id, report_date=date.today(), campaign_id=8801, adgroup_id=ADG,
            keyword_id=72001, keyword="离心泵 价格", device=1,
            impression=300, click=20, cost=100.0, avg_rank=1.5, fetched_at=now,
        ))
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


def check(label, cond, detail=""):
    global failed
    if not cond:
        failed = True
    print(f"{'✅' if cond else '❌'} {label} {detail}")


with TestClient(app) as client:
    def lst(**params):
        r = client.get("/api/v1/search-terms", params={"tenant_id": tenant_id, **params}, headers=auth)
        assert r.status_code == 200, r.text
        return r.json()

    b = lst()
    check("全部 4 条", b["total"] == 4, str(b["total"]))
    check("汇总 有点击 3", b["summary"]["with_click"] == 3, str(b["summary"]))
    check("汇总展现合计 700", b["summary"]["impression"] == 700, str(b["summary"]["impression"]))
    check("窗口非空", b["window"] and b["window"]["start"], str(b["window"]))

    check("只看有点击 = 3", lst(has_click=True)["total"] == 3)
    check("只看零点击 = 1", lst(has_click=False)["total"] == 1)
    check("未添加筛选 = 3", lst(status="not_added")["total"] == 3)
    check("已添加筛选 = 1", lst(status="added")["total"] == 1)
    check("搜索 磁力泵 = 1", lst(q="磁力泵")["total"] == 1)
    top = lst()["search_terms"][0]
    check("默认按展现降序(已添加价格词300)", top["query_word"] == "离心泵 价格", top["query_word"])
    check("行含点击字段", "click" in top and top["click"] == 20, str(top.get("click")))

    # A：关键词详情触发搜索词下钻（trigger_keyword 含「离心泵 价格」的 3 条）
    d = client.get("/api/v1/keywords/72001", params={"tenant_id": tenant_id}, headers=auth)
    check("详情 200", d.status_code == 200, d.text[:120])
    sq = d.json().get("search_queries") if d.status_code == 200 else None
    check("详情下钻触发搜索词 3 条", sq is not None and len(sq) == 3, str(len(sq) if sq else None))
    check("下钻含点击/已加标识", bool(sq) and "click" in sq[0] and "is_added" in sq[0], str(sq[0] if sq else None))

    # ===== 阶段二：加否词 / 转拓词（dry-run 保护） =====
    rn = client.post("/api/v1/search-terms/negative",
                     json={"tenant_id": tenant_id, "word": "离心泵 多少钱", "adgroup_id": ADG, "match_mode": "exact"},
                     headers=auth)
    check("加否词 200", rn.status_code == 200, rn.text[:160])
    nj = rn.json() if rn.status_code == 200 else {}
    check("加否词演练 dry_run", nj.get("dry_run") is True and nj.get("action", {}).get("status") == "dry_run",
          str(nj.get("action", {}).get("status")))

    re_ = client.post("/api/v1/search-terms/expand",
                      json={"tenant_id": tenant_id, "word": "离心泵 报价", "adgroup_id": ADG, "price": 5.0, "match_mode": "phrase"},
                      headers=auth)
    check("转拓词 200", re_.status_code == 200, re_.text[:160])
    ej = re_.json() if re_.status_code == 200 else {}
    check("转拓词演练 dry_run", ej.get("dry_run") is True and ej.get("action", {}).get("status") == "dry_run",
          str(ej.get("action", {}).get("status")))

    rbad = client.post("/api/v1/search-terms/expand",
                       json={"tenant_id": tenant_id, "word": "越界词", "adgroup_id": ADG, "price": 2000, "match_mode": "phrase"},
                       headers=auth)
    check("转拓词出价越界 400", rbad.status_code == 400, rbad.text[:120])

    acts = client.get("/api/v1/search-terms/actions", params={"tenant_id": tenant_id}, headers=auth).json()
    check("写回台账 2 条(越界不落账)", len(acts["actions"]) == 2, str(len(acts["actions"])))

print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
