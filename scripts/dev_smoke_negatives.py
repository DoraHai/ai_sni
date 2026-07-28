"""否词管理冒烟：平铺 / 重复检测（单元撞计划）/ 冲突检测（否词撞现役关键词）/ 筛选。

用法（本地 docker compose 的 PG）：
  env DATABASE_URL=postgresql+asyncpg://sem_app:dev_only_password@127.0.0.1:5432/sem_prod \
      ... 其余 env 同 .env.example 填假值 ... \
      PYTHONPATH=. .venv/bin/python scripts/dev_smoke_negatives.py
"""
import asyncio
from datetime import datetime

from sqlalchemy import delete, select

from app.database import async_session_factory, engine
from app.models import Adgroup, BaiduAccount, Campaign, Keyword, Tenant
from app.security.crypto import encrypt

CAMP = 9301
ADG = 9401

failed = False


def check(label: str, cond: bool, detail: str = "") -> None:
    global failed
    mark = "✅" if cond else "❌"
    if not cond:
        failed = True
    print(f"{mark} {label} {detail}")


async def seed() -> int:
    async with async_session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.name == "否词冒烟租户"))
        if tenant is None:
            tenant = Tenant(name="否词冒烟租户", strategy="lead", monthly_budget=10000)
            session.add(tenant)
            await session.flush()
        if await session.scalar(
            select(BaiduAccount).where(BaiduAccount.tenant_id == tenant.id)
        ) is None:
            session.add(
                BaiduAccount(
                    tenant_id=tenant.id, baidu_username="否词冒烟账户", baidu_ucid=99999993,
                    access_token_encrypted=encrypt("fake-token"),
                    expires_at=datetime(2026, 9, 1), auth_mode="self", status="active",
                )
            )
        for model in (Keyword, Campaign, Adgroup):
            await session.execute(delete(model).where(model.tenant_id == tenant.id))

        session.add_all(
            [
                Campaign(
                    tenant_id=tenant.id, campaign_id=CAMP, campaign_name="规整填料计划",
                    # 计划级：短语否 [免费, 论文]，精确否 [招聘]
                    negative_words=["免费", "论文"],
                    exact_negative_words=["招聘"],
                ),
                Adgroup(
                    tenant_id=tenant.id, adgroup_id=ADG, campaign_id=CAMP,
                    adgroup_name="核心词单元",
                    # 单元级：短语否 [免费(与计划重复), 价格(与关键词冲突)]，精确否 [二手]
                    negative_words=["免费", "价格"],
                    exact_negative_words=["二手"],
                ),
            ]
        )
        # 现役关键词「规整填料价格」：被单元短语否「价格」命中 → 冲突
        session.add(Keyword(tenant_id=tenant.id, keyword_id=64001, keyword="规整填料价格",
                            campaign_id=CAMP, adgroup_id=ADG, pause=False))
        # 已暂停词不参与冲突检测：「论文规整填料」与计划否词「论文」字面冲突但 pause=True
        session.add(Keyword(tenant_id=tenant.id, keyword_id=64002, keyword="论文规整填料",
                            campaign_id=CAMP, adgroup_id=ADG, pause=True))
        await session.commit()
        tid = tenant.id
    await engine.dispose()
    return tid


tenant_id = asyncio.run(seed())

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

auth = {"X-API-Key": get_settings().admin_api_key}

with TestClient(app) as client:
    def fetch(**params) -> dict:
        r = client.get("/api/v1/negative-words",
                       params={"tenant_id": tenant_id, **params}, headers=auth)
        assert r.status_code == 200, r.text
        return r.json()

    b = fetch()
    s = b["summary"]
    check("平铺总数 6（计划 3 + 单元 3）", s["total"] == 6
          and s["campaign_level"] == 3 and s["adgroup_level"] == 3, str(s))
    check("匹配方式计数（短语 4 / 精确 2）", s["phrase"] == 4 and s["exact"] == 2, str(s))
    check("重复检测 1（单元「免费」撞计划）", s["duplicates"] == 1, str(s))
    check("冲突检测 1（「价格」撞规整填料价格）", s["conflicts"] == 1, str(s))

    dup = next(i for i in b["items"] if "duplicate" in i["flags"])
    check("重复条目是单元级「免费」", dup["word"] == "免费" and dup["scope"] == "adgroup"
          and "可清理" in dup["note"], str(dup["note"]))

    conflict = next(i for i in b["items"] if "conflict" in i["flags"])
    check("冲突条目带关键词示例", conflict["word"] == "价格"
          and conflict["conflict_keywords"] == ["规整填料价格"], str(conflict["conflict_keywords"]))
    check("暂停词不参与冲突（论文无 flag）",
          all("conflict" not in i["flags"] for i in b["items"] if i["word"] == "论文"))

    check("范围筛选 计划级 3", fetch(scope="campaign")["total"] == 3)
    check("匹配筛选 精确 2", fetch(match="exact")["total"] == 2)
    check("flag 筛选 conflict 1", fetch(flag="conflict")["total"] == 1)
    check("搜索否词", fetch(q="二手")["total"] == 1)
    check("搜索单元名", fetch(q="核心词单元")["total"] == 3)
    check("筛选不影响 summary", fetch(scope="campaign")["summary"]["total"] == 6)

failed_text = "\n冒烟失败" if failed else "\n冒烟全部通过"
print(failed_text)
raise SystemExit(1 if failed else 0)
