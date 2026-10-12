"""Synthetic native-SEO/JWT/HTTPS broker fixture, owned loopback PG only."""
import argparse
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import types

ROOT_NAME='distribution-device-pairing-tests-20261012'
PG=Path('D:/sem-cockpit-pg-runtime/bin')
PYTHON=Path('D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe')
CENTRAL=Path(__file__).resolve().parents[1]
NATIVE=Path('D:/SNIPERS国内版/ai_sni-worktrees/seo-review-response-acceptance-20261012')
NATIVE_HEAD='b4d8387123355348f79e26ea2838585c5106a4b9'
FAULTS={}


def owned(value):
    root=Path(value).resolve()
    if root.parent!=Path(os.environ['TEMP']).resolve() or root.name!=ROOT_NAME:raise RuntimeError('Exact owned remote test root required')
    return root


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')


def env(root):
    private=read(root/'secrets.json');config=read(root/'environment.json')
    result={key:value for key,value in os.environ.items() if key.upper() in {'SYSTEMROOT','WINDIR','PATH','TEMP','TMP','LOCALAPPDATA','APPDATA','USERPROFILE'}}
    result.update(PYTHONUTF8='1',DATABASE_URL='postgresql+asyncpg://device_pairing_test@127.0.0.1:55547/device_pairing_test',
        JWT_SECRET=private['jwt'],ADMIN_API_KEY=private['admin'],CRYPTO_MASTER_KEY_B64=private['crypto'],
        BAIDU_APP_ID='synthetic',BAIDU_SECRET_KEY='synthetic',BAIDU_DEFAULT_USERNAME='synthetic',BAIDU_DEFAULT_UCID='1',
        BAIDU_SELF_ACCESS_TOKEN='synthetic',BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',BAIDU_WRITE_DRY_RUN='true',
        API_CONTROLS_ENABLED='true',API_METERING_ENABLED='true',DISTRIBUTION_REMOTE_CONTROL_ENABLED='true',DISTRIBUTION_DEVICE_PAIRING_ENABLED='true',
        REMOTE_TEST_ROOT=str(root),REMOTE_TEST_SCHEMA=config['schema'])
    return result


def command(root,args,*,native=False):
    with (root/'last-error-private.log').open('ab') as log:
        result=subprocess.run([str(a) for a in args],cwd=root,env=env(root) if native else None,
            stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError('Owned fixture command failed; inspect private error log')


def prepare(root):
    config=read(root/'environment.json')
    if config['root']!=str(root) or config['port']!=55881 or config['pg_port']!=55547 or config['production'] is not False:
        raise RuntimeError('Exact owned test config required')
    if Path.cwd().resolve()!=root or (root/'.env').exists():raise RuntimeError('Private no-dotenv cwd required')
    sys.path.append(str(root/'python-deps'))
    from distribution_assembled_worker import assemble,HEADS
    old=HEADS['seo']
    try:HEADS['seo']=NATIVE_HEAD;manifest=assemble(NATIVE,'seo')
    finally:HEADS['seo']=old
    manifest['assembly_original_central_head']=manifest['central_head']
    manifest['central_head']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CENTRAL,text=True).strip()
    manifest['remote_files']={name:hashlib.sha256((CENTRAL/name).read_bytes()).hexdigest() for name in (
        'app/distribution_pairing_contract.py','app/distribution_pairing.py','app/api/distribution_pairing.py',
        'app/api/distribution.py','scripts/distribution_device_pairing_schema.sql','scripts/distribution_pairing_test_service.py')}
    import app
    package=types.ModuleType('app.api');package.__path__=[str(NATIVE/'app/api'),str(CENTRAL/'app/api')]
    sys.modules['app.api']=package;app.api=package
    from app import database
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker,AsyncSession
    class FaultSession(AsyncSession):
        async def commit(self):
            if FAULTS.pop('commit',False):
                from sqlalchemy import text
                await self.execute(text('SELECT 1/0'))
            return await super().commit()
    engine=create_async_engine(os.environ['DATABASE_URL'],hide_parameters=True,
        connect_args={'server_settings':{'search_path':config['schema'],'timezone':'UTC','lock_timeout':'5000','statement_timeout':'15000'}},
        execution_options={'schema_translate_map':{'public':config['schema']}})
    sessions=async_sessionmaker(engine,class_=FaultSession,expire_on_commit=False);database.engine=engine;database.async_session_factory=sessions
    from app import api_controls,api_metering
    api_controls.async_session_factory=sessions;api_metering.async_session_factory=sessions
    return config,engine,sessions,manifest


