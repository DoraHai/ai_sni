"""Build a hash-bound, immutable Git release for the independent API unit."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import subprocess
import tarfile
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git','-C',str(ROOT),*args])


def assemble(commit):
    tracked = set(git('ls-tree','-r','--name-only',commit).decode().splitlines())
    selected = {n for n in tracked if n.startswith('app/distribution') and n.endswith('.py')}
    selected |= {n for n in tracked if n.startswith('app/models/') and n.endswith('.py')}
    selected |= {'app/seo_distribution_sources.py','app/seo_distribution_results.py',
                 'app/seo_distribution_media.py','app/api/distribution.py',
                 'app/api/distribution_pairing.py','app/api/distribution_remote.py',
                 'app/api/distribution_task_resolution_read.py'}
    api_init = 'deploy/distribution-production/api-init.py'
    source = {}
    pending = list(selected)
    # Follow only native app imports. API package initialization is an explicit
    # tracked build input, so importing a broker cannot start a SEM registry.
    def add_module(module):
        name = module.replace('.','/')
        for file in (name+'.py',name+'/__init__.py'):
            if file in tracked and file not in source and file not in pending:
                pending.append(file)
                break
        parts=module.split('.')
        for i in range(1,len(parts)):
            package='/'.join(parts[:i])+'/__init__.py'
            if package in tracked and package not in source and package not in pending:
                pending.append(package)
    while pending:
        name=pending.pop()
        if name in source: continue
        origin = api_init if name=='app/api/__init__.py' else name
        data=git('show',commit+':'+origin)
        source[name]=(origin,data)
        tree=ast.parse(data,filename=name)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                for alias in node.names:
                    if alias.name.startswith('app.'):
                        add_module(alias.name)
            elif isinstance(node,ast.ImportFrom):
                module=node.module or ''
                if node.level:
                    package=name[:-3].replace('/','.')
                    if not name.endswith('__init__.py'): package=package.rsplit('.',1)[0]
                    else: package=package.rsplit('.',1)[0]
                    for _ in range(node.level-1):package=package.rsplit('.',1)[0]
                    module=package+('.'+module if module else '')
                if module=='app' or module.startswith('app.'):
                    add_module(module)
                    for alias in node.names:add_module(module+'.'+alias.name)
    for name in ('docs/fixtures/mht-distribution-capabilities-v1.json',
                 'scripts/nord_distribution_acl_policy.json',
                 'scripts/nord_seo_distribution_storage_policy.json',
                 'app/static/seo-distribution-media/index.html',
                 'app/static/seo-distribution-media/app.js',
                 'app/static/seo-distribution-media/style.css',
                 'frontend/src/store/sessionStorage.js',
                 'deploy/distribution-production/source-pins.json',
                 'deploy/distribution-production/requirements.txt',
                 'deploy/distribution-production/gsnipers-distribution.service',
                 'deploy/distribution-production/nginx-location.conf',
                 'scripts/publish_distribution_production.py'):
        source[name]=(name,git('show',commit+':'+name))
    forbidden=('app/main.py','app/seo_main.py','app/geo_main.py','app/scheduler.py',
               'app/api/auth.py','app/baidu/writeback.py')
    assert not any(n in source for n in forbidden), 'Business entry/provider imported'
    assert source['app/api/__init__.py'][0]==api_init
    return source


def build(output):
    if git('status','--porcelain').strip():raise RuntimeError('Commit all inputs before build')
    commit=git('rev-parse','HEAD').decode().strip()
    source=assemble(commit)
    manifest={'schema':1,'release_commit':commit,'release_kind':'independent_distribution_api',
        'git_tree_clean':True,'database_baseline':'0107_seo_site_delete',
        'native_named_auth':True,'token_issuance':False,'automatic_publish':False,
        'remote_control':False,'workers':False,'schemas_applied_by_publisher':False,
        'files':{name:{'git_path':origin,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
                 for name,(origin,data) in sorted(source.items())}}
    data=json.dumps(manifest,ensure_ascii=False,indent=2).encode()+b'\n'
    output.mkdir(parents=True,exist_ok=False)
    archive=output/('distribution-production-'+commit[:12]+'.tar.gz')
    with tarfile.open(archive,'w:gz') as tar:
        for name,payload in sorted({**{n:d for n,(_,d) in source.items()},'release-manifest.json':data}.items()):
            item=tarfile.TarInfo(name);item.size=len(payload);item.mode=0o644;item.mtime=0
            tar.addfile(item,io.BytesIO(payload))
    (output/'release-manifest.json').write_bytes(data)
    sha=hashlib.sha256(archive.read_bytes()).hexdigest()
    (output/'SHA256SUMS').write_text(sha+'  '+archive.name+'\n')
    print(json.dumps({'release_commit':commit,'archive':str(archive),'sha256':sha,
                      'files':len(source)},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
