"""单格巡检探测冒烟：租户 LLM + deepseek 引擎 openai_compat。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main(tenant_id: int = 1) -> int:
    from sqlalchemy import select

    from app.ai.deepseek import chat_json
    from app.database import async_session_factory
    from app.geo.content.ai_settings import resolve_llm_credentials
    from app.geo.content.probe import resolve_engine_llm, run_probe_draft
    from app.models.geo_tracking_engine import GeoTrackingEngine
    from app.models.tenant import Tenant

    async with async_session_factory() as session:
        tenant = await session.get(Tenant, tenant_id)
        brand = (tenant.name if tenant else None) or "GEO Demo Brand"
        tenant_llm = await resolve_llm_credentials(session, tenant_id)
        if not tenant_llm:
            print("FAIL no tenant llm")
            return 1
        engines = (
            await session.execute(
                select(GeoTrackingEngine).where(
                    GeoTrackingEngine.tenant_id == tenant_id,
                    GeoTrackingEngine.enabled.is_(True),
                )
            )
        ).scalars().all()
        print(
            "engines",
            [
                {
                    "key": e.engine_key,
                    "mode": e.sample_mode,
                    "model": e.model,
                    "has_key": bool(e.api_key_encrypted),
                }
                for e in engines
            ],
        )
        # probe one engine
        target = next((e for e in engines if e.engine_key == "deepseek"), engines[0])
        llm, mode, reason = resolve_engine_llm(
            engine=target.engine_key,
            tenant_llm=tenant_llm,
            engine_row=target,
        )
        print(
            "resolve",
            {
                "engine": target.engine_key,
                "mode": mode,
                "reason": reason,
                "source": llm.get("source"),
                "model": llm.get("model"),
            },
        )
        draft = await run_probe_draft(
            question="制造业企业如何选择支持私有化部署的数据分析平台？",
            brand=brand,
            brand_names=[brand],
            engine=target.engine_key,
            llm=llm,
            chat_json=chat_json,
            sample_mode=mode,
            fallback_reason=reason,
        )
        print(
            "probe_ok",
            {
                "sample_mode": draft.get("sample_mode"),
                "simulated": draft.get("simulated"),
                "mentions_brand": draft.get("suggested_mentions_brand"),
                "model": draft.get("model"),
                "provider": draft.get("provider"),
                "raw_len": len(str(draft.get("raw_text") or "")),
                "raw_head": str(draft.get("raw_text") or "")[:120],
            },
        )
    return 0


if __name__ == "__main__":
    tid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    raise SystemExit(asyncio.run(main(tid)))
