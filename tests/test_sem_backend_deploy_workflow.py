from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/production-sem-backend-deploy.yml"


def _workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _trigger_block(workflow: str) -> str:
    return workflow[workflow.index("on:\n") : workflow.index("permissions:\n")]


def test_sem_backend_release_is_manual_only() -> None:
    workflow = _workflow()
    trigger = _trigger_block(workflow)
    assert "workflow_dispatch:" in trigger
    assert "push:" not in trigger
    assert "pull_request:" not in trigger
    assert "confirmation:" in trigger
    assert "release_sha:" in trigger
    assert "DEPLOY_SEM_BACKEND" in workflow
    assert r"^[0-9a-f]{40}$" in workflow
    assert 'WORKFLOW_REF" != "refs/heads/main' in workflow


def test_sem_backend_release_rejects_stale_production_heads() -> None:
    workflow = _workflow()
    assert "RELEASE_BRANCH: codex/production-sem-backend" in workflow
    assert "SEM_PRODUCTION_BRANCH" not in workflow
    assert re.search(r"codex/production-sem(?!-backend)", workflow) is None
    assert "currently at codex/production-sem-backend HEAD" in workflow
    assert (
        workflow.count(
            'git ls-remote origin "refs/heads/$RELEASE_BRANCH"'
        )
        >= 3
    )
    assert "Refusing stale SEM backend release" in workflow
    assert "Refusing stale SEM backend upload" in workflow
    assert "Refusing stale SEM backend apply" in workflow
    assert "ref: ${{ inputs.release_sha }}" in workflow


def test_sem_backend_archive_is_git_bound_and_migration_free() -> None:
    workflow = _workflow()
    assert 'git archive --format=tar "$RELEASE_SHA"' in workflow
    assert "app migrations requirements.txt alembic.ini" in workflow
    assert "module=sem" in workflow
    assert "commit=$RELEASE_SHA" in workflow
    assert "migration=not-run" in workflow
    assert "sem-release/backend/app/main.py" in workflow
    assert "sem-release/backend/alembic.ini" in workflow
    assert "retention-days: 1" in workflow
    assert "^120000 " in workflow
    assert "Archive contains parent traversal" in workflow
    assert "forbidden local, cache, or database file" in workflow


def test_sem_backend_workflow_never_executes_database_or_other_module_deploys() -> None:
    workflow = _workflow()
    assert not re.search(r"\balembic\s+(upgrade|downgrade|stamp)\b", workflow)
    assert "platform-deploy apply geo" not in workflow
    assert "platform-deploy apply seo" not in workflow
    assert "platform-deploy apply diagnostic" not in workflow
    assert "nginx" not in workflow.lower()
    assert "deploy-sem.sh" not in workflow
    assert "frontend/" not in workflow
    assert "SEM_DEPLOY_SSH_KEY" not in workflow
    assert workflow.count("platform-deploy apply sem") == 1
    assert (
        "sudo -n /usr/local/sbin/platform-deploy apply sem "
        "'$remote_path' '$RELEASE_SHA' '$archive_sha256' DEPLOY_SEM"
    ) in workflow


def test_sem_backend_release_reruns_recent_high_risk_regressions() -> None:
    workflow = _workflow()
    for suite in (
        "tests/test_keyword_refresh.py",
        "tests/test_scheduler_account_iteration.py",
        "tests/test_sem_identity_repair_preview.py",
        "tests/test_sem_public_http_security.py",
        "tests/test_campaign_region.py",
        "tests/test_campaign_schedule.py",
    ):
        assert suite in workflow


def test_sem_backend_release_uses_restricted_serialized_environment() -> None:
    workflow = _workflow()
    assert "permissions:\n  contents: read" in workflow
    assert "group: production-sem-backend-deployment" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "environment: production" in workflow
    assert 'test "$DEPLOY_USER" = "platform-deploy"' in workflow
    for secret in (
        "DEPLOY_SSH_KEY",
        "DEPLOY_KNOWN_HOSTS",
        "DEPLOY_HOST",
        "DEPLOY_PORT",
        "DEPLOY_USER",
    ):
        assert f"secrets.{secret}" in workflow


def test_sem_frontend_and_backend_release_jobs_remain_separate() -> None:
    backend = _workflow()
    shared_ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "Deploy SEM frontend only" in shared_ci
    assert "SEM_DEPLOY_SSH_KEY" in shared_ci
    assert "backend is a separate reviewed release" in shared_ci
    assert "Deploy current SEM backend production head" in backend
    assert "SEM_DEPLOY_SSH_KEY" not in backend
