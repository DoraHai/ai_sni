"""线索管理冒烟：create → list(+summary) → patch(状态/成交额) → delete。

本地跑（docker PG + 假 env）：
    PYTHONPATH=. .venv/bin/python scripts/dev_smoke_leads.py
"""
import asyncio

import httpx

from app.config import get_settings
from app.database import async_session_factory
from app.main import app
from app.models import Tenant
from sqlalchemy import select


async def main() -> None:
    key = get_settings().admin_api_key
    # 找一个本地存在的租户（FK 约束）
    async with async_session_factory() as s:
        tid = await s.scalar(select(Tenant.id).order_by(Tenant.id).limit(1))
    if tid is None:
        print("本地没有 tenant，跳过（生产有苏尔寿 tenant_id=1）")
        return
    print(f"用 tenant_id={tid}")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t", headers={"X-API-Key": key}) as c:
        # create
        r = await c.post("/api/v1/leads", json={
            "tenant_id": tid, "contact_name": "冒烟测试", "phone": "13800000000",
            "status": "new", "intent_level": "high", "lead_time": "2026-06-25", "note": "smoke",
        })
        print("CREATE", r.status_code, r.json().get("lead", {}).get("id"))
        lid = r.json()["lead"]["id"]

        # list + summary
        r = await c.get("/api/v1/leads", params={"tenant_id": tid})
        j = r.json()
        print("LIST", r.status_code, "total=", j["total"], "summary=", j["summary"])

        # patch → 成交 + 金额
        r = await c.patch(f"/api/v1/leads/{lid}", params={"tenant_id": tid},
                          json={"status": "won", "deal_amount": 12000})
        print("PATCH", r.status_code, r.json()["lead"]["status_label"], r.json()["lead"]["deal_amount"])

        # list again → 成交额应反映
        r = await c.get("/api/v1/leads", params={"tenant_id": tid})
        print("SUMMARY after won", r.json()["summary"])

        # validation: 空姓名空电话应 400
        r = await c.post("/api/v1/leads", json={"tenant_id": tid, "status": "new"})
        print("EMPTY guard", r.status_code, "(期望 400)")

        # delete (清理)
        r = await c.delete(f"/api/v1/leads/{lid}", params={"tenant_id": tid})
        print("DELETE", r.status_code)


if __name__ == "__main__":
    asyncio.run(main())
