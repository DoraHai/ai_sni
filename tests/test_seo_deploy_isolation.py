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


def test_deployment_runtime_and_nginx_are_outside_minimal_sync() -> None:
    assert not (ROOT / "deploy/seo-service.service").exists()
    assert not (ROOT / "deploy/seo-frontend.nginx.conf").exists()


def test_deployment_module_is_outside_minimal_sync() -> None:
    assert not (ROOT / "ops/platform-deploy/modules/seo").exists()


def test_production_deploy_workflow_is_outside_minimal_sync() -> None:
    assert not (ROOT / ".github/workflows/production-seo-deploy.yml").exists()


def test_shared_ci_keeps_sem_production_guards_unchanged() -> None:
    workflow = _read(".github/workflows/ci.yml")
    assert "codex/production-sem" in workflow
    assert "sem-frontend-build:" in workflow
    assert "deploy-sem:" in workflow


def test_frontend_exposes_explicit_seo_build_contract() -> None:
    package = _read("frontend/package.json")
    assert '"build:seo"' in package
    assert '"verify:seo-build"' in package
