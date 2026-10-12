"""Authenticated HTTP registration and fixed HTTPS-to-independent MHT handoff."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4
import pytest
from test_distribution_control_postgres import fixture, SCOPE, core, device_exchange, receipt
from test_distribution_execution import prepare, progress
from app import distribution_execution as execution
from app.distribution_execution_capabilities import frozen_manifest, MHT_MANIFEST_SHA256, current

PREFIX='/api/distribution/capabilities/v1/device'

def request(b,revision=0):
    return {'capabilityVersion':1,'deviceId':b['device_id'],'adapterVersion':'reviewed-manual-handoff-v1',
            'manifestDigest':MHT_MANIFEST_SHA256,'manifest':frozen_manifest(),'bindingIds':[str(b['id'])],
            'expiresAt':core.now_ms()+3600000,'expectedRevision':revision,'requestId':str(uuid4())}

async def post(f,b,body,path='/register',token=None):
    r=await f.client.post(PREFIX+path,headers={'Authorization':'Bearer '+(token or b['credential'])},json=body)
    assert r.headers.get('cache-control')=='no-store'
    return r

def test_authenticated_registration_duplicate_renewal_and_revocation(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False)
            status_path='/api/distribution/capabilities/v1/device/'+b['device_id']+'/status'
            headers={'Authorization':'Bearer '+b['credential']}
            before=await f.client.get(status_path,headers=headers)
            assert before.status_code==200 and before.json()['registration'] is None
            body=request(b)
            results=await asyncio.gather(post(f,b,body),post(f,b,body))
            assert all(r.status_code==200 for r in results),[r.status_code for r in results]
            first=results[0].json();assert first==results[1].json()
            assert (await f.client.get(status_path,headers=headers)).json()['registration']==first
            assert first['revision']==1 and first['automaticSubmit'] is False and first['publicationVerified'] is False
            assert first['allowedBindings']==[{'bindingId':str(b['id']),'platform':'wechat-article','stages':['preflight','handoff']}]
            await execution.run_once(f.sessions)
            assert len((await progress(f))['items'])==1
            exchange=await device_exchange(f,{'id':b['device_id'],'credential':b['credential']})
            assert len(exchange.json()['tasks'])==1
            renewal=request(b,1);renewal['expiresAt']+=1000
            second=await post(f,b,renewal);assert second.status_code==200
            assert second.json()['attestationDigest']==first['attestationDigest']
            assert second.json()['registrationId']==first['registrationId']
            assert (await device_exchange(f,{'id':b['device_id'],'credential':b['credential']})).json()['tasks']
            revoke={'capabilityVersion':1,'deviceId':b['device_id'],'expectedRevision':2,'requestId':str(uuid4())}
            r=await post(f,b,revoke,'/revoke');assert r.status_code==200 and not r.json()['active']
            assert (await post(f,b,revoke,'/revoke')).json()==r.json()
            assert not (await device_exchange(f,{'id':b['device_id'],'credential':b['credential']})).json()['tasks']
            assert (await progress(f))['items'][0]['status']=='unknown'
            new=await post(f,b,request(b,3));assert new.status_code==200
            assert new.json()['attestationDigest']!=first['attestationDigest']
            await execution.run_once(f.sessions);assert len((await progress(f))['items'])==1
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publish_reservations'))['n']==0
                assert await current(db,b['device_id'],'wechat-article','handoff',binding_id=uuid4()) is None
    asyncio.run(run())

@pytest.mark.parametrize('change',['token','jwt','manifest','digest','stages','binding','expiry','revision','device'])
def test_capability_registration_rejects_unauthorized_or_promoted_requests(monkeypatch,change):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);body=request(b);token=None;expected=422
            if change=='token':token='invalid'+'x'*48;expected=401
            elif change=='jwt':token=f.tokens[8];expected=401
            elif change=='manifest':body['manifest']['automaticSubmit']=True
            elif change=='digest':body['manifestDigest']='b'*64
            elif change=='stages':body['stages']=['publish']
            elif change=='binding':body['bindingIds']=[str(uuid4())];expected=403
            elif change=='expiry':body['expiresAt']=core.now_ms()+86401000
            elif change=='revision':body['expectedRevision']=1;expected=409
            else:body['deviceId']=str(uuid4());expected=401
            r=await post(f,b,body,token=token);assert r.status_code==expected,r.text
            await execution.run_once(f.sessions);assert not (await progress(f))['items']
    asyncio.run(run())

def test_request_identity_cannot_mutate_and_device_binding_revocation_blocks_registration(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);body=request(b)
            assert (await post(f,b,body)).status_code==200
            altered=deepcopy(body);altered['expiresAt']+=1
            assert (await post(f,b,altered)).status_code==409
            assert (await f.call('POST','/bindings/'+str(b['id'])+'/revoke',actor=8)).status_code==200
            assert (await post(f,b,request(b,1))).status_code==403
            assert (await f.call('POST','/devices/'+b['device_id']+'/revoke',actor=8)).status_code==200
            assert (await post(f,b,body)).status_code==401
    asyncio.run(run())


@pytest.mark.parametrize('outcome',['complete','terminate','unknown'])
def test_normal_handoff_closes_without_publication_and_unknown_stays_held(monkeypatch,outcome):
    async def run():
        async with fixture(monkeypatch) as f:
            original,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions);device={'id':b['device_id'],'credential':b['credential']}
            task=(await device_exchange(f,device)).json()['tasks'][0]
            code='LOGIN_REQUIRED' if outcome=='terminate' else 'HUMAN_REQUIRED'
            assert (await device_exchange(f,device,[receipt(task,'awaiting-human',code)])).status_code==200
            if outcome=='unknown':assert (await device_exchange(f,device,[receipt(task,'unknown','EXECUTION_RESULT_UNKNOWN')])).status_code==200
            r=receipt(task,'canceled' if outcome=='terminate' else 'succeeded','HUMAN_INTERVENTION_COMPLETED' if outcome=='terminate' else 'HUMAN_HANDOFF_ACCEPTED',evidence='human-reported');r['sequence']=5
            body={'handoffVersion':1,'deviceId':b['device_id'],'grantId':task['grantId'],'receipt':r}
            response=await f.client.post('/api/distribution/handoff/v1/device/receipt',headers={'Authorization':'Bearer '+b['credential']},json=body)
            if outcome=='unknown':assert response.status_code==409
            else:
                assert response.status_code==200,response.text
                assert response.json()['result']==('HANDOFF_TERMINATED' if outcome=='terminate' else 'HANDOFF_COMPLETE')
                assert response.json()['publicationVerified'] is False
                duplicate=await f.client.post('/api/distribution/handoff/v1/device/receipt',headers={'Authorization':'Bearer '+b['credential']},json=body)
                assert duplicate.json()==response.json()
                # Strict execution v1 still refuses these extra human closure codes.
                assert (await device_exchange(f,device,[r])).status_code==403
                if outcome=='terminate':
                    policy=(await f.call('GET','/account-policies',actor=8)).json()['items'][0]['policy']
                    assert policy['paused_reason']=='LOGIN_REQUIRED'
                    assert (await f.call('POST','/account-pause',actor=8,json={'binding_id':str(b['id']),'action':'resume','expected_revision':policy['revision'],'request_id':str(uuid4())})).status_code==200
                publish={**original,'action':'publish','confirm_manual_publication':True,'request_id':str(uuid4())}
                result=await f.call('POST','/tasks',json=publish);assert result.status_code==200,result.text
                envelope=(await device_exchange(f,device)).json();assert any(t['action']=='publish' for t in envelope['tasks'])
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']==('held' if outcome=='unknown' else 'released' if outcome=='terminate' else 'consumed')
                assert (await core.one(db,"SELECT count(*) AS n FROM distribution_tasks WHERE action='publish' AND status='succeeded'"))['n']==0
    asyncio.run(run())


@pytest.mark.parametrize('action',['end','device','binding'])
@pytest.mark.parametrize('started',[False,True])
def test_unstarted_revocation_releases_handoff_slot_but_exposed_attempt_stays_held(monkeypatch,action,started):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions)
            if started:assert (await device_exchange(f,{'id':b['device_id'],'credential':b['credential']})).json()['tasks']
            if action=='end':r=await f.call('POST','/control',json={**SCOPE,'action':'end','expected_revision':1,'request_id':str(uuid4())})
            elif action=='device':r=await f.call('POST','/devices/'+b['device_id']+'/revoke',actor=8)
            else:r=await f.call('POST','/bindings/'+str(b['id'])+'/revoke',actor=8)
            assert r.status_code==200,r.text
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']==('held' if started else 'released')
                assert (await core.one(db,'SELECT status FROM distribution_tasks'))['status']==('unknown' if started else 'canceled')
                from app import distribution_scheduling as scheduling
                schedule=await scheduling.schedule(db,b)
                assert schedule['available'] is (not started)
    asyncio.run(run())


@pytest.mark.parametrize('started',[False,True])
def test_binding_switch_never_borrows_new_binding_channel_permission(monkeypatch,started):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions)
            device={'id':b['device_id'],'credential':b['credential']}
            if started:assert (await device_exchange(f,device)).json()['tasks']
            second=(await f.call('POST','/devices',actor=8,json={'label':'switched device'})).json()['device']
            r=await f.call('POST','/bindings',actor=8,json={**SCOPE,'device_id':second['id'],'account_id':'second_local','external_account_id':b['external_account_id'],'platform':b['platform'],'confirm_account_ownership':True});assert r.status_code==200
            new_binding=r.json()['binding']['id']
            assert (await f.call('POST','/project-channel',json={**SCOPE,'binding_id':str(b['id']),'content_type':'article','enabled':False,'expected_revision':1,'request_id':str(uuid4())})).status_code==200
            assert (await f.call('POST','/project-channel',json={**SCOPE,'binding_id':new_binding,'content_type':'article','enabled':True,'expected_revision':0,'request_id':str(uuid4())})).status_code==200
            async with f.sessions() as db:
                await db.execute(core.text('UPDATE distribution_queue SET binding_id=:id'),{'id':new_binding});await db.commit()
            assert not (await device_exchange(f,device)).json()['tasks']
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']==('held' if started else 'released')
                assert (await core.one(db,'SELECT status FROM distribution_tasks'))['status']==('unknown' if started else 'canceled')
    asyncio.run(run())


def test_dispatch_binding_switch_exits_before_acquiring_second_device_under_scope(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            second=(await f.call('POST','/devices',actor=8,json={'label':'racing device'})).json()['device']
            r=await f.call('POST','/bindings',actor=8,json={**SCOPE,'device_id':second['id'],'account_id':'racing_local','external_account_id':b['external_account_id'],'platform':b['platform'],'confirm_account_ownership':True});assert r.status_code==200
            new_binding=r.json()['binding']['id']
            legacy={**SCOPE,'variant_id':11,'binding_id':new_binding,'source_revision':f.sources.content['version'],'expected_digest':core.content_digest(f.sources.content),'action':'preflight','confirm_reviewed_content':True,'request_id':str(uuid4())}
            assert (await f.call('POST','/tasks',json=legacy)).status_code==200
            device_locked=asyncio.Event();second_locked=asyncio.Event();original=core.lock
            async def observe(db,key):
                await original(db,key)
                if key=='device:'+b['device_id']:device_locked.set()
                if key=='device:'+second['id']:second_locked.set()
            monkeypatch.setattr(core,'lock',observe)
            async with f.sessions() as scan:
                await original(scan,'scope:'+core.canonical(SCOPE))
                queue_id=(await core.one(scan,'SELECT id FROM distribution_queue'))['id']
                async def dispatch():
                    async with f.sessions() as db:
                        result=await execution.dispatch_one(db,queue_id);await db.commit();return result
                work=asyncio.create_task(dispatch());await asyncio.wait_for(device_locked.wait(),3)
                exchange=asyncio.create_task(device_exchange(f,second));await asyncio.wait_for(second_locked.wait(),3)
                await scan.execute(core.text('UPDATE distribution_queue SET binding_id=:id'),{'id':new_binding});await scan.commit()
                result,envelope=await asyncio.wait_for(asyncio.gather(work,exchange),3)
                assert result=='BINDING_CHANGED_RETRY' and envelope.status_code==200
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_execution_intents'))['n']==0
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==1
                assert (await core.one(db,"SELECT count(*) AS n FROM distribution_tasks WHERE action='handoff'"))['n']==0
    asyncio.run(run())


def test_fixed_https_registration_dispatch_and_independent_mht_human_handoff(monkeypatch):
    """No direct attestation INSERT: Node HTTPS -> API -> durable worker -> MHT."""
    async def run():
        import ipaddress, shutil, socket, tempfile
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import uvicorn
        runner=Path(os.environ['DISTRIBUTION_NODE_RUNNER'])
        assert runner.is_file() and runner.name=='https-runner.mjs'
        registration=Path(__file__).parents[1]/'scripts/distribution_capability_https_fixture.mjs'
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False)
            await execution.run_once(f.sessions);assert not (await progress(f))['items']
            with tempfile.TemporaryDirectory(prefix='distribution-capability-tls-') as temp:
                root=Path(temp);key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
                name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'distribution-capability-loopback')])
                cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
                cert_path=root/'loopback.pem';key_path=root/'loopback.key'
                cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
                sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                server=uvicorn.Server(uvicorn.Config(f.app,host='127.0.0.1',port=port,ssl_keyfile=str(key_path),ssl_certfile=str(cert_path),access_log=False,log_level='critical',lifespan='off'))
                running=asyncio.create_task(server.serve(sockets=[sock]))
                async def command(script,payload):
                    env={**os.environ,'NODE_EXTRA_CA_CERTS':str(cert_path),'MHT_DISTRIBUTION_DEVICE_TOKEN':b['credential']}
                    process=await asyncio.create_subprocess_exec(shutil.which('node'),str(script),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
                    try:
                        stdout,_=await asyncio.wait_for(process.communicate(json.dumps(payload).encode()),30)
                        assert process.returncode==0,'Fixed HTTPS transport rejected operation'
                        return [json.loads(line) for line in stdout.splitlines()]
                    finally:
                        if process.returncode is None:process.kill();await process.wait()
                try:
                    async with asyncio.timeout(10):
                        while not server.started:await asyncio.sleep(.02)
                    origin=f'https://127.0.0.1:{port}'
                    payload={'origin':origin,'deviceId':b['device_id'],'bindingIds':[str(b['id'])],'expiresAt':core.now_ms()+3600000,'expectedRevision':0,'requestId':str(uuid4())}
                    registered=(await command(registration,payload))[0]
                    assert registered['active'] and registered['allowedBindings'][0]['stages']==['preflight','handoff']
                    assert (await command(registration,payload))[0]==registered
                    await asyncio.gather(execution.run_once(f.sessions),execution.run_once(f.sessions))
                    result=(await command(runner,{'origin':origin,'deviceId':b['device_id'],'cycles':3}))[-1]
                    assert result['phase']=='verified' and result['stages']['awaiting-human']==1
                    view=await progress(f);assert len(view['items'])==1
                    item=view['items'][0];assert item['status']=='awaiting-human' and item['receipt']['code']=='HUMAN_REQUIRED'
                    assert item['receipt']['evidence']=='none' and item['receipt']['publicUrl'] is None
                    assert item['capability_digest']==registered['attestationDigest']
                    async with f.sessions() as db:
                        assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publish_reservations'))['n']==0
                        assert (await core.one(db,'SELECT publication_grant_id FROM distribution_tasks'))['publication_grant_id'] is None
                        assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='held'
                finally:
                    server.should_exit=True;await asyncio.wait_for(running,10);sock.close()
    asyncio.run(run())


@pytest.mark.parametrize('change',['source','pause','permission','expiry'])
def test_handoff_closure_rechecks_current_source_and_authority(monkeypatch,change):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions);device={'id':b['device_id'],'credential':b['credential']}
            task=(await device_exchange(f,device)).json()['tasks'][0]
            assert (await device_exchange(f,device,[receipt(task,'awaiting-human','HUMAN_REQUIRED')])).status_code==200
            if change=='source':f.sources.content['body']+=' edited'
            elif change=='pause':assert (await f.call('POST','/control',json={**SCOPE,'action':'pause','expected_revision':1,'request_id':str(uuid4())})).status_code==200
            else:
                async with f.sessions() as db:
                    await db.execute(core.text('UPDATE distribution_handoff_permissions SET enabled=false' if change=='permission' else 'UPDATE distribution_device_capability_registrations SET expires_at=0'));await db.commit()
            body={'handoffVersion':1,'deviceId':b['device_id'],'grantId':task['grantId'],'receipt':receipt(task,'succeeded','HUMAN_HANDOFF_ACCEPTED',evidence='human-reported')}
            result=await f.client.post('/api/distribution/handoff/v1/device/receipt',headers={'Authorization':'Bearer '+b['credential']},json=body)
            assert result.status_code==403
            async with f.sessions() as db:assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='held'
    asyncio.run(run())


def test_explicit_advisor_investigation_of_revoked_unknown_cannot_replay_or_publish(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions)
            task=(await device_exchange(f,{'id':b['device_id'],'credential':b['credential']})).json()['tasks'][0]
            assert (await f.call('POST','/devices/'+b['device_id']+'/revoke',actor=8)).status_code==200
            f.sources.content['body']+=' new approved version later'
            body={**SCOPE,'task_id':task['id'],'source_revision':task['content']['version'],'content_digest':task['contentDigest'],'outcome':'not-published','confirm_platform_checked':True,'confirm_executor_stopped':True,'confirm_no_publication':True,'request_id':str(uuid4())}
            path='/api/distribution/handoff/v1/advisor/resolution'
            async def call(value,actor=7):return await f.client.post(path,headers={'Authorization':'Bearer '+f.tokens[actor]},json=value)
            assert (await call(body,9)).status_code==403
            assert (await call({**body,'confirm_no_publication':False})).status_code==422
            assert (await call({**body,'content_digest':'b'*64})).status_code==409
            async with f.sessions() as db:assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='held'
            result=await call(body);assert result.status_code==200,result.text
            assert result.json()['result']=='HANDOFF_NOT_PUBLISHED' and result.json()['publicationVerified'] is False
            assert (await call(body)).json()==result.json()
            await execution.run_once(f.sessions)
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='released'
                assert (await core.one(db,'SELECT status,revoked FROM distribution_tasks'))=={'status':'failed','revoked':True}
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==1
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_handoff_resolutions'))['n']==1
            item=(await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]
            assert item['handoff_resolution']['outcome']=='not-published'
    asyncio.run(run())


def test_login_ready_creates_new_unique_attempt_bounded_to_three(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions);device={'id':b['device_id'],'credential':b['credential']}
            identities=[]
            for attempt in (1,2,3):
                task=(await device_exchange(f,device)).json()['tasks'][0]
                identities.append((task['id'],task['grantId'],task['leaseId']))
                assert (await device_exchange(f,device,[receipt(task,'awaiting-human','LOGIN_REQUIRED')])).status_code==200
                close={'handoffVersion':1,'deviceId':b['device_id'],'grantId':task['grantId'],'receipt':receipt(task,'canceled','HUMAN_INTERVENTION_COMPLETED',evidence='human-reported')}
                r=await f.client.post('/api/distribution/handoff/v1/device/receipt',headers={'Authorization':'Bearer '+b['credential']},json=close);assert r.status_code==200,r.text
                p=(await f.call('GET','/account-policies',actor=8)).json()['items'][0]['policy']
                assert (await f.call('POST','/account-pause',actor=8,json={'binding_id':str(b['id']),'action':'resume','expected_revision':p['revision'],'request_id':str(uuid4())})).status_code==200
                retry={**SCOPE,'task_id':task['id'],'source_revision':task['content']['version'],'content_digest':task['contentDigest'],'confirm_executor_stopped':True,'confirm_no_publication':True,'request_id':str(uuid4())}
                async def again():return await f.client.post('/api/distribution/handoff/v1/advisor/retry',headers={'Authorization':'Bearer '+f.tokens[7]},json=retry)
                results=await asyncio.gather(again(),again())
                if attempt==3:assert all(r.status_code==409 and r.json()['detail']['code']=='handoff_attempt_limit' for r in results)
                else:
                    assert all(r.status_code==200 for r in results),[r.text for r in results]
                    assert results[0].json()==results[1].json()
                    assert results[0].json()['attempt']==attempt+1
                    assert results[0].json()['previous_task_id']==task['id']
            assert all(len({row[i] for row in identities})==3 for i in range(3))
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_execution_intents'))['n']==3
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_handoff_retry_links'))['n']==2
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publish_reservations'))['n']==0
    asyncio.run(run())


def test_unknown_retry_requires_investigation_and_never_resurrects_old_attempt(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions);device={'id':b['device_id'],'credential':b['credential']}
            task=(await device_exchange(f,device)).json()['tasks'][0]
            assert (await device_exchange(f,device,[receipt(task,'unknown','EXECUTION_RESULT_UNKNOWN')])).status_code==200
            retry={**SCOPE,'task_id':task['id'],'source_revision':task['content']['version'],'content_digest':task['contentDigest'],'confirm_executor_stopped':True,'confirm_no_publication':True,'request_id':str(uuid4())}
            async def call(path,value):return await f.client.post('/api/distribution/handoff/v1/advisor/'+path,headers={'Authorization':'Bearer '+f.tokens[7]},json=value)
            assert (await call('retry',retry)).json()['detail']['code']=='handoff_investigation_required'
            investigation={**retry,'outcome':'not-published','confirm_platform_checked':True,'request_id':str(uuid4())}
            assert (await call('resolution',investigation)).status_code==200
            result=await call('retry',retry);assert result.status_code==200,result.text
            new=(await device_exchange(f,device)).json()['tasks'][0]
            assert new['id']!=task['id'] and new['grantId']!=task['grantId']
            assert (await progress(f))['items'][1]['status']=='failed'
    asyncio.run(run())


@pytest.mark.parametrize('operation',['resolution','retry'])
def test_recovery_device_lock_precedes_geo_style_tenant_for_update(monkeypatch,operation):
    """Two real PG transactions reproduce frozen GEO entitlement's row lock."""
    async def run():
        from types import MethodType
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions);device={'id':b['device_id'],'credential':b['credential']}
            task=(await device_exchange(f,device)).json()['tasks'][0]
            assert (await device_exchange(f,device,[receipt(task,'unknown','EXECUTION_RESULT_UNKNOWN')])).status_code==200
            body={**SCOPE,'task_id':task['id'],'source_revision':task['content']['version'],'content_digest':task['contentDigest'],'confirm_executor_stopped':True,'confirm_no_publication':True,'request_id':str(uuid4())}
            path='/api/distribution/handoff/v1/advisor/'
            if operation=='resolution':body.update(outcome='not-published',confirm_platform_checked=True)
            else:
                resolved=await f.client.post(path+'resolution',headers={'Authorization':'Bearer '+f.tokens[7]},json={**body,'outcome':'not-published','confirm_platform_checked':True,'request_id':str(uuid4())});assert resolved.status_code==200
            original_auth=f.sources.authorize_scope
            async def native_row_lock(self,db,actor,tenant,scope):
                await db.execute(core.text('SELECT id FROM tenants WHERE id=:id FOR UPDATE'),{'id':tenant})
                await original_auth(db,actor,tenant,scope)
            f.sources.authorize_scope=MethodType(native_row_lock,f.sources)
            original_lock=core.lock;waiting_device=asyncio.Event()
            async def observe(db,key):
                if asyncio.current_task().get_name()=='handoff-recovery' and key=='device:'+b['device_id']:waiting_device.set()
                await original_lock(db,key)
            monkeypatch.setattr(core,'lock',observe)
            async with f.sessions() as exchange_db:
                await original_lock(exchange_db,'device:'+b['device_id'])
                pending=asyncio.create_task(f.client.post(path+operation,headers={'Authorization':'Bearer '+f.tokens[7]},json=body),name='handoff-recovery')
                try:
                    await asyncio.wait_for(waiting_device.wait(),3)
                    # Old authorize-before-device order already holds this row and
                    # deadlocks here. New order leaves it free for the exchange.
                    await asyncio.wait_for(exchange_db.execute(core.text('SELECT id FROM tenants WHERE id=4 FOR UPDATE')),3)
                    await exchange_db.commit()
                    result=await asyncio.wait_for(pending,3);assert result.status_code==200,result.text
                finally:
                    if not pending.done():pending.cancel()
                    await asyncio.gather(pending,return_exceptions=True)
    asyncio.run(run())


