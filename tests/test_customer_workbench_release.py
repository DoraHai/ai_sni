import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('static_release', ROOT / 'ops/customer-workbench/static_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
COMMIT = 'a' * 40


def files():
    data = {name: ('test ' + name).encode() for name in ['index.html', 'app.js', 'app.css']}
    manifest = dict(schema=1, base='/customer-workbench/', sourceTreeClean=True, upstreamCommit=COMMIT,
        files={name: dict(bytes=len(value), sha256=release.sha(value)) for name, value in data.items()})
    data['release-manifest.json'] = json.dumps(manifest).encode()
    return data


def archive(data, extra=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as tar:
        for name, value in data.items():
            info = tarfile.TarInfo('customer-workbench/' + name)
            info.size = len(value)
            tar.addfile(info, io.BytesIO(value))
        if extra:
            tar.addfile(extra)
    stream.seek(0)
    return stream


def test_real_format_and_manifest_identity():
    data = files()
    assert release.payload(archive(data), COMMIT) == data
    with pytest.raises(ValueError, match='identity'):
        release.payload(archive(data), 'b' * 40)
    data['app.js'] = b'modified'
    with pytest.raises(ValueError, match='digest'):
        release.payload(archive(data), COMMIT)


@pytest.mark.parametrize('name,kind', [('../outside', tarfile.REGTYPE),
    ('customer-workbench/app.js', tarfile.REGTYPE), ('customer-workbench/link', tarfile.SYMTYPE),
    ('customer-workbench/secret.env', tarfile.REGTYPE)])
def test_archive_rejects_traversal_duplicates_links_and_extra_files(name, kind):
    extra = tarfile.TarInfo(name)
    extra.type = kind
    extra.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
    with pytest.raises(ValueError):
        release.payload(archive(files(), extra), COMMIT)


@pytest.mark.skipif(os.name == 'nt', reason='production atomic symlink behavior is Linux-specific')
def test_activation_retry_and_failed_smoke_restore(tmp_path):
    data = files()
    release.activate(tmp_path, COMMIT, data)
    assert (tmp_path / 'current').resolve() == tmp_path / 'releases' / COMMIT
    release.activate(tmp_path, COMMIT, data)
    def fail():
        raise RuntimeError('public mismatch')
    with pytest.raises(RuntimeError):
        release.activate(tmp_path, 'b' * 40, data, verify=fail)
    assert (tmp_path / 'current').resolve().name == COMMIT
    with pytest.raises(ValueError, match='immutable'):
        release.activate(tmp_path, COMMIT, {**data, 'app.js': b'bad'})


@pytest.mark.skipif(os.name == 'nt', reason='production atomic symlink behavior is Linux-specific')
def test_first_failure_and_stale_authorization_leave_no_current(tmp_path):
    def fail():
        raise RuntimeError('stopped')
    with pytest.raises(RuntimeError):
        release.activate(tmp_path, COMMIT, files(), authorize=fail)
    assert not (tmp_path / 'current').exists()
    with pytest.raises(RuntimeError):
        release.activate(tmp_path, COMMIT, files(), verify=fail)
    assert not (tmp_path / 'current').is_symlink()
