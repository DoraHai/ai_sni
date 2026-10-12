"""Negative-history contract/SELECT and in-memory HTTP; no live PG/JWT/TLS."""
import ast
import asyncio
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app import distribution_control as core, distribution_task_resolution_read as reader
from app.distribution_task_resolution_contract import TaskResolutionRead, TaskResolutionReadView

ROOT=Path(__file__).parents[1]
PATH='/api/distribution/v1/device/task-resolution'
NOW=1791809000000
CREDENTIAL='synthetic-offline-credential-'+'z'*32
FIXTURE=json.loads((ROOT/'docs/fixtures/distribution-task-resolution-read-v1.json').read_text())


class Result:
    def __init__(self,items):self.items=items
    def mappings(self):return self
    def all(self):return self.items


class Database:
    def __init__(self,*,resolved=False):
        req=FIXTURE['request']
        self.task={'id':req['taskId'],'device_id':req['deviceId'],'binding_id':'00000000-0000-4000-8000-000000000006',
            'tenant_id':15,'module':'seo','scope_id':6,'account_id':req['accountId'],'platform':req['platform'],
            'advisor_user_id':100007,'grant_id':req['grantId'],'publication_grant_id':req['publicationGrantId'],
            'lease_id':req['leaseId'],'source_revision':req['contentVersion'],'content_digest':req['contentDigest'],
            'action':'publish','status':'failed' if resolved else 'unknown','revoked':resolved,
            'grant_expires_at':NOW-1000,'lease_expires_at':NOW-1000,'receipt':{'status':'unknown'}}
        self.binding={'id':self.task['binding_id'],**{k:self.task[k] for k in ('tenant_id','module','scope_id','device_id','account_id','platform')},
            'external_account_id':'gh_synthetic','active':True,'device_active':True}
        self.device={'id':req['deviceId'],'active':True,'credential_hash':hashlib.sha256(CREDENTIAL.encode()).hexdigest()}
        self.project={'state':'paused','revision':4,'owner_user_id':100007}
        self.resolution={'id':1,'task_id':self.task['id'],'outcome':'not-published','public_url':None,
            'actor_id':100007,'checked_at':NOW-1000} if resolved else None
        self.calls=[];self.task_reads=0;self.binding_reads=0;self.mutate_after_lock=None
        self.scope_granted=True;self.fail=False
    async def execute(self,statement,params):
        sql=str(statement)
        assert sql.startswith('SELECT'), 'Reader cannot mutate database'
        self.calls.append((sql,copy.deepcopy(params)))
        if self.fail:raise SQLAlchemyError('private database error sentinel')
        if 'pg_advisory_xact_lock' in sql:return Result([])
        if 'FROM distribution_devices' in sql:return Result([self.device] if self.device['active'] else [])
        if 'FROM distribution_tasks' in sql:
            self.task_reads+=1
            if self.task_reads==2 and self.mutate_after_lock:self.mutate_after_lock(self)
            return Result([copy.deepcopy(self.task)] if params['id']==self.task['id'] and params['device']==self.task['device_id'] else [])
        if 'FROM distribution_bindings' in sql:
            self.binding_reads+=1
            return Result([copy.deepcopy(self.binding)] if params['id']==self.binding['id'] else [])
        if 'FROM distribution_controls' in sql:return Result([copy.deepcopy(self.project)] if self.project else [])
        if 'FROM distribution_task_resolutions' in sql:
            assert 'ORDER BY id DESC LIMIT 1' in sql
            return Result([copy.deepcopy(self.resolution)] if self.resolution is not None else [])
        raise AssertionError('Unexpected reader query')


@pytest.fixture(autouse=True)
def scoped_adapter(monkeypatch):
    async def authorize_scope(db,actor,tenant,scope):
        db.calls.append(('native_scope_sentinel',{'actor':actor,'tenant':tenant,'scope':scope}))
        assert actor==100007 and tenant==15 and scope==6
        if not db.scope_granted:raise core.problem('scope_forbidden',403)
    monkeypatch.setattr(core,'adapter',lambda module:SimpleNamespace(authorize_scope=authorize_scope))
    monkeypatch.setattr(core,'now_ms',lambda:NOW)