def test_end_account_lock_precedes_geo_style_tenant_row_lock_across_projects(monkeypatch):
    async def run():
        from types import MethodType
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions)
            original_auth=f.sources.authorize_scope
            async def geo_authorize(self,db,actor,tenant,scope):
                await db.execute(core.text('SELECT id FROM tenants WHERE id=:id FOR UPDATE'),{'id':tenant})
                await original_auth(db,actor,tenant,scope)
            f.sources.authorize_scope=MethodType(geo_authorize,f.sources)
            original_lock=core.lock;account_wait=asyncio.Event()
            async def observe(db,key):
                if asyncio.current_task().get_name()=='ending-project' and key=='account:'+b['platform']+':'+b['external_account_id']:account_wait.set()
                await original_lock(db,key)
            monkeypatch.setattr(core,'lock',observe)
            async with f.sessions() as other_project:
                # A different project/device holds its scope then the canonical
                # account, exactly as dispatch/exchange does before GEO auth.
                await original_lock(other_project,'scope:'+core.canonical({**SCOPE,'scope_id':21}))
                await original_lock(other_project,'account:'+b['platform']+':'+b['external_account_id'])
                ending=asyncio.create_task(f.call('POST','/control',json={**SCOPE,'action':'end','expected_revision':1,'request_id':str(uuid4())}),name='ending-project')
                try:
                    await asyncio.wait_for(account_wait.wait(),3)
                    await asyncio.wait_for(other_project.execute(core.text('SELECT id FROM tenants WHERE id=4 FOR UPDATE')),3)
                    await other_project.commit()
                    result=await asyncio.wait_for(ending,3);assert result.status_code==200,result.text
                finally:
                    if not ending.done():ending.cancel()
                    await asyncio.gather(ending,return_exceptions=True)
            async with f.sessions() as db:assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='released'
    asyncio.run(run())


