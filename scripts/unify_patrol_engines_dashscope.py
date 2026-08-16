"""将监测引擎统一为 openai_compat + 租户百炼凭证，便于巡检真采样。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main(tenant_id: int = 1) -> int:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.geo.content.ai_settings import (
        PROVIDER_PRESETS,
        encrypt_api_key,
        resolve_llm_credentials,
    )
    from app.models.geo_tracking_engine import GeoTrackingEngine

    preset = PROVIDER_PRESETS["dashscope"]
    async with async_session_factory() as session:
        llm = await resolve_llm_credentials(session, tenant_id)
        if not llm or not llm.get("api_key"):
            print("FAIL: no tenant dashscope credentials")
            return 1
        engines = (
            await session.execute(
                select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == tenant_id)
            )
        ).scalars().all()
        if not engines:
            print("FAIL: no engines")
            return 1
        enc = encrypt_api_key(llm["api_key"])
        base = (llm.get("base_url") or preset["base_url"]).rstrip("/")
        model = llm.get("model") or preset["model"]
        n = 0
        for e in engines:
            e.sample_mode = "openai_compat"
            e.api_base_url = base
            e.model = model
            e.api_key_encrypted = enc
            e.enabled = True
            note = (e.note or "").strip()
            if "unified-dashscope" not in note:
                e.note = (note + " | unified-dashscope").strip(" |")
            n += 1
        await session.commit()
        print(
            "ok",
            {
                "tenant_id": tenant_id,
                "engines": n,
                "base_url": base,
                "model": model,
                "key_len": len(llm["api_key"]),
                "source": llm.get("source"),
            },
        )
    return 0


if __name__ == "__main__":
    tid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    raise SystemExit(asyncio.run(main(tid)))