def run(db,raw=None,credential=CREDENTIAL):
    return asyncio.run(reader.read(db,credential,TaskResolutionRead.model_validate(raw or FIXTURE['request'])))


def test_unknown_without_stored_resolution_is_null_and_changes_no_state():
    db=Database();before=copy.deepcopy((db.task,db.binding,db.project,db.resolution))
    value=run(db)
    assert value=={**FIXTURE['request'],'resolution':None,'asOf':NOW,'publicationVerified':False,'executionAuthorized':False}
    assert (db.task,db.binding,db.project,db.resolution)==before
    assert db.task_reads==2 and db.binding_reads==2


@pytest.mark.parametrize('state,revision',[('paused',4),('paused',20),('running',5)])
def test_exact_saved_not_published_allows_old_expired_revoked_grants_but_never_execution(state,revision):
    db=Database(resolved=True);db.project.update(state=state,revision=revision)
    before=copy.deepcopy((db.task,db.binding,db.project,db.resolution))
    assert run(db)==FIXTURE['response']
    assert (db.task,db.binding,db.project,db.resolution)==before
    keys=['device:'+db.task['device_id'],'scope:'+core.canonical({'module':'seo','tenant_id':15,'scope_id':6}),
          'account:wechat-article:gh_synthetic']
    locks=[params['key'] for sql,params in db.calls if 'pg_advisory_xact_lock' in sql]
    assert locks==[int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'big',signed=True) for key in keys]


@pytest.mark.parametrize('field,value',[
    ('deviceId','00000000-0000-4000-8000-000000000099'),('taskId','00000000-0000-4000-8000-000000000099'),
    ('grantId','00000000-0000-4000-8000-000000000099'),('publicationGrantId','00000000-0000-4000-8000-000000000099'),
    ('leaseId','00000000-0000-4000-8000-000000000099'),('customerId','16'),('projectId','seo-7'),
    ('accountId','foreign_account'),('platform','xiaohongshu-image'),('contentVersion','new_version'),('contentDigest','f'*64)])
def test_old_complete_target_tuple_must_match(field,value):
    raw={**FIXTURE['request'],field:value}
    db=Database(resolved=True)
    with pytest.raises(HTTPException) as error:run(db,raw)
    assert error.value.status_code==403


@pytest.mark.parametrize('change',['credential','device_revoked','binding_revoked','binding_device_revoked','binding_account',
    'binding_scope','owner_changed','project_ended','missing_project','advisor_scope_revoked','handoff','sem'])
def test_current_auth_and_scope_cannot_be_borrowed_from_old_history(change):
    db=Database(resolved=True);credential=CREDENTIAL
    if change=='credential':credential='different credential'
    if change=='device_revoked':db.device['active']=False
    if change=='binding_revoked':db.binding['active']=False
    if change=='binding_device_revoked':db.binding['device_active']=False
    if change=='binding_account':db.binding['account_id']='foreign'
    if change=='binding_scope':db.binding['tenant_id']=16
    if change=='owner_changed':db.project['owner_user_id']=100008
    if change=='project_ended':db.project['state']='ended'
    if change=='missing_project':db.project=None
    if change=='advisor_scope_revoked':db.scope_granted=False
    if change=='handoff':db.task['action']='handoff'
    if change=='sem':db.task['module']='sem'
    with pytest.raises(HTTPException):run(db,credential=credential)


def test_geo_is_denied_before_scope_account_locks_or_native_authorization(monkeypatch):
    db=Database(resolved=True);db.task['module']='geo';db.binding['module']='geo'
    raw={**FIXTURE['request'],'projectId':'geo-6'}
    def never_adapter(module):raise AssertionError('GEO authorization must not be entered')
    monkeypatch.setattr(core,'adapter',never_adapter)
    with pytest.raises(HTTPException) as error:run(db,raw)
    assert error.value.status_code==403
    assert db.task_reads==1 and db.binding_reads==0
    assert len([sql for sql,params in db.calls if 'pg_advisory_xact_lock' in sql])==1
    assert not any(sql=='native_scope_sentinel' for sql,params in db.calls)


