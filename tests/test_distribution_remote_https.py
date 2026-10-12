"""Actual native SEO auth/source + HTTPS + PostgreSQL; synthetic PNG executor."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import ssl
import struct
import time
import subprocess
from uuid import uuid4
import zlib

import httpx
import pytest

ROOT=Path(os.environ.get('REMOTE_BROKER_TEST_ROOT',''))
if not os.environ.get('REMOTE_BROKER_TEST_ROOT'):pytest.skip('Owned HTTPS fixture required',allow_module_level=True)
if ROOT.resolve().parent!=Path(os.environ['TEMP']).resolve() or ROOT.name!='distribution-remote-broker-tests-20261012':raise RuntimeError('Exact private fixture required')
PREFIX='/api/distribution/v1/remote'
SCOPE={'module':'seo','tenant_id':15,'scope_id':6}


def png(width=32,height=24):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\x45\x67\x89\xff'*width)*height))+chunk(b'IEND',b'')


class Fixture:
    def __init__(self):
        self.context=ssl.create_default_context(cafile=str(ROOT/'loopback.pem'))
        self.client=httpx.Client(base_url='https://127.0.0.1:55871',verify=self.context,trust_env=False,timeout=20)
        password=json.loads((ROOT/'secrets.json').read_text(encoding='utf-8'))['password'];self.tokens={};self.open=[]
        for actor in ('advisor','admin','customer','foreign','reviewer'):
            value=self.client.post('/api/v1/auth/login',json={'username':actor,'password':password})
            assert value.status_code==200,'actual native login failed'
            self.tokens[actor]=value.json()['token']
        for tenant,site in ((15,6),(16,7)):
            self.call('PUT','/api/v1/seo/workbench/advisor-assignments',actor='admin',json={'tenant_id':tenant,'site_id':site,'advisor_user_id':100007,'active':True})

    def call(self,method,path,actor='advisor',expected=200,**kwargs):
        response=self.client.request(method,path,headers={'Authorization':'Bearer '+self.tokens[actor]},**kwargs)
        assert response.status_code==expected,(method,path,response.status_code)
        if path.startswith(PREFIX):assert response.headers['cache-control']=='no-store'
        return response.json()

    def device(self,scope=SCOPE):
        device=self.call('POST','/api/distribution/v1/devices',actor='admin',json={'label':'Synthetic remote executor'})['device']
        binding=self.call('POST','/api/distribution/v1/bindings',actor='admin',json={**scope,'device_id':device['id'],
            'account_id':'remote-'+uuid4().hex,'external_account_id':'remote-'+uuid4().hex,'platform':'wechat-article','confirm_account_ownership':True})['binding']
        return {'device':device,'binding':binding,'scope':scope}

    def create(self,identity=None,**changes):
        identity=identity or self.device();req={**identity['scope'],'binding_id':identity['binding']['id'],'purpose':'account-login','request_id':str(uuid4()),**changes}
        result=self.call('POST',PREFIX+'/sessions',json=req)
        result['identity']=identity;self.open.append(result);return result

    def close(self,value):
        return self.call('POST',PREFIX+'/sessions/'+value['session']['id']+'/close',json={'request_id':str(uuid4()),'control_nonce':value['control_nonce']})

    def read_frame(self,value,expected=200):
        response=self.client.get(PREFIX+'/sessions/'+value['session']['id']+'/frame',headers={'Authorization':'Bearer '+self.tokens['advisor']})
        assert response.status_code==expected,('frame read',response.status_code)
        assert response.headers['cache-control']=='no-store'
        return response

    def frame(self,value,seq=1,revision=1,width=32,height=24,raw=None,at=None,expected=200,identity=None,read=True):
        ident=identity or value['identity'];headers={'Authorization':'Bearer '+ident['device']['credential'],'Content-Type':'image/png',
            'X-Remote-Device-Id':ident['device']['id'],'X-Remote-Session-Id':value['session']['id'],'X-Frame-Seq':str(seq),
            'X-Control-Revision':str(revision),'X-Viewport-Width':str(width),'X-Viewport-Height':str(height),'X-Frame-Captured-At':str(at or int(time.time()*1000))}
        response=self.client.post(PREFIX+'/device/frame',headers=headers,content=raw if raw is not None else png(width,height))
        assert response.status_code==expected,('frame upload',response.status_code)
        assert response.headers['cache-control']=='no-store'
        if expected==200 and read:self.read_frame(value)
        return response.json()

    def poll(self,identity):
        response=self.client.post(PREFIX+'/device/poll',headers={'Authorization':'Bearer '+identity['device']['credential']},json={'device_id':identity['device']['id']})
        assert response.status_code==200;return response.json()

    def input(self,value,seq=1,revision=1,command=None,packet=None,expected=200):
        req={'command_id':command or str(uuid4()),'control_nonce':value['control_nonce'],'frame_seq':seq,'control_revision':revision,
            'input':packet or {'kind':'text','text':'synthetic-sensitive-sentinel'}}
        return self.call('POST',PREFIX+'/sessions/'+value['session']['id']+'/input',json=req,expected=expected)

    def finish(self):
        for value in self.open:
            try:self.close(value)
            except AssertionError:pass # actual revocation/expiry negatives stay fenced
        self.client.close()

    def task(self):
        """Native creation/review/confirmation/adaptation; no mock source writer."""
        identity=self.device()
        keyword=self.call('POST','/api/v1/seo/keywords',json={'tenant_id':15,'site_id':6,'keyword':'合成远程验收 '+uuid4().hex[:8]})
        body=keyword['keyword']+'\n\n'+('这是远程控制隔离验收的合成文稿，仅用于验证版本与人工审核边界。\n'*30)
        master=self.call('POST','/api/v1/seo/content-assets',json={**{'tenant_id':15,'site_id':6},'title':keyword['keyword']+' 本地审核稿',
            'keyword_ids':[keyword['id']],'content_type':'article','draft':body,'status':'drafting'})
        version=master.get('version_count') or 1
        self.call('POST',f'/api/v1/seo/content-assets/{master["id"]}/submit-review',params={'tenant_id':15},json={'version_count':version,'note':'Synthetic local native review'})
        self.call('POST',f'/api/v1/seo/content-assets/{master["id"]}/review',actor='reviewer',params={'tenant_id':15},json={'version_count':version,'decision':'approve','note':'Separate synthetic reviewer'})
        delivery=self.call('GET',f'/api/v1/seo/workbench/content-assets/{master["id"]}/delivery',params={'tenant_id':15,'site_id':6})
        self.call('POST',f'/api/v1/seo/workbench/content-assets/{master["id"]}/confirmations',params={'tenant_id':15},json={
            'version_count':delivery['content']['version_count'],'payload_hash':delivery['content']['payload_hash'],
            'decision':'approve','actor_mode':'advisor_proxy','note':'Local synthetic advisor version confirmation'})
        connection=self.call('POST','/api/v1/seo/content-distribution/connections',json={'tenant_id':15,'platform_code':'wechat_browser','name':'Remote synthetic connection '+uuid4().hex[:8],'enabled':True})
        adapted=self.call('POST','/api/v1/seo/content-distribution/adapt',json={'tenant_id':15,'site_id':6,'content_id':master['id'],'connection_id':connection['id'],'use_ai':False})
        variant=self.call('POST','/api/v1/seo/content-distribution/variants',json={'tenant_id':15,'site_id':6,'content_id':master['id'],
            'connection_id':connection['id'],'source_version':adapted['source_version'],'title':adapted['title'],'content':adapted['content'],
            'status':'pending_review','ai_generated':False})
        self.call('POST',f'/api/v1/seo/content-distribution/variants/{variant["id"]}/review',actor='reviewer',json={'tenant_id':15,'site_id':6,'decision':'approve','note':'Local separate channel review'})
        source=self.call('GET','/api/distribution/v1/source',params={**SCOPE,'variant_id':variant['id'],'platform':'wechat-article'})
        control=self.call('GET','/api/distribution/v1/scope',params=SCOPE)['project']
        if control['state']=='paused':
            self.call('POST','/api/distribution/v1/control',json={**SCOPE,'action':'start' if control['revision']==0 else 'resume',
                'expected_revision':control['revision'],'request_id':str(uuid4())})
        task=self.call('POST','/api/distribution/v1/tasks',json={**SCOPE,'binding_id':identity['binding']['id'],'variant_id':variant['id'],
            'source_revision':source['source_revision'],'expected_digest':source['content_digest'],'action':'preflight',
            'confirm_reviewed_content':True,'confirm_manual_publication':False,'expires_in_seconds':600,'request_id':str(uuid4())})['task']
        exchange=self.client.post('/api/distribution/v1/device/exchange',headers={'Authorization':'Bearer '+identity['device']['credential']},
            json={'contractVersion':1,'deviceId':identity['device']['id'],'receipts':[]})
        assert exchange.status_code==200 and len(exchange.json()['tasks'])==1
        bound={'task_id':task['id'],'expected_source_revision':source['source_revision'],'expected_content_digest':source['content_digest']}
        master['_adapted']=adapted;master['_connection_id']=connection['id']
        return identity,bound,master


@pytest.fixture
def f():
    value=Fixture()
    try:yield value
    finally:value.finish()


def test_real_scope_identity_query_sem_and_frame_headers(f):
    value=f.create();sid=value['session']['id']
    for actor in ('customer','foreign','reviewer'):
        f.call('GET',PREFIX+'/sessions/'+sid,actor=actor,expected=403)
        f.call('GET',PREFIX+'/sessions/'+sid+'/frame',actor=actor,expected=403)
    f.call('POST',PREFIX+'/sessions',actor='customer',expected=403,json={**SCOPE,'binding_id':value['identity']['binding']['id'],'purpose':'account-login','request_id':str(uuid4())})
    f.call('GET',PREFIX+'/sessions/'+sid+'?key=x',expected=400)
    f.call('POST',PREFIX+'/sessions',expected=422,json={**SCOPE,'module':'sem','binding_id':value['identity']['binding']['id'],'purpose':'account-login','request_id':str(uuid4())})
    f.frame(value)
    response=f.client.get(PREFIX+'/sessions/'+sid+'/frame',headers={'Authorization':'Bearer '+f.tokens['advisor']})
    assert response.status_code==200 and response.content==png()
    assert response.headers['x-remote-session-id']==sid
    assert response.headers['x-remote-device-id']==value['identity']['device']['id']
    assert all(response.headers.get(name) for name in ('x-frame-captured-at','x-frame-seq','x-control-revision','x-viewport-width','x-viewport-height'))
    assert response.headers['cache-control']=='no-store'


def test_single_use_input_delivery_ack_and_privacy(f):
    value=f.create();f.frame(value);cmd=str(uuid4());f.input(value,command=cmd)
    f.input(value,command=cmd,expected=409)
    first=f.poll(value['identity']);assert len(first['commands'])==1
    assert first['commands'][0]['command_id']==cmd
    assert f.poll(value['identity'])['commands']==[]
    ack={'device_id':value['identity']['device']['id'],'session_id':value['session']['id'],'command_id':cmd,
        'command_seq':1,'control_revision':1,'state':'applied','code':'INPUT_APPLIED'}
    for _ in range(2):
        response=f.client.post(PREFIX+'/device/ack',headers={'Authorization':'Bearer '+value['identity']['device']['credential']},json=ack)
        assert response.status_code==200
    f.input(value,expected=409) # new UUID cannot reuse the already acted-on picture
    f.frame(value,seq=2);f.input(value,seq=2)
    f.close(value)
    metadata=f.call('GET','/test/metadata',actor='admin');assert metadata['payloads']==metadata['frames']==metadata['read_frames']==0


@pytest.mark.parametrize('case',['old','future','dimensions','png','oversize'])
def test_late_frame_png_limits_and_viewport(f,case):
    value=f.create();f.frame(value)
    if case=='old':f.frame(value,seq=1,expected=409)
    elif case=='future':f.frame(value,seq=2,at=int(time.time()*1000)+100000,expected=409)
    elif case=='dimensions':f.frame(value,seq=2,raw=png(33,24),expected=422)
    elif case=='png':f.frame(value,seq=2,raw=b'not-png',expected=422)
    else:f.frame(value,seq=2,raw=b'x'*(2097152+1),expected=413)


def test_resize_cancels_queued_input_and_rejects_old_ack(f):
    value=f.create();f.frame(value);cmd=f.input(value)['command_id']
    assert f.frame(value,seq=2,width=40,read=False)['control_revision']==2
    assert f.poll(value['identity'])['commands']==[]
    assert f.call('GET','/test/metadata',actor='admin')['read_frames']==0
    f.input(value,seq=1,revision=1,expected=409)
    f.input(value,seq=2,revision=1,expected=409)
    f.read_frame(value)
    f.input(value,seq=2,revision=2)
    ack={'device_id':value['identity']['device']['id'],'session_id':value['session']['id'],'command_id':cmd,
        'command_seq':1,'control_revision':1,'state':'applied','code':'INPUT_APPLIED'}
    response=f.client.post(PREFIX+'/device/ack',headers={'Authorization':'Bearer '+value['identity']['device']['credential']},json=ack)
    assert response.status_code==409


def test_two_current_sessions_compete_and_other_device_cannot_capture(f):
    identity=f.device();value=f.create(identity)
    req={**SCOPE,'binding_id':identity['binding']['id'],'purpose':'account-verification','request_id':str(uuid4())}
    f.call('POST',PREFIX+'/sessions',expected=409,json=req)
    f.frame(value,identity=f.device(),expected=403)
    f.close(value);replacement=f.create(identity,purpose='account-verification')
    assert replacement['session']['id']!=value['session']['id']


def test_real_current_assignment_and_role_withdrawal(f):
    value=f.create();f.frame(value)
    f.call('PUT','/api/v1/seo/workbench/advisor-assignments',actor='admin',json={**{'tenant_id':15,'site_id':6},'advisor_user_id':100007,'active':False})
    f.call('GET',PREFIX+'/sessions/'+value['session']['id'],expected=403)
    f.call('PUT','/api/v1/seo/workbench/advisor-assignments',actor='admin',json={'tenant_id':15,'site_id':6,'advisor_user_id':100007,'active':True})
    other=f.create()
    f.call('POST','/test/mutate',actor='admin',json={'kind':'advisor-role','active':False})
    try:f.call('GET',PREFIX+'/sessions/'+other['session']['id'],expected=403)
    finally:f.call('POST','/test/mutate',actor='admin',json={'kind':'advisor-role','active':True})
    assert f.call('GET','/test/metadata',actor='admin')['nonces']==0
    assert f.call('GET','/test/metadata',actor='admin')['read_frames']==0


def test_binding_revoke_and_expired_session_fence(f):
    value=f.create();f.frame(value);f.input(value)
    f.call('POST','/api/distribution/v1/bindings/'+value['identity']['binding']['id']+'/revoke',actor='admin')
    assert f.poll(value['identity'])['sessions']==[]
    assert f.poll(value['identity'])['commands']==[]
    assert f.call('GET','/test/metadata',actor='admin')['read_frames']==0
    other=f.create();f.call('POST','/test/mutate',actor='admin',json={'kind':'expire-session','id':other['session']['id']})
    f.call('GET',PREFIX+'/sessions/'+other['session']['id']+'/frame',expected=410)


@pytest.mark.parametrize('mode',['audit','commit'])
def test_actual_pg_failure_releases_capacity(f,mode):
    before=f.call('GET','/test/metadata',actor='admin')
    identity=f.device();f.call('POST','/test/fault',actor='admin',json={'mode':mode})
    f.call('POST',PREFIX+'/sessions',expected=503,json={**SCOPE,'binding_id':identity['binding']['id'],'purpose':'account-login','request_id':str(uuid4())})
    after=f.call('GET','/test/metadata',actor='admin')
    assert before==after
    f.create(identity)


def test_global_capacity_parallel_across_native_scopes(f):
    identities=[f.device(SCOPE if i%2==0 else {'module':'seo','tenant_id':16,'scope_id':7}) for i in range(10)]
    async def run():
        async with httpx.AsyncClient(base_url='https://127.0.0.1:55871',verify=f.context,trust_env=False,timeout=30) as client:
            async def create(identity):
                r=await client.post(PREFIX+'/sessions',headers={'Authorization':'Bearer '+f.tokens['advisor']},json={**identity['scope'],
                    'binding_id':identity['binding']['id'],'purpose':'account-login','request_id':str(uuid4())})
                if r.status_code==200:f.open.append({**r.json(),'identity':identity})
                return r.status_code
            return await asyncio.gather(*(create(identity) for identity in identities))
    codes=asyncio.run(run());assert codes.count(200)==8 and codes.count(503)==2
    metadata=f.call('GET','/test/metadata',actor='admin');assert metadata['nonces']==metadata['active_rows']==8


@pytest.mark.parametrize('packet',[{'kind':'key','key':'F12'},{'kind':'key','key':'Enter','modifier':'Ctrl'},
    {'kind':'url','url':'file:///private'},{'kind':'text','text':'sensitive\ncontrol'},{'kind':'mouse','event':'click','x':99,'y':1,'button':'left'}])
def test_input_allowlist_without_sensitive_echo(f,packet):
    value=f.create();f.frame(value)
    response=f.client.post(PREFIX+'/sessions/'+value['session']['id']+'/input',headers={'Authorization':'Bearer '+f.tokens['advisor']},json={
        'command_id':str(uuid4()),'control_nonce':value['control_nonce'],'frame_seq':1,'control_revision':1,'input':packet})
    assert response.status_code==422
    assert 'control_nonce' not in response.text and 'sensitive' not in response.text


@pytest.mark.parametrize('change',['scope','source','lease','pause'])
def test_real_native_approved_task_intervention_and_current_changes(f,change):
    identity,task,master=f.task()
    value=f.create(identity,purpose='task-intervention',task=task)
    assert set(value['session']['task'])=={'task_id','grant_id','lease_id','source_revision','content_digest'}
    assert value['session']['task']['task_id']==task['task_id']
    assert value['session']['task']['source_revision']==task['expected_source_revision']
    f.frame(value)
    if change=='scope':
        other=f.device()
        f.call('POST',PREFIX+'/sessions',expected=409,json={**SCOPE,'binding_id':other['binding']['id'],
            'purpose':'task-intervention','task':task,'request_id':str(uuid4())})
        f.close(value)
    elif change=='source':
        adapted=master['_adapted']
        f.call('POST','/api/v1/seo/content-distribution/variants',json={'tenant_id':15,'site_id':6,'content_id':master['id'],
            'connection_id':master['_connection_id'],'source_version':adapted['source_version'],'title':adapted['title'],
            'content':adapted['content']+'<p>本地合成渠道稿有新修改，等待重新审核。</p>','status':'pending_review','ai_generated':False})
        f.call('GET',PREFIX+'/sessions/'+value['session']['id'],expected=409)
    elif change=='lease':
        f.call('POST','/test/mutate',actor='admin',json={'kind':'expire-lease','id':task['task_id']})
        f.input(value,expected=409)
    else:
        control=f.call('GET','/api/distribution/v1/scope',params=SCOPE)['project']
        f.call('POST','/api/distribution/v1/control',json={**SCOPE,'action':'pause','expected_revision':control['revision'],'request_id':str(uuid4())})
        f.input(value,expected=409)
        # Login preparation is separate and remains legal while paused.
        f.create()


def service_command(action):
    from scripts.distribution_remote_test_service import PYTHON,CENTRAL
    result=subprocess.run([str(PYTHON),str(CENTRAL/'scripts/distribution_remote_test_service.py'),'--root',str(ROOT),action],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,'owned fixture lifecycle failed'


def wait_service(client,port=55871):
    for _ in range(80):
        try:
            value=client.get(f'https://127.0.0.1:{port}/test-health')
            if value.status_code==200:return value.json()
        except httpx.TransportError:pass
        time.sleep(.1)
    raise AssertionError('owned fixture did not become ready')


def test_runtime_second_process_cannot_steal_owner(f):
    from scripts.distribution_remote_test_service import PYTHON,CENTRAL,env
    value=f.create();epoch=value['session']['broker_epoch']
    with (ROOT/'second-owner-private.log').open('wb') as log:
        result=subprocess.run([str(PYTHON),str(CENTRAL/'scripts/distribution_remote_test_service.py'),'--root',str(ROOT),'serve'],
            cwd=ROOT,env=env(ROOT),stdout=log,stderr=log,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode!=0
    assert f.call('GET',PREFIX+'/sessions/'+value['session']['id'])['session']['broker_epoch']==epoch
    assert f.call('GET','/test/metadata',actor='admin')['nonces']==1


@pytest.mark.parametrize('delivery',['queued','delivered'])
def test_runtime_restart_discards_private_input_and_png(f,delivery):
    value=f.create();f.frame(value);f.input(value)
    if delivery=='delivered':assert len(f.poll(value['identity'])['commands'])==1
    old_epoch=value['session']['broker_epoch']
    service_command('stop');service_command('start');new=wait_service(f.client)
    assert new['broker_epoch']!=old_epoch
    view=f.call('GET',PREFIX+'/sessions/'+value['session']['id'])['session']
    assert view['state']=='closed' and view['code']=='BROKER_RESTARTED' and view['frame'] is None
    assert view['last_command_state']==('canceled' if delivery=='queued' else 'unknown')
    assert f.poll(value['identity'])['commands']==[]
    f.call('GET',PREFIX+'/sessions/'+value['session']['id']+'/frame',expected=410)
    assert f.call('GET','/test/metadata',actor='admin')['payloads']==0
    assert f.call('GET','/test/metadata',actor='admin')['read_frames']==0


def test_runtime_owner_lock_loss_fails_closed(f):
    value=f.create();f.frame(value);f.input(value)
    f.call('POST','/test/mutate',actor='admin',json={'kind':'owner-lost'})
    try:
        f.call('GET',PREFIX+'/sessions/'+value['session']['id'],expected=503)
        assert f.call('GET','/test/metadata',actor='admin')['payloads']==0
        assert f.call('GET','/test/metadata',actor='admin')['read_frames']==0
        response=f.client.post(PREFIX+'/device/poll',headers={'Authorization':'Bearer '+value['identity']['device']['credential']},json={'device_id':value['identity']['device']['id']})
        assert response.status_code==503
    finally:service_command('stop');service_command('start');wait_service(f.client)


def test_runtime_disabled_instance_does_not_acquire_owner(f):
    from scripts.distribution_remote_test_service import PYTHON,CENTRAL,env
    value=f.create();epoch=value['session']['broker_epoch']
    with (ROOT/'disabled-instance-private.log').open('wb') as log:
        proc=subprocess.Popen([str(PYTHON),str(CENTRAL/'scripts/distribution_remote_test_service.py'),'--root',str(ROOT),'serve-off'],
            cwd=ROOT,env=env(ROOT),stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            wait_service(f.client,55872)
            response=f.client.post('https://127.0.0.1:55872'+PREFIX+'/sessions',headers={'Authorization':'Bearer '+f.tokens['advisor']},
                json={**SCOPE,'binding_id':value['identity']['binding']['id'],'purpose':'account-login','request_id':str(uuid4())})
            assert response.status_code==503 and response.json()['detail']['code']=='REMOTE_DISABLED'
            assert f.call('GET',PREFIX+'/sessions/'+value['session']['id'])['session']['broker_epoch']==epoch
        finally:
            service_command('stop');service_command('start');wait_service(f.client)


def test_remote_database_contains_metadata_only(f):
    import asyncpg
    cfg=json.loads((ROOT/'environment.json').read_text(encoding='utf-8'))
    async def read_metadata():
        db=await asyncpg.connect('postgresql://remote_broker_test@127.0.0.1:55537/remote_broker_test',server_settings={'search_path':cfg['schema']})
        try:
            async with db.transaction(readonly=True):
                values=[]
                for table in ('distribution_remote_sessions','distribution_remote_commands','distribution_events'):
                    rows=await db.fetch(f'SELECT row_to_json(t)::text AS value FROM {table} t')
                    values.extend(row['value'] for row in rows)
                assert all('synthetic-sensitive-sentinel' not in row and 'png_base64' not in row for row in values)
                return len(values)
        finally:await db.close()
    assert asyncio.run(read_metadata())>0


def test_recent_read_frame_survives_uploads_before_input_and_delivery(f):
    value=f.create();f.frame(value)
    f.frame(value,seq=2,read=False)
    command=f.input(value,seq=1)
    f.frame(value,seq=3,read=False)
    delivered=f.poll(value['identity'])['commands']
    assert len(delivered)==1 and delivered[0]['command_id']==command['command_id'] and delivered[0]['frame_seq']==1
    assert set(delivered[0])=={'session_id','command_id','command_seq','control_revision','frame_seq','input'}
    assert f.poll(value['identity'])['commands']==[]
    ack={'device_id':value['identity']['device']['id'],'session_id':value['session']['id'],'command_id':command['command_id'],
        'command_seq':1,'control_revision':1,'state':'applied','code':'INPUT_APPLIED'}
    response=f.client.post(PREFIX+'/device/ack',headers={'Authorization':'Bearer '+value['identity']['device']['credential']},json=ack)
    assert response.status_code==200


def test_recent_frame_requires_successful_controller_read(f):
    value=f.create();f.frame(value,read=False)
    f.input(value,expected=409)
    f.call('GET',PREFIX+'/sessions/'+value['session']['id']+'/frame',actor='reviewer',expected=403)
    f.input(value,expected=409)
    f.read_frame(value);f.input(value)


def test_recent_frame_failed_read_commit_does_not_authorize_input(f):
    value=f.create();f.frame(value,read=False)
    f.call('POST','/test/fault',actor='admin',json={'mode':'commit'})
    f.read_frame(value,expected=503)
    assert f.call('GET','/test/metadata',actor='admin')['read_frames']==0
    f.input(value,expected=409)
    f.read_frame(value);f.input(value)


@pytest.mark.parametrize('stage',['input','delivery'])
def test_recent_frame_expiry_uses_original_capture_not_new_upload(f,stage):
    value=f.create();f.frame(value,at=int(time.time()*1000)-4000)
    if stage=='delivery':f.input(value)
    time.sleep(1.2)
    f.frame(value,seq=2,read=False)
    if stage=='input':f.input(value,seq=1,expected=409)
    else:
        assert f.poll(value['identity'])['commands']==[]
        assert f.call('GET',PREFIX+'/sessions/'+value['session']['id'])['session']['last_command_state']=='unknown'
    assert f.call('GET','/test/metadata',actor='admin')['read_frames']==0


def test_recent_frame_history_is_bounded_metadata(f):
    value=f.create()
    for seq in range(1,18):f.frame(value,seq=seq)
    metadata=f.call('GET','/test/metadata',actor='admin')
    assert metadata['read_frames']==metadata['max_session_read_frames']==16
    assert metadata['frames']==1 and metadata['payloads']==0
    f.input(value,seq=1,expected=409)
    f.input(value,seq=2)
    f.frame(value,seq=18)
    delivered=f.poll(value['identity'])['commands']
    assert len(delivered)==1 and delivered[0]['frame_seq']==2
