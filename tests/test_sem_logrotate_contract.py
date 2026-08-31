"""Contracts for the separately deployed SEM backend log rotation policy."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rotation_targets_the_systemd_append_logs_without_restart_hooks():
    service = _read("deploy/sem-backend.service")
    rotation = _read("deploy/sem-backend.logrotate")

    assert "StandardOutput=append:/var/log/sem-backend/stdout.log" in service
    assert "StandardError=append:/var/log/sem-backend/stderr.log" in service
    assert "/var/log/sem-backend/stdout.log" in rotation
    assert "/var/log/sem-backend/stderr.log" in rotation
    assert "daily" in rotation
    assert "rotate 14" in rotation
    assert "maxsize 50M" in rotation
    assert "copytruncate" in rotation
    assert "compress" in rotation
    assert "su root root" in rotation
    assert "systemctl" not in rotation
    assert "postrotate" not in rotation


def test_runbook_requires_permission_hardening_and_dry_run_validation():
    runbook = _read("deploy/README-SEM-LOGGING.md")

    assert "mode `0750`" in runbook
    assert "mode `0640`" in runbook
    assert "logrotate --debug --state /dev/null" in runbook
    assert "`sem-backend` remains active" in runbook
    assert "db=ok" in runbook
    assert "does not require restarting" in runbook
    assert "database data" in runbook


def test_ci_uses_the_real_logrotate_parser_without_forcing_rotation():
    workflow = _read(".github/workflows/ci.yml")

    assert "sem-logrotate-config:" in workflow
    assert "contents: read" in workflow
    assert "sudo logrotate --debug --state /dev/null" in workflow
    assert '"$RUNNER_TEMP/sem-backend.logrotate"' in workflow
    assert "logrotate --force" not in workflow
    assert "logrotate -f" not in workflow
