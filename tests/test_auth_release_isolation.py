"""Safety contracts for the isolated Auth release channel."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_auth_workflow_requires_exact_branch_head_and_verified_build():
    workflow = _read(".github/workflows/production-auth-deploy.yml")

    assert "AUTH_PRODUCTION_BRANCH: codex/production-auth" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$RELEASE_SHA"' in workflow
    assert workflow.count('git ls-remote origin "refs/heads/$AUTH_PRODUCTION_BRANCH"') >= 3
    assert "node --test scripts/test-auth-redirect.mjs" in workflow
    assert "npm run build:auth" in workflow
    assert "npm run verify:auth-build" in workflow
    assert "environment: production" in workflow


def test_auth_workflow_uses_existing_restricted_platform_channel():
    workflow = _read(".github/workflows/production-auth-deploy.yml")

    for secret in (
        "DEPLOY_SSH_KEY",
        "DEPLOY_KNOWN_HOSTS",
        "DEPLOY_HOST",
        "DEPLOY_PORT",
        "DEPLOY_USER",
    ):
        assert f"secrets.{secret}" in workflow
    assert "StrictHostKeyChecking=yes" in workflow
    assert "sudo -n /usr/local/sbin/platform-deploy apply auth" in workflow
    assert "DEPLOY_AUTH" in workflow


def test_auth_module_records_current_and_previous_and_rolls_back_on_failure():
    module = _read("ops/platform-deploy/modules/auth")
    dispatcher = _read("ops/platform-deploy/platform-deploy")

    assert "RELEASE_COMMIT" in module
    assert 'previous_release="$(readlink "$auth_root/current"' in module
    assert 'mv -Tf "$auth_root/previous.next" "$auth_root/previous"' in module
    assert 'mv -Tf "$auth_root/current.next" "$auth_root/current"' in module
    assert "rollback()" in module
    assert module.count("rollback") >= 4
    assert "https://gsnipers.snipers.com.cn/login?release=${commit}" in module
    assert "Auth asset check failed" in module
    assert "auth_current_release=" in dispatcher
    assert "auth_previous_release=" in dispatcher


def test_auth_release_cannot_include_backend_or_runtime_actions():
    module = _read("ops/platform-deploy/modules/auth")
    workflow = _read(".github/workflows/production-auth-deploy.yml")
    manual_script = _read("frontend/scripts/deploy-auth.sh")

    assert "backend=not-included" in module
    assert "migration=not-run" in module
    assert "service_restart=not-run" in module
    assert "backend=not-included" in workflow
    assert "migration=not-run" in workflow
    assert "service_restart=not-run" in workflow
    assert "Direct Auth SSH deployment is disabled" in manual_script
    assert "rsync" not in manual_script
    assert "ssh " not in manual_script
