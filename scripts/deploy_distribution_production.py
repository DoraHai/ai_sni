"""Upload a frozen artifact to private staging and invoke its formal publisher."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess


def deploy(archive,receipt,expected_nginx,output):
    root=Path(__file__).resolve().parents[1]
    if subprocess.check_output(['git','-C',str(root),'status','--porcelain']).strip():
        raise RuntimeError('Deployment source tree must be committed')
    commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    verification=json.loads((archive.parent/'verification.json').read_text(encoding='utf-8'))
    payload=archive.read_bytes();sha=hashlib.sha256(payload).hexdigest()
    if not verification['passed'] or verification['release_commit']!=commit or verification['archive_sha256']!=sha:
        raise RuntimeError('Current frozen artifact verification differs')
    db=json.loads(receipt.read_text(encoding='utf-8'))
    if not (db.get('ok') and db.get('status')=='APPLIED_AND_VERIFIED'
            and db.get('independent_review_status')=='PASS'
            and db.get('release_commit')=='102e4026539d0de24851b27d8f7ead5fc56e8ca8'):
        raise RuntimeError('Reviewed core database receipt required before deployment')
    receipt_sha=hashlib.sha256(receipt.read_bytes()).hexdigest()
    config={'commit':commit,'sha':sha,'archive':base64.b64encode(payload).decode(),
            'receipt_path':db['server_json_receipt_path'],'receipt_sha':receipt_sha,
            'expected_nginx':expected_nginx}
    # Code and public artifact bytes only, never credentials or a human JWT.
    script=r'''
import base64,hashlib,json,pathlib,subprocess,tarfile,tempfile
c=CONFIG
p=pathlib.Path(c['receipt_path'])
assert hashlib.sha256(p.read_bytes()).hexdigest()==c['receipt_sha']
r=json.loads(p.read_text());assert r['status']=='APPLIED_AND_VERIFIED'
stage=pathlib.Path(tempfile.mkdtemp(prefix='distribution-release-'+c['commit'][:12]+'-',dir='/var/tmp'))
stage.chmod(0o700)
archive=stage/'release.tar.gz';archive.write_bytes(base64.b64decode(c['archive']))
assert hashlib.sha256(archive.read_bytes()).hexdigest()==c['sha']
with tarfile.open(archive) as tar:
 manifest=json.load(tar.extractfile('release-manifest.json'))
 assert manifest['release_commit']==c['commit']
 name='scripts/publish_distribution_production.py';b=tar.extractfile(name).read()
 assert hashlib.sha256(b).hexdigest()==manifest['files'][name]['sha256']
 publisher=stage/'publish_distribution_production.py';publisher.write_bytes(b)
process=subprocess.run(['/opt/sem-backend/.venv/bin/python',str(publisher),
 '--archive',str(archive),'--sha256',c['sha'],'--commit',c['commit'],
 '--expected-nginx-sha256',c['expected_nginx']],capture_output=True,text=True)
(stage/'publisher.stdout').write_text(process.stdout);(stage/'publisher.stderr').write_text(process.stderr)
if process.returncode:
 print(json.dumps({'status':'failed','stage':str(stage),'publisher_exit':process.returncode,
                   'diagnostic':process.stderr[-1000:]}))
else:print(process.stdout.strip())
raise SystemExit(process.returncode)
'''.replace('CONFIG',repr(config))
    process=subprocess.run(['C:/Windows/System32/OpenSSH/ssh.exe','-T','-o','BatchMode=yes',
        '-o','StrictHostKeyChecking=yes','g-snipers-101','python3','-'],
        input=script.encode('utf-8'),capture_output=True)
    response=process.stdout.decode('utf-8','replace')
    output.write_text(response,encoding='utf-8')
    if process.returncode:
        print(response.strip())
        raise RuntimeError('Formal deployment failed; on-host diagnostics retained')
    result=json.loads(response);assert result['status']=='deployed' and result['release_commit']==commit
    print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--database-receipt',type=Path,required=True)
    p.add_argument('--expected-nginx-sha256',required=True);p.add_argument('--receipt-output',type=Path,required=True)
    a=p.parse_args();deploy(a.archive,a.database_receipt,a.expected_nginx_sha256,a.receipt_output)
