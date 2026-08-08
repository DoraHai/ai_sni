"""M1 stage acceptance against a running GEO API (default :8011)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
API_KEY = sys.argv[2] if len(sys.argv) > 2 else "geo-demo-local-key"
TENANT_ID = int(sys.argv[3]) if len(sys.argv) > 3 else 1

PASS = 0
FAIL = 0


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
        with urllib.request.urlopen(request, timeout=30) as resp:
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
    if expect is not None and code != expect:
        raise AssertionError(f"{method} {path} -> {code} (want {expect}): {payload}")
    return code, payload


def check(name: str, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"[PASS] {name}")
        PASS += 1
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {name}: {exc}")
        FAIL += 1


def main() -> int:
    print(f"M1 accept BASE={BASE} TENANT_ID={TENANT_ID}")

    def health():
        _, h = req("GET", "/api/v1/geo/content-health", expect=200)
        assert h.get("status") == "ok"

    def content_stats_and_citations():
        _, stats = req("GET", f"/api/v1/geo/content-stats?tenant_id={TENANT_ID}", expect=200)
        for key in (
            "visibility_mention_rate",
            "snapshots_with_citations",
            "distinct_cited_domains",
            "snapshots_with_competitors",
        ):
            assert key in stats, f"missing {key}"
        _, cites = req("GET", f"/api/v1/geo/citation-insights?tenant_id={TENANT_ID}", expect=200)
        assert "items" in cites
        assert "own_domain_cite_rate" in cites or cites.get("own_domains") is not None

    def extract_urls():
        code, data = req(
            "POST",
            "/api/v1/geo/answer-snapshots/extract-urls",
            {
                "tenant_id": TENANT_ID,
                "raw_text": "参见 https://www.zhihu.com/question/1 与 https://toutiao.com/a/2。",
            },
            expect=200,
        )
        urls = data.get("suggested_cited_urls") or []
        assert "https://www.zhihu.com/question/1" in urls
        assert "https://toutiao.com/a/2" in urls

    def visibility_snapshot_loop():
        _, prompts = req("GET", f"/api/v1/geo/prompts?tenant_id={TENANT_ID}", expect=200)
        items = prompts.get("items") or []
        if not items:
            _, created = req(
                "POST",
                "/api/v1/geo/prompts",
                {
                    "tenant_id": TENANT_ID,
                    "question": "B2B 获客平台怎么选？有哪些推荐？",
                    "priority": 10,
                    "tags": ["accept_m1"],
                    "source": "manual",
                    "question_group": "推荐",
                    "is_brand_probe": False,
                },
                expect=200,
            )
            pid = created["id"]
        else:
            pid = items[0]["id"]
        _, snap = req(
            "POST",
            "/api/v1/geo/answer-snapshots",
            {
                "tenant_id": TENANT_ID,
                "prompt_id": pid,
                "engine": "chatgpt",
                "raw_text": (
                    "可以看 Tableau、PowerBI；也有人提到 GrowthSniper。"
                    "参考 https://zhuanlan.zhihu.com/p/1"
                ),
                "mentions_brand": True,
                "competitors": ["Tableau", "PowerBI"],
                "brand_position": "mentioned",
                "sentiment": "positive",
                "cited_urls": [],
                "note": "accept-m1",
            },
            expect=200,
        )
        assert snap.get("cited_urls"), "empty cited_urls should autofill from text"
        assert any("zhihu.com" in u for u in snap["cited_urls"])
        _, comps = req(
            "GET", f"/api/v1/geo/competitor-insights?tenant_id={TENANT_ID}", expect=200
        )
        names = {i["name"] for i in comps.get("items") or []}
        assert "Tableau" in names
        _, evals = req(
            "GET", f"/api/v1/geo/evaluation-insights?tenant_id={TENANT_ID}", expect=200
        )
        assert (evals.get("sentiment_counts") or {}).get("positive", 0) >= 1
        _, cites = req(
            "GET", f"/api/v1/geo/citation-insights?tenant_id={TENANT_ID}", expect=200
        )
        domains = {i["domain"] for i in cites.get("items") or []}
        assert "zhuanlan.zhihu.com" in domains or "zhihu.com" in domains

    def probe_hygiene_fields():
        _, stats = req("GET", f"/api/v1/geo/content-stats?tenant_id={TENANT_ID}", expect=200)
        assert "snapshots_visibility" in stats
        assert "probe_recognition_rate" in stats
        # rate may be null if only probes; key must exist
        assert "visibility_mention_rate" in stats

    def period_diff():
        now = datetime.utcnow()
        after_to = now.isoformat(timespec="seconds") + "Z"
        after_from = (now - timedelta(days=14)).isoformat(timespec="seconds") + "Z"
        before_to = (now - timedelta(days=14, minutes=1)).isoformat(timespec="seconds") + "Z"
        before_from = (now - timedelta(days=28)).isoformat(timespec="seconds") + "Z"
        path = (
            f"/api/v1/geo/visibility-period-diff?tenant_id={TENANT_ID}"
            f"&before_from={before_from}&before_to={before_to}"
            f"&after_from={after_from}&after_to={after_to}"
        )
        _, data = req("GET", path, expect=200)
        assert "before" in data and "after" in data and "delta" in data
        assert "visibility_mention_rate" in data["delta"]

    def publishing_channels():
        _, ch = req(
            "GET", f"/api/v1/geo/publishing-channels?tenant_id={TENANT_ID}", expect=200
        )
        items = ch.get("items") or []
        assert len(items) >= 5
        types = {i.get("channel_type") for i in items}
        assert "website" in types

    def webhook_guard_without_export():
        """Push must fail at publish gate on a *fresh* task (no export/review)."""
        _, ch = req(
            "GET", f"/api/v1/geo/publishing-channels?tenant_id={TENANT_ID}", expect=200
        )
        website = next(i for i in ch["items"] if i.get("channel_type") == "website")
        _, acc = req(
            "POST",
            "/api/v1/geo/channel-accounts",
            {
                "tenant_id": TENANT_ID,
                "channel_id": website["id"],
                "display_name": f"accept-webhook-{int(datetime.utcnow().timestamp())}",
                "auth_type": "webhook",
                "credentials": {
                    "webhook_url": "https://example.com/hooks/geo-accept",
                    "method": "POST",
                },
            },
            expect=200,
        )
        assert acc.get("has_credentials") is True
        assert "webhook_url" not in json.dumps(acc)
        # Create empty task so push cannot succeed (avoids flaky first-list-item already published)
        stamp = int(datetime.utcnow().timestamp())
        _, pr = req(
            "POST",
            "/api/v1/geo/prompts",
            {
                "tenant_id": TENANT_ID,
                "question": f"m1-webhook-gate-{stamp}",
                "status": "active",
            },
            expect=200,
        )
        _, task = req(
            "POST",
            "/api/v1/geo/content-tasks",
            {
                "tenant_id": TENANT_ID,
                "prompt_id": pr["id"],
                "title": f"m1-webhook-gate-{stamp}",
            },
            expect=200,
        )
        tid = task["id"]
        code, payload = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/push",
            {
                "tenant_id": TENANT_ID,
                "channel": "website",
                "account_id": acc["id"],
                "mode": "draft",
                "create_publication": False,
            },
        )
        assert code == 400, payload
        detail = str(payload.get("detail") or "")
        # Must be a *gate* error, not upstream webhook HTTP status (that would mean push ran)
        assert "Webhook 返回" not in detail, detail
        assert any(
            k in detail
            for k in (
                "导出",
                "审校",
                "渠道",
                "门禁",
                "生成",
                "就绪",
                "禁止",
                "内网",
                "本机",
                "事实",
                "规则",
                "母稿",
                "变体",
            )
        ), detail

    def static_pages():
        for path in (
            "/geo/dashboard.html",
            "/geo/citations.html",
            "/geo/visibility.html",
            "/geo/channels.html",
        ):
            request = urllib.request.Request(f"http://127.0.0.1:5176{path}")
            with urllib.request.urlopen(request, timeout=10) as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8", errors="replace")
                assert "<html" in body.lower()

    check("content-health", health)
    check("content-stats + citation-insights keys", content_stats_and_citations)
    check("extract-urls from answer text", extract_urls)
    check("snapshot → competitor/evaluation/citation", visibility_snapshot_loop)
    check("D0 visibility hygiene fields on stats", probe_hygiene_fields)
    check("visibility-period-diff", period_diff)
    check("publishing-channels bootstrap", publishing_channels)
    check("webhook push blocked without ready export", webhook_guard_without_export)
    check("static geo pages on :5176", static_pages)

    print(f"\nResult: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
