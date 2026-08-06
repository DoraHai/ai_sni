"""Step-1 delivery closeout verification (code + API + static pages)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
API_KEY = sys.argv[2] if len(sys.argv) > 2 else "geo-demo-local-key"
TENANT_ID = int(sys.argv[3]) if len(sys.argv) > 3 else 1

PASS = 0
FAIL = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""))
        PASS += 1
    else:
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def req(method: str, path: str, body: dict | None = None, timeout: int = 60):
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


def main() -> int:
    print(f"Step-1 verify BASE={BASE} TENANT={TENANT_ID}\n")

    # --- Code (V6 / N2 / S3 / S4) ---
    vue = (ROOT / "frontend/src/views/geo/GeoTaskEditorView.vue").read_text(encoding="utf-8")
    static = (
        ROOT / "frontend/public/deal-sniper-prototype/geo/editor.html"
    ).read_text(encoding="utf-8")

    ok("V6 Vue generate toast + hint", "母稿已生成" in vue and "generateHint" in vue)
    ok("V6 needs_fix explained", "needs_fix" in vue and "补丁修齐" in vue)
    ok("N2 publishGateHint 审校", "publishGateHint" in vue and "未通过审校" in vue)
    ok(
        "N2 button not master-only hard disable",
        ':disabled="docTab === \'master\'"' not in vue
        or "publishGateHint" in vue and "回填 URL" in vue,
    )
    ok("S3 static AI 建议 Brief", "btnSuggestBrief" in static and "suggested_brief" in static)
    ok("S4 static generate feedback", "母稿已生成" in static and "bodyLen" in static)
    ok(
        "S4 static patch apply feedback",
        "applyPatch" in static or "插入修复" in static,
    )

    # --- Static pages S1/S2 ---
    for path, want in (("/geo/dashboard.html", 200), ("/dashboard.html", 404)):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:5176{path}", timeout=5) as resp:
                code = resp.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        except Exception as exc:  # noqa: BLE001
            code = 0
            detail = str(exc)
            ok(f"S1/S2 {path}", False, detail)
            continue
        ok(f"S1/S2 {path} -> {want}", code == want, f"got {code}")

    # Static editor loads
    try:
        url = (
            "http://127.0.0.1:5176/geo/editor.html"
            f"?tenant_id={TENANT_ID}&api_key={API_KEY}"
            f"&api_origin={BASE}&task_id=6"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        ok(
            "S3 editor.html loads",
            resp.status == 200
            and "btnGenerate" in body
            and "btnSuggestBrief" in body,
        )
    except Exception as exc:  # noqa: BLE001
        ok("S3 editor.html loads", False, str(exc))

    # --- N2 API: publish without review ---
    code, tasks = req("GET", f"/api/v1/geo/content-tasks?tenant_id={TENANT_ID}")
    items = (tasks or {}).get("items") or []
    tid = None
    for t in items:
        _, d = req("GET", f"/api/v1/geo/content-tasks/{t['id']}?tenant_id={TENANT_ID}")
        if not d.get("article"):
            continue
        if d.get("review_status") == "approved":
            continue
        if not (d.get("variants") or []):
            req(
                "POST",
                f"/api/v1/geo/content-tasks/{t['id']}/variants?tenant_id={TENANT_ID}",
                {"channels": ["website"]},
            )
        tid = t["id"]
        break

    if tid is None:
        ok("N2 publish 400 without review", False, "no unapproved task with article")
    else:
        code, payload = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/publications",
            {
                "tenant_id": TENANT_ID,
                "channel": "website",
                "published_url": "https://example.com/step1-n2",
                "note": "step1",
            },
        )
        detail = str((payload or {}).get("detail") or payload)
        ok(
            "N2 publish 400 + 审校/门禁文案",
            code == 400
            and any(k in detail for k in ("审校", "门禁", "就绪", "规则")),
            f"task={tid} code={code} detail={detail[:100]}",
        )

    # Health
    code, h = req("GET", "/api/v1/geo/content-health")
    ok("API content-health", code == 200 and (h or {}).get("status") == "ok")

    print(f"\nResult: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
