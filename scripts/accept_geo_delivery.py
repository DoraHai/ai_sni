"""GEO MVP delivery acceptance: content main path (Brief → facts → generate → variants → gates).

Usage:
  python scripts/accept_geo_delivery.py [BASE] [API_KEY] [TENANT_ID]

Default BASE=http://127.0.0.1:8011  API_KEY=geo-demo-local-key  TENANT_ID=1

Requires a running GEO API. LLM recommended for generate/suggest; heuristic still exercised.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime

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


def check(name: str, fn) -> None:
    global PASS, FAIL
    try:
        fn()
        print(f"[PASS] {name}")
        PASS += 1
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {name}: {exc}")
        FAIL += 1


def ensure_verified_facts(min_n: int = 3) -> list[int]:
    _, facts = req("GET", f"/api/v1/geo/facts?tenant_id={TENANT_ID}&status=active", expect=200)
    items = facts.get("items") or []
    verified = [f for f in items if f.get("trust_level") == "verified"]
    ids = [int(f["id"]) for f in verified[:min_n]]
    if len(ids) >= min_n:
        return ids

    # create + verify more
    need = min_n - len(ids)
    stamp = int(datetime.utcnow().timestamp())
    for i in range(need):
        _, created = req(
            "POST",
            "/api/v1/geo/facts",
            {
                "tenant_id": TENANT_ID,
                "title": f"交付验收事实 {stamp}-{i}",
                "statement": f"可核验陈述 {stamp}-{i}：覆盖 80% 场景，周期约 14 天，服务 120 家客户。",
                "fact_type": "product",
                "source_name": "交付验收源",
                "trust_level": "needs_review",
                "status": "active",
            },
            expect=200,
        )
        fid = int(created["id"])
        req(
            "POST",
            f"/api/v1/geo/facts/{fid}/verify?tenant_id={TENANT_ID}",
            expect=200,
        )
        ids.append(fid)
    return ids[:min_n]


def main() -> int:
    print(f"Delivery accept BASE={BASE} TENANT_ID={TENANT_ID}")
    state: dict = {}

    def health():
        _, h = req("GET", "/api/v1/geo/content-health", expect=200)
        assert h.get("status") == "ok"

    def verified_facts():
        ids = ensure_verified_facts(3)
        assert len(ids) >= 3, ids
        state["fact_ids"] = ids

    def create_task_with_prompt():
        stamp = int(datetime.utcnow().timestamp())
        _, p = req(
            "POST",
            "/api/v1/geo/prompts",
            {
                "tenant_id": TENANT_ID,
                "question": f"交付验收：制造业如何选择私有化数据分析平台？#{stamp}",
                "priority": 5,
                "tags": ["delivery_accept"],
                "source": "manual",
                "question_group": "推荐",
                "is_brand_probe": False,
            },
            expect=200,
        )
        pid = int(p["id"])
        _, task = req(
            "POST",
            "/api/v1/geo/content-tasks",
            {
                "tenant_id": TENANT_ID,
                "prompt_id": pid,
                "title": f"交付验收任务 {stamp}",
                "target_channels": ["website", "wechat", "zhihu"],
                "brief": {},
            },
            expect=200,
        )
        state["task_id"] = int(task["id"])
        state["prompt_id"] = pid

    def suggest_brief_fills():
        tid = state["task_id"]
        _, res = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/suggest-brief?tenant_id={TENANT_ID}",
            {"overwrite": True, "use_llm": True},
            expect=200,
            timeout=90,
        )
        sb = res.get("suggested_brief") or {}
        for key in ("industry", "audience", "intent", "content_type", "cta"):
            assert str(sb.get(key) or "").strip(), f"missing suggested {key}: {sb}"
        state["brief"] = sb
        # persist
        _, task = req(
            "PATCH",
            f"/api/v1/geo/content-tasks/{tid}?tenant_id={TENANT_ID}",
            {"brief": sb},
            expect=200,
        )
        assert task.get("brief_ready") is True or all(
            str((task.get("brief") or {}).get(k) or "").strip()
            for k in ("industry", "audience", "intent", "content_type", "cta")
        )

    def retrieve_non_empty():
        tid = state["task_id"]
        _, res = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/retrieve-facts?tenant_id={TENANT_ID}",
            {"limit": 8, "verified_only": False},
            expect=200,
        )
        items = res.get("items") or []
        assert len(items) >= 1, f"retrieve empty: {res.get('query_meta')}"
        assert (res.get("count") is None) or res["count"] >= 1

    def bind_facts():
        tid = state["task_id"]
        ids = state["fact_ids"]
        _, task = req(
            "PUT",
            f"/api/v1/geo/content-tasks/{tid}/facts?tenant_id={TENANT_ID}",
            {"fact_ids": ids},
            expect=200,
        )
        assert len(task.get("facts") or []) >= 3
        assert task.get("status") in ("facts_bound", "ready", "needs_fix", "editing", "draft")

    def generate_master():
        tid = state["task_id"]
        code, task = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/generate?tenant_id={TENANT_ID}",
            expect=None,
            timeout=120,
        )
        if code != 200:
            # Allow soft skip only when LLM not configured; still fail if brief/facts gate wrong
            detail = str((task or {}).get("detail") or task)
            if "API Key" in detail or "未配置" in detail or "AI" in detail:
                print(f"  [WARN] generate skipped (LLM): {detail[:160]}")
                state["article_ok"] = False
                return
            raise AssertionError(f"generate -> {code}: {task}")
        art = task.get("article") or {}
        assert (art.get("body_markdown") or "").strip(), "empty master body"
        state["article_ok"] = True

    def apply_one_patch_if_needed():
        assert state.get("task_id"), "task not created"
        if not state.get("article_ok"):
            raise AssertionError("no master article — generate step must pass first")
        tid = state["task_id"]
        _, chk = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/check?tenant_id={TENANT_ID}&require_channels=false",
            expect=200,
        )
        patches = chk.get("patches") or []
        if not patches:
            return
        code = patches[0]["code"]
        before = len(((chk.get("task") or {}).get("article") or {}).get("body_markdown") or "")
        _, res = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/apply-patch?tenant_id={TENANT_ID}",
            {"code": code},
            expect=200,
        )
        assert res.get("body_changed") is True or (res.get("body_len_after") or 0) > before
        assert "geo_score" in res
        art = (res.get("article") or (res.get("task") or {}).get("article") or {})
        assert (art.get("body_markdown") or "").strip()

    def variants_and_channel_rule():
        assert state.get("task_id"), "task not created"
        if not state.get("article_ok"):
            raise AssertionError("no master article — generate step must pass first")
        tid = state["task_id"]
        _, task = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/variants?tenant_id={TENANT_ID}",
            {"channels": ["website", "wechat", "zhihu"]},
            expect=200,
        )
        channels = {v.get("channel") for v in (task.get("variants") or [])}
        assert {"website", "wechat", "zhihu"} <= channels, channels
        # rule_result should be refreshed after variants
        checks = (task.get("rule_result") or {}).get("checks") or []
        ch = next((c for c in checks if c.get("code") == "channel_variant_ready"), None)
        if ch is not None:
            assert ch.get("passed") is True, ch
        _, chk = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/check?tenant_id={TENANT_ID}&require_channels=true",
            expect=200,
        )
        ch2 = next(c for c in (chk.get("checks") or []) if c.get("code") == "channel_variant_ready")
        assert ch2.get("passed") is True, ch2

    def publish_blocked_without_review():
        assert state.get("task_id"), "task not created"
        if not state.get("article_ok"):
            raise AssertionError("no master article — generate step must pass first")
        tid = state["task_id"]
        # ensure variants exist
        req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/variants?tenant_id={TENANT_ID}",
            {"channels": ["website"]},
            expect=200,
        )
        code, payload = req(
            "POST",
            f"/api/v1/geo/content-tasks/{tid}/publications",
            {
                "tenant_id": TENANT_ID,
                "channel": "website",
                "published_url": "https://example.com/geo-delivery-accept",
                "note": "accept",
            },
        )
        assert code == 400, payload
        detail = str(payload.get("detail") or "")
        assert "审校" in detail or "就绪" in detail or "规则" in detail or "门禁" in detail, detail

    check("content-health", health)
    check("≥3 verified facts", verified_facts)
    check("create prompt + task", create_task_with_prompt)
    check("suggest-brief fills required fields + save", suggest_brief_fills)
    check("retrieve-facts non-empty", retrieve_non_empty)
    check("bind ≥3 facts", bind_facts)
    check("generate master article", generate_master)
    check("apply-patch changes body + score", apply_one_patch_if_needed)
    check("variants refresh channel_variant_ready", variants_and_channel_rule)
    check("publish blocked without review/ready", publish_blocked_without_review)

    print(f"\nResult: {PASS} passed, {FAIL} failed")
    if state.get("task_id"):
        print(f"Created task_id={state['task_id']} (safe to keep as accept sample)")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
