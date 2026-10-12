"""Owned synthetic Windows executor lifecycle; no original account/profile use."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess

from distribution_server_pilot_environment import owned,read,write,PORTS

MHT=Path('D:/微信小工具箱项目/wechat-toolbox-server-executor-20261012')
MHT_HEAD='c69b4f704e98404b3429eef280ca264f175bcb33'
PACKAGE=MHT/'release/remote-executor-frame-authority-20261012'
MANIFEST_SHA='f2b183d115c80a4a18d6665c97c41bb555ab8957e37a01f71bc93df8b24bb90f'


def verify_package():
    head=subprocess.check_output(['git','-C',str(MHT),'rev-parse','HEAD'],text=True).strip()
    if head!=MHT_HEAD or subprocess.check_output(['git','-C',str(MHT),'status','--porcelain'],text=True).strip():
        raise RuntimeError('Exact clean frozen executor required')
    if hashlib.sha256((PACKAGE/'manifest.json').read_bytes()).hexdigest()!=MANIFEST_SHA:
        raise RuntimeError('Frozen package manifest mismatch')
    manifests=[read(PACKAGE/'manifest.json')['artifacts'],read(PACKAGE/'package-support-manifest.json')['files']]
    for entries in manifests:
        for entry in entries:
            if hashlib.sha256((PACKAGE/entry['name']).read_bytes()).hexdigest()!=entry['sha256']:
                raise RuntimeError('Executor artifact changed')
    runtime=read(PACKAGE/'electron-runtime-manifest.json')
    for entry in runtime['files']:
        if hashlib.sha256((PACKAGE/'electron'/entry['name']).read_bytes()).hexdigest()!=entry['sha256']:
            raise RuntimeError('Executor runtime changed')


def config_path(root):return root/'seo-remote-executor.json'


def prepare(root):
    verify_package();public=read(root/'seo-pairing.json');private=read(root/'seo-pairing-private.json')
    expected={'module':'seo','tenant_id':15,'scope_id':6}
    if public['scope']!=expected or public['deviceId']!=private['deviceId'] or public['bindingIds']!=private['bindingIds']:
        raise RuntimeError('Exact fresh paired identity required')
    parent=root/'mht-remote-seo';home=parent/'gsnipers-distribution-agent/remote-executor'
    if home.exists():raise RuntimeError('Refuse to replace existing executor profile or credential')
    home.mkdir(parents=True)
    secret=home/'device.secret';secret.write_text(private['credential'],encoding='utf-8')
    # The Windows runner explicitly rejects credentials accessible to other SIDs.
    script="$p=$env:PILOT_DEVICE_SECRET_FILE;$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User;$acl=New-Object System.Security.AccessControl.FileSecurity;$acl.SetAccessRuleProtection($true,$false);$acl.SetOwner($sid);$rule=New-Object System.Security.AccessControl.FileSystemAccessRule($sid,'FullControl','Allow');$acl.AddAccessRule($rule);[System.IO.File]::SetAccessControl($p,$acl)"
    env={**os.environ,'PILOT_DEVICE_SECRET_FILE':str(secret)}
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=env,check=True,capture_output=True)
    config={'remote_version':1,'origin':f'https://127.0.0.1:{PORTS["seo"]}',
        'parent_root':str(parent),'device_id':public['deviceId'],'backend':'electron',
        'page_mode':'synthetic-login','allow_real_login':False,'credential_file':str(secret),
        'bindings':[{'deviceId':public['deviceId'],'bindingId':public['bindingIds'][0],
         'accountId':public['accountId'],'platform':'wechat-article','customerId':'15','projectId':'seo-6',
         **expected}]}
    write(config_path(root),config)
    write(root/'executor-package-proof.json',{'mht_head':MHT_HEAD,'manifest_sha256':MANIFEST_SHA,
        'runtime_files_verified':len(read(PACKAGE/'electron-runtime-manifest.json')['files']),
        'original_profile_used':False,'real_platform_login':False,'automatic_submit':False})


def args(root,action):
    if not config_path(root).is_file():raise RuntimeError('Fresh owned executor config required')
    config=read(config_path(root));home=(root/'mht-remote-seo/gsnipers-distribution-agent/remote-executor').resolve()
    if (Path(config['credential_file']).resolve()!=home/'device.secret' or config['origin']!='https://127.0.0.1:55861'
        or config['page_mode']!='synthetic-login' or config['allow_real_login'] is not False):
        raise RuntimeError('Only owned synthetic executor allowed')
    return ['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
        str(PACKAGE/'remote-executor-start.ps1'),'-ConfigFile',str(config_path(root)),
        '-CaFile',str(root/'loopback.pem'),'-Action',action]


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('action',choices=('prepare','start','status','stop'));a=p.parse_args();root=owned(a.root)
    if a.action=='prepare':prepare(root)
    elif a.action=='start':
        verify_package()
        with (root/'executor-run.log').open('ab') as log:
            process=subprocess.Popen(args(root,'run'),cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        write(root/'executor-process.json',{'pid':process.pid,'config':str(config_path(root))})
    else:
        value=subprocess.run(args(root,a.action),cwd=root,check=True,capture_output=True)
        print(value.stdout.decode('utf-8',errors='replace').strip())
    if a.action in ('prepare','start'):print('{"owned_executor":true,"synthetic_platform":true,"formal_publication":false}')


if __name__=='__main__':main()
