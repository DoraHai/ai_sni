"""Install one traceable HTTPS gateway; never reload production nginx.

This gateway forwards advisor/customer requests to the existing isolated SEO
API. Company-device routes stay private. Cloud security-group changes are not
performed here; public reachability must be proved separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import ssl
import stat
import subprocess
import urllib.request
from uuid import uuid4

BASE = Path('/opt/gsnipers-distribution-acceptance')
WORK = BASE / 'work/distribution-server-pilot-20261012'
# A root nginx master must not read config below the API service's writable
# parent. This separate root-owned prefix has only root-owned ancestors.
GATEWAY = Path('/opt/gsnipers-distribution-acceptance-gateway')
UNIT_NAME = 'gsnipers-distribution-acceptance-gateway.service'
UNIT_PATH = Path('/etc/systemd/system') / UNIT_NAME
PORT = '58443/tcp'
FILES = ('standalone-nginx.conf', 'nginx-proxy.inc', UNIT_NAME)
CONTROL_SOURCE = 'scripts/distribution_acceptance_gateway.py'
PRODUCTION = (Path('/etc/nginx/nginx.conf'), Path('/etc/nginx/conf.d/gsnipers.conf'))


def need(value, code):
    if not value:
        raise RuntimeError(code)


def run(args, allowed=(0,)):
    result = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=30)
    need(result.returncode in allowed, 'Gateway command failed: ' + args[0])
    return result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_links(path):
    for item in (path, *path.parents):
        need(not stat.S_ISLNK(item.lstat().st_mode), 'Gateway path must not contain symlinks')


def write(path, data, mode, uid, gid):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(path, uid, gid)


def production_fingerprint():
    return {'files': {str(path): sha(path) for path in PRODUCTION},
            'main_pid': run(['systemctl', 'show', 'nginx.service', '-p', 'MainPID', '--value']).stdout.strip()}


def persist_manifest(manifest):
    pending = GATEWAY / ('manifest-next-' + uuid4().hex + '.json')
    write(pending, (json.dumps(manifest, indent=2) + '\n').encode(), 0o600, 0, 0)
    os.replace(pending, GATEWAY / 'manifest.json')


def health():
    ca = WORK / 'loopback.pem'
    no_links(ca)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ca))))
    with opener.open('https://127.0.0.1:55861/acceptance/health', timeout=10) as response:
        need(response.status == 200, 'Owned SEO API must be healthy')
        value = json.loads(response.read(1048576))
    need(value.get('module') == 'seo' and value.get('port') == 55861
         and value.get('schema') == 'acceptance_seo' and value.get('production') is False,
         'Only independent SEO may be exposed')
    return {key: value[key] for key in ('central_head', 'native_head', 'module', 'schema', 'production')}


def git(source, *args):
    return run(['runuser', '-u', 'distacceptance', '--', 'git', '-c', 'core.fsmonitor=false',
                '-c', 'core.hooksPath=/dev/null', '-c', 'safe.directory=' + str(source), '-C', str(source), *args])


def install(source, expected, expected_manifest):
    source = Path(source)
    need(re.fullmatch('[a-f0-9]{40}', expected) is not None and source == BASE / 'releases' / expected / 'central',
         'An exact immutable source checkout is required')
    no_links(source)
    need(git(source, 'rev-parse', 'HEAD').stdout.strip() == expected,
         'Gateway source commit changed')
    need(not git(source, 'status', '--porcelain').stdout.strip(),
         'Gateway source must be clean')
    need(re.fullmatch('[a-f0-9]{64}', expected_manifest) is not None, 'A caller-pinned artifact manifest is required')
    prefix = 'deploy/distribution-acceptance-gateway/'
    artifact_raw = git(source, 'show', expected + ':' + prefix + 'artifact-manifest.json').stdout.encode()
    need(hashlib.sha256(artifact_raw).hexdigest() == expected_manifest, 'Gateway artifact manifest changed')
    artifacts = json.loads(artifact_raw)['files']
    need(set(artifacts) == {*(prefix + name for name in FILES), CONTROL_SOURCE}, 'Gateway artifact list changed')
    blobs = {}
    for name in FILES:
        blobs[name] = git(source, 'show', expected + ':' + prefix + name).stdout.encode()
        need(hashlib.sha256(blobs[name]).hexdigest() == artifacts[prefix + name], 'Gateway file differs from reviewed artifact')
        need(b'\r' not in blobs[name] and 0 < len(blobs[name]) < 32768, 'Gateway source format invalid')
    control = git(source, 'show', expected + ':' + CONTROL_SOURCE).stdout.encode()
    need(hashlib.sha256(control).hexdigest() == artifacts[CONTROL_SOURCE], 'Gateway control differs from reviewed artifact')
    no_links(BASE)
    parent = GATEWAY.parent.stat()
    need(parent.st_uid == 0 and not stat.S_IMODE(parent.st_mode) & 0o022, 'Gateway parent must be root owned')
    need(not GATEWAY.exists() and not UNIT_PATH.exists(), 'Do not replace an existing gateway')
    need(not run(['ss', '-ltnH', 'sport', '=', ':58443']).stdout.strip(), 'Do not take an occupied port')
    observed = health()
    before = production_fingerprint()
    actor = pwd.getpwnam('distacceptance')
    os.mkdir(GATEWAY, 0o750)
    os.chown(GATEWAY, 0, actor.pw_gid)
    for name in ('run', 'log', 'tmp'):
        os.mkdir(GATEWAY / name, 0o700)
    for name in ('body', 'proxy'):
        os.mkdir(GATEWAY / 'tmp' / name, 0o700)
        os.chown(GATEWAY / 'tmp' / name, actor.pw_uid, actor.pw_gid)
    os.chown(GATEWAY / 'tmp', 0, actor.pw_gid)
    os.chmod(GATEWAY / 'tmp', 0o750)
    manifest = {'schema': 1, 'source_commit': expected, 'source_root': str(source),
                'upstream_observed': observed, 'port': 58443, 'production': False,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in blobs.items()},
                'production_before': before, 'firewall_added': False, 'firewall_cleanup_intent': False,
                'firewall_timeout_seconds': 7200, 'cloud_security_group_verified': False}
    manifest['control_sha256'] = hashlib.sha256(control).hexdigest()
    for name in ('standalone-nginx.conf', 'nginx-proxy.inc'):
        write(GATEWAY / name, blobs[name], 0o640, 0, actor.pw_gid)
    write(UNIT_PATH, blobs[UNIT_NAME], 0o644, 0, 0)
    write(GATEWAY / 'gateway-control.py', control, 0o600, 0, 0)
    write(GATEWAY / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode(), 0o600, 0, 0)
    run(['/usr/sbin/nginx', '-t', '-p', str(GATEWAY) + '/', '-c', str(GATEWAY / 'standalone-nginx.conf')])
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'start', UNIT_NAME])
    try:
        run(['systemctl', 'is-active', '--quiet', UNIT_NAME])
        # This test uses the public certificate chain with no custom CA or -k.
        local = run(['curl', '--fail', '--silent', '--show-error', '--noproxy', '*',
                     '--resolve', 'gsnipers.snipers.com.cn:58443:127.0.0.1',
                     '--dump-header', '-', '--output', '/dev/null',
                     'https://gsnipers.snipers.com.cn:58443/customer-workbench/?console=advisor'])
        need('200' in local.stdout.splitlines()[0], 'Strict local public TLS probe failed')
        prior = run(['firewall-cmd', '--zone=public', '--query-port=' + PORT], allowed=(0, 1))
        if prior.returncode == 1:
            # Persist the known-absent-port cleanup intent before the external
            # command; a killed installer must not leave stop guessing false.
            manifest['firewall_cleanup_intent'] = True
            persist_manifest(manifest)
            run(['firewall-cmd', '--zone=public', '--add-port=' + PORT, '--timeout=7200'])
            manifest['firewall_added'] = True
        need(production_fingerprint() == before, 'Production nginx changed during independent setup')
        manifest['strict_local_public_tls'] = True
        persist_manifest(manifest)
    except BaseException:
        run(['systemctl', 'stop', UNIT_NAME])
        if manifest['firewall_added'] or manifest['firewall_cleanup_intent']:
            run(['firewall-cmd', '--zone=public', '--remove-port=' + PORT], allowed=(0, 1))
        raise
    print(json.dumps({'installed': True, 'source_commit': expected, 'strict_local_tls': True,
                      'production_nginx_unchanged': True, 'cloud_security_group_verified': False,
                      'public_reachability_verified': False, 'permanent_firewall_change': False,
                      'url': 'https://gsnipers.snipers.com.cn:58443/customer-workbench/?console=advisor'}))


def verify():
    no_links(GATEWAY)
    manifest = json.loads((GATEWAY / 'manifest.json').read_text())
    need(manifest.get('production') is False and manifest.get('port') == 58443, 'Owned gateway manifest required')
    for item in (GATEWAY, *GATEWAY.parents):
        meta = item.stat()
        need(meta.st_uid == 0 and not stat.S_IMODE(meta.st_mode) & 0o022, 'Gateway ancestors must be root controlled')
    for name in ('standalone-nginx.conf', 'nginx-proxy.inc'):
        no_links(GATEWAY / name)
        need(sha(GATEWAY / name) == manifest['files'][name], 'Gateway ownership changed')
    no_links(UNIT_PATH)
    need(sha(UNIT_PATH) == manifest['files'][UNIT_NAME], 'Gateway unit ownership changed')
    no_links(GATEWAY / 'gateway-control.py')
    need(sha(GATEWAY / 'gateway-control.py') == manifest['control_sha256'], 'Gateway control ownership changed')
    return manifest


def stop():
    manifest = verify()
    run(['systemctl', 'stop', UNIT_NAME])
    if manifest['firewall_added'] or manifest.get('firewall_cleanup_intent', False):
        run(['firewall-cmd', '--zone=public', '--remove-port=' + PORT], allowed=(0, 1))
    print(json.dumps({'stopped': True, 'native_tasks_not_canceled': True, 'production': False,
                      'files_preserved': True, 'cloud_security_group_cleanup_required': True}))


def main():
    need(os.getuid() == 0, 'Root required to set up the owned gateway')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'stop', 'verify'))
    parser.add_argument('--source-root')
    parser.add_argument('--expected-commit')
    parser.add_argument('--artifact-manifest-sha')
    args = parser.parse_args()
    if args.action == 'install':
        need(args.source_root is not None and args.expected_commit is not None and args.artifact_manifest_sha is not None,
             'Exact source and artifact arguments required')
        install(args.source_root, args.expected_commit, args.artifact_manifest_sha)
    elif args.action == 'verify':
        verify()
    else:
        stop()


if __name__ == '__main__':
    main()
