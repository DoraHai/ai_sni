"""Check the actual assembled unit's isolation and unauthenticated boundaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

CHECK = r'''
import os,sys,asyncio,json
os.environ.update(DATABASE_URL="postgresql+asyncpg://unused:unused@127.0.0.1:9/test",
 BAIDU_APP_ID="unused",BAIDU_SECRET_KEY="unused",BAIDU_DEFAULT_USERNAME="unused",
 BAIDU_DEFAULT_UCID="1",BAIDU_SELF_ACCESS_TOKEN="unused",
 BAIDU_SELF_TOKEN_EXPIRES_AT="2099-01-01T00:00:00Z",
 CRYPTO_MASTER_KEY_B64="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
 ADMIN_API_KEY="unit-only-invalid-key",JWT_SECRET="unit-only-invalid-jwt",
 DISTRIBUTION_DEVICE_PAIRING_ENABLED="true",ADMIN_API_KEY_QUERY_ENABLED="false")
from app.distribution_production import app
from app import seo_distribution_sources,seo_distribution_results
from httpx import ASGITransport,AsyncClient
paths={r.path for r in app.routes}
assert "/api/distribution/v1/device-pairings/claim" in paths
assert "/api/distribution/capabilities/v1/device/register" in paths
assert "/api/distribution/v1/device/exchange" in paths
assert "/api/distribution/v1/device/task-resolution" in paths
assert "/api/seo/distribution-media/workspace" in paths
assert not any("/remote/" in p or "/login" in p or "/auth" in p for p in paths)
assert not {"app.main","app.scheduler","app.api.auth","app.baidu.writeback"}.intersection(sys.modules)
async def check():
 async with AsyncClient(transport=ASGITransport(app=app),base_url="https://gsnipers.snipers.com.cn") as c:
  for path in ["/api/distribution/v1/platform-directory?module=seo&tenant_id=1&scope_id=1", "/api/distribution/v1/device-pairings"]:
   r=await c.get(path);assert r.status_code==401,(path,r.status_code)
   assert r.headers.get("cache-control")=="no-store"
  r=await c.get("/api/distribution/v1/device-pairings?key=unit-only-invalid-key");assert r.status_code==400
  r=await c.get("/api/distribution/v1/platform-directory?module=seo&tenant_id=1&scope_id=1&key=unit-only-invalid-key")
  assert r.status_code in (400,401)
  r=await c.get("/api/distribution/v1/platform-directory?module=seo&tenant_id=1&scope_id=1",headers={"X-API-Key":"unit-only-invalid-key"})
  assert r.status_code==403
  r=await c.get("http://gsnipers.snipers.com.cn/api/distribution/v1/device-pairings");assert r.status_code==426
  r=await c.get("/api/distribution/v1/device-pairings",headers={"Authorization":"Bearer invalid"});assert r.status_code==401
  r=await c.get("/api/distribution/v1/remote/sessions");assert r.status_code==404
  r=await c.get("/docs");assert r.status_code==404
  r=await c.get("/api/seo/distribution-media/variants?tenant_id=1&site_id=1");assert r.status_code==401
  r=await c.get("/api/seo/distribution-media/workspace");assert r.status_code==200
  assert 'frame-ancestors' in r.headers['content-security-policy']
  for asset in ('app.js','style.css','session.js'):
   r=await c.get('/api/seo/distribution-media/ui/'+asset);assert r.status_code==200
 print(json.dumps({"passed":True,"assembled_routes":len(paths),"anonymous_advisor_and_pairing_denied":True,
  "query_key_not_accepted":True,"api_key_cannot_replace_named_advisor":True,"invalid_bearer_denied":True,
  "https_only_pairing":True,"remote_and_auth_routes_absent":True,"business_entries_not_imported":True,
  "production_database_or_tasks_used":False}))
asyncio.run(check())
'''


def verify(archive,sha,report):
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=sha:raise RuntimeError('Archive SHA differs')
    with tempfile.TemporaryDirectory(prefix='distribution-production-check-') as directory:
        root=Path(directory)
        with tarfile.open(archive) as tar:
            names=[m.name for m in tar.getmembers()]
            assert len(names)==len(set(names))
            manifest=json.load(tar.extractfile('release-manifest.json'))
            assert set(names)==set(manifest['files'])|{'release-manifest.json'}
            for member in tar.getmembers():
                path=Path(member.name)
                assert member.isfile() and not path.is_absolute() and '..' not in path.parts
                payload=tar.extractfile(member).read()
                if member.name!='release-manifest.json':
                    info=manifest['files'][member.name]
                    assert len(payload)==info['bytes'] and hashlib.sha256(payload).hexdigest()==info['sha256']
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(payload)
        assert manifest['files']['app/api/__init__.py']['git_path']=='deploy/distribution-production/api-init.py'
        script=root/'artifact_check.py';script.write_text(CHECK)
        run=subprocess.run([sys.executable,'-B',str(script)],cwd=root,capture_output=True,text=True)
        if run.returncode:raise RuntimeError(run.stderr[-3500:])
        result=json.loads(run.stdout.strip())
        result.update(release_commit=manifest['release_commit'],archive_sha256=sha,
                      artifact_files_verified=len(manifest['files']))
        report.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--sha256',required=True);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();verify(a.archive,a.sha256,a.report)
