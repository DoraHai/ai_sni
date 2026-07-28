"""调价回写冒烟（回写「最终执行价」：dry-run 安全网 + 20% 硬上限 + 价格区间 + 台账留痕）。

回写的是人工拍板的最终执行价，旧价/20% 基准 = 关键词库内当前出价（Keyword.price），
不依赖 AI 建议。默认 BAIDU_WRITE_DRY_RUN 未设=True（演练）：updateWord 被 client 拦截不发 HTTP。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_writeback.py
"""
import asyncio
from datetime import datetime

from sqlalchemy import delete, select

from app.database import async_session_factory, engine
from app.models import BaiduAccount, BidWriteback, Keyword, Tenant
from app.security.crypto import encrypt

# 三个关键词：当前价都 8.0；回写 9.0(+12.5%演练) / 12.0(+50%超限) / 1500(越界)
KW_OK, KW_OVER, KW_RANGE = 71001, 71002, 71003


def _kw(tenant_id: int, kw: int, text: str) -> Keyword:
    return Keyword(
        tenant_id=tenant_id, keyword_id=kw, keyword=text,
        campaign_id=8801, adgroup_id=8901, match_type=48,
        price=8.0, pause=False, quality=7,
        total_impression=100, category="normal", category_source="auto",
    )


async def seed() -> int:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "回写冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="回写冒烟租户", strategy="lead", monthly_budget=10000)
            session.add(tenant)
            await session.flush()
        # 先清引用 account 外键的台账/关键词，再重建 account（避免跨运行 CRYPTO key 变化致 decrypt 失败）
        await session.execute(delete(BidWriteback).where(BidWriteback.tenant_id == tenant.id))
        await session.execute(delete(Keyword).where(Keyword.tenant_id == tenant.id))
        await session.execute(delete(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id))
        await session.flush()
        session.add(BaiduAccount(
            tenant_id=tenant.id, baidu_username="回写冒烟账户", baidu_ucid=99999996,
            access_token_encrypted=encrypt("fake-token"),
            expires_at=datetime(2026, 9, 1), auth_mode="self", status="active",
        ))
        session.add_all([
            _kw(tenant.id, KW_OK, "离心泵 价格"),
            _kw(tenant.id, KW_OVER, "离心泵 维修"),
            _kw(tenant.id, KW_RANGE, "磁力泵"),
        ])
        await session.commit()
        tid = tenant.id
    await engine.dispose()
    return tid


tenant_id = asyncio.run(seed())

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

settings = get_settings()
auth = {"X-API-Key": settings.admin_api_key}
failed = False


def check(label: str, cond: bool, detail: str = "") -> None:
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


check("演练开关默认开启(dry-run)", settings.baidu_write_dry_run is True,
      str(settings.baidu_write_dry_run))


def wb(kw, price):
    return client.post(f"/api/v1/keywords/{kw}/writeback",
                       json={"tenant_id": tenant_id, "price": price}, headers=auth)


with TestClient(app) as client:
    # 1) 正常回写最终执行价：dry-run 拦截，不真发，台账 status=dry_run
    r = wb(KW_OK, 9.0)
    check("正常回写 200", r.status_code == 200, r.text[:160])
    body = r.json() if r.status_code == 200 else {}
    rec = body.get("writeback", {})
    check("响应标明 dry_run", body.get("dry_run") is True, str(body.get("dry_run")))
    check("台账 status=dry_run", rec.get("status") == "dry_run", str(rec.get("status")))
    check("旧价快照=当前出价 8.0", rec.get("old_bid") == 8.0, str(rec.get("old_bid")))
    check("最终执行价 9.0", rec.get("new_bid") == 9.0, str(rec.get("new_bid")))
    check("change_pct 12.5", rec.get("change_pct") == 12.5, str(rec.get("change_pct")))

    # 2) 演练模式不改本地出价（KW_OK 仍 8.0）
    lr = client.get("/api/v1/keywords", params={"tenant_id": tenant_id}, headers=auth).json()
    ok_row = next((k for k in lr["keywords"] if k["keyword_id"] == KW_OK), {})
    check("演练后本地出价仍 8.0", ok_row.get("price") == 8.0, str(ok_row.get("price")))

    # 3) 超 20% 硬上限 → 400
    r2 = wb(KW_OVER, 12.0)
    check("超20%被拒 400", r2.status_code == 400, r2.text[:160])
    check("拒因含硬上限", "硬上限" in r2.text, r2.text[:160])

    # 4) 价格越区间 → 400
    r3 = wb(KW_RANGE, 1500.0)
    check("越区间被拒 400", r3.status_code == 400, r3.text[:160])
    check("拒因含合法区间", "合法区间" in r3.text, r3.text[:160])

    # 5) 被拒的不落台账：只有 1 条回写记录
    wl = client.get("/api/v1/writeback", params={"tenant_id": tenant_id}, headers=auth).json()
    check("台账仅 1 条(被拒不落账)", len(wl["writebacks"]) == 1, str(len(wl["writebacks"])))
    check("status_counts dry_run=1", wl["status_counts"].get("dry_run") == 1, str(wl["status_counts"]))

    # 6) 批量回写：正常→演练，超限/越界→跳过（rejected），不落账
    rb = client.post("/api/v1/keywords/writeback-batch",
                     json={"tenant_id": tenant_id, "items": [
                         {"keyword_id": KW_OK, "price": 9.0},
                         {"keyword_id": KW_OVER, "price": 12.0},
                         {"keyword_id": KW_RANGE, "price": 1500.0},
                     ]}, headers=auth)
    check("批量回写 200", rb.status_code == 200, rb.text[:160])
    bj = rb.json() if rb.status_code == 200 else {}
    check("批量 total=3", bj.get("total") == 3, str(bj.get("total")))
    check("批量演练 1 个(KW_OK)", bj.get("simulated") == [KW_OK], str(bj.get("simulated")))
    check("批量跳过 2 个(超限+越界)", len(bj.get("rejected", [])) == 2, str(bj.get("rejected")))
    check("批量无真写", bj.get("applied") == [], str(bj.get("applied")))

print("\n冒烟失败" if failed else "\n冒烟全部通过")
raise SystemExit(1 if failed else 0)
