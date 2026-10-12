"""Run the reviewed native pilot in a separate Linux cluster and working directory."""
import argparse
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys

BASE = Path('/opt/gsnipers-distribution-acceptance')
WORK = BASE / 'work/distribution-server-pilot-20261012'
PORTS = {'pg': 55483, 'seo': 55861, 'geo': 55862}
NATIVE = {'seo': 'b4d8387123355348f79e26ea2838585c5106a4b9',
          'geo': '46dacbd805afc00f37eba344306fde004039efed'}
SNAPSHOT_SHA = 'f75d382a54ec33f0c892cc4c6afcc17b082c130cc1b58236fb4dde48e383f609'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def private_write(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        output.write(value)


def git(directory, *arguments):
    return subprocess.check_output(['git', '-C', str(directory), *arguments], text=True).strip()


def verify_release(release):
    release = Path(release).resolve()
    if release.parent != BASE / 'releases' or not release.is_dir():
        raise RuntimeError('An owned immutable acceptance release is required')
    for name in ('central', 'seo', 'geo'):
        tree = release / name
        if git(tree, 'status', '--porcelain'):
            raise RuntimeError('Acceptance source must be committed and clean')
        if name in NATIVE and git(tree, 'rev-parse', 'HEAD') != NATIVE[name]:
            raise RuntimeError('Native source pin changed')
    central = release / 'central'
    manifest = read(central / 'customer-workbench/dist/customer-workbench/release-manifest.json')
    if manifest['sourceTreeClean'] is not True or manifest['upstreamCommit'] != git(central, 'rev-parse', 'HEAD'):
        raise RuntimeError('Standard advisor release is not bound to its clean source')
    for name, expected in manifest['files'].items():
        data = (central / 'customer-workbench/dist/customer-workbench' / name).read_bytes()
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise RuntimeError('Standard advisor artifact hash mismatch')
    return release


def bootstrap(release):
    release = verify_release(release)
    if WORK.exists():
        raise RuntimeError('Do not replace an existing acceptance environment')
    WORK.mkdir(parents=True, mode=0o700)
    private_write(WORK / 'postgres.secret', secrets.token_urlsafe(48))
    private_write(WORK / 'secrets.json', json.dumps({
        'jwt_secret': secrets.token_urlsafe(48), 'admin_key': secrets.token_urlsafe(48),
        'crypto_key': base64.b64encode(secrets.token_bytes(32)).decode(),
        'password': secrets.token_urlsafe(24),
    }))
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Independent distribution acceptance')])
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
            x509.DNSName('localhost')]), critical=False).sign(key, hashes.SHA256()))
    private_write(WORK / 'loopback.key', key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    private_write(WORK / 'loopback.pem', certificate.public_bytes(serialization.Encoding.PEM).decode())
    private_write(WORK / 'environment.json', json.dumps({
        'environment_version': 1, 'platform': 'linux-acceptance', 'root': str(WORK),
        'ports': PORTS, 'production': False, 'central_root': str(release / 'central'),
        'native_roots': {module: str(release / module) for module in NATIVE},
        'native_heads': NATIVE, 'dependency_fallback': str(BASE / 'venv/lib/python3.11/site-packages'),
        'automaticSubmit': False, 'publicationVerified': False, 'initialized': False,
    }, indent=2))


def environment(module):
    if WORK.resolve() != WORK or (WORK / '.env').exists():
        raise RuntimeError('Owned private acceptance work directory required')
    for name in ('secrets.json', 'postgres.secret', 'environment.json', 'loopback.key'):
        file = WORK / name
        if file.stat().st_uid != os.getuid() or stat.S_IMODE(file.stat().st_mode) & 0o077:
            raise RuntimeError('Private acceptance configuration permissions invalid')
    config = read(WORK / 'environment.json')
    if config.get('production') is not False or config.get('platform') != 'linux-acceptance' or config.get('ports') != PORTS:
        raise RuntimeError('A separate Linux acceptance configuration is required')
    verify_release(Path(config['central_root']).parent)
    values = read(WORK / 'secrets.json')
    password = (WORK / 'postgres.secret').read_text(encoding='utf-8').strip()
    # Replace inherited credentials and dotenv search roots before importing any application code.
    clean = {name: value for name, value in os.environ.items() if name in {'PATH', 'LANG', 'LC_ALL', 'SYSTEMD_EXEC_PID'}}
    clean.update(TEMP=str(WORK.parent), TMP=str(WORK.parent), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
        DISTRIBUTION_ACCEPTANCE_ROOT=str(WORK), DISTRIBUTION_REMOTE_CONTROL_ENABLED='true',
        DISTRIBUTION_DEVICE_PAIRING_ENABLED='true', API_CONTROLS_ENABLED='true', API_METERING_ENABLED='true',
        BAIDU_WRITE_DRY_RUN='true', BAIDU_APP_ID='acceptance-disabled', BAIDU_SECRET_KEY='acceptance-disabled',
        BAIDU_DEFAULT_USERNAME='acceptance-disabled', BAIDU_DEFAULT_UCID='1',
        BAIDU_SELF_ACCESS_TOKEN='acceptance-disabled', BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',
        JWT_SECRET=values['jwt_secret'], ADMIN_API_KEY=values['admin_key'], CRYPTO_MASTER_KEY_B64=values['crypto_key'],
        DEEPSEEK_API_KEY='acceptance-planner-simulator-only', DASHSCOPE_API_KEY='', DEEPSEEK_MODEL='sim-local-distribution-planning',
        DATABASE_URL=f'postgresql+asyncpg://distribution_acceptance:{password}@127.0.0.1:{PORTS["pg"]}/distribution_acceptance_{module}')
    os.environ.clear()
    os.environ.update(clean)
    os.chdir(WORK)
    sys.path.insert(0, str(Path(config['central_root']) / 'scripts'))
    return config


async def initialize(native, root, config, engine, sessions, module, manifest):
    snapshot = root / 'customer-snapshot.json'
    if not snapshot.is_file() or hashlib.sha256(snapshot.read_bytes()).hexdigest() != SNAPSHOT_SHA:
        raise RuntimeError('Exact previously authorized customer snapshot required before acceptance DDL')
    await native.initialize(root, config, engine, sessions, module, manifest)
    if module == 'seo':
        await native.native_schema(root, config, engine, module)
    await native.pilot_schema(root, config, engine, module)
    from sqlalchemy import text
    source = Path(config['central_root']) / 'scripts/distribution_device_pairing_schema.sql'
    if not source.is_file():
        raise RuntimeError('Reviewed one-time pairing schema required')
    async with engine.begin() as connection:
        if await connection.scalar(text('SELECT current_schema()')) != 'acceptance_' + module:
            raise RuntimeError('Refuse pairing DDL outside the isolated acceptance schema')
        raw = (await connection.get_raw_connection()).driver_connection
        await raw.execute(source.read_text(encoding='utf-8-sig').replace('BEGIN;', '').replace('COMMIT;', ''))
    private_write(root / (module + '-linux-pairing-schema.json'), json.dumps({
        'schema': 'acceptance_' + module, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'production_mutations': False, 'automatic_submit': False,
    }, indent=2))
    await engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('bootstrap', 'initialize', 'serve', 'worker'))
    parser.add_argument('--release', type=Path)
    parser.add_argument('--module', choices=tuple(NATIVE), default='seo')
    arguments = parser.parse_args()
    if arguments.action == 'bootstrap':
        bootstrap(arguments.release)
        print(json.dumps({'bootstrapped': True, 'production': False, 'private_credentials_printed': False}))
        return
    environment(arguments.module)
    import distribution_server_pilot_native as native
    root, config, engine, sessions, manifest = native.prepare(WORK / 'environment.json', arguments.module)
    native.install_transport_guard()
    if arguments.action == 'initialize':
        asyncio.run(initialize(native, root, config, engine, sessions, arguments.module, manifest))
        print(json.dumps({'initialized_module': arguments.module, 'production': False}))
    elif arguments.action == 'serve':
        import uvicorn
        uvicorn.run(native.application(root, config, sessions, arguments.module, manifest), host='127.0.0.1',
            port=PORTS[arguments.module], ssl_keyfile=str(WORK / 'loopback.key'), ssl_certfile=str(WORK / 'loopback.pem'),
            access_log=False, log_level='warning')
    else:
        asyncio.run(native.work(sessions, arguments.module))


if __name__ == '__main__':
    main()