async def seed(root):
    config,engine,sessions,manifest=prepare(root)
    import app.models
    from app.database import Base
    from app.models import Tenant
    from app.models.module_workspace import TenantModule,SeoSite
    from app.models.user import User
    from app.models.role import Role
    from app.security.auth import hash_password
    from sqlalchemy import text
    from sqlalchemy.schema import CreateTable
    try:
        async with engine.begin() as db:
            await db.execute(text('CREATE SCHEMA '+config['schema']))
            for table in Base.metadata.tables.values():
                if (table.name in {'tenants','tenant_modules','roles','users'} or table.name.startswith('seo_')) and table.name not in {'seo_site_advisor_assignments','seo_content_confirmations'}:
                    await db.execute(CreateTable(table,include_foreign_key_constraints=[]))
            raw=(await db.get_raw_connection()).driver_connection
            sources=[NATIVE/'scripts/api_metering_schema.sql',NATIVE/'scripts/api_controls_schema.sql']
            sources += [CENTRAL/('scripts/distribution_'+name+'_schema.sql') for name in ['control','scheduling','publication','queue','planning','execution','capability_registration','remote']]
            sources.append(CENTRAL/'scripts/distribution_device_pairing_schema.sql')
            for source in sources:await raw.execute(source.read_text(encoding='utf-8-sig').replace('BEGIN;','').replace('COMMIT;',''))
            source=NATIVE/'migrations/versions/20261001_0105_seo_content_confirmations.py'
            if not source.is_file():
                source=next((NATIVE/'migrations/versions').glob('*0105*'))
            spec=importlib.util.spec_from_file_location('remote_native_0105',source);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            def upgrade(sync):
                migration.op=Operations(MigrationContext.configure(sync));migration.upgrade()
            await db.run_sync(upgrade)
            await db.execute(text('CREATE TABLE alembic_version(version_num varchar(64) PRIMARY KEY)'))
            await db.execute(text('INSERT INTO alembic_version VALUES(:version)'),{'version':migration.revision})
            write(root/'native-schema.json',{'actual_upgrade':True,'revision':migration.revision,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'production':False})
        async with sessions.begin() as db:
            db.add_all([Tenant(id=15,name='Remote synthetic tenant'),Tenant(id=16,name='Remote foreign tenant')])
            db.add_all([Role(id=1,name='Remote test advisor',permissions={'seo.content':'edit','seo.site':'edit','seo.assets':'edit','seo.keywords':'edit'}),
                Role(id=2,name='Remote test admin',permissions={'seo.content':'edit','seo.site':'edit','seo.assets':'edit','seo.keywords':'edit','settings.accounts':'edit','settings.customers':'edit'}),
                Role(id=3,name='Remote test customer',permissions={'seo.content':'view','seo.site':'view'}),Role(id=4,name='Pairing rescue admin',permissions={'settings.accounts':'edit','settings.customers':'edit'})])
            secret=read(root/'secrets.json')['password']
            for uid,name,role,tenant in [(100007,'advisor',1,None),(100008,'admin',2,None),(100012,'reviewer',1,None),
                    (100015,'customer',3,15),(100016,'foreign',3,16),(100009,'rescue',4,None)]:
                db.add(User(id=uid,username=name,display_name=name,password_hash=hash_password(secret),role_id=role,tenant_id=tenant,is_active=True))
            for module_id,tenant,site in [(1,15,6),(2,16,7)]:
                db.add(TenantModule(id=module_id,tenant_id=tenant,module_code='seo',status='active'))
                db.add(SeoSite(id=site,tenant_id=tenant,tenant_module_id=module_id,name='Synthetic remote website',domain=f'remote-{tenant}.example',canonical_domain=f'remote-{tenant}.example',status='active',site_settings={}))
        write(root/'native-manifest.json',manifest)
    finally:await engine.dispose()


