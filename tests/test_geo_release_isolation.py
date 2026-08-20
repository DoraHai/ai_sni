"""Regression checks for the independently deployable GEO boundary."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_sem_backend_does_not_mount_geo_or_run_geo_jobs():
    main = _read("app/main.py")
    sem_scheduler = _read("app/scheduler.py")
    assert "geo_router" not in main
    assert "geo_oauth_public_router" not in main
    assert "run_geo_visibility_patrols" not in sem_scheduler
    assert "run_geo_daily_metrics_nightly" not in sem_scheduler


def test_geo_service_owns_routes_guard_and_scheduler():
    geo_main = _read("app/geo_main.py")
    geo_scheduler = _read("app/geo/scheduler.py")
    assert "app.include_router(geo_router)" in geo_main
    assert "app.include_router(geo_oauth_public_router)" in geo_main
    assert "start_geo_scheduler()" in geo_main
    assert "enforce_production_secrets" in geo_main
    assert "geo_visibility_patrols" in geo_scheduler
    assert "geo_daily_metrics_nightly" in geo_scheduler


def test_sem_frontend_has_no_geo_workbench_menu_or_routes():
    app = _read("frontend/src/App.vue")
    router = _read("frontend/src/router/index.js")
    main = _read("frontend/src/main.js")
    assert "GEO 增长" not in app
    assert "../views/geo/" not in router
    assert "'/geo/overview'" not in router
    assert "./styles/geo-page.css" not in main


def test_nginx_keeps_geo_in_the_independent_include():
    nginx = _read("deploy/nginx.conf")
    geo_routes = _read("deploy/geo-routes.nginx.conf")
    assert "include /etc/nginx/snippets/geo-routes.conf;" in nginx
    assert "127.0.0.1:8010" not in nginx
    assert "location ^~ /api/v1/geo/" in geo_routes
    assert "127.0.0.1:8010" in geo_routes


def test_static_geo_resolves_logged_in_tenant_context():
    api = _read("frontend/public/deal-sniper-prototype/geo/assets/geo-api-v1.js")
    workbench = _read(
        "frontend/public/deal-sniper-prototype/geo/assets/geo-workbench-v1.js"
    )
    assert "sessionStorage.getItem('sem_tenant_id')" in api
    assert "JSON.parse(raw).tenant_id" in api
    assert "'/api/v1/auth/tenants'" in api
    assert "resolveTenantContext" in api
    assert "当前客户" in workbench
    assert "正在识别当前客户" in workbench


def test_production_geo_deploy_is_scoped_and_does_not_migrate_database():
    module = _read("ops/platform-deploy/modules/geo")
    workflow = _read(".github/workflows/production-geo-deploy.yml")

    assert "/opt/geo-service" in module
    assert "/opt/geo-frontend" in module
    assert "/opt/sem-backend/.venv/bin/python" in module
    assert "systemctl restart geo-service" in module
    assert "systemctl restart sem-backend" not in module
    assert "/opt/sem-backend/releases" not in module
    assert "alembic upgrade" not in module
    assert "migration=not-run" in module
    assert "previous release restored" in module

    assert "codex/production-geo" in workflow
    assert "DEPLOY_GEO" in workflow
    assert "platform-deploy apply geo" in workflow
    assert "alembic upgrade" not in workflow
