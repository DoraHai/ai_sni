"""Actual main.app, real JWT and production composition in disposable SQLite.

Separate interpreter: no .env, real settings, scheduler, network or shared stubs.
Only the real application's database dependency is redirected to its test session.
"""
import asyncio
import builtins
import io
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
def protect(original):
    def checked(file, *args, **kw):
        if isinstance(file, (str, Path)) and Path(file).name == '.env':
            raise AssertionError('real .env forbidden')
        return original(file, *args, **kw)
    return checked
builtins.open, io.open = protect(builtins.open), protect(io.open)
def no_network(*args, **kw):
    raise AssertionError('network forbidden')
socket.create_connection = socket.getaddrinfo = no_network


async def run(directory):
    import app.config
    import yaml
    for key in app.config.Settings.model_fields:
        os.environ.pop(key.upper(), None)
    workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8'))
    for job in workflow['jobs'].values():
        for step in job.get('steps', []):
            if step.get('name') == 'Run tests':
                os.environ.update({k: str(v) for k, v in step['env'].items()
                                   if not k.endswith('_TEST_DATABASE_URL')})
    os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///' + str(directory / 'main.sqlite')
    app.config.Settings.model_config['env_file'] = None
    app.config.get_settings.cache_clear()
    # The production factory supplies PG-only pool options. Preserve the real
    # factory/database module while selecting a valid pool for disposable SQLite.
    import sqlalchemy.ext.asyncio as sa_async
    original_engine = sa_async.create_async_engine
    def local_engine(url, **kw):
        kw.pop('pool_size', None)
        kw.pop('max_overflow', None)
        return original_engine(url, **kw)
    sa_async.create_async_engine = local_engine
    # ASGITransport must not enter application lifespan or start background jobs.
    from unittest.mock import Mock
    import app.scheduler
    scheduler_start = Mock(side_effect=AssertionError('scheduler start forbidden'))
    app.scheduler.start_scheduler = scheduler_start
    from app.main import app
    from app.database import engine, async_session_factory as factory, get_session
    from app.security import auth
    from app.security.auth import require_auth
    from app.sem_phase1a.production_principals import production_principal_dependency
    from app.models import Tenant, TenantModule, BaiduAccount
    from app.models.user import User
    from app.models.role import Role
    from app.models.advisor_tenant_grant import AdvisorTenantGrant
    from app.permissions import ALL_EDIT, CLIENT_PERMS
    from sqlalchemy import MetaData, Table, Column, BigInteger, text, event
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    from httpx import AsyncClient, ASGITransport
    from datetime import datetime
    import jwt
    @compiles(JSONB, 'sqlite')
    def jsonb(type_, compiler, **kw):
        return 'JSON'
    @event.listens_for(engine.sync_engine, 'connect')
    def fks(db, _):
        db.execute('PRAGMA foreign_keys=ON')
    metadata = MetaData()
    Table('baidu_oauth_grants', metadata, Column('id', BigInteger, primary_key=True))
    for model in (Role, Tenant, User, AdvisorTenantGrant, TenantModule, BaiduAccount):
        model.__table__.to_metadata(metadata)
    cfg = Config(); cfg.set_main_option('script_location', str(ROOT / 'migrations'))
    scripts = ScriptDirectory.from_config(cfg)
    assert scripts.get_heads() == ['0079_sem_phase0_sources']
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        def migrate(db):
            with Operations.context(MigrationContext.configure(db)):
                for rev in ('0077_sem_phase1a_shadow', '0078_sem_phase1a_grants', '0079_sem_phase0_sources'):
                    scripts.get_revision(rev).module.upgrade()
        await connection.run_sync(migrate)
    async with factory() as session, session.begin():
        session.add_all([
            Role(id=1, name='合成顾问', is_system=False, permissions={'seo.site':'edit','seo.content':'edit'}),
            Role(id=2, name='品牌方客户', is_system=True, permissions=CLIENT_PERMS),
            Role(id=3, name='管理员', is_system=True, permissions=ALL_EDIT),
            Role(id=4, name='合成平台管理员', is_system=False,
                 permissions={'settings.accounts':'edit','settings.customers':'edit'}),
            Tenant(id=101, name='合成客户'), Tenant(id=102, name='合成其他客户'),
            User(id=1, username='synthetic-advisor', password_hash='unused', role_id=1, tenant_id=101),
            User(id=2, username='synthetic-customer', password_hash='unused', role_id=2, tenant_id=101),
            User(id=7, username='synthetic-other', password_hash='unused', role_id=2, tenant_id=102),
            User(id=8, username='synthetic-platform', password_hash='unused', role_id=4),
            User(id=9, username='synthetic-admin', password_hash='unused', role_id=3),
            TenantModule(id=1, tenant_id=101, module_code='sem', status='active'),
            TenantModule(id=2, tenant_id=102, module_code='sem', status='active'),
            AdvisorTenantGrant(id=10, user_id=1, tenant_id=101, grant_source='admin', granted_by=1)])
        await session.flush([o for o in session.new if isinstance(o, (Role, Tenant))])
        await session.flush([o for o in session.new if isinstance(o, User)])
        await session.flush()
        for aid, tid in ((201,101),(204,101),(202,102)):
            session.add(BaiduAccount(id=aid, tenant_id=tid, baidu_username='synthetic-'+str(aid), baidu_ucid=aid,
                access_token_encrypted='unused', expires_at=datetime(2099,1,1)))
        await session.flush()
        await session.execute(text('INSERT INTO sem_phase1a_account_grants(user_id,tenant_id,account_id,advisor_grant_id) '
            'VALUES(1,101,201,10),(2,101,201,NULL),(7,102,202,NULL)'))
    signing = secrets.token_hex(32)
    auth._jwt_secret = lambda: signing
    def token(uid, **changes):
        now = int(time.time())
        claims = {'sub':str(uid),'iat':now,'exp':now+3600}
        if uid == 1:
            claims.update(scope_kind='advisor_tenant', aud='advisor-business', tid=101, gid=10, auth_exp=now+3600)
        claims.update(changes)
        return jwt.encode(claims, signing, algorithm='HS256')
    headers = {uid: {'Authorization':'Bearer '+token(uid)} for uid in (1,2,7,8,9)}
    # No overrides of require_auth, principal, role/module or service boundaries.
    assert not app.dependency_overrides
    assert __import__('inspect').signature(production_principal_dependency()).parameters['ctx'].default.dependency is require_auth
    logging.disable(logging.CRITICAL)
    async def sql(statement):
        async with factory() as session, session.begin():
            await session.execute(text(statement))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='https://testserver') as api:
        source = '/api/v1/sem/phase0/submissions'
        shadow = '/api/v1/sem/phase1a/shadow/plans'
        grants = '/api/v1/sem/phase1a/account-grants/accounts/201'
        payload = json.loads((ROOT/'docs/sem-phase1a/fixtures/submission.internal.json').read_text(encoding='utf-8'))
        payload['page_content'] = 'product: 合成生产来源\nbenefit: 可核验提交\nkeywords: 合成测试'
        advisor_outcomes = [None] * 15
        response = await api.post(source, data={'metadata':json.dumps(payload)}, headers=headers[1])
        assert response.status_code == 201, ('source', response.status_code, response.text)
        advisor_outcomes[13] = response.status_code
        create = {'tenant_id':101,'account_id':201,'page_id':payload['landing_page_id'],'submission_revision':1}
        response = await api.post(shadow, json=create, headers=headers[1])
        assert response.status_code == 201, ('create', response.status_code, response.text)
        advisor_outcomes[0] = response.status_code
        pid = response.json()['plan_id']
        assert response.json()['backend'] == 'submitted_only'
        assert all(s['origin']=='submission' for s in response.json()['sources'])
        assert not response.json()['synthetic']
        response = await api.post(f'{shadow}/{pid}/rulings', json={'expected_version':1,'reason':'合成裁定'},headers=headers[1])
        assert response.status_code == 200, ('ruling',response.status_code,response.text)
        advisor_outcomes[3] = response.status_code
        assert 'account_cap_unverified' in response.json()['rehearsal_only_blockers']
        cases = [
            ('POST',shadow, {'json':create}),
            ('POST',shadow+'/batch', {'json':{'tenant_id':101,'account_id':201,
                'pages':[{'page_id':payload['landing_page_id'],'submission_revision':1}]}}),
            ('GET',f'{shadow}/{pid}',{}),
            ('POST',f'{shadow}/{pid}/rulings',{'json':{'expected_version':2,'reason':'合成裁定'}}),
            ('POST',f'{shadow}/{pid}/structure',{'json':{'expected_version':2,'reason':'合成改名',
                'operations':[{'action':'update','row_id':'r-2','text':'合成方案'}]}}),
            ('GET',f'{shadow}/{pid}/excel/advisor',{}),
            ('POST',f'{shadow}/{pid}/previews/advisor',{'files':{'file':('internal.xlsx',b'fixture')}}),
            ('POST',f'{shadow}/{pid}/apply-preview',{'json':{'expected_version':2,'preview_id':'missing'}}),
            ('POST',f'{shadow}/{pid}/approvals',{'json':{'expected_version':2,'reason':'合成复核','row_ids':['r-1']}}),
            ('GET',f'{shadow}/{pid}/expiry-suggestions',{}),
            ('GET',grants+'?tenant_id=101',{}),
            ('POST',grants,{'json':{'tenant_id':101,'user_id':1,'advisor_grant_id':10}}),
            ('POST',grants+'/revoke',{'json':{'tenant_id':101,'user_id':1}}),
            ('POST',source,{'data':{'metadata':json.dumps(payload)}}),
            ('GET',f'{source}/101/201/{payload["landing_page_id"]}/1',{})]
        mounted = {(m,r.path) for r in app.routes if getattr(r,'path','').startswith(('/api/v1/sem/phase1a','/api/v1/sem/phase0'))
                   for m in r.methods}
        assert len(mounted) == len(cases) == 15
        from starlette.routing import Match
        for method,path,_ in cases:
            matches = [r for r in app.routes if r.matches({'type':'http','method':method,'path':path.split('?')[0],
                'root_path':''})[0] == Match.FULL]
            assert len(matches) == 1
        # Actual OpenAPI and route inventory, restricted to the newly mounted API.
        schema = app.openapi()
        paths = [p for p in schema['paths'] if p.startswith(('/api/v1/sem/phase1a','/api/v1/sem/phase0'))]
        assert len(paths) == len({p for _,p in mounted})
        for p in paths:
            assert not any(term in p for term in ('execute','upload-to-baidu','enable','customer-confirm','auto-pause'))
        results = {'inventory':15}
        async def grant_snapshot():
            async with factory() as session:
                snapshots = []
                for query in (
                    'SELECT * FROM sem_phase1a_account_grants ORDER BY account_id,user_id',
                    'SELECT * FROM sem_phase1a_grant_audit ORDER BY id'):
                    snapshots.append(tuple((await session.execute(text(query))).all()))
                return tuple(snapshots)

        async def uninitialized(name, account_id, tenant_id=101, target_user=1, grant_id=10):
            before = await grant_snapshot()
            path = grants.replace('/201','/'+str(account_id))
            body = {'tenant_id':tenant_id,'user_id':target_user,'advisor_grant_id':grant_id}
            requests = [('GET',path+'?tenant_id='+str(tenant_id),{}),
                        ('POST',path,{'json':body}),
                        ('POST',path+'/revoke',{'json':body})]
            for uid in (8,9):
                outcomes = []
                for index,(method,path,kwargs) in enumerate(requests):
                    response = await api.request(method,path,headers=headers[uid],**kwargs)
                    assert response.status_code == 403, (name,uid,index,response.text)
                    assert response.json()['detail']['code'] == 'GRANT_ACCOUNT_NOT_INITIALIZED'
                    outcomes.append(response.status_code)
                results[name+'_'+str(uid)] = outcomes
            assert await grant_snapshot() == before

        # Account 204 has no seed even though other accounts have active grants.
        await uninitialized('first_binding',204)

        async def matrix(name, uid, expected):
            outcomes = []
            for index,(method,path,kwargs) in enumerate(cases):
                response = await api.request(method,path,headers=headers.get(uid,{}),**kwargs)
                assert response.status_code == expected, (name,index,response.status_code,response.text)
                outcomes.append(response.status_code)
            results[name] = outcomes
        await matrix('anonymous',None,401)
        # Empty authorization data closes *all* routes, including both admin types.
        async with factory() as session, session.begin():
            snapshot = list((await session.execute(text('SELECT user_id,tenant_id,account_id,advisor_grant_id FROM sem_phase1a_account_grants'))).all())
            await session.execute(text('DELETE FROM sem_phase1a_account_grants'))
        for uid in (1,2,7,8,9):
            await matrix('empty_'+str(uid),uid,403)
        async with factory() as session, session.begin():
            for uid,tid,aid,gid in snapshot:
                await session.execute(text('INSERT INTO sem_phase1a_account_grants(user_id,tenant_id,account_id,advisor_grant_id) '
                    'VALUES(:uid,:tid,:aid,:gid)'),{'uid':uid,'tid':tid,'aid':aid,'gid':gid})
        await matrix('cross_tenant',7,403)
        for status in ('suspended','closed'):
            await sql("UPDATE tenant_modules SET status='"+status+"' WHERE tenant_id=101")
            for uid in (1,2,8,9):
                await matrix(status+'_'+str(uid),uid,403)
        for status in ('trial','active'):
            await sql("UPDATE tenant_modules SET status='"+status+"',expires_at='2000-01-01' WHERE tenant_id=101")
            for uid in (1,2,8,9):
                await matrix('expired_'+status+'_'+str(uid),uid,403)
        await sql("UPDATE tenant_modules SET status='active',expires_at=NULL WHERE tenant_id=101")
        # Customer GET of JSON/source/expiry is read-only; Excel GET writes audit.
        customer_outcomes = []
        for index,(method,path,kwargs) in enumerate(cases):
            response = await api.request(method,path,headers=headers[2],**kwargs)
            allowed = index in (2,9,14)
            assert response.status_code == (200 if allowed else 403), ('customer',index,response.status_code,response.text)
            customer_outcomes.append(response.status_code)
        results['customer_readonly'] = customer_outcomes
        # Same tenant, unauthorized account denies every source/shadow endpoint.
        other = {**payload, 'account_id':204, 'landing_page_id':'other-page'}
        from app.sem_phase0.store import AdvisorPrincipal
        from app.sem_phase1a.production import ProductionServices
        from app.sem_phase0.contracts import LandingSubmission
        from app.sem_phase1a.contracts import CreateRequest, RulingRequest
        # Trusted unit setup only, never an HTTP auth override.
        who = AdvisorPrincipal('1','advisor',frozenset({(101,204)}))
        services = ProductionServices(engine)
        await services.call('sources','submit',who,LandingSubmission.model_validate(other),[])
        other_plan = await services.call('shadow','create',who,CreateRequest(tenant_id=101,account_id=204,page_id='other-page',submission_revision=1))
        for index,(method,path,kwargs) in enumerate(cases):
            if 10 <= index <= 12:
                continue
            changed = dict(kwargs)
            if index in (0,1):
                changed['json'] = {**kwargs['json'],'account_id':204}
            elif index == 13:
                changed['data'] = {'metadata':json.dumps(other)}
            path = path.replace(pid,other_plan['plan_id']).replace('/101/201/','/101/204/')
            for uid in (1,2):
                response = await api.request(method,path,headers=headers[uid],**changed)
                assert response.status_code == 403, ('unbound',index,response.status_code,response.text)
        results['unbound_account'] = 24
        # Full 15-endpoint administrator vectors include a real revoke/regrant.
        for uid in (8,9):
            outcomes = []
            for index,(method,path,kwargs) in enumerate(cases):
                response = await api.request(method,path,headers=headers[uid],**kwargs)
                assert response.status_code == (200 if 10 <= index <= 12 else 403), (
                    'admin',uid,index,response.status_code,response.text)
                outcomes.append(response.status_code)
            results['admin_'+str(uid)] = outcomes
            response = await api.post(grants,json=cases[11][2]['json'],headers=headers[uid])
            assert response.status_code == 200 and response.json()['changed']
            assert (await api.get(grants+'?tenant_id=102',headers=headers[uid])).status_code == 403

        # Advisor has a valid bound account, yet all management operations deny
        # before any grant or audit mutation, including the two POST routes.
        before = await grant_snapshot()
        for index in (10,11,12):
            method,path,kwargs = cases[index]
            response = await api.request(method,path,headers=headers[1],**kwargs)
            assert response.status_code == 403, ('advisor-management',index,response.text)
            expected = 'ADVISOR_ROUTE_NOT_AVAILABLE' if index == 10 else 'ADVISOR_HIGH_RISK_WRITES_DISABLED'
            assert response.json()['detail']['code'] == expected
            advisor_outcomes[index] = response.status_code
        assert await grant_snapshot() == before
        # Full advisor success path reaches real persisted service, every endpoint.
        response = await api.post(shadow+'/batch',json=cases[1][2]['json'],headers=headers[1])
        assert response.status_code == 201
        advisor_outcomes[1] = response.status_code
        response=await api.post(f'{shadow}/{pid}/structure',json=cases[4][2]['json'],headers=headers[1])
        assert response.status_code==200, ('structure',response.status_code,response.text)
        advisor_outcomes[4] = response.status_code
        exported=await api.get(f'{shadow}/{pid}/excel/advisor',headers=headers[1]);assert exported.status_code==200
        advisor_outcomes[5] = exported.status_code
        preview=await api.post(f'{shadow}/{pid}/previews/advisor',files={'file':('internal.xlsx',exported.content)},headers=headers[1])
        assert preview.status_code==200, ('preview',preview.status_code,preview.text)
        advisor_outcomes[6] = preview.status_code
        applied=await api.post(f'{shadow}/{pid}/apply-preview',json={'expected_version':3,'preview_id':preview.json()['preview_id']},headers=headers[1])
        assert applied.status_code==200, ('apply',applied.status_code,applied.text)
        advisor_outcomes[7] = applied.status_code
        reviewed=await api.post(f'{shadow}/{pid}/approvals',json={'expected_version':4,'reason':'合成逐项复核',
            'row_ids':[r['row_id'] for r in applied.json()['rows']]},headers=headers[1])
        assert reviewed.status_code==422 and reviewed.json()['detail']['code']=='DUPLICATE_BLOCKED', reviewed.text
        advisor_outcomes[8] = reviewed.status_code
        for index in (2,9,14):
            method,path,kwargs = cases[index]
            response = await api.request(method,path,headers=headers[1],**kwargs)
            assert response.status_code == 200, ('advisor-read',index,response.text)
            advisor_outcomes[index] = response.status_code
        assert None not in advisor_outcomes
        results['advisor_bound'] = advisor_outcomes

        # Account 202's only binding can be revoked; public APIs cannot restore it.
        response = await api.post(grants.replace('/201','/202')+'/revoke',
            json={'tenant_id':102,'user_id':7},headers=headers[9])
        assert response.status_code == 200 and response.json()['changed']
        await uninitialized('last_binding_revoked',202,tenant_id=102,target_user=7,grant_id=None)
        response=await api.post(source,data={'metadata':json.dumps({**payload,'expected_revision':1})},
            files={'screenshots':('never-echo.png',b'\x89PNG\r\n\x1a\nfixture','image/png')},headers=headers[1])
        assert response.status_code==503 and response.json()['detail']['code']=='ATTACHMENT_STORAGE_UNAVAILABLE'
        assert 'never-echo' not in response.text
        results['attachment_fail_closed'] = 1
        malformed={**payload,'never-echo-field-name':'never-echo-value'}
        response=await api.post(source,data={'metadata':json.dumps(malformed)},headers=headers[1])
        assert response.status_code==422 and 'never-echo' not in response.text
        # Revoke through the actual administrator route: next request immediately denies.
        response=await api.post(grants+'/revoke',json={'tenant_id':101,'user_id':1},headers=headers[9])
        assert response.status_code==200
        await matrix('revoked',1,403)
        # Regrant while another active customer binding keeps initialization valid.
        response=await api.post(grants,json={'tenant_id':101,'user_id':1,'advisor_grant_id':10},headers=headers[9])
        assert response.status_code==200
        await sql('UPDATE users SET role_id=2 WHERE id=1')
        await matrix('db_role_changed',1,403)
        await sql('UPDATE users SET role_id=1 WHERE id=1')
        # Append newer source: old plan immediately becomes stale, without weaker hash checks.
        response=await api.post(source,data={'metadata':json.dumps({**payload,'expected_revision':1})},headers=headers[1])
        assert response.status_code==201
        assert (await api.get(f'{shadow}/{pid}',headers=headers[1])).status_code==409
        results['new_source_invalidates'] = 1
        # Unknown and execution-like routes never become advisor accessible.
        for suffix in ('execute','upload-to-baidu','enable','customer-confirm','future-write'):
            assert (await api.post(f'{shadow}/{pid}/{suffix}',json={},headers=headers[1])).status_code in (403,404)
        results['closed_routes'] = 5
    scheduler_start.assert_not_called()
    results['scheduler_not_started'] = 1
    await engine.dispose()
    return results


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='sem-slice5-main-') as temp:
        result = asyncio.run(run(Path(temp)))
    Path(sys.argv[1]).write_text(json.dumps(result,sort_keys=True),encoding='utf-8')
    print('SLICE5_MAIN_MATRIX_EXECUTED')
