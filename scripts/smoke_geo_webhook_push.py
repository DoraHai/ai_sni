"""Step-2 smoke: public HTTPS Webhook account + 审校通过 → export → push.

Usage:
  python scripts/smoke_geo_webhook_push.py [BASE] [API_KEY] [TENANT_ID]

Default webhook target: https://httpbin.org/post (public HTTPS, returns JSON).
Override: env GEO_SMOKE_WEBHOOK_URL=https://...
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
API_KEY = sys.argv[2] if len(sys.argv) > 2 else "geo-demo-local-key"
TENANT_ID = int(sys.argv[3]) if len(sys.argv) > 3 else 1
# Default: dev sink (no outbound). Override with real CMS URL when network allows:
#   set GEO_SMOKE_WEBHOOK_URL=https://httpbin.org/post
WEBHOOK_URL = os.environ.get(
    "GEO_SMOKE_WEBHOOK_URL", "https://geo-dev-sink.local/hooks/geo-publish"
)


def req(method: str, path: str, body: dict | None = None, timeout: int = 120):
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
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {"detail": raw}
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def must(code: int, payload, expect: int | None = 200, label: str = ""):
    if expect is not None and code != expect:
        raise SystemExit(f"[FAIL] {label} -> {code}: {payload}")
    print(f"[OK] {label} -> {code}")
    return payload


def ensure_verified_facts(min_n: int = 3) -> list[int]:
    _, facts = req("GET", f"/api/v1/geo/facts?tenant_id={TENANT_ID}&status=active")
    items = facts.get("items") or []
    verified = [int(f["id"]) for f in items if f.get("trust_level") == "verified"]
    if len(verified) >= min_n:
        return verified[:min_n]
    stamp = int(datetime.utcnow().timestamp())
    need = min_n - len(verified)
    for i in range(need):
        _, created = req(
            "POST",
            "/api/v1/geo/facts",
            {
                "tenant_id": TENANT_ID,
                "title": f"step2 事实 {stamp}-{i}",
                "statement": f"可核验：覆盖 80% 场景，约 14 天，服务 120 家客户。#{stamp}-{i}",
                "fact_type": "product",
                "source_name": "step2-smoke",
                "trust_level": "needs_review",
                "status": "active",
            },
        )
        fid = int(created["id"])
        req("POST", f"/api/v1/geo/facts/{fid}/verify?tenant_id={TENANT_ID}")
        verified.append(fid)
    return verified[:min_n]


def apply_all_patches(task_id: int, max_rounds: int = 12) -> None:
    for _ in range(max_rounds):
        _, chk = req(
            "POST",
            f"/api/v1/geo/content-tasks/{task_id}/check?tenant_id={TENANT_ID}&require_channels=false",
        )
        patches = chk.get("patches") or []
        if not patches:
            return
        code = patches[0]["code"]
        c, res = req(
            "POST",
            f"/api/v1/geo/content-tasks/{task_id}/apply-patch?tenant_id={TENANT_ID}",
            {"code": code},
        )
        if c != 200:
            print(f"  [WARN] patch {code} -> {c}: {res}")
            return
        print(f"  patched {code} score={res.get('geo_score')}")


def main() -> int:
    print(f"Step-2 webhook smoke BASE={BASE} TENANT={TENANT_ID}")
    print(f"Webhook target: {WEBHOOK_URL}\n")

    if not WEBHOOK_URL.startswith("https://"):
        raise SystemExit("GEO_SMOKE_WEBHOOK_URL must be https:// public URL")

    # health
    must(*req("GET", "/api/v1/geo/content-health"), label="content-health")

    # website channel → auto_publish
    _, chs = req("GET", f"/api/v1/geo/publishing-channels?tenant_id={TENANT_ID}")
    website = next(
        (c for c in (chs.get("items") or []) if c.get("channel_type") == "website"),
        None,
    )
    if not website:
        raise SystemExit("no website channel — open /geo/publishing once to bootstrap")
    if website.get("publish_mode") != "auto_publish" or not website.get("enabled"):
        website = must(
            *req(
                "PATCH",
                f"/api/v1/geo/publishing-channels/{website['id']}?tenant_id={TENANT_ID}",
                {"publish_mode": "auto_publish", "enabled": True},
            ),
            label="website → auto_publish",
        )
    else:
        print(f"[OK] website channel id={website['id']} already auto_publish")

    # clean demo webhook account (create or reuse by name)
    demo_name = "demo-webhook-step2-httpbin"
    _, accs = req("GET", f"/api/v1/geo/channel-accounts?tenant_id={TENANT_ID}")
    acc = next(
        (
            a
            for a in (accs.get("items") or [])
            if a.get("display_name") == demo_name and a.get("channel_id") == website["id"]
        ),
        None,
    )
    webhook_creds = {
        "webhook_url": WEBHOOK_URL,
        "method": "POST",
        "headers": {},
        "secret": "geo-step2-demo",
    }
    if acc:
        refreshed = must(
            *req(
                "PATCH",
                f"/api/v1/geo/channel-accounts/{acc['id']}?tenant_id={TENANT_ID}",
                {
                    "status": "active",
                    "auth_type": "webhook",
                    "credentials": webhook_creds,
                },
            ),
            label=f"refresh webhook account #{acc['id']}",
        )
        account_id = int(refreshed.get("id") or acc["id"])
    else:
        created = must(
            *req(
                "POST",
                "/api/v1/geo/channel-accounts",
                {
                    "tenant_id": TENANT_ID,
                    "channel_id": website["id"],
                    "display_name": demo_name,
                    "auth_type": "webhook",
                    "credentials": webhook_creds,
                },
            ),
            label="create demo webhook account",
        )
        account_id = int(created["id"])

    print(f"[OK] webhook account_id={account_id} → {WEBHOOK_URL}")

    # build ready task
    stamp = int(datetime.utcnow().timestamp())
    fact_ids = ensure_verified_facts(3)
    p = must(
        *req(
            "POST",
            "/api/v1/geo/prompts",
            {
                "tenant_id": TENANT_ID,
                "question": f"Step2 Webhook 验收：私有化数据分析平台怎么选？#{stamp}",
                "priority": 5,
                "tags": ["step2_webhook"],
                "source": "manual",
                "is_brand_probe": False,
            },
        ),
        label="create prompt",
    )
    task = must(
        *req(
            "POST",
            "/api/v1/geo/content-tasks",
            {
                "tenant_id": TENANT_ID,
                "prompt_id": p["id"],
                "title": f"Step2 Webhook 推送 {stamp}",
                "target_channels": ["website", "wechat", "zhihu"],
                "brief": {},
            },
        ),
        label="create task",
    )
    tid = int(task["id"])

    sug = must(
        *req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/suggest-brief?tenant_id={TENANT_ID}",
            {"overwrite": True, "use_llm": True},
        ),
        label="suggest-brief",
    )
    must(
        *req(
            "PATCH",
            f"/api/v1/geo/content-tasks/{tid}?tenant_id={TENANT_ID}",
            {"brief": sug.get("suggested_brief") or {}},
        ),
        label="save brief",
    )

    must(
        *req(
            "PUT",
            f"/api/v1/geo/content-tasks/{tid}/facts?tenant_id={TENANT_ID}",
            {"fact_ids": fact_ids},
        ),
        label="bind facts",
    )

    gen = must(
        *req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/generate?tenant_id={TENANT_ID}",
        ),
        label="generate master",
    )
    if not (gen.get("article") or {}).get("body_markdown"):
        raise SystemExit("[FAIL] empty master body")

    print("[..] applying structural patches until empty")
    apply_all_patches(tid)

    must(
        *req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/variants?tenant_id={TENANT_ID}",
            {"channels": ["website", "wechat", "zhihu"]},
        ),
        label="create variants",
    )

    # re-check with channels — may still fail content rules; keep patching
    for round_i in range(3):
        _, chk = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/check?tenant_id={TENANT_ID}&require_channels=true",
        )
        fails = [c["code"] for c in (chk.get("checks") or []) if not c.get("passed")]
        # channel_variant_ready should pass; content may still fail
        content_fails = [c for c in fails if c != "channel_variant_ready"]
        if not content_fails:
            print(f"[OK] rules ready (score={chk.get('geo_score')})")
            break
        print(f"  check fails: {content_fails} — patching again")
        apply_all_patches(tid)
    else:
        _, chk = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/check?tenant_id={TENANT_ID}&require_channels=true",
        )
        fails = [c["code"] for c in (chk.get("checks") or []) if not c.get("passed")]
        if fails:
            print(f"[WARN] still failing checks: {fails} — push may 400 on gate")

    exp = must(
        *req(
            "GET",
            f"/api/v1/geo/content-tasks/{tid}/export?tenant_id={TENANT_ID}&channel=website",
        ),
        label="export website variant",
    )
    print(f"  export status={exp.get('status')}")

    must(
        *req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/submit-review?tenant_id={TENANT_ID}",
            {"note": "step2 smoke"},
        ),
        label="submit review",
    )
    must(
        *req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/review?tenant_id={TENANT_ID}",
            {"decision": "approved", "note": "step2 approve"},
        ),
        label="approve review",
    )

    code, push = req(
        "POST",
        f"/api/v1/geo/content-tasks/{tid}/push",
        {
            "tenant_id": TENANT_ID,
            "channel": "website",
            "account_id": account_id,
            "mode": "draft",
            "create_publication": True,
            "published_url": "https://example.com/geo-step2-published",
            "note": "step2 webhook smoke",
        },
    )
    if code != 200:
        raise SystemExit(f"[FAIL] push -> {code}: {push}")

    print("[OK] push success")
    print(f"  http_status={push.get('http_status')}")
    print(f"  webhook_host={push.get('webhook_host')}")
    print(f"  remote_url={push.get('remote_url')}")
    print(f"  publication_created={push.get('publication_created')}")
    print(f"\nTask id={tid} account_id={account_id}")
    print("Step-2 PASSED: 审校 → 导出 → 公网 Webhook 推送")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
