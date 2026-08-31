import asyncio
from pathlib import Path
from unittest.mock import patch

from fastapi import Response

from app import seo_main


ROOT = Path(__file__).parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class _HealthResult:
    def __init__(self, revisions: list[str]):
        self.revisions = revisions

    def scalars(self):
        return self.revisions


class _HealthConnection:
    def __init__(self, revisions: list[str]):
        self.revisions = revisions

    async def execute(self, statement):
        return _HealthResult(self.revisions if "alembic_version" in str(statement) else [])


class _HealthContext:
    def __init__(self, revisions: list[str]):
        self.connection = _HealthConnection(revisions)

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class _HealthEngine:
    def __init__(self, revisions: list[str]):
        self.revisions = revisions

    def connect(self):
        return _HealthContext(self.revisions)


def test_seo_service_mounts_only_seo_routes() -> None:
    source = _read("app/seo_main.py")
    assert "from app.api.seo import router as seo_router" in source
    assert "from app.api.customer_modules import seo_sites_router" in source
    assert "app.include_router(seo_router)" in source
    assert "app.include_router(seo_sites_router)" in source
    assert "customer_modules_router" not in source
    assert "geo_projects_router" not in source
    assert "app.main" not in source
    assert "geo_router" not in source
    assert "from app.scheduler" not in source
    assert "start_seo_scheduler" in source
    assert "shutdown_seo_scheduler" in source
    assert 'SEO_REQUIRED_SCHEMA_REVISION = "0081_seo_monitor_cascade"' in source
    assert "SELECT version_num FROM alembic_version ORDER BY version_num" in source
    assert 'schema_status = "error"' in source
    assert "response.status_code = 503" in source


def test_seo_health_accepts_only_the_required_database_revision() -> None:
    response = Response()
    with patch.object(
        seo_main,
        "engine",
        _HealthEngine([seo_main.SEO_REQUIRED_SCHEMA_REVISION]),
    ):
        result = asyncio.run(seo_main.seo_health(response))

    assert response.status_code == 200
    assert result["db"] == "ok"
    assert result["schema"] == "ok"
    assert result["schema_revision"] == seo_main.SEO_REQUIRED_SCHEMA_REVISION


def test_seo_health_fails_closed_when_database_revision_is_stale() -> None:
    response = Response()
    with patch.object(seo_main, "engine", _HealthEngine(["0079_seo_content_review_workflow"])):
        result = asyncio.run(seo_main.seo_health(response))

    assert response.status_code == 503
    assert result["db"] == "error"
    assert result["schema"] == "error"
    assert "expected 0081_seo_monitor_cascade" in result["db_error"]


def test_seo_scheduler_registers_only_rank_collection() -> None:
    source = _read("app/seo_scheduler.py")
    assert 'id="collect_daily_seo_rankings"' in source
    assert "fetch_today_keyword_report" not in source
    assert "fetch_yesterday_keyword_report" not in source
    assert "purge_old_assistant_messages" not in source


def test_seo_service_has_dedicated_runtime_and_routes() -> None:
    service = _read("deploy/seo-service.service")
    nginx = _read("deploy/seo-frontend.nginx.conf")
    assert "app.seo_main:app" in service
    assert "127.0.0.1 --port 8020" in service
    assert "/opt/seo-service/current" in service
    assert "location ^~ /api/v1/seo/" in nginx
    assert "127.0.0.1:8020" in nginx
    assert "alias /opt/seo-frontend/current/assets/;" in nginx
    assert "alias /opt/seo-frontend/current/index.html;" in nginx
    assert "rewrite ^ /seo/index.html last;" in nginx
    assert "root /opt/seo-frontend/current;" not in nginx


def test_seo_deployer_never_restarts_other_modules_or_runs_migrations() -> None:
    module = _read("ops/platform-deploy/modules/seo")
    assert "backend_root='/opt/seo-service'" in module
    assert "frontend_root='/opt/seo-frontend'" in module
    assert "systemctl restart seo-service" in module
    assert "migration=not-run" in module
    assert "alembic upgrade" not in module
    assert "systemctl restart sem-backend" not in module
    assert "systemctl restart geo-service" not in module
    assert "/opt/geo-" not in module
    assert "/opt/sem-frontend" not in module


