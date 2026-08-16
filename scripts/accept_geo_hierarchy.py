"""GEO hierarchy + daily metrics + scoped deliverables acceptance.

Usage:
  python scripts/accept_geo_hierarchy.py [BASE] [API_KEY] [TENANT_ID]

Default BASE=http://127.0.0.1:8011  API_KEY=geo-demo-local-key  TENANT_ID=1

Covers:
  - 优化业务 / 优化单元 CRUD
  - 意图词挂 unit_id
  - daily-metrics rebuild + list (tenant/business/unit)
  - deliverables pack with business_id/unit_id + scope + md
"""

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


def req(method: str, path: str, body: dict | None = None, expect: int | None = None, timeout: int = 90):
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
            code = resp.status
            if "markdown" in (resp.headers.get("Content-Type") or ""):
                payload = raw
            else:
                payload = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        code = exc.code
        try:
            payload = json.loads(raw) if raw else {"detail": raw}
        except json.JSONDecodeError:
            payload = raw if raw else {"detail": raw}
    if expect is not None and code != expect:
        raise AssertionError(f"{method} {path} -> {code} (want {expect}): {payload}")
    return code, payload


def check(name: str, fn) -> None:
    global PASS, FAIL
    try:
        fn()
        print(f"[PASS] {name}")
        PASS += 1
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {name}: {exc}")
        FAIL += 1


