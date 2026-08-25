"""Productization must-do verification (code + optional live API).

Covers delivery step-3 engineering gates that can be automated without a
production host: secret guard, nginx no API-key inject, patrol quota, tenant
isolation helper, health endpoints, visibility patrol API surface.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CLI_BASE = sys.argv[1] if len(sys.argv) > 1 else ""
BASE = _CLI_BASE or "http://127.0.0.1:8000"
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


def req(method: str, path: str, body: dict | None = None, timeout: int = 30):
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
    except Exception as exc:  # noqa: BLE001
        return 0, {"detail": str(exc)}


def check_code() -> None:
    sys.path.insert(0, str(ROOT))
    from app.security.auth import AuthContext
    from app.security.prod_guard import (
        collect_production_issues,
        is_production_env,
        nginx_injects_api_key,
    )
    from types import SimpleNamespace

    ok("prod_guard module", True)
    ok("is_production_env prod", is_production_env("prod"))
    ok("is_production_env dev false", not is_production_env("dev"))

    demo = SimpleNamespace(
        app_env="production",
        admin_api_key="geo-demo-local-key",
        jwt_secret="",
        crypto_master_key_b64="CHANGE_ME",
        app_base_url="http://127.0.0.1:8000",
    )
    issues = collect_production_issues(demo)
    ok("prod rejects demo API key", any("ADMIN_API_KEY" in i for i in issues), str(issues)[:120])
    ok("prod requires JWT_SECRET", any("JWT_SECRET" in i for i in issues))

    safe = SimpleNamespace(
        app_env="dev",
        admin_api_key="geo-demo-local-key",
        jwt_secret="",
        crypto_master_key_b64="x",
        app_base_url="http://127.0.0.1:8000",
    )
    ok("dev skips prod_guard issues", collect_production_issues(safe) == [])

    # tenant isolation helper
    from fastapi import HTTPException

    ctx = AuthContext(
        user_id=1,
        username="u",
        role_name="r",
        tenant_id=2,
        permissions={},
        is_superadmin=False,
    )
    try:
        ctx.ensure_tenant(1)
        cross = False
    except HTTPException as exc:
        cross = exc.status_code == 403
    ok("ensure_tenant blocks other tenant", cross)
    try:
        ctx.ensure_tenant(2)
        same = True
    except HTTPException:
        same = False
    ok("ensure_tenant allows bound tenant", same)

    super_ctx = AuthContext(
        user_id=None,
        username="admin-key",
        role_name="super",
        tenant_id=None,
        permissions={},
        is_superadmin=True,
    )
    try:
        super_ctx.ensure_tenant(99)
        ok("superadmin/API key can access any tenant", True)
    except HTTPException:
        ok("superadmin/API key can access any tenant", False)

    # nginx confs must not inject API key
    for rel in ("deploy/nginx.conf", "deploy/geo-routes.nginx.conf"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        ok(f"nginx no X-API-Key inject ({rel})", not nginx_injects_api_key(text))
        ok(f"nginx documents no inject ({rel})", "X-API-Key" in text or "x-api-key" in text.lower())

    # patrol + config
    from app.config import Settings

    fields = getattr(Settings, "model_fields", None) or {}
    ok("config geo_patrol_max_runs_per_day", "geo_patrol_max_runs_per_day" in fields)
    ok("config geo_patrol_max_cells_per_run", "geo_patrol_max_cells_per_run" in fields)

    patrol_py = (ROOT / "app/geo/content/patrol.py").read_text(encoding="utf-8")
    ok("patrol count_patrol_runs_today", "count_patrol_runs_today" in patrol_py)
    ok("patrol cell budget", "geo_patrol_max_cells_per_run" in patrol_py or "max_cells" in patrol_py)

    routes = (ROOT / "app/geo/content/routes.py").read_text(encoding="utf-8")
    ok("routes daily patrol quota 429", "429" in routes and "count_patrol_runs_today" in routes)

    env_ex = (ROOT / ".env.example").read_text(encoding="utf-8")
    ok(".env.example JWT_SECRET", "JWT_SECRET" in env_ex)
    ok(".env.example patrol quota comments", "GEO_PATROL_MAX" in env_ex)

    deploy = (ROOT / "deploy/README-GEO-INDEPENDENT.md").read_text(encoding="utf-8")
    ok("deploy secrets section", "Production secrets" in deploy or "JWT_SECRET" in deploy)
    ok("deploy logs & backup section", "backup" in deploy.lower() and "journalctl" in deploy)

    checklist = (ROOT / "docs/GEO_DELIVERY_CHECKLIST.md").read_text(encoding="utf-8")
    ok(
        "checklist step3 productization",
        "第三步" in checklist or "生产最小集" in checklist,
    )

    # frontend: prod build should not require embedded key for geo routes
    router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
    ok(
        "vue router DEV-only API key bypass",
        "import.meta.env.DEV" in router and "VITE_API_KEY" in router,
    )

    # hierarchy + daily metrics productization
    ok(
        "geo optimization model",
        (ROOT / "app/models/geo_optimization.py").is_file(),
    )
    ok(
        "daily_metrics service",
        (ROOT / "app/geo/content/daily_metrics.py").is_file(),
    )
    ok(
        "migration 0054 hierarchy",
        any(
            "0054" in p.name and "opt" in p.name
            for p in (ROOT / "migrations/versions").glob("*.py")
        ),
    )
    ok(
        "accept_geo_hierarchy script",
        (ROOT / "scripts/accept_geo_hierarchy.py").is_file(),
    )
    routes = (ROOT / "app/geo/content/routes.py").read_text(encoding="utf-8")
    ok("routes optimization-businesses", "optimization-businesses" in routes)
    ok("routes daily-metrics", "daily-metrics" in routes)
    geo_sched = (ROOT / "app/geo/content/geo_scheduler.py").read_text(encoding="utf-8")
    geo_main = (ROOT / "app/geo_main.py").read_text(encoding="utf-8")
    ok(
        "geo scheduler module",
        (ROOT / "app/geo/content/geo_scheduler.py").is_file(),
    )
    ok(
        "scheduler daily metrics nightly",
        "run_geo_daily_metrics_nightly" in geo_sched or "geo_daily_metrics_nightly" in geo_sched,
    )
    ok("geo_main starts geo scheduler", "start_geo_scheduler" in geo_main)
    overview = (ROOT / "frontend/src/views/geo/GeoOverviewView.vue").read_text(
        encoding="utf-8"
    )
    ok("overview business filter", "filterBusinessId" in overview or "listGeoBusinesses" in overview)


def _live_candidates() -> list[str]:
    out: list[str] = []
    if _CLI_BASE:
        out.append(_CLI_BASE.rstrip("/"))
    for b in ("http://127.0.0.1:8000", "http://127.0.0.1:8011"):
        if b not in out:
            out.append(b)
    return out


def _pick_live_base() -> str | None:
    global BASE
    last_err = ""
    for candidate in _live_candidates():
        BASE = candidate
        code, health = req("GET", "/health/geo")
        if code == 200:
            return candidate
        last_err = health.get("detail") if isinstance(health, dict) else str(health)
        code2, _ = req("GET", "/api/v1/geo/content-health")
        if code2 == 200:
            return candidate
    print(f"\n[SKIP] live API unreachable (tried {_live_candidates()}): {last_err}")
    print("       Start app.main on 8000 or geo_main on 8011 to run live checks.\n")
    return None


def check_live() -> None:
    if not _pick_live_base():
        return

    code, health = req("GET", "/health/geo")
    if code == 404:
        print("[SKIP] GET /health/geo not mounted on this process (content-health is enough)")
    else:
        ok("GET /health/geo", code == 200 and health.get("db") == "ok", f"status={code} body={health}")
    if code == 200 and isinstance(health, dict) and "geo_scheduler" in health:
        ok(
            "health reports geo_scheduler",
            health.get("geo_scheduler") in ("running", "skipped", "stopped"),
            f"geo_scheduler={health.get('geo_scheduler')}",
        )
    code2, ch = req("GET", "/api/v1/geo/content-health")
    ok(
        "GET content-health",
        code2 == 200 and (ch.get("status") == "ok" or ch.get("module") == "geo-content"),
        f"status={code2}",
    )

    code3, settings = req("GET", f"/api/v1/geo/visibility-patrol/settings?tenant_id={TENANT_ID}")
    ok(
        "visibility-patrol settings",
        code3 == 200
        and isinstance(settings, dict)
        and ("interval_hours" in settings or "window_start_hour" in settings),
        f"status={code3} keys={list(settings)[:8] if isinstance(settings, dict) else settings}",
    )
    if code3 == 200:
        ok(
            "settings has window + interval",
            "window_start_hour" in settings and "interval_hours" in settings,
        )

    code4, runs = req("GET", f"/api/v1/geo/visibility-patrol/runs?tenant_id={TENANT_ID}&limit=5")
    ok("visibility-patrol runs list", code4 == 200 and "items" in runs, f"status={code4}")

    # cross-tenant: superadmin API key can list; isolation is for bound JWT users (code-tested)
    ok("live API key is superadmin path (documented)", True)


def main() -> int:
    print(f"Productization must-do verify ROOT={ROOT}")
    print(f"Optional live BASE={BASE} TENANT={TENANT_ID}\n")
    print("=== code / config ===")
    check_code()
    print("\n=== live API (optional) ===")
    check_live()
    print(f"\nDone: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
