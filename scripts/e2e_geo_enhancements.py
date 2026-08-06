"""HTTP-level critical path for productization enhancements (no browser)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

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
            ct = resp.headers.get("Content-Type") or ""
            if "markdown" in ct or path.endswith("format=md"):
                return resp.status, raw
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {"detail": raw}
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload
    except Exception as exc:  # noqa: BLE001
        return 0, {"detail": str(exc)}


def main() -> int:
    print(f"Enhancements e2e BASE={BASE} TENANT={TENANT_ID}\n")

    code, stats = req("GET", f"/api/v1/geo/content-stats?tenant_id={TENANT_ID}")
    ok("content-stats", code == 200 and isinstance(stats, dict), f"status={code}")
    if code == 200:
        ok("stats has probe_recognition_rate key", "probe_recognition_rate" in stats)
        ok("stats has visibility_top1_rate key", "visibility_top1_rate" in stats)
        ok("stats has metric_notes", isinstance(stats.get("metric_notes"), dict))

    end = datetime.utcnow()
    start = end - timedelta(days=14)
    mid = end - timedelta(days=7)
    iso = lambda d: d.isoformat(timespec="seconds")  # noqa: E731
    q = (
        f"/api/v1/geo/visibility-period-diff?tenant_id={TENANT_ID}"
        f"&before_from={iso(start)}&before_to={iso(mid)}"
        f"&after_from={iso(mid)}&after_to={iso(end)}"
    )
    code, diff = req("GET", q)
    ok("period-diff", code == 200 and "delta" in diff, f"status={code}")

    group_q = urllib.parse.urlencode({"tenant_id": TENANT_ID, "group": "推荐"})
    code, bp = req("GET", f"/api/v1/geo/channel-blueprint?{group_q}")
    ok(
        "channel-blueprint",
        code == 200
        and isinstance(bp, dict)
        and (bp.get("channels") is not None or bp.get("all_channels") is not None),
        f"status={code} detail={bp if code != 200 else 'ok'}",
    )

    code, ops = req("GET", f"/api/v1/geo/visibility-patrol/ops-status?tenant_id={TENANT_ID}")
    ok(
        "patrol ops-status",
        code == 200 and "quota" in ops and "engines" in ops,
        f"status={code}",
    )

    code, pack = req(
        "GET",
        f"/api/v1/geo/deliverables/pack?tenant_id={TENANT_ID}"
        f"&from={iso(start)}&to={iso(end)}",
    )
    ok("deliverables pack json", code == 200 and "summary" in pack, f"status={code}")
    if code == 200:
        ok(
            "deliverables summary visibility_mention_rate",
            "visibility_mention_rate" in (pack.get("summary") or {}),
        )

    code, md = req(
        "GET",
        f"/api/v1/geo/deliverables/pack?tenant_id={TENANT_ID}&format=md"
        f"&from={iso(start)}&to={iso(end)}",
    )
    ok(
        "deliverables markdown",
        code == 200 and isinstance(md, str) and "GEO 交付摘要" in md,
        f"status={code}",
    )

    print(f"\nResult: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
