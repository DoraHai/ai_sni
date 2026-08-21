from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_seo_service_mounts_only_seo_routes() -> None:
    source = _read("app/seo_main.py")
    assert "from app.api.seo import router as seo_router" in source
    assert "app.include_router(seo_router)" in source
    assert "app.main" not in source
    assert "geo_router" not in source
    assert "start_scheduler" not in source


def test_seo_service_has_dedicated_runtime_and_routes() -> None:
    service = _read("deploy/seo-service.service")
    nginx = _read("deploy/seo-frontend.nginx.conf")
    assert "app.seo_main:app" in service
    assert "127.0.0.1 --port 8020" in service
    assert "/opt/seo-service/current" in service
    assert "location ^~ /api/v1/seo/" in nginx
    assert "127.0.0.1:8020" in nginx


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


def test_production_workflow_auto_deploys_only_the_exact_production_head() -> None:
    workflow = _read(".github/workflows/production-seo-deploy.yml")
    assert "workflow_dispatch:" not in workflow
    assert "push:" in workflow
    assert "codex/production-seo" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert workflow.count('git ls-remote origin "refs/heads/$SEO_PRODUCTION_BRANCH"') >= 4
    assert "Refusing stale SEO release" in workflow
    assert "Refusing stale SEO deployment" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "DEPLOY_SEO" in workflow
    assert "platform-deploy apply seo" in workflow
    assert "migration=not-run" in workflow
    assert "alembic upgrade" not in workflow
    assert "Apply SEO frontend and backend without database migration" in workflow
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