@pytest.mark.parametrize('expired',[True,False])
def test_offline_expired_exposed_handoff_is_investigable_without_read_side_effects(monkeypatch,expired):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions);device={'id':b['device_id'],'credential':b['credential']}
            task=(await device_exchange(f,device)).json()['tasks'][0]
            assert (await device_exchange(f,device,[receipt(task,'awaiting-human','HUMAN_REQUIRED')])).status_code==200
            if expired:
                async with f.sessions() as db:
                    await db.execute(core.text('UPDATE distribution_tasks SET lease_expires_at=0'));await db.commit()
            item=(await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]
            assert item['handoff_investigable'] is expired and item['status']=='awaiting-human'
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='held'
                assert (await core.one(db,'SELECT status FROM distribution_tasks'))['status']=='awaiting-human'
            body={**SCOPE,'task_id':task['id'],'source_revision':task['content']['version'],'content_digest':task['contentDigest'],'outcome':'not-published','confirm_platform_checked':True,'confirm_executor_stopped':True,'confirm_no_publication':True,'request_id':str(uuid4())}
            result=await f.client.post('/api/distribution/handoff/v1/advisor/resolution',headers={'Authorization':'Bearer '+f.tokens[7]},json=body)
            assert result.status_code==(200 if expired else 409),result.text
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']==('released' if expired else 'held')
                assert (await core.one(db,"SELECT count(*) AS n FROM distribution_events WHERE action='handoff_expired_fenced'"))['n']==int(expired)
            if expired:
                retry={k:v for k,v in body.items() if k not in ('outcome','confirm_platform_checked')};retry['request_id']=str(uuid4())
                result=await f.client.post('/api/distribution/handoff/v1/advisor/retry',headers={'Authorization':'Bearer '+f.tokens[7]},json=retry);assert result.status_code==200,result.text
                new=(await device_exchange(f,device)).json()['tasks'][0];assert new['id']!=task['id'] and new['leaseId']!=task['leaseId']
    asyncio.run(run())


