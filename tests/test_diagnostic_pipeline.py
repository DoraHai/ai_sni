import importlib.util
import io
from pathlib import Path
import tarfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("diagnostic_archive", ROOT / "ops/platform-deploy/modules/diagnostic_archive.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def pack(tmp_path, name, kind=tarfile.REGTYPE):
    path = tmp_path / "test.tgz"
    with tarfile.open(path, "w:gz") as tar:
        item = tarfile.TarInfo(name)
        item.type = kind
        item.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
        item.size = 0
        tar.addfile(item, io.BytesIO())
    return path


@pytest.mark.parametrize("name,kind", [
    ("diagnostic-release/backend/app/../../../../etc/passwd", tarfile.REGTYPE),
    ("/etc/passwd", tarfile.REGTYPE),
    ("diagnostic-release/backend/app/link", tarfile.SYMTYPE),
    ("diagnostic-release/backend/app/.env", tarfile.REGTYPE),
    ("diagnostic-release/backend/sitecustomize.py", tarfile.REGTYPE),
    ("diagnostic-release/backend/app/device", tarfile.CHRTYPE),
])
def test_reject_unsafe_archive(tmp_path, name, kind):
    with pytest.raises(ValueError):
        validator.validate(pack(tmp_path, name, kind))


def test_accept_diagnostic_source(tmp_path):
    validator.validate(pack(tmp_path, "diagnostic-release/backend/app/diagnostic_main.py"))


def test_deploy_is_module_scoped_and_uses_trusted_helper():
    module = (ROOT / "ops/platform-deploy/modules/diagnostic").read_text()
    assert "systemctl restart diagnostic-service" in module
    assert "systemctl restart geo-service" not in module
    assert "/opt/geo-service" not in module
    assert "/opt/sem-backend" not in module
    assert "diagnostic_archive.py" in module
    assert "flock -n" in module
    assert "rollback" in module
    workflow = (ROOT / ".github/workflows/production-diagnostic-deploy.yml").read_text()
    assert "pull_request:" in workflow
    assert "github.event_name != 'pull_request'" in workflow
    assert "codex/production-diagnostic" in workflow
    assert "apply diagnostic" in workflow
    assert "apply geo" not in workflow
