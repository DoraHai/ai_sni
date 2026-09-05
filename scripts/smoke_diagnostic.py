"""Read-only on-server smoke: no secret values or customer content are printed."""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path("/opt/diagnostic-service")
for name in ("shared.env", "providers.env", ".env"):
    for key, value in dotenv_values(ROOT / name).items():
        if value is not None:
            os.environ[key] = value
sys.path.insert(0, str(ROOT / "current"))

import httpx
from sqlalchemy import select
from app.config import get_settings
from app.database import engine
from app.models import Tenant


async def main():
    async with engine.connect() as conn:
        tenant_id = await conn.scalar(select(Tenant.id).order_by(Tenant.id).limit(1))
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8012",
                                headers={"X-API-Key": get_settings().admin_api_key}) as client:
        health = await client.get("/health/diagnostic")
        assert health.status_code == 200 and health.json()["db"] == "ok"
        if tenant_id is not None:
            for path in ("/assets/profile", "/audits/history", "/audits/latest", "/assets/knowledge"):
                response = await client.get("/api/v1/diagnostic" + path,
                                            params={"tenant_id": tenant_id})
                assert response.status_code == 200, (path, response.status_code)
                print(path + "=ok")
        response = await client.post("/api/v1/diagnostic/assets/brand/discover",
                                     json={"tenant_id": -1, "website": "https://example.com"})
        assert response.status_code == 404 and response.json()["detail"] == "客户不存在"
        print("authenticated_discovery_route=ok")
    await engine.dispose()


asyncio.run(main())