def make_app(root):
    config,engine,sessions,manifest=prepare(root)
    write(root/'runtime-manifest.json',manifest)
    from fastapi import FastAPI,APIRouter,Depends
    from app.database import get_session
    from app.api.distribution import router
    from app.api.auth import router as native_auth
    from app.api.seo import router as native_seo
    app=FastAPI(title='Owned synthetic remote broker')
    async def database():
        async with sessions() as db:yield db
    app.dependency_overrides[get_session]=database;app.include_router(router)
    for route in native_auth.routes:
        if route.endpoint.__name__ in {'login','me'}:app.router.routes.append(route)
    names={'create_seo_keyword','upsert_advisor_assignment','create_content_confirmation','get_content_delivery','create_content_asset','submit_content_review',
        'decide_content_review','create_distribution_connection','adapt_content_distribution','save_distribution_variant','review_distribution_variant','update_content_asset'}
    selected=APIRouter()
    for route in native_seo.routes:
        if route.endpoint.__name__ in names:selected.routes.append(route)
    app.include_router(selected)
    from app.security.auth import require_auth
    from app.api.distribution import named
    from app import distribution_control as core
    base_audit=core.audit
    async def audit(db,actor,action,target,result,task_id=None):
        if action in ('pairing_created','pairing_claimed') and FAULTS.pop('audit',False):await db.execute(core.text('SELECT 1/0'))
        return await base_audit(db,actor,action,target,result,task_id)
    core.audit=audit
    from pydantic import BaseModel,ConfigDict
    from typing import Literal
    class TestFault(BaseModel):
        model_config=ConfigDict(extra='forbid')
        mode:Literal['audit','commit']
    class TestMutation(BaseModel):
        model_config=ConfigDict(extra='forbid')
        kind:Literal['expire-session','advisor-role','expire-lease','owner-lost','expire-pairing','admin-role','site-status','module-status','scope-schema']
        id:str=''
        active:bool=True
    @app.post('/test/fault')
    async def fault(req:TestFault,db=Depends(database),ctx=Depends(require_auth)):
        await named(db,ctx,admin=True);FAULTS[req.mode]=True;return {'armed':True}
    @app.post('/test/mutate')
    async def mutate(req:TestMutation,db=Depends(database),ctx=Depends(require_auth)):
        await named(db,ctx,admin=True)
        if req.kind=='expire-pairing':await db.execute(core.text('UPDATE distribution_device_pairings SET expires_at=created_at+1 WHERE id=:id'),{'id':req.id})
        elif req.kind=='admin-role':await db.execute(core.text('UPDATE roles SET permissions=CAST(:perms AS jsonb) WHERE id=2'),{'perms':json.dumps({key:'edit' for key in ('settings.accounts','settings.customers','seo.site','seo.content','seo.assets','seo.keywords')} if req.active else {})})
        elif req.kind=='site-status':await db.execute(core.text('UPDATE seo_sites SET status=:status WHERE id=6'),{'status':'active' if req.active else 'paused'})
        elif req.kind=='module-status':await db.execute(core.text('UPDATE tenant_modules SET status=:status WHERE tenant_id=15 AND module_code=\'seo\''),{'status':'active' if req.active else 'paused'})
        elif req.kind=='scope-schema':await db.execute(core.text('ALTER TABLE '+('owned_missing_advisor_schema RENAME TO seo_site_advisor_assignments' if req.active else 'seo_site_advisor_assignments RENAME TO owned_missing_advisor_schema')))
        elif req.kind=='expire-session':await db.execute(core.text('UPDATE distribution_remote_sessions SET expires_at=:at WHERE id=:id'),{'at':core.now_ms()-1,'id':req.id})
        elif req.kind=='expire-lease':await db.execute(core.text('UPDATE distribution_tasks SET lease_expires_at=:at WHERE id=:id'),{'at':core.now_ms()-1,'id':req.id})
        elif req.kind=='owner-lost':
            from app.distribution_remote import broker
            await broker.owner.execute('SELECT pg_advisory_unlock_all()')
        else:
            perms={key:'edit' if req.active else 'view' for key in ('seo.site','seo.content','seo.assets','seo.keywords')}
            await db.execute(core.text('UPDATE roles SET permissions=CAST(:perms AS jsonb) WHERE id=1'),{'perms':json.dumps(perms)})
        await db.commit();return {'owned_fixture_changed':True}
    @app.get('/test/metadata')
    async def metadata(db=Depends(database),ctx=Depends(require_auth)):
        await named(db,ctx,admin=True)
        from app.distribution_remote import broker
        return {'nonces':len(broker.nonces),'frames':len(broker.frames),'payloads':len(broker.payloads),
            'read_frames':sum(len(history) for history in broker.read_frames.values()),
            'max_session_read_frames':max((len(history) for history in broker.read_frames.values()),default=0),
            'active_rows':await db.scalar(core.text("SELECT count(*) FROM distribution_remote_sessions WHERE state IN ('requested','active')"))}
    @app.get('/test-health')
    async def health():
        from app.distribution_remote import broker
        return {'native_head':NATIVE_HEAD,'central_head':manifest['central_head'],'remote_files':manifest['remote_files'],
            'broker_epoch':broker.epoch,'automatic_submit':False,'production':False,'module':'seo'}
    # No external transport or publication is part of the synthetic fixture.
    import httpx
    async def guarded(self,request):raise RuntimeError('External network disabled in remote broker test')
    httpx.AsyncHTTPTransport.handle_async_request=guarded
    return app