def test_factory_mounts_real_new_reader_only_for_seo(monkeypatch):
    source=(ROOT/'scripts/distribution_server_pilot_native.py').read_text()
    blocks=[node for node in ast.walk(ast.parse(source)) if isinstance(node,ast.If)
            and ast.unparse(node.test)=="module == 'seo'"
            and 'app.include_router(task_resolution_read_router)' in ast.get_source_segment(source,node)]
    assert len(blocks)==1
    sentinel=object()
    monkeypatch.setitem(__import__('sys').modules,'app.api.distribution_task_resolution_read',SimpleNamespace(router=sentinel))
    compiled=compile(ast.Module(body=[blocks[0]],type_ignores=[]),'<real factory SEO guard>','exec')
    calls=[];app=SimpleNamespace(include_router=lambda route:calls.append(route))
    exec(compiled,{'module':'geo','app':app})
    assert calls==[]
    exec(compiled,{'module':'seo','app':app})
    assert calls==[sentinel]


@pytest.mark.parametrize('change',['published_correction','public_url','other_actor','task_unknown','task_succeeded',
    'task_not_revoked','future_check','bad_check','changed_account_after_lock','binding_revoked_after_lock','source_after_lock'])
def test_no_proof_for_latest_correction_conflict_or_changed_post_lock_target(change):
    db=Database(resolved=True)
    if change=='published_correction':db.resolution.update(id=2,outcome='published',public_url='https://mp.weixin.qq.com/s/synthetic')
    if change=='public_url':db.resolution['public_url']='https://mp.weixin.qq.com/s/synthetic'
    if change=='other_actor':db.resolution['actor_id']=100008
    if change=='task_unknown':db.task['status']='unknown'
    if change=='task_succeeded':db.task['status']='succeeded'
    if change=='task_not_revoked':db.task['revoked']=False
    if change=='future_check':db.resolution['checked_at']=NOW+1
    if change=='bad_check':db.resolution['checked_at']=None
    if change=='changed_account_after_lock':db.mutate_after_lock=lambda d:d.binding.update(external_account_id='gh_changed')
    if change=='binding_revoked_after_lock':db.mutate_after_lock=lambda d:d.binding.update(active=False)
    if change=='source_after_lock':db.mutate_after_lock=lambda d:d.task.update(source_revision='changed')
    with pytest.raises(HTTPException):run(db)


@pytest.mark.parametrize('change',[
    {'resolutionVersion':True},{'resolutionVersion':1.0},{'resolutionVersion':2},{'action':'publish'},
    {'body':'forbidden'},{'token':'forbidden'},{'taskId':'arbitrary'}, {'contentDigest':'A'*64}])
def test_strict_request_does_not_accept_execution_or_credential_fields(change):
    with pytest.raises(ValidationError):TaskResolutionRead.model_validate({**FIXTURE['request'],**change})


def test_view_rejects_check_newer_than_read_and_is_only_whitelist():
    bad=copy.deepcopy(FIXTURE['response']);bad['resolution']['checkedAt']=bad['asOf']+1
    with pytest.raises(ValidationError):TaskResolutionReadView.model_validate(bad)
    assert set(TaskResolutionReadView.model_validate(FIXTURE['response']).model_dump())==set(FIXTURE['response'])
    with pytest.raises(ValidationError):TaskResolutionReadView.model_validate({**FIXTURE['response'],'content':'forbidden'})


