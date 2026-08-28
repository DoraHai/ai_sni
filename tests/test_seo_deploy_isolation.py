from pathlib import Path


ROOT = Path(__file__).parents[1]
BASELINE_HEADERS = (
    'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;',
    'add_header X-Content-Type-Options "nosniff" always;',
    'add_header Referrer-Policy "strict-origin-when-cross-origin" always;',
    'add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;',
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _location_block(config: str, marker: str) -> str:
    start = config.index(marker)
    brace = config.index("{", start)
    depth = 0
    for index in range(brace, len(config)):
        if config[index] == "{":
            depth += 1
        elif config[index] == "}":
            depth -= 1
            if depth == 0:
                return config[start : index + 1]
    raise AssertionError(f"unterminated nginx location: {marker}")


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


def test_seo_cache_locations_repeat_security_headers() -> None:
    config = _read("deploy/seo-frontend.nginx.conf")
    for marker in (
        "location ^~ /seo/assets/",
        "location = /seo/index.html",
        "location /seo/",
    ):
        block = _location_block(config, marker)
        for header in BASELINE_HEADERS:
            assert header in block

    for marker in ("location = /seo/index.html", "location /seo/"):
        block = _location_block(config, marker)
        assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in block
        assert "frame-ancestors 'self'" in block
        assert 'add_header X-Frame-Options "DENY"' not in block


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
    assert "Apply SEO frontend and backend without database migration" in workflow
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
