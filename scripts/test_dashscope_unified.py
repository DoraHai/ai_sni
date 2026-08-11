"""统一百炼配置连通性测试（env + 租户 resolve）。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main() -> int:
    from app.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    print("env_dashscope_set", bool(s.dashscope_api_key), "model", s.dashscope_model)
    print("env_deepseek_set", bool(s.deepseek_api_key))

    from app.ai.deepseek import _resolve_creds, chat_json, is_enabled

    print("is_enabled", is_enabled())
    key, base, model = _resolve_creds()
    print(
        "resolve_env",
        {
            "base_url": base,
            "model": model,
            "key_len": len(key),
            "masked": f"{key[:4]}****{key[-4:]}",
        },
    )

    data = await chat_json(
        "你是连通性检测。只输出一个 JSON 对象，不要 markdown 代码块。",
        '请返回：{"ok": true, "echo": "unified-dashscope-env-test"}',
        timeout=60.0,
    )
    print("chat_json_env_ok", json.dumps(data, ensure_ascii=False))

    from app.database import async_session_factory
    from app.geo.content.ai_settings import resolve_llm_credentials

    async with async_session_factory() as session:
        llm = await resolve_llm_credentials(session, 1)
        if not llm:
            print("tenant_resolve_failed")
            return 2
        print(
            "tenant_resolve",
            {
                "provider": llm["provider"],
                "model": llm["model"],
                "source": llm["source"],
                "base_url": llm["base_url"],
                "key_len": len(llm["api_key"]),
            },
        )
        data2 = await chat_json(
            "你是连通性检测。只输出一个 JSON 对象，不要 markdown 代码块。",
            '请返回：{"ok": true, "echo": "unified-dashscope-tenant-test"}',
            timeout=60.0,
            api_key=llm["api_key"],
            base_url=llm["base_url"],
            model=llm["model"],
        )
        print("chat_json_tenant_ok", json.dumps(data2, ensure_ascii=False))

    # HTTP 测试（若 API 已起）
    try:
        import httpx

        # trust_env=False：避免系统 HTTP_PROXY 劫持 127.0.0.1
        with httpx.Client(trust_env=False, timeout=60.0) as client:
            r = client.post(
                "http://127.0.0.1:8000/api/v1/geo/ai-settings/test",
                params={"tenant_id": 1},
                headers={"X-API-Key": s.admin_api_key},
            )
            print("http_main", r.status_code, r.text[:300])
            r2 = client.post(
                "http://127.0.0.1:8011/api/v1/geo/ai-settings/test",
                params={"tenant_id": 1},
                headers={"X-API-Key": s.admin_api_key},
            )
            print("http_geo", r2.status_code, r2.text[:300])
    except Exception as exc:  # noqa: BLE001
        print("http_skip", type(exc).__name__, str(exc)[:160])

    print("ALL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