def route_module(monkeypatch,db):
    # Use the unchanged real PrivateRoute and credential parser AST; dependency
    # binding is an in-memory sentinel, not a fake native JWT/PG success claim.
    source=(ROOT/'app/api/distribution.py').read_text()
    nodes=[node for node in ast.parse(source).body if isinstance(node,(ast.ClassDef,ast.FunctionDef))
           and node.name in {'PrivateRoute','device_credential'}]
    original={'APIRoute':APIRoute,'JSONResponse':JSONResponse,'RequestValidationError':RequestValidationError,
              'HTTPException':HTTPException,'SQLAlchemyError':SQLAlchemyError,'core':core}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<unchanged private route>','exec'),original)
    async def unbound():raise AssertionError('Owned override required');yield
    async def owned():yield db
    monkeypatch.setitem(__import__('sys').modules,'app.database',SimpleNamespace(get_session=unbound))
    monkeypatch.setitem(__import__('sys').modules,'app.api.distribution',SimpleNamespace(
        PrivateRoute=original['PrivateRoute'],device_credential=original['device_credential']))
    spec=importlib.util.spec_from_file_location('exact_task_resolution_route',ROOT/'app/api/distribution_task_resolution_read.py')
    api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
    app=FastAPI();app.dependency_overrides[unbound]=owned;app.include_router(api.router)
    return app


def test_http_reader_uses_real_credential_compare_owned_dependency_and_no_publication_fence(monkeypatch):
    async def scenario():
        db=Database();app=route_module(monkeypatch,db)
        gate_spec=importlib.util.spec_from_file_location('resolution_read_gate',ROOT/'scripts/distribution_single_publication_gate.py')
        gate=importlib.util.module_from_spec(gate_spec);__import__('sys').modules[gate_spec.name]=gate;gate_spec.loader.exec_module(gate)
        @app.middleware('http')
        async def fence(request,next_call):
            if gate.publication_request(request):return JSONResponse(status_code=403,content={'detail':'original fence'})
            return await next_call(request)
        auth={'authorization':'Bearer '+CREDENTIAL}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://127.0.0.1') as client:
            response=await client.post(PATH,json=FIXTURE['request'],headers=auth)
            assert response.status_code==200 and response.json()['resolution'] is None
            assert response.headers['cache-control']=='no-store'
            db.task.update(status='failed',revoked=True);db.resolution=Database(resolved=True).resolution
            assert (await client.post(PATH,json=FIXTURE['request'],headers=auth)).json()==FIXTURE['response']
            assert (await client.post(PATH,json=FIXTURE['request'])).status_code==401
            assert (await client.post(PATH+'?key=synthetic',json=FIXTURE['request'],headers=auth)).status_code==401
            assert (await client.post(PATH,json=FIXTURE['request'],headers={'authorization':'Bearer '+'jwt'*20})).status_code==401
            assert (await client.post(PATH,json={**FIXTURE['request'],'action':'publish'},headers=auth)).status_code==422
            assert (await client.get(PATH,headers=auth)).status_code==405
            assert (await client.post('/api/distribution/v1/publication-writeback',json={},headers=auth)).status_code==403
            db.fail=True
            failure=await client.post(PATH,json=FIXTURE['request'],headers=auth)
            assert failure.status_code==503 and 'private database error' not in failure.text
    asyncio.run(scenario())


def test_read_only_source_and_factory_manifest_bindings():
    node=ast.parse((ROOT/'app/distribution_task_resolution_read.py').read_text())
    calls={call.func.attr if isinstance(call.func,ast.Attribute) else call.func.id for call in ast.walk(node)
           if isinstance(call,ast.Call) and isinstance(call.func,(ast.Name,ast.Attribute))}
    assert not calls & {'commit','flush','audit','add','delete','source','enqueue','create_task','fetch','urlopen','execute'}
    factory=(ROOT/'scripts/distribution_server_pilot_native.py').read_text()
    for name in ('app/distribution_task_resolution_contract.py','app/distribution_task_resolution_read.py',
                 'app/api/distribution_task_resolution_read.py','docs/fixtures/distribution-task-resolution-read-v1.json'):
        assert name in factory
    assert 'app.include_router(task_resolution_read_router)' in factory
    route=(ROOT/'app/api/distribution_task_resolution_read.py').read_text()
    assert 'db=Depends(get_session)' in route and 'device_credential(request)' in route
    assert "@router.post('/task-resolution',response_model=TaskResolutionReadView)" in route
