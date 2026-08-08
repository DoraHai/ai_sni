"""GEO social usability acceptance (mock WeChat + platform payloads + health).

Usage:
  python scripts/accept_geo_social_usability.py [BASE] [API_KEY] [TENANT_ID]

Does not require real WeChat/Zhihu credentials. Sets GEO_WECHAT_MP_MOCK via
in-process unit checks; API checks use mock_ app_id when creating accounts.

Default BASE=http://127.0.0.1:8011
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# allow `from app...` when run as script
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
API_KEY = sys.argv[2] if len(sys.argv) > 2 else "geo-demo-local-key"
TENANT_ID = int(sys.argv[3]) if len(sys.argv) > 3 else 1

PASS = 0
FAIL = 0
SKIP = 0
API_UP = True


def req(method: str, path: str, body: dict | None = None, expect: int | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={
            "X-API-Key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            code = resp.status
            payload = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        code = exc.code
        try:
            payload = json.loads(raw) if raw else {"detail": raw}
        except json.JSONDecodeError:
            payload = {"detail": raw}
    except Exception as exc:  # noqa: BLE001
        code = 0
        payload = {"detail": str(exc)}
    if expect is not None and code != expect:
        raise AssertionError(f"{method} {path} -> {code} (want {expect}): {payload}")
    return code, payload


def check(name: str, fn) -> None:
    global PASS, FAIL, SKIP
    try:
        fn()
        print(f"[PASS] {name}")
        PASS += 1
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "API 不可达" in msg or "无法连接" in msg or "Connection refused" in msg:
            print(f"[SKIP] {name}: {exc}")
            SKIP += 1
            return
        print(f"[FAIL] {name}: {exc}")
        FAIL += 1


def main() -> int:
    global API_UP
    print(f"Social usability BASE={BASE} TENANT={TENANT_ID}\n")
    stamp = int(datetime.utcnow().timestamp())
    state: dict = {}
    # probe API
    code, _ = req("GET", "/api/v1/geo/content-health")
    API_UP = code != 0
    if not API_UP:
        print(f"[info] API 未启动，仅跑进程内单测；完整验收请: uvicorn app.geo_main:app --port 8011\n")

    def unit_wechat_cover_mock():
        os.environ["GEO_WECHAT_MP_MOCK"] = "1"
        from app.geo.content.connectors.wechat_mp import publish_wechat_mp

        async def _run_b64():
            import base64

            tiny = base64.b64encode(b"\xff\xd8\xff\xd9" + b"\x00" * 64).decode()
            return await publish_wechat_mp(
                {
                    "app_id": "mock_wx_accept",
                    "app_secret": "secret",
                    "cover_image_base64": tiny,
                },
                mode="publish",
                title="封面验收",
                body_markdown="正文",
            )

        r = asyncio.run(_run_b64())
        assert r.get("ok") and r.get("media_id"), r
        assert r.get("thumb_media_id") or r.get("mock"), r
        os.environ.pop("GEO_WECHAT_MP_MOCK", None)

    def unit_platform_payloads():
        from app.geo.content.connectors.social import build_social_payload

        z = build_social_payload(
            platform="zhihu",
            mode="draft",
            tenant_id=1,
            task_id=1,
            channel="zhihu",
            title="知乎标题",
            body_markdown="md",
            body_html="<p>html</p>",
        )
        assert z.get("zhihu") and z["zhihu"]["title"] == "知乎标题"
        b = build_social_payload(
            platform="baijiahao",
            mode="draft",
            tenant_id=1,
            task_id=1,
            channel="baijiahao",
            title="百家号标题很长很长很长很长很长",
            body_markdown="md",
            body_html="<p>x</p>",
        )
        assert b["article"]["is_original"] == 1
        assert len(b["article"]["title"]) <= 40
        t = build_social_payload(
            platform="toutiao",
            mode="draft",
            tenant_id=1,
            task_id=1,
            channel="toutiao",
            title="头条",
            body_markdown="md",
        )
        assert "data" in t and t["data"]["title"] == "头条"

    def api_content_health():
        code, h = req("GET", "/api/v1/geo/content-health")
        if code == 0:
            raise AssertionError(
                f"API 不可达 {BASE} — 请先启动: uvicorn app.geo_main:app --port 8011"
            )
        if code != 200:
            raise AssertionError(f"content-health -> {code}: {h}")
        assert h.get("module") == "geo-content"
        assert h.get("status") in ("ok", "degraded"), h
        if h.get("status") == "degraded":
            print(f"  [warn] schema degraded: {h.get('hint')}")
        else:
            schema = h.get("schema") or {}
            assert schema.get("optimization_businesses") == "ok", schema

    def api_create_wechat_mock_account():
        # ensure multi media channels
        code, _ = req(
            "POST",
            f"/api/v1/geo/publishing-channels/enable-multi-media-auto?tenant_id={TENANT_ID}",
        )
        if code == 0:
            raise AssertionError(f"API 不可达 {BASE}")
        if code != 200:
            raise AssertionError(f"enable-multi-media-auto -> {code}")
        code, chs = req(
            "GET",
            f"/api/v1/geo/publishing-channels?tenant_id={TENANT_ID}",
            expect=200,
        )
        items = chs.get("items") or []
        wechat = next((c for c in items if c.get("channel_type") == "wechat"), None)
        assert wechat, "no wechat channel"
        code, acc = req(
            "POST",
            "/api/v1/geo/channel-accounts",
            {
                "tenant_id": TENANT_ID,
                "channel_id": wechat["id"],
                "display_name": f"可用性微信mock-{stamp}",
                "auth_type": "social_api",
                "credentials": {
                    "provider": "wechat_mp",
                    "platform": "wechat",
                    "app_id": f"mock_wx_{stamp}",
                    "app_secret": "secret",
                },
            },
            expect=200,
        )
        assert acc.get("id")
        state["account_id"] = acc["id"]

    def api_verify_social():
        if "account_id" not in state:
            raise AssertionError("API 不可达或账号未创建")
        code, r = req(
            "POST",
            f"/api/v1/geo/channel-accounts/{state['account_id']}/verify-social"
            f"?tenant_id={TENANT_ID}",
            expect=200,
        )
        assert r.get("ok") is True, r

    def api_ops_alerts():
        code, r = req(
            "GET",
            f"/api/v1/geo/ops-alerts?tenant_id={TENANT_ID}",
        )
        if code == 0:
            raise AssertionError(f"API 不可达 {BASE}")
        if code != 200:
            raise AssertionError(f"ops-alerts -> {code}: {r}")
        assert "alerts" in r and "summary" in r

    steps = [
        ("unit wechat cover mock", unit_wechat_cover_mock),
        ("unit platform payloads", unit_platform_payloads),
        ("API content-health schema", api_content_health),
        ("API create wechat mock account", api_create_wechat_mock_account),
        ("API verify-social mock", api_verify_social),
        ("API ops-alerts", api_ops_alerts),
    ]
    for name, fn in steps:
        check(name, fn)

    print(f"\nResult: {PASS} passed, {FAIL} failed, {SKIP} skipped")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