def test_seo_frontend_deployer_cannot_touch_backend_services_or_migrations() -> None:
    dispatcher = _read("ops/platform-deploy/modules/seo")
    module = _read("ops/platform-deploy/modules/seo-frontend")
    installer = _read("ops/platform-deploy/install-seo-frontend.sh")
    assert "DEPLOY_SEO_FRONTEND" in dispatcher
    assert "exec \"$frontend_entry\" \"$@\"" in dispatcher
    assert "frontend_root='/opt/seo-frontend'" in module
    assert "backend=not-included" in module
    assert "migration=not-run" in module
    assert "service_restart=not-run" in module
    assert "systemctl" not in module
    assert "alembic" not in module.lower()
    assert "/opt/seo-service" not in module
    assert "/etc/nginx" not in module
    assert "nginx -s" not in module
    assert "systemctl" not in installer
    assert "/etc/nginx" not in installer
    assert "/opt/seo-service" not in installer
    attributes = _read(".gitattributes")
    assert "/ops/platform-deploy/install-seo-frontend.sh text eol=lf" in attributes
    assert "/ops/platform-deploy/modules/seo text eol=lf" in attributes
    assert "/ops/platform-deploy/modules/seo-frontend text eol=lf" in attributes


def test_frontend_only_workflow_isolated_and_full_workflow_path_scoped() -> None:
    frontend = _read(".github/workflows/production-seo-frontend-deploy.yml")
    full = _read(".github/workflows/production-seo-deploy.yml")
    assert "DEPLOY_SEO_FRONTEND" in frontend
    assert "platform-deploy apply seo" in frontend
    assert "backend=not-included" in frontend
    assert "service_restart=not-run" in frontend
    assert "alembic upgrade" not in frontend.lower()
    assert "python -m alembic" not in frontend.lower()
    assert "systemctl" not in frontend
    assert "nginx" not in frontend.lower()
    assert "frontend/**" in frontend
    assert "app/**" not in frontend
    assert "migrations/**" not in frontend
    assert "frontend_only=false" in frontend
    assert "deploy/seo-service\\.service" in frontend
    assert "- app/**" in full
    assert "- migrations/**" in full
    assert "- frontend/**" not in full
    assert "production-seo-deployment" in frontend
    assert "production-seo-deployment" in full
    assert "linked_assets" in frontend
    assert "grep -Eho 'seo-[A-Za-z0-9_-]+\\.(js|css)'" in frontend


def test_production_workflow_auto_deploys_only_the_exact_production_head() -> None:
    workflow = _read(".github/workflows/production-seo-deploy.yml")
    assert "workflow_dispatch:" not in workflow
    assert "push:" in workflow
    assert "codex/production-seo" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert "environment: production\n" in workflow
    assert "environment: production-seo" not in workflow
    assert workflow.count('git ls-remote origin "refs/heads/$SEO_PRODUCTION_BRANCH"') >= 4
    assert "Refusing stale SEO release" in workflow
    assert "Refusing stale SEO deployment" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "DEPLOY_SEO" in workflow
    assert "platform-deploy apply seo" in workflow
    assert "migration=not-run" in workflow
    assert "alembic upgrade" not in workflow
    assert "Apply schema-compatible SEO release without running database migration" in workflow
    assert "tests/test_seo_scheduler.py" in workflow
    assert "production-sem" not in workflow
    assert "production-geo" not in workflow


def test_shared_ci_defers_production_seo_prs_to_seo_baseline() -> None:
    workflow = _read(".github/workflows/ci.yml")
    assert "branches-ignore:" in workflow
    assert "- codex/production-seo" in workflow


def test_frontend_exposes_explicit_seo_build_contract() -> None:
    package = _read("frontend/package.json")
    assert '"build:seo"' in package
    assert '"verify:seo-build"' in package
