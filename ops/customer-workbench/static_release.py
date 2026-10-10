"""Static package handler called only by the existing platform dispatcher.

No database, API credentials, processes or nginx mutations. First installation
stages a current release; the separately reviewed route release makes it public.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

FILES = {"index.html", "app.js", "app.css", "release-manifest.json"}
ROOT = Path('/opt/customer-workbench')
UPLOAD = Path('/home/platform-deploy/uploads')
MAX = 32 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def authorize_head(commit):
    # Both transports read the same Git reference. Never fall back after an
    # observed mismatch; an unavailable source cannot authorize activation.
    url = 'https://api.github.com/repos/DoraHai/ai_sni/branches/codex%2Fproduction-sem?release_check=' + uuid4().hex
    request = Request(url, headers={'Accept': 'application/vnd.github+json',
                                   'User-Agent': 'gsnipers-static-release', 'Cache-Control': 'no-cache'})
    try:
        with urlopen(request, timeout=15) as response:
            require(response.status == 200 and response.geturl() == url, 'unexpected branch source')
            body = response.read(65537)
            require(len(body) <= 65536, 'oversized branch source')
            branch = json.loads(body)
            require(isinstance(branch, dict) and branch.get('name') == 'codex/production-sem', 'wrong branch source')
            observed = branch.get('commit', {}).get('sha')
            require(isinstance(observed, str) and re.fullmatch(r'[0-9a-f]{40}', observed), 'invalid branch head')
    except (URLError, TimeoutError, OSError):
        output = subprocess.check_output(['git', 'ls-remote', '--refs',
            'https://github.com/DoraHai/ai_sni.git', 'refs/heads/codex/production-sem'], text=True, timeout=20).strip()
        require(output == commit + '\trefs/heads/codex/production-sem', 'stale production head')
        return
    require(observed == commit, 'stale production head')


def payload(archive, commit):
    require(re.fullmatch(r'[0-9a-f]{40}', commit), 'invalid commit')
    result = {}
    with tarfile.open(fileobj=archive, mode='r:gz') as tar:
        seen = set()
        for member in tar:
            require(member.name not in seen, 'duplicate archive entry')
            seen.add(member.name)
            if member.name.rstrip('/') == 'customer-workbench' and member.isdir():
                continue
            name = member.name.removeprefix('customer-workbench/')
            require(member.name == 'customer-workbench/' + name and name in FILES,
                    'unexpected archive path')
            require(member.isfile() and 0 < member.size <= MAX, 'invalid file type or size')
            result[name] = tar.extractfile(member).read(MAX + 1)
        require(set(result) == FILES, 'missing release files')
    manifest = json.loads(result['release-manifest.json'])
    require(manifest.get('schema') == 1 and manifest.get('sourceTreeClean') is True
            and manifest.get('upstreamCommit') == commit and manifest.get('base') == '/customer-workbench/',
            'wrong release identity')
    require(set(manifest.get('files', {})) == FILES - {'release-manifest.json'}, 'invalid manifest file set')
    for name in FILES - {'release-manifest.json'}:
        entry = manifest['files'][name]
        require(entry.get('sha256') == sha(result[name]) and entry.get('bytes') == len(result[name]),
                'file digest mismatch: ' + name)
    return result


def checked_target(root, link):
    path = root / link
    if not path.exists() and not path.is_symlink():
        return None
    require(path.is_symlink(), 'active path is not a symlink')
    target = path.resolve(strict=True)
    require(target.parent == root / 'releases' and re.fullmatch(r'[0-9a-f]{40}', target.name),
            'active release outside expected root')
    return target


def switch(root, name, target):
    temporary = root / (name + '.next')
    require(not temporary.exists() and not temporary.is_symlink(), 'unexpected temporary link')
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, root / name)


def activate(root, commit, files, verify=lambda: None, authorize=lambda: None):
    require(not root.is_symlink(), 'release root is a symlink')
    root.mkdir(mode=0o755, exist_ok=True)
    releases = root / 'releases'
    require(not releases.is_symlink(), 'release directory is a symlink')
    releases.mkdir(mode=0o755, exist_ok=True)
    old = checked_target(root, 'current')
    checked_target(root, 'previous')
    target = releases / commit
    if target.exists() or target.is_symlink():
        require(target.is_dir() and not target.is_symlink(), 'invalid existing release')
        require(set(p.name for p in target.iterdir()) == FILES, 'existing release file set mismatch')
        for name, data in files.items():
            require(not (target / name).is_symlink() and (target / name).read_bytes() == data,
                    'immutable release mismatch')
    else:
        stage = Path(tempfile.mkdtemp(prefix='.staging-', dir=releases))
        for name, data in files.items():
            with (stage / name).open('xb') as f:
                f.write(data)
            (stage / name).chmod(0o644)
        stage.chmod(0o755)
        os.replace(stage, target)
    authorize()  # Final production-head check; stage remains inert if stale.
    changed = old != target
    if changed:
        switch(root, 'current', target)
    try:
        verify()
        if changed and old:
            switch(root, 'previous', old)
    except Exception:
        if changed:
            if old:
                switch(root, 'current', old)
            else:
                (root / 'current').unlink()
        raise
    return old


def main(args):
    import fcntl
    import pwd
    require(os.geteuid() == 0 and len(args) == 4, 'root dispatcher and four arguments required')
    archive, commit, digest, confirmation = args
    require(confirmation == 'DEPLOY_CUSTOMER_WORKBENCH', 'wrong confirmation')
    require(re.fullmatch(r'[0-9a-f]{40}', commit) and re.fullmatch(r'[0-9a-f]{64}', digest), 'invalid release identity')
    archive = Path(archive)
    require(archive.parent == UPLOAD and re.fullmatch('customer-workbench-' + commit + r'\.tgz\.part-\d+-\d+', archive.name),
            'unexpected upload path')
    with Path('/run/lock/platform-route-deploy.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        flags = os.O_RDONLY | os.O_NOFOLLOW
        with os.fdopen(os.open(archive, flags), 'rb') as f:
            stat = os.fstat(f.fileno())
            import stat as stat_module
            require(stat_module.S_ISREG(stat.st_mode) and stat.st_nlink == 1 and stat.st_size <= MAX
                    and stat.st_uid == pwd.getpwnam('platform-deploy').pw_uid, 'invalid upload ownership/type/size')
            data = f.read(MAX + 1)
        require(sha(data) == digest, 'archive digest mismatch')
        import io
        # Parse a root-held byte snapshot, never a mutable uploader-controlled path.
        files = payload(io.BytesIO(data), commit)
        def authorize():
            authorize_head(commit)
        authorize()
        config = Path('/etc/nginx/conf.d/gsnipers.conf').read_text()
        public = 'alias /opt/customer-workbench/current/index.html;' in config
        def verify():
            if public:
                for name in ['index.html', 'app.js', 'app.css']:
                    suffix = '' if name == 'index.html' else name
                    body = subprocess.check_output(['curl', '-fsS', '--max-time', '15',
                        '-H', 'Cache-Control: no-cache', 'https://gsnipers.snipers.com.cn/customer-workbench/' + suffix], timeout=20)
                    require(body == files[name], 'public static file mismatch: ' + name)
        old = activate(ROOT, commit, files, verify, authorize)
        print(json.dumps({'module': 'customer-workbench', 'commit': commit,
            'previous': str(old) if old else None, 'status': 'public-verified' if public else 'staged-awaiting-route',
            'migration': 'not-run', 'nginx': 'unchanged'}))


if __name__ == '__main__':
    main(sys.argv[1:])
