"""手动启动一次可见度巡检并轮询状态。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    import httpx

    from app.config import get_settings

    s = get_settings()
    headers = {"X-API-Key": s.admin_api_key, "Content-Type": "application/json"}
    # 控制规模：6 意图词 × 3 引擎，便于本次手动验证尽快完成
    body = {
        "tenant_id": 1,
        "auto_persist": True,
        "prefer_real": True,
        "prompt_limit": 6,
        "engine_keys": ["deepseek", "doubao", "chatgpt"],
        "run_async": True,
    }
    base = "http://127.0.0.1:8000"
    with httpx.Client(trust_env=False, timeout=60.0) as client:
        r = client.post(f"{base}/api/v1/geo/visibility-patrol/runs", headers=headers, json=body)
        print("start", r.status_code, r.text[:600])
        if r.status_code >= 400:
            return 1
        data = r.json()
        run = data.get("run") or {}
        rid = run.get("id")
        print("run_id", rid, "status", run.get("status"), "async", data.get("async"))
        if not rid:
            return 1

        last_status = None
        for i in range(120):
            time.sleep(5)
            gr = client.get(
                f"{base}/api/v1/geo/visibility-patrol/runs/{rid}",
                params={"tenant_id": 1},
                headers=headers,
            )
            if gr.status_code != 200:
                print("poll_http", i + 1, gr.status_code, gr.text[:200])
                continue
            g = gr.json()
            st = g.get("status")
            summary = g.get("summary") or {}
            print(
                f"poll {i + 1}: status={st} "
                f"real={summary.get('real_samples')} "
                f"persona={summary.get('persona_samples')} "
                f"ok={summary.get('ok_cells')} "
                f"err={summary.get('error_cells') or summary.get('errors')} "
                f"cells={summary.get('cells') or summary.get('total_cells')}"
            )
            last_status = st
            if st in ("done", "completed", "failed", "error", "cancelled"):
                print(
                    "FINAL",
                    json.dumps(
                        {
                            "id": g.get("id"),
                            "status": st,
                            "trigger": g.get("trigger"),
                            "error": g.get("error"),
                            "summary": summary,
                            "engine_keys": g.get("engine_keys"),
                            "prompt_limit": g.get("prompt_limit"),
                        },
                        ensure_ascii=False,
                        default=str,
                    )[:1500],
                )
                items = g.get("items") or []
                print("items", len(items))
                for it in items[:6]:
                    raw = str(it.get("raw_text") or "")[:70]
                    print(
                        " -",
                        it.get("engine"),
                        it.get("sample_mode"),
                        "ok=",
                        it.get("ok"),
                        "sim=",
                        it.get("simulated"),
                        "brand=",
                        it.get("suggested_mentions_brand"),
                        raw,
                    )
                return 0 if st in ("done", "completed") else 2
        print("TIMEOUT status=", last_status)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
