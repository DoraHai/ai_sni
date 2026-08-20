"""Safety checks for the restricted SEM frontend deployment boundary."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_sem_frontend_deploy_uses_unprivileged_account_and_readable_modes():
    script = _read("frontend/scripts/deploy-sem.sh")

    assert "sem-deploy@101.200.193.83" in script
    assert "root@101.200.193.83" not in script
    assert "chown" not in script
    assert "--chmod=D0755,F0644" in script
    assert "StrictHostKeyChecking=yes" in script


def test_sem_ci_uses_pinned_host_key_and_dedicated_secret():
    workflow = _read(".github/workflows/ci.yml")

    assert "SEM_DEPLOY_SSH_KEY" in workflow
    assert "DEPLOY_KNOWN_HOSTS" in workflow
    assert "ssh-keyscan" not in workflow
    assert "DEPLOY_TARGET: sem-deploy@101.200.193.83" in workflow
    assert "environment: production" in workflow
