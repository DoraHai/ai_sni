"""Formal on-host publisher for the isolated distribution release.

Validates the whole artifact before changing the independent service, checks
catalog readiness, then atomically installs one narrowly scoped nginx include.
No migrations, login/token creation, SEM/provider work or task creation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import urllib.error

ROOT=Path('/opt/gsnipers-distribution')
NGINX=Path('/etc/nginx/conf.d/gsnipers.conf')
SNIPPET=Path('/etc/nginx/snippets/distribution-production.conf')
UNIT=Path('/etc/systemd/system/gsnipers-distribution.service')
ANCHOR='    include /etc/nginx/snippets/geo-routes.conf;'
INCLUDE='    include /etc/nginx/snippets/distribution-production.conf;'


def run(*args):
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.returncode:
        # Do not return provider env/secret-bearing diagnostics to a client.
        raise RuntimeError('Command failed: '+Path(args[0]).name)
    return result.stdout


def atomic(path,data,mode=0o644):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as file:file.write(data)
        os.chmod(name,mode);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def switch(release):
    temporary=ROOT/'current.next'
    if temporary.is_symlink():temporary.unlink()
    temporary.symlink_to(release);os.replace(temporary,ROOT/'current')


def safe_env():
    from dotenv import dotenv_values
    values=dotenv_values('/opt/sem-backend/.env')
    keep=('DATABASE_URL','JWT_SECRET','ADMIN_API_KEY','CRYPTO_MASTER_KEY_B64')
    if any(not values.get(key) for key in keep):raise RuntimeError('Native security config missing')
    from sqlalchemy.engine import make_url
    url=make_url(values['DATABASE_URL'])
    if url.username!='sem_runtime' or url.database!='sem_prod':
        raise RuntimeError('Expected native production runtime database')
    env={key:values[key] for key in keep}
    env.update(APP_ENV='production',APP_BASE_URL='https://gsnipers.snipers.com.cn',
        ADMIN_API_KEY_QUERY_ENABLED='false',GEO_ALLOW_SELF_REVIEW='false',
        DISTRIBUTION_DEVICE_PAIRING_ENABLED='true',DISTRIBUTION_REMOTE_CONTROL_ENABLED='false',
        BAIDU_APP_ID='unused-distribution',BAIDU_SECRET_KEY='unused-distribution',
        BAIDU_DEFAULT_USERNAME='unused-distribution',BAIDU_DEFAULT_UCID='1',
        BAIDU_SELF_ACCESS_TOKEN='unused-distribution',
        BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',BAIDU_WRITE_DRY_RUN='true')
    # systemd quoted EnvironmentFile syntax, no shell expansion or secret argv.
    return ''.join(key+'="'+value.replace('\\','\\\\').replace('"','\\"')+'"\n'
                   for key,value in env.items()).encode()


def verify_archive(archive,sha,commit):
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=sha:raise RuntimeError('Archive hash differs')
    if not re.fullmatch('[a-f0-9]{40}',commit):raise RuntimeError('Invalid Git commit')
    with tarfile.open(archive,'r:gz') as tar:
        members=tar.getmembers();names=[m.name for m in members]
        if len(names)!=len(set(names)):raise RuntimeError('Duplicate archive members')
        for member in members:
            p=Path(member.name)
            if not member.isfile() or p.is_absolute() or '..' in p.parts:raise RuntimeError('Unsafe archive')
        manifest=json.load(tar.extractfile('release-manifest.json'))
        if manifest['release_commit']!=commit or not manifest['git_tree_clean']:
            raise RuntimeError('Release provenance differs')
        if set(names)!=set(manifest['files'])|{'release-manifest.json'}:raise RuntimeError('Archive file set differs')
        for name,info in manifest['files'].items():
            b=tar.extractfile(name).read()
            if len(b)!=info['bytes'] or hashlib.sha256(b).hexdigest()!=info['sha256']:
                raise RuntimeError('Artifact content differs')
        return manifest


def health(commit):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8145/health/distribution',timeout=4) as response:
            body=json.load(response)
        return body if body.get('status')=='ok' and body.get('release_commit')==commit else None
    except (OSError,ValueError):return None


def publish(archive,sha,commit,nginx_sha):
    if os.geteuid()!=0:raise RuntimeError('Publisher needs on-host service administrator')
    manifest=verify_archive(archive,sha,commit)
    original=NGINX.read_bytes()
    if hashlib.sha256(original).hexdigest()!=nginx_sha:raise RuntimeError('Nginx changed since preflight')
    text=original.decode()
    if INCLUDE not in text:
        if text.count(ANCHOR)!=1 or '/api/distribution/' in text:
            raise RuntimeError('Unexpected nginx distribution routing')
        candidate=text.replace(ANCHOR,INCLUDE+'\n'+ANCHOR).encode()
    else:candidate=original
    previous=(ROOT/'current').resolve() if (ROOT/'current').is_symlink() else None
    if previous is None:
        sock=socket.socket()
        try:
            if sock.connect_ex(('127.0.0.1',8145))==0:raise RuntimeError('Dedicated port occupied')
        finally:sock.close()
    release=ROOT/'releases'/commit
    if release.exists():raise RuntimeError('Release exists; inspect before retry')
    old_unit=UNIT.read_bytes() if UNIT.exists() else None
    old_snippet=SNIPPET.read_bytes() if SNIPPET.exists() else None
    ROOT.mkdir(parents=True,exist_ok=True);release.mkdir(parents=True)
    # Explicit individually verified regular files; never tar.extractall.
    with tarfile.open(archive,'r:gz') as tar:
        for member in tar.getmembers():
            path=release/member.name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(tar.extractfile(member).read());path.chmod(0o644)
    for name,info in manifest['files'].items():
        if hashlib.sha256((release/name).read_bytes()).hexdigest()!=info['sha256']:
            raise RuntimeError('On-host second hash check failed')
    python='/usr/bin/python3.11'
    run(python,'-m','venv',str(release/'.venv'))
    run(str(release/'.venv/bin/python'),'-m','pip','install','--disable-pip-version-check',
        '-r',str(release/'deploy/distribution-production/requirements.txt'))
    run('chown','-R','sem:sem',str(release))
    shared=ROOT/'shared';shared.mkdir(exist_ok=True);shared.chmod(0o700)
    config=safe_env();atomic(shared/'distribution.env',config,0o600)
    backup=ROOT/'routing-history'/commit;backup.mkdir(parents=True)
    atomic(backup/'gsnipers.conf',original)
    if old_unit is not None:atomic(backup/'service.previous',old_unit)
    switched=False;nginx_changed=False
    try:
        atomic(UNIT,(release/'deploy/distribution-production/gsnipers-distribution.service').read_bytes())
        switch(release);switched=True
        run('systemctl','daemon-reload');run('systemctl','restart','gsnipers-distribution')
        status=None
        for _ in range(45):
            status=health(commit)
            if status:break
            time.sleep(1)
        if not status:raise RuntimeError('Distribution catalog readiness failed')
        atomic(SNIPPET,(release/'deploy/distribution-production/nginx-location.conf').read_bytes())
        atomic(NGINX,candidate);nginx_changed=True
        run('nginx','-t');run('systemctl','reload','nginx')
        # Strict TLS via the real server_name; anonymous adviser access stays 401.
        url='https://gsnipers.snipers.com.cn/api/distribution/v1/platform-directory?module=seo&tenant_id=1&scope_id=1'
        result=run('curl','--silent','--show-error','--resolve','gsnipers.snipers.com.cn:443:127.0.0.1',
                   '-o','/dev/null','-w','%{http_code}',url).decode()
        if result!='401':raise RuntimeError('Public anonymous auth check failed')
        run('systemctl','enable','gsnipers-distribution')
        receipt={'status':'deployed','release_commit':commit,'archive_sha256':sha,
            'health':status,'anonymous_advisor_http':401,'previous_release':str(previous) if previous else None,
            'nginx_before_sha256':nginx_sha,'nginx_after_sha256':hashlib.sha256(candidate).hexdigest(),
            'database_ddl_by_publisher':False,'other_business_services_restarted':False,
            'real_task_or_publication_done':False}
        atomic(backup/'deployment-receipt.json',json.dumps(receipt,indent=2).encode()+b'\n')
        print(json.dumps(receipt))
    except Exception:
        if nginx_changed:
            atomic(NGINX,original)
            if old_snippet is not None:atomic(SNIPPET,old_snippet)
            elif SNIPPET.exists():SNIPPET.unlink()
            run('nginx','-t');run('systemctl','reload','nginx')
        if switched:
            if previous:
                switch(previous)
                if old_unit is not None:atomic(UNIT,old_unit)
                run('systemctl','daemon-reload');run('systemctl','restart','gsnipers-distribution')
            else:
                run('systemctl','stop','gsnipers-distribution')
                if (ROOT/'current').is_symlink():(ROOT/'current').unlink()
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--sha256',required=True);p.add_argument('--commit',required=True)
    p.add_argument('--expected-nginx-sha256',required=True)
    a=p.parse_args();publish(a.archive,a.sha256,a.commit,a.expected_nginx_sha256)