@pytest.mark.parametrize('resolved',[False,True])
def test_device_resolution_read_is_exact_scoped_negative_evidence_without_side_effects(monkeypatch,resolved):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False);assert (await post(f,b,request(b))).status_code==200
            await execution.run_once(f.sessions);device={'id':b['device_id'],'credential':b['credential']}
            task=(await device_exchange(f,device)).json()['tasks'][0]
            assert (await device_exchange(f,device,[receipt(task,'unknown','EXECUTION_RESULT_UNKNOWN')])).status_code==200
            if resolved:
                investigation={**SCOPE,'task_id':task['id'],'source_revision':task['content']['version'],'content_digest':task['contentDigest'],'outcome':'not-published','confirm_platform_checked':True,'confirm_executor_stopped':True,'confirm_no_publication':True,'request_id':str(uuid4())}
                r=await f.client.post('/api/distribution/handoff/v1/advisor/resolution',headers={'Authorization':'Bearer '+f.tokens[7]},json=investigation);assert r.status_code==200
            read={k:task[k] for k in ('deviceId','grantId','leaseId','customerId','projectId','accountId','platform','contentDigest')};read.update(handoffVersion=1,taskId=task['id'],contentVersion=task['content']['version'])
            path='/api/distribution/handoff/v1/device/resolution'
            async def call(value,token=b['credential']):return await f.client.post(path,headers={'Authorization':'Bearer '+token},json=value)
            async with f.sessions() as db:
                before=await core.one(db,'SELECT count(*) AS n FROM distribution_events')
            r=await call(read);assert r.status_code==200,r.text
            assert {k:r.json()[k] for k in read}==read and r.json()['publicationVerified'] is False
            proof=r.json()['resolution']
            if resolved:assert proof['outcome']=='not-published' and proof['evidence']=='advisor-reported' and proof['checkedAt']>0
            else:assert proof is None
            assert (await call(read)).json()==r.json()
            for key in ('taskId','grantId','leaseId','customerId','projectId','accountId','contentVersion','contentDigest'):
                altered={**read,key:'b'*64 if key=='contentDigest' else str(uuid4())}
                assert (await call(altered)).status_code==403
            assert (await call(read,token=f.tokens[8])).status_code==401
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_events'))==before
                stored=await core.one(db,'SELECT status,receipt FROM distribution_tasks')
                assert stored['status']==('failed' if resolved else 'unknown') and stored['receipt']['status']=='unknown'
            assert (await f.call('POST','/bindings/'+str(b['id'])+'/revoke',actor=8)).status_code==200
            assert (await call(read)).status_code==409
    asyncio.run(run())


