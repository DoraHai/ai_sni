from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "ops/platform-deploy/modules/sem"
INSTALLER_PATH = ROOT / "ops/platform-deploy/install-sem.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
@pytest.mark.parametrize("path", [MODULE_PATH, INSTALLER_PATH])
def test_sem_platform_scripts_are_valid_bash(path: Path) -> None:
    subprocess.run(["bash", "-n", str(path)], check=True)


def test_sem_module_validates_archive_identity_and_migration_policy() -> None:
    module = _read(MODULE_PATH)

    assert 'confirmation must be DEPLOY_SEM' in module
    assert 'commit must be a full lowercase SHA' in module
    assert 'archive sha256 is invalid' in module
    assert 'archive must not contain symbolic or hard links' in module
    assert 'archive contains parent traversal' in module
    assert "grep -Fxq 'module=sem'" in module
    assert 'grep -Fxq "commit=$commit"' in module
    assert "grep -Fxq 'migration=not-run'" in module
    assert not re.search(r"\balembic\s+(upgrade|downgrade|stamp)\b", module)


def test_sem_module_persists_root_owned_read_only_release_identity() -> None:
    module = _read(MODULE_PATH)

    manifest_install = (
        'install -o root -g root -m 0444 "$payload/MANIFEST" '
        '"$backend_release/MANIFEST"'
    )
    assert manifest_install in module
    assert 'chown root:root "$backend_release/RELEASE_COMMIT"' in module
    assert 'chmod 0444 "$backend_release/RELEASE_COMMIT"' in module
    assert 'chown root:root "$backend_release"' in module
    assert 'chmod 0555 "$backend_release"' in module
    assert 'persisted manifest commit mismatch' in module
    assert 'persisted migration policy mismatch' in module
    assert 'persisted release commit mismatch' in module


def test_sem_module_only_switches_and_restarts_sem_backend() -> None:
    module = _read(MODULE_PATH)

    assert "backend_root='/opt/sem-backend'" in module
    assert 'backend_release="$backend_root/releases/$release_id"' in module
    assert "systemctl restart sem-backend" in module
    assert "systemctl stop sem-backend" in module
    for forbidden in (
        "geo-service",
        "seo-service",
        "nginx",
        "/opt/sem-frontend",
        "/opt/geo-service",
        "/opt/seo-service",
    ):
        assert forbidden not in module
    assert "previous release restored" in module


def test_sem_module_health_check_binds_runtime_to_release_commit() -> None:
    module = _read(MODULE_PATH)

    assert 'http://127.0.0.1:8000/health' in module
    assert '"db"[[:space:]]*:[[:space:]]*"ok"' in module
    assert r'\"release_commit\"[[:space:]]*:[[:space:]]*\"$commit\"' in module
    assert 'SEM health release commit mismatch; previous release restored' in module


def test_sem_installer_is_explicit_backed_up_and_non_deploying() -> None:
    installer = _read(INSTALLER_PATH)

    assert 'usage: install-sem.sh --enable|--locked' in installer
    assert "backup_parent='/var/backups/platform-deploy'" in installer
    assert 'mktemp -d "$backup_parent/sem-' in installer
    assert 'bash -n "$module_source"' in installer
    assert 'mv -Tf "$module_next" "$module_target"' in installer
    assert 'cmp -s "$module_source" "$module_target"' in installer
    assert "restore_previous" in installer
    assert 'if [[ "$install_succeeded" != true ]]' in installer
    assert "previous module restored" in installer
    assert "systemctl restart" not in installer
    assert "systemctl reload" not in installer
    assert "platform-deploy apply" not in installer
    assert "alembic" not in installer.lower()