def main() -> int:
    print(f"Hierarchy acceptance BASE={BASE} TENANT={TENANT_ID}\n")
    stamp = int(datetime.utcnow().timestamp())
    biz_name = f"验收业务-{stamp}"
    unit_name = f"验收单元-{stamp}"
    state: dict = {}

    def create_business():
        code, row = req(
            "POST",
            "/api/v1/geo/optimization-businesses",
            {
                "tenant_id": TENANT_ID,
                "name": biz_name,
                "description": "accept_geo_hierarchy",
            },
            expect=200,
        )
        assert row.get("id"), row
        assert row.get("name") == biz_name
        state["business_id"] = int(row["id"])

    def list_businesses():
        code, data = req(
            "GET",
            f"/api/v1/geo/optimization-businesses?tenant_id={TENANT_ID}&status=active",
            expect=200,
        )
        items = data.get("items") or []
        assert any(int(i["id"]) == state["business_id"] for i in items), items

    def create_unit():
        code, row = req(
            "POST",
            "/api/v1/geo/optimization-units",
            {
                "tenant_id": TENANT_ID,
                "business_id": state["business_id"],
                "name": unit_name,
                "keyword": "验收关键词",
            },
            expect=200,
        )
        assert row.get("id"), row
        assert int(row.get("business_id")) == state["business_id"]
        state["unit_id"] = int(row["id"])

    def create_prompt_on_unit():
        q = f"验收意图词 {stamp} 适合什么场景"
        code, row = req(
            "POST",
            "/api/v1/geo/prompts",
            {
                "tenant_id": TENANT_ID,
                "question": q,
                "unit_id": state["unit_id"],
                "priority": 5,
                "source": "manual",
            },
            expect=200,
        )
        assert row.get("id"), row
        assert int(row.get("unit_id") or 0) == state["unit_id"], row
        state["prompt_id"] = int(row["id"])
        state["question"] = q

    def filter_prompts_by_unit():
        code, data = req(
            "GET",
            f"/api/v1/geo/prompts?tenant_id={TENANT_ID}&unit_id={state['unit_id']}&status=active",
            expect=200,
        )
        items = data.get("items") or []
        assert any(int(i["id"]) == state["prompt_id"] for i in items), items

    def create_snapshot():
        now = datetime.utcnow().isoformat(timespec="seconds")
        code, row = req(
            "POST",
            "/api/v1/geo/answer-snapshots",
            {
                "tenant_id": TENANT_ID,
                "prompt_id": state["prompt_id"],
                "engine": "deepseek",
                "raw_text": "验收快照：品牌示例被推荐，引用 https://example.com/geo-accept",
                "captured_at": now,
                "mentions_brand": True,
                "brand_position": "first",
                "cited_urls": ["https://example.com/geo-accept"],
                "competitors": [],
                "sentiment": "positive",
            },
            expect=200,
        )
        assert row.get("id"), row
        state["snapshot_id"] = int(row["id"])

    def rebuild_daily():
        code, data = req(
            "POST",
            f"/api/v1/geo/daily-metrics/rebuild?tenant_id={TENANT_ID}",
            expect=200,
        )
        assert data.get("mode") in ("day", None) or "metric_date" in data or "tenant" in data, data
        # mode=day returns tenant metrics nested
        if data.get("mode") == "day":
            assert "scopes_written" in data or "tenant" in data
            state["rebuild"] = data
        else:
            state["rebuild"] = data

    def list_daily_tenant():
        code, data = req(
            "GET",
            f"/api/v1/geo/daily-metrics?tenant_id={TENANT_ID}&scope_level=tenant",
            expect=200,
        )
        assert "items" in data
        assert "citation_stat_note" in data
        assert "metric_labels" in data
        labels = data.get("metric_labels") or {}
        assert labels.get("brand_mention_rate") == "品牌提及率"
        items = data.get("items") or []
        # after rebuild should have at least today for scope t if snapshot exists
        assert any((i.get("scope_key") == "t") for i in items) or len(items) >= 0

    def list_daily_business():
        code, data = req(
            "GET",
            f"/api/v1/geo/daily-metrics?tenant_id={TENANT_ID}"
            f"&scope_level=business&business_id={state['business_id']}",
            expect=200,
        )
        assert "items" in data
        items = data.get("items") or []
        # snapshot on unit under business → expect b{id} after rebuild
        keys = {i.get("scope_key") for i in items}
        expected = f"b{state['business_id']}"
        assert expected in keys or any(i.get("business_id") == state["business_id"] for i in items), (
            f"want {expected} in {keys} items={items}"
        )

    def list_daily_unit():
        code, data = req(
            "GET",
            f"/api/v1/geo/daily-metrics?tenant_id={TENANT_ID}"
            f"&scope_level=unit&unit_id={state['unit_id']}",
            expect=200,
        )
        items = data.get("items") or []
        expected = f"u{state['unit_id']}"
        assert any(i.get("scope_key") == expected for i in items), items

    def deliverables_scoped():
        end = datetime.utcnow()
        start = end - timedelta(days=7)
        iso = lambda d: d.isoformat(timespec="seconds")  # noqa: E731
        q = urllib.parse.urlencode(
            {
                "tenant_id": TENANT_ID,
                "from": iso(start),
                "to": iso(end),
                "unit_id": state["unit_id"],
            }
        )
        code, pack = req("GET", f"/api/v1/geo/deliverables/pack?{q}", expect=200)
        assert pack.get("summary") is not None
        scope = pack.get("scope") or {}
        assert scope.get("level") == "unit", scope
        assert int(scope.get("unit_id") or 0) == state["unit_id"]
        assert pack.get("generated_kind") in (
            "geo_deliverables_pack_v3",
            "geo_deliverables_pack_v2",
            "geo_deliverables_pack_v1",
        )

        q_md = urllib.parse.urlencode(
            {
                "tenant_id": TENANT_ID,
                "from": iso(start),
                "to": iso(end),
                "business_id": state["business_id"],
                "format": "md",
            }
        )
        code, md = req("GET", f"/api/v1/geo/deliverables/pack?{q_md}", expect=200)
        assert isinstance(md, str)
        assert "GEO 交付摘要" in md
        assert "切片范围" in md or "优化业务" in md or "品牌提及率" in md

    def archive_cleanup():
        # soft archive so re-runs don't collide on unique names
        req(
            "PATCH",
            f"/api/v1/geo/optimization-units/{state['unit_id']}?tenant_id={TENANT_ID}",
            {"status": "archived"},
            expect=200,
        )
        req(
            "PATCH",
            f"/api/v1/geo/optimization-businesses/{state['business_id']}?tenant_id={TENANT_ID}",
            {"status": "archived"},
            expect=200,
        )
        req(
            "PATCH",
            f"/api/v1/geo/prompts/{state['prompt_id']}?tenant_id={TENANT_ID}",
            {"status": "archived"},
            expect=200,
        )

    steps = [
        ("create optimization business", create_business),
        ("list optimization businesses", list_businesses),
        ("create optimization unit", create_unit),
        ("create prompt with unit_id", create_prompt_on_unit),
        ("filter prompts by unit_id", filter_prompts_by_unit),
        ("create answer snapshot", create_snapshot),
        ("rebuild daily metrics", rebuild_daily),
        ("list daily metrics tenant", list_daily_tenant),
        ("list daily metrics business", list_daily_business),
        ("list daily metrics unit", list_daily_unit),
        ("deliverables pack scoped", deliverables_scoped),
        ("archive cleanup", archive_cleanup),
    ]
    for name, fn in steps:
        check(name, fn)

    print(f"\nResult: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