def test_frozen_mht_actual_clients_register_renew_close_and_revoke(monkeypatch):
    """No direct attestation INSERT: Node HTTPS -> API -> durable worker -> MHT."""
    async def run():
        import ipaddress, shutil, socket, tempfile
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import uvicorn
        snapshot=Path(os.environ['DISTRIBUTION_MHT_FROZEN_SNAPSHOT'])
        source=json.loads((snapshot/'snapshot.json').read_text())['source_commit']
        runner=Path(__file__).parents[1]/'scripts/distribution_frozen_mht_pair.mjs'
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False)
            await execution.run_once(f.sessions);assert not (await progress(f))['items']
            with tempfile.TemporaryDirectory(prefix='distribution-capability-tls-') as temp:
                root=Path(temp);key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
                name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'distribution-capability-loopback')])
                cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
                cert_path=root/'loopback.pem';key_path=root/'loopback.key'
                cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
                sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                server=uvicorn.Server(uvicorn.Config(f.app,host='127.0.0.1',port=port,ssl_keyfile=str(key_path),ssl_certfile=str(cert_path),access_log=False,log_level='critical',lifespan='off'))
                running=asyncio.create_task(server.serve(sockets=[sock]))
                async def command(script,payload):
                    env={**os.environ,'NODE_EXTRA_CA_CERTS':str(cert_path),'MHT_DISTRIBUTION_DEVICE_TOKEN':b['credential']}
                    process=await asyncio.create_subprocess_exec(shutil.which('node'),str(script),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
                    try:
                        stdout,_=await asyncio.wait_for(process.communicate(json.dumps(payload).encode()),30)
                        assert process.returncode==0,'Fixed HTTPS transport rejected operation'
                        return [json.loads(line) for line in stdout.splitlines()]
                    finally:
                        if process.returncode is None:process.kill();await process.wait()
                try:
                    async with asyncio.timeout(10):
                        while not server.started:await asyncio.sleep(.02)
                    origin=f'https://127.0.0.1:{port}'
                    base={'origin':origin,'deviceId':b['device_id'],'snapshot':str(snapshot),'sourceCommit':source,'root':str(root)}
                    registration={'bindingIds':[str(b['id'])],'expiresAt':core.now_ms()+3600000,'expectedRevision':0,'requestId':str(uuid4())}
                    registered=(await command(runner,{**base,'phase':'register','registration':registration}))[0]
                    assert registered['phase']=='registered' and registered['revision']==1
                    renewed=(await command(runner,{**base,'phase':'renew'}))[0]
                    assert renewed['revision']==2 and renewed['attestationDigest']==registered['attestationDigest']
                    await asyncio.gather(execution.run_once(f.sessions),execution.run_once(f.sessions))
                    result=(await command(runner,{**base,'phase':'handoff'}))[0]
                    assert len(result)==1 and result[0]['receipt']['code']=='HUMAN_REQUIRED'
                    view=await progress(f);item=view['items'][0]
                    assert item['status']=='awaiting-human' and item['capability_digest']==registered['attestationDigest']
                    task=result[0]['task']
                    closed=(await command(runner,{**base,'phase':'complete','task':task}))[0]
                    assert closed[0]['receipt']['code']=='HUMAN_HANDOFF_ACCEPTED'
                    assert closed[0]['outboxPending'] is False
                    assert (await progress(f))['items'][0]['status']=='succeeded'
                    revoked=(await command(runner,{**base,'phase':'revoke'}))[0]
                    assert revoked['phase']=='revoked' and revoked['revision']==3
                    async with f.sessions() as db:
                        assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publish_reservations'))['n']==0
                        assert (await core.one(db,'SELECT publication_grant_id FROM distribution_tasks'))['publication_grant_id'] is None
                        assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='consumed'
                finally:
                    server.should_exit=True;await asyncio.wait_for(running,10);sock.close()
    asyncio.run(run())


@pytest.mark.parametrize('initial_state',['unknown','expired-human'])
def test_frozen_mht_unknown_investigation_retry_resolution_and_restart(monkeypatch,initial_state):
    """Real central TLS and frozen MHT; deliberate executor fault, synthetic source."""
    async def run():
        import ipaddress, shutil, socket, tempfile
        from datetime import datetime, timedelta, timezone
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import uvicorn
        snapshot=Path(os.environ['DISTRIBUTION_MHT_FROZEN_SNAPSHOT'])
        source=json.loads((snapshot/'snapshot.json').read_text())['source_commit']
        runner=Path(__file__).parents[1]/'scripts/distribution_frozen_mht_pair.mjs'
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f,attest=False)
            await execution.run_once(f.sessions);assert not (await progress(f))['items']
            with tempfile.TemporaryDirectory(prefix='distribution-capability-tls-') as temp:
                root=Path(temp);key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
                name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'distribution-capability-loopback')])
                cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
                cert_path=root/'loopback.pem';key_path=root/'loopback.key'
                cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
                sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                server=uvicorn.Server(uvicorn.Config(f.app,host='127.0.0.1',port=port,ssl_keyfile=str(key_path),ssl_certfile=str(cert_path),access_log=False,log_level='critical',lifespan='off'))
                running=asyncio.create_task(server.serve(sockets=[sock]))
                async def command(script,payload):
                    env={**os.environ,'NODE_EXTRA_CA_CERTS':str(cert_path),'MHT_DISTRIBUTION_DEVICE_TOKEN':b['credential']}
                    process=await asyncio.create_subprocess_exec(shutil.which('node'),str(script),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
                    try:
                        stdout,_=await asyncio.wait_for(process.communicate(json.dumps(payload).encode()),30)
                        assert process.returncode==0,'Fixed HTTPS transport rejected operation'
                        return [json.loads(line) for line in stdout.splitlines()]
                    finally:
                        if process.returncode is None:process.kill();await process.wait()
                try:
                    async with asyncio.timeout(10):
                        while not server.started:await asyncio.sleep(.02)
                    origin=f'https://127.0.0.1:{port}'
                    base={'origin':origin,'deviceId':b['device_id'],'snapshot':str(snapshot),'sourceCommit':source,'root':str(root)}
                    assert source==os.environ.get('DISTRIBUTION_MHT_EXPECTED_COMMIT','bd8fcc50f2ead8b8cbf07ba6512b40b121e5334b')
                    from app import distribution_handoff_receipts as closure
                    from fastapi import HTTPException
                    original=closure.resolution_read;mode={'value':'real'};reads=[]
                    async def response_fault(db,credential,req):
                        try:value=await original(db,credential,req)
                        except HTTPException as exc:
                            reads.append({'taskId':req.taskId,'error':exc.status_code,'detail':exc.detail});raise
                        reads.append({'taskId':req.taskId,'mode':mode['value'],'proof':value['resolution'] is not None})
                        if mode['value']=='deny':raise HTTPException(403,'synthetic unauthorized proof response')
                        if mode['value']!='real':value={**value,mode['value']:str(uuid4())}
                        return value
                    monkeypatch.setattr(closure,'resolution_read',response_fault)
                    registration={'bindingIds':[str(b['id'])],'expiresAt':core.now_ms()+3600000,'expectedRevision':0,'requestId':str(uuid4())}
                    assert (await command(runner,{**base,'phase':'register','registration':registration}))[0]['phase']=='registered'
                    await execution.run_once(f.sessions)
                    initial=(await command(runner,{**base,'phase':'unknown' if initial_state=='unknown' else 'handoff'}))[0]
                    assert len(initial)==1 and initial[0]['receipt']['status']==('unknown' if initial_state=='unknown' else 'awaiting-human')
                    old=initial[0];task=old['task'];assert not old['outboxPending'] and old['resolution'] is None
                    # Real null response before investigation cannot clear the old lane.
                    pending=(await command(runner,{**base,'phase':'handoff'}))[0][0]
                    assert pending['receipt']==old['receipt'] and pending['audit']==old['audit'] and pending['resolution'] is None
                    async with f.sessions() as db:
                        saved=(await core.one(db,'SELECT receipt FROM distribution_tasks WHERE id=:id',id=task['id']))['receipt']
                        assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='held'
                    if initial_state=='expired-human':
                        async with f.sessions() as db:
                            await db.execute(core.text('UPDATE distribution_tasks SET grant_expires_at=:at,lease_expires_at=:at WHERE id=:id'),{'at':core.now_ms()-1,'id':task['id']});await db.commit()
                    investigation={**SCOPE,'task_id':task['id'],'source_revision':task['content']['version'],'content_digest':task['contentDigest'],'outcome':'not-published','confirm_platform_checked':True,'confirm_executor_stopped':True,'confirm_no_publication':True,'request_id':str(uuid4())}
                    resolution=await f.client.post('/api/distribution/handoff/v1/advisor/resolution',headers={'Authorization':'Bearer '+f.tokens[7]},json=investigation)
                    assert resolution.status_code==200
                    retry={k:v for k,v in investigation.items() if k not in ('outcome','confirm_platform_checked')};retry['request_id']=str(uuid4())
                    retry_result=await f.client.post('/api/distribution/handoff/v1/advisor/retry',headers={'Authorization':'Bearer '+f.tokens[7]},json=retry)
                    assert retry_result.status_code==200
                    read={k:task[k] for k in ('deviceId','grantId','leaseId','customerId','projectId','accountId','platform','contentDigest')};read.update(handoffVersion=1,taskId=task['id'],contentVersion=task['content']['version'])
                    direct=await f.client.post('/api/distribution/handoff/v1/device/resolution',headers={'Authorization':'Bearer '+b['credential']},json=read)
                    assert direct.status_code==200,direct.text
                    assert direct.json()['resolution'] is not None
                    legacy_snapshot=Path(os.environ['DISTRIBUTION_MHT_LEGACY_SNAPSHOT'])
                    legacy_source=json.loads((legacy_snapshot/'snapshot.json').read_text())['source_commit']
                    assert legacy_source=='834a883276b499bff2cd649abfa5ba63db648fd7'
                    legacy_wait=None
                    # HTTPS transport and strict parser must reject independently corrupted echoes.
                    for bad in ('deny','taskId','grantId','leaseId','projectId','contentVersion','contentDigest'):
                        mode['value']=bad
                        batch={**base,'phase':'handoff'}
                        if bad=='deny':batch.update(snapshot=str(legacy_snapshot),sourceCommit=legacy_source)
                        blocked=(await command(runner,batch))[0]
                        assert len(blocked)==2
                        prior=next(t for t in blocked if t['id']==task['id']);new=next(t for t in blocked if t['id']!=task['id'])
                        assert prior['resolution'] is None and prior['receipt']==old['receipt'] and prior['audit']==old['audit']
                        assert new['receipt']['status']=='queued' and new['receipt']['code']=='ACCOUNT_INTERVENTION_REQUIRED'
                        if bad=='deny':
                            assert new['outboxPending'] and new['outboxPayload'] is not None
                            legacy_wait={'payload':new['outboxPayload'],'audit':new['audit']}
                            rejected=await device_exchange(f,{'id':b['device_id'],'credential':b['credential']},[new['receipt']])
                            assert rejected.status_code==403  # central frozen v1 uses receipt_scope_mismatch for unsupported codes
                    mode['value']='real'
                    recovered=(await command(runner,{**base,'phase':'handoff'}))[0]
                    prior=next(t for t in recovered if t['id']==task['id']);new=next(t for t in recovered if t['id']!=task['id'])
                    assert prior['receipt']==old['receipt'] and prior['audit']==old['audit'] and not prior['authorizationAllowed']
                    assert prior['resolution'] is not None, json.dumps({'proof':direct.json()['resolution'],'reads':reads,'status':new['receipt']['code']})
                    proof=json.loads(prior['resolution']['payload']);assert proof['resolution']['outcome']=='not-published' and proof['publicationVerified'] is False
                    assert new['receipt']['status']=='awaiting-human' and new['receipt']['code']=='HUMAN_REQUIRED'
                    assert all(new['task'][key]!=task[key] for key in ('id','grantId','leaseId'))
                    assert new['task']['content']==task['content'] and new['task']['contentDigest']==task['contentDigest']
                    assert not prior['outboxPending'] and not new['outboxPending']
                    assert {'payload':legacy_wait['payload'],'retained':1} in new['isolatedOutbox']
                    assert new['audit'][:len(legacy_wait['audit'])]==legacy_wait['audit']
                    assert sum(json.loads(row['receipt'])['status']=='running' for row in new['audit'])==1
                    before_reads=sum(row['taskId']==task['id'] for row in reads)
                    restarted=(await command(runner,{**base,'phase':'handoff'}))[0]
                    assert sum(row['taskId']==task['id'] for row in reads)==before_reads
                    assert [(t['id'],t['receipt'],t['audit'],t['resolution']) for t in restarted]==[(t['id'],t['receipt'],t['audit'],t['resolution']) for t in recovered]
                    async with f.sessions() as db:
                        stored=await core.one(db,'SELECT status,revoked,receipt FROM distribution_tasks WHERE id=:id',id=task['id'])
                        assert stored['status']=='failed' and stored['revoked'] and stored['receipt']==saved
                        assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==2
                        assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publish_reservations'))['n']==0
                        assert (await core.one(db,'SELECT count(*) AS n FROM distribution_handoff_resolutions'))['n']==1
                        assert sorted(row['state'] for row in await core.rows(db,'SELECT state FROM distribution_handoff_slots'))==['held','released']
                    if os.environ.get('DISTRIBUTION_RECOVERY_PROOF_DIRECTORY'):
                        import hashlib, subprocess
                        destination=Path(os.environ['DISTRIBUTION_RECOVERY_PROOF_DIRECTORY']);destination.mkdir(parents=True,exist_ok=True)
                        evidence={'scenario':initial_state,'result':'PASS','central_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'mht_snapshot':json.loads((snapshot/'snapshot.json').read_text()),'resolution_reads':reads,'original_receipt':old['receipt'],'original_audit':old['audit'],'recovered_original_receipt':prior['receipt'],'recovered_original_audit':prior['audit'],'negative_proof':proof,'new_receipt':new['receipt'],'new_task_id':new['id'],'new_grant_id':new['task']['grantId'],'new_lease_id':new['task']['leaseId'],'new_dispatch_count':1,'restart_replay':False,'old_authorization_allowed':False,'legacy_wait_receipt_raw':legacy_wait['payload'],'legacy_wait_audit':legacy_wait['audit'],'legacy_wait_isolated_retained':new['isolatedOutbox'],'legacy_mht_source_commit':legacy_source,'old_slot':'released','new_slot':'held','publicationVerified':False,'source':'synthetic approved source; executor fault only for unknown; actual HumanHandoffExecutor for expired-human and all new attempts','adversarial_responses':'test wrapper injects 403 and corrupted echoes after actual central scoped read; null is actual unresolved central response','proof_files_sha256':{str(path.relative_to(Path(__file__).parents[1])):hashlib.sha256(path.read_bytes()).hexdigest() for path in (Path(__file__),runner)}}
                        (destination/(initial_state+'.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                finally:
                    server.should_exit=True;await asyncio.wait_for(running,10);sock.close()
    asyncio.run(run())
