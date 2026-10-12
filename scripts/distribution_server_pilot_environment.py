"""Owned loopback acceptance lifecycle. Never starts a production app or SEM."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request
import ssl
import shutil
import socket

CENTRAL = Path(__file__).resolve().parents[1]
PYTHON = Path('D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe')
PG = Path('D:/sem-cockpit-pg-runtime/bin')
PORTS = {'pg': 55483, 'seo': 55861, 'geo': 55862}
NATIVE = {name: CENTRAL.parent / directory for name, directory in (
    ('seo', 'seo-review-response-acceptance-20261012'), ('geo', 'geo-manual-channel-acceptance-20261012'))}
NATIVE_HEADS={'seo':'b4d8387123355348f79e26ea2838585c5106a4b9','geo':'46dacbd805afc00f37eba344306fde004039efed'}
SNAPSHOT_SHA='f75d382a54ec33f0c892cc4c6afcc17b082c130cc1b58236fb4dde48e383f609'
ROOT_NAME='distribution-server-pilot-20261012'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def owned(path):
    path = Path(path).resolve()
    temp = Path(os.environ['TEMP']).resolve()
    if path.parent != temp or path.name != ROOT_NAME:
        raise RuntimeError('Acceptance root must be an owned direct TEMP child')
    return path


def child_env(root, module=None):
    # A clean cwd and allowlisted environment cannot load a production dotenv.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'TEMP', 'TMP', 'LOCALAPPDATA'}}
    private = read(root / 'secrets.json')
    env.update(BAIDU_APP_ID='acceptance-disabled', BAIDU_SECRET_KEY='acceptance-disabled',
        BAIDU_DEFAULT_USERNAME='acceptance-disabled', BAIDU_DEFAULT_UCID='1',
        BAIDU_SELF_ACCESS_TOKEN='acceptance-disabled', BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',
        BAIDU_WRITE_DRY_RUN='true', API_CONTROLS_ENABLED='true', API_METERING_ENABLED='true',
        DISTRIBUTION_REMOTE_CONTROL_ENABLED='true',
        JWT_SECRET=private['jwt_secret'], ADMIN_API_KEY=private['admin_key'],
        CRYPTO_MASTER_KEY_B64=private['crypto_key'], DEEPSEEK_API_KEY='acceptance-planner-simulator-only', DASHSCOPE_API_KEY='',
        DEEPSEEK_MODEL='sim-local-distribution-planning',
        DISTRIBUTION_ACCEPTANCE_ROOT=str(root), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    if module:
        env['DATABASE_URL'] = f'postgresql+asyncpg://distribution_acceptance@127.0.0.1:{PORTS["pg"]}/distribution_acceptance_{module}'
    return env


def command(root, args, module=None):
    # PostgreSQL's Windows daemon can inherit pipe handles after pg_ctl exits.
    # Files avoid waiting forever for an inherited pipe's EOF.
    log = root/('command-'+secrets.token_hex(8)+'.log')
    with log.open('wb') as stream:
        result = subprocess.run([str(value) for value in args], env=child_env(root, module), cwd=root,
                                stdout=stream, stderr=stream, timeout=240)
    if result.returncode:
        (root / 'last-command-error.log').write_bytes(log.read_bytes())
        raise RuntimeError('Acceptance command failed; inspect private last-command-error.log')
    return log.read_text(encoding='utf-8', errors='replace')


def init(root, snapshot=None):
    if root.exists(): raise RuntimeError('Fresh acceptance root must not already exist')
    for port in PORTS.values():
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',port))==0: raise RuntimeError('Foreign listener on new acceptance port')
    if not snapshot or hashlib.sha256(Path(snapshot).read_bytes()).hexdigest()!=SNAPSHOT_SHA:
        raise RuntimeError('Exact enriched read-only snapshot required')
    root.mkdir(parents=True)
    dependencies=Path(os.environ['TEMP'])/'distribution-acceptance-customers-20261012/python-deps'
    if not dependencies.is_dir() or {p.name for p in dependencies.iterdir()}!={'docx','lxml','lxml-5.3.2.dist-info','python_docx-1.2.0.dist-info'}:
        raise RuntimeError('Reviewed dependency-only source required')
    shutil.copytree(dependencies,root/'python-deps')
    import base64
    write(root / 'secrets.json', {'jwt_secret': secrets.token_urlsafe(48), 'admin_key': secrets.token_urlsafe(48),
        'crypto_key': base64.b64encode(secrets.token_bytes(32)).decode(), 'password': secrets.token_urlsafe(24)})
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Distribution isolated acceptance')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc)+timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        .sign(key, hashes.SHA256()))
    (root / 'loopback.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (root / 'loopback.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    if snapshot:
        (root / 'customer-snapshot.json').write_bytes(Path(snapshot).read_bytes())
    config = {'environment_version': 1, 'root': str(root), 'ports': PORTS,
        'native_roots': {key: str(value.resolve()) for key, value in NATIVE.items()},
        'native_heads': NATIVE_HEADS,
        'central_root': str(CENTRAL), 'initialized': False, 'automaticSubmit': False,
        'publicationVerified': False, 'production': False,
        'dependency_fallback': 'C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python',
        'dependency_bundle_version': '26.1009.11318'}
    write(root / 'environment.json', config)
    command(root, [PG/'initdb.exe', '-D', root/'pg', '-U', 'distribution_acceptance', '-A', 'trust', '--encoding=UTF8'])
    with (root/'pg/postgresql.conf').open('a', encoding='utf-8') as stream:
        stream.write("\nlisten_addresses='127.0.0.1'\nport=55483\ntimezone='UTC'\n")
    start_pg(root)
    complete_initialization(root)


def complete_initialization(root):
    config = read(root/'environment.json')
    if config['initialized']: raise RuntimeError('Refuse to reinitialize an active acceptance environment')
    start_pg(root)
    for module in NATIVE:
        name = 'distribution_acceptance_'+module
        if not (root/(module+'-import-report.json')).exists():
            existing = command(root, [PG/'psql.exe','-h','127.0.0.1','-p',str(PORTS['pg']),
                '-U','distribution_acceptance','-d','postgres','-t','-A','-c',
                "SELECT 1 FROM pg_database WHERE datname='"+name+"'"]).strip()
            if existing == '1':
                # Only an unfinished, owned DB may be reset. No API is started.
                command(root, [PG/'dropdb.exe','-h','127.0.0.1','-p',str(PORTS['pg']),
                    '-U','distribution_acceptance',name])
            command(root, [PG/'createdb.exe', '-h', '127.0.0.1', '-p', str(PORTS['pg']), '-U',
                'distribution_acceptance', name])
            command(root, [PYTHON, CENTRAL/'scripts/distribution_server_pilot_native.py', '--config',
                root/'environment.json', '--module', module, 'initialize'], module)
        # Import completion is distinct from native migration completion.
        # Recovery must not skip actual 0105 after an interrupted native-schema.
        if module=='seo':
            command(root,[PYTHON,CENTRAL/'scripts/distribution_server_pilot_native.py','--config',
                root/'environment.json','--module',module,'native-schema'],module)
            proof=read(root/'seo-native-schema.json')
            actual=command(root,[PG/'psql.exe','-h','127.0.0.1','-p',str(PORTS['pg']),
                '-U','distribution_acceptance','-d',name,'-t','-A','-c',
                'SELECT version_num FROM acceptance_seo.alembic_version']).strip()
            if not proof.get('actual_native_upgrade_executed') or proof.get('productionDDL') is not False or actual!=proof.get('revision') or actual!='0105_seo_content_confirmations':
                raise RuntimeError('Actual native 0105 schema proof required before startup')
    config['initialized'] = True
    write(root/'environment.json', config)


def start_pg(root):
    data = root/'pg'
    if (data/'postmaster.pid').exists():
        lines = (data/'postmaster.pid').read_text().splitlines()
        if Path(lines[1]).resolve() != data.resolve() or lines[3] != str(PORTS['pg']):
            raise RuntimeError('PostgreSQL ownership mismatch')
        return
    command(root, [PG/'pg_ctl.exe', '-D', data, '-o','-h 127.0.0.1 -p 55483 -c timezone=UTC', '-l', root/'postgres.log', 'start', '-w'])


def status(root):
    context = ssl.create_default_context(cafile=str(root/'loopback.pem'))
    result = {}
    for module in NATIVE:
        try:
            with urllib.request.urlopen(f'https://127.0.0.1:{PORTS[module]}/acceptance/health', context=context, timeout=2) as response:
                data = json.load(response)
            if data['environment_root'] != str(root) or data['module'] != module:
                raise RuntimeError('Foreign service on acceptance port')
            result[module] = data
        except OSError:
            result[module] = {'running': False}
    return result


def start(root, selected_modules=None):
    config = read(root/'environment.json')
    if not config['initialized']:
        raise RuntimeError('Environment initialization incomplete')
    start_pg(root)
    state = read(root/'processes.json') if (root/'processes.json').exists() else {}
    if any(value.get('running') for value in status(root).values()):
        raise RuntimeError('An acceptance API is already running; use status/stop')
    selected_modules=selected_modules or tuple(NATIVE)
    if not selected_modules or any(module not in NATIVE for module in selected_modules):
        raise RuntimeError('Known pilot modules required')
    for module in selected_modules:
        for kind in ('serve', 'worker'):
            log = (root/f'{module}-{kind}.log').open('ab')
            process = subprocess.Popen([str(PYTHON), str(CENTRAL/'scripts/distribution_server_pilot_native.py'),
                '--config', str(root/'environment.json'), '--module', module, kind], cwd=root,
                env=child_env(root, module), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            log.close()
            state[module+'-'+kind] = process.pid
            write(root/'processes.json', state)
    deadline = time.monotonic()+30
    while time.monotonic()<deadline:
        current = status(root)
        if all(current[module].get('running') for module in selected_modules):
            write(root/'health-summary.json', {module:{key:value[key] for key in
                ('running','module','port','native_head','central_head','automaticSubmit','publicationVerified','production')}
                for module,value in current.items() if module in selected_modules})
            return
        time.sleep(.2)
    stop(root)
    raise RuntimeError('Acceptance API readiness failed; services stopped, inspect private logs')


def stop(root):
    state = read(root/'processes.json') if (root/'processes.json').exists() else {}
    for pid in state.values():
        # Verify the recorded process command belongs to this exact private config.
        query = f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; if($p){{$p.CommandLine}}"
        line = subprocess.check_output(['powershell', '-NoProfile', '-Command', query], text=True).strip()
        if not line:
            continue
        if str(root/'environment.json') not in line or 'distribution_server_pilot_native.py' not in line:
            raise RuntimeError('Refuse to stop a reused or foreign PID')
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], stdout=subprocess.DEVNULL, check=True)
    write(root/'processes.json', {})
    data = root/'pg'
    if (data/'postmaster.pid').exists():
        lines = (data/'postmaster.pid').read_text().splitlines()
        if Path(lines[1]).resolve() != data.resolve() or lines[3] != str(PORTS['pg']):
            raise RuntimeError('Refuse to stop foreign PostgreSQL')
        command(root, [PG/'pg_ctl.exe', '-D', data, 'stop', '-m', 'fast', '-w'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--module',choices=tuple(NATIVE))
    parser.add_argument('action', choices=('init', 'resume-init', 'start', 'stop', 'status', 'manifest'))
    args = parser.parse_args()
    root = owned(args.root)
    if args.action == 'init': init(root, args.snapshot)
    elif args.action == 'resume-init': complete_initialization(root)
    elif args.action == 'start': start(root,(args.module,) if args.module else None)
    elif args.action == 'stop': stop(root)
    elif args.action == 'status': print(json.dumps(status(root), ensure_ascii=False))
    elif args.action == 'manifest':
        print(json.dumps(read(root/'environment.json'), ensure_ascii=False))
    if args.action in ('init', 'resume-init', 'start', 'stop'):
        print(json.dumps({'action': args.action, 'environment_root': str(root), 'production': False}))


if __name__ == '__main__': main()