def init(root):
    if root.exists():raise RuntimeError('Owned remote fixture already exists')
    for port in (55547,55881):
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('New fixture port occupied')
    root.mkdir();write(root/'secrets.json',{'jwt':secrets.token_urlsafe(48),'admin':secrets.token_urlsafe(48),
        'crypto':base64.b64encode(secrets.token_bytes(32)).decode(),'password':secrets.token_urlsafe(24)})
    write(root/'environment.json',{'root':str(root),'schema':'device_pairing_'+secrets.token_hex(16),'port':55881,'pg_port':55547,'production':False})
    dependency=Path(os.environ['TEMP'])/'distribution-acceptance-full-flow-20261012/python-deps'
    if not dependency.is_dir():raise RuntimeError('Reviewed dependency-only directory unavailable')
    shutil.copytree(dependency,root/'python-deps')
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Owned remote broker test')])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False).sign(key,hashes.SHA256()))
    (root/'loopback.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM));(root/'loopback.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    command(root,[PG/'initdb.exe','-D',root/'pg','-U','device_pairing_test','-A','trust','--encoding=UTF8'])
    command(root,[PG/'pg_ctl.exe','-D',root/'pg','-o','-h 127.0.0.1 -p 55547 -c timezone=UTC','-l',root/'postgres.log','start','-w'])
    command(root,[PG/'createdb.exe','-h','127.0.0.1','-p','55547','-U','device_pairing_test','device_pairing_test'])
    command(root,[PYTHON,Path(__file__),'--root',root,'seed'],native=True)


def start(root):
    log=(root/'serve-private.log').open('ab')
    proc=subprocess.Popen([str(PYTHON),str(Path(__file__)),'--root',str(root),'serve'],cwd=root,env=env(root),
        stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));log.close()
    write(root/'process.json',{'pid':proc.pid,'script':str(Path(__file__).resolve()),'root':str(root)})


def stop(root):
    # Matches only this exact private fixture's Python serve processes.
    script="Get-CimInstance Win32_Process | Where-Object {$_.Name -eq 'python.exe' -and $_.CommandLine -like '*distribution_pairing_test_service.py*' -and $_.CommandLine -like '*distribution-device-pairing-tests-20261012*' -and $_.CommandLine -match '\\bserve(?:-off)?\\b'} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
    subprocess.run(['powershell.exe','-NoProfile','-Command',script],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('action',choices=['init','seed','start','stop','serve','serve-off']);args=p.parse_args();root=owned(args.root)
    if args.action=='init':init(root)
    elif args.action=='seed':asyncio.run(seed(root))
    elif args.action=='start':start(root)
    elif args.action=='stop':stop(root)
    else:
        if args.action=='serve-off':os.environ['DISTRIBUTION_REMOTE_CONTROL_ENABLED']='false';os.environ['DISTRIBUTION_DEVICE_PAIRING_ENABLED']='false'
        import uvicorn
        uvicorn.run(make_app(root),host='127.0.0.1',port=55882 if args.action=='serve-off' else 55881,ssl_certfile=str(root/'loopback.pem'),ssl_keyfile=str(root/'loopback.key'),workers=1,access_log=False)
    print('owned_remote_fixture_'+args.action)


if __name__=='__main__':main()
