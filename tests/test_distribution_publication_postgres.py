"""Real JWT/PostgreSQL checks and outbox transactions; synthetic native writer."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from test_distribution_control_postgres import fixture, prepare, device_exchange, receipt, SCOPE, core
from app import distribution_publication_results as results

URL='https://mp.weixin.qq.com/s/synthetic-public'


async def published(f):
    device,req=await prepare(f,'publish',external='gh_test')
    task=(await f.call('POST','/tasks',json=req)).json()['task']
    envelope=(await device_exchange(f,device)).json()['tasks'][0]
    done=receipt(envelope,'succeeded','HUMAN_PUBLISHED',evidence='human-reported',url=URL)
    assert (await device_exchange(f,device,[done])).status_code==200
    return task


def check(task,**changes):
    return {**SCOPE,'task_id':task['id'],'mode':'human','expected_public_url':URL,
        'confirm_public_access':True,'confirm_target_account':True,'confirm_approved_content':True,'request_id':str(uuid4()),**changes}


async def native_writer(f,monkeypatch, *, fail=False,bad_result=False):
    async with f.sessions() as db:
        await db.execute(text('CREATE TABLE synthetic_native_publications(id bigserial PRIMARY KEY,task_id uuid UNIQUE,verified boolean NOT NULL)'))
        await db.commit()
    async def record(db,actor,tenant,scope,variant,payload):
        source,digest=await core.source(db,actor,SCOPE,variant,payload['platform'])
        if source['source_revision']!=payload['source_revision'] or digest!=payload['content_digest']:
            raise core.problem('source_changed')
        assert (tenant,scope)==(4,19) and actor==payload['verified_by']==7
        row=await core.one(db,'INSERT INTO synthetic_native_publications(task_id,verified) VALUES(:id,true) '
            'ON CONFLICT(task_id) DO UPDATE SET verified=EXCLUDED.verified RETURNING id',id=payload['task_id'])
        if fail: raise core.problem('NATIVE_SYNTHETIC_UNAVAILABLE',503)
        return {'module':'seo','publication_id':row['id'],'monitor_state':'pending',
                'verification':payload['verification'],'idempotent':False,**({'publication_id':-1} if bad_result else {})}
    monkeypatch.setattr(results,'result_adapter',lambda module:SimpleNamespace(record_publication=record))


def test_human_three_checks_required_scope_private_and_unknown_not_adopted(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            task=await published(f)
            for name in ('confirm_public_access','confirm_target_account','confirm_approved_content'):
                assert (await f.call('POST','/publication-check',json=check(task,**{name:False}))).status_code==422
            for actor in (8,9):assert (await f.call('POST','/publication-check',actor=actor,json=check(task))).status_code==403
            assert (await f.call('POST','/publication-check',json=check(task,tenant_id=5))).status_code==403
            assert (await f.call('POST','/publication-check',json=check(task,expected_public_url='https://evil.invalid/s/a'))).status_code==409
            assert (await f.call('POST','/publication-check',json=check(task,body='client forged'))).status_code==422
            async with f.sessions() as db:
                await db.execute(text("UPDATE distribution_tasks SET status='unknown' WHERE id=:id"),{'id':task['id']});await db.commit()
            assert (await f.call('POST','/publication-check',json=check(task))).status_code==409
    asyncio.run(run())


def test_verified_result_writes_once_across_concurrent_checks_and_paused_project(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await native_writer(f,monkeypatch);task=await published(f)
            current=(await f.call('GET','/scope',params=SCOPE)).json()['project']
            assert (await f.call('POST','/control',json={**SCOPE,'action':'pause','expected_revision':current['revision'],'request_id':str(uuid4())})).status_code==200
            response=await asyncio.gather(*[f.call('POST','/publication-check',json=check(task)) for _i in range(3)])
            assert all(r.status_code==200 for r in response)
            assert all(r.json()['publication']['writeback']['state']=='written' for r in response)
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM synthetic_native_publications'))['n']==1
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publication_checks'))['n']==3
            view=(await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]['publication']
            assert view['check']['verification']=='human-verified' and view['writeback']['result']['monitor_state']=='pending'
    asyncio.run(run())


def test_request_id_replay_conflict_and_no_accidental_republication(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await native_writer(f,monkeypatch);task=await published(f);payload=check(task)
            first=await f.call('POST','/publication-check',json=payload)
            assert first.status_code==200
            assert (await f.call('POST','/publication-check',json=payload)).json()==first.json()
            assert (await f.call('POST','/publication-check',json={**payload,'mode':'machine'})).status_code==409
            assert len((await f.call('GET','/tasks',params=SCOPE)).json()['items'])==1
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publication_checks'))['n']==1
                with __import__('pytest').raises(Exception):
                    await db.execute(text('DELETE FROM distribution_publication_checks'));await db.commit()
    asyncio.run(run())


def test_native_failure_and_bad_contract_roll_back_but_preserve_check_for_explicit_retry(monkeypatch):
    async def run():
        for bad in (False,True):
            async with fixture(monkeypatch) as f:
                await native_writer(f,monkeypatch,fail=not bad,bad_result=bad);task=await published(f)
                first=await f.call('POST','/publication-check',json=check(task));assert first.status_code==200
                publication=first.json()['publication']
                assert publication['check']['status']=='verified' and publication['writeback']['state']=='pending'
                async with f.sessions() as db:
                    assert (await core.one(db,'SELECT count(*) AS n FROM synthetic_native_publications'))['n']==0
                # Swap only the synthetic writer, not the persisted check.
                async def record(db,actor,tenant,scope,variant,payload):
                    row=await core.one(db,'INSERT INTO synthetic_native_publications(task_id,verified) VALUES(:id,true) RETURNING id',id=payload['task_id'])
                    return {'module':'seo','publication_id':row['id'],'monitor_state':'pending','verification':payload['verification'],'idempotent':False}
                monkeypatch.setattr(results,'result_adapter',lambda module:SimpleNamespace(record_publication=record))
                req={**SCOPE,'task_id':task['id'],'event_id':publication['writeback']['event_id'],'request_id':str(uuid4())}
                assert (await f.call('POST','/publication-writeback',json={**req,'event_id':str(uuid4())})).status_code==409
                response=await f.call('POST','/publication-writeback',json=req);assert response.status_code==200
                assert response.json()['publication']['writeback']['state']=='written'
                assert (await f.call('POST','/publication-writeback',json=req)).json()==response.json()
    asyncio.run(run())


def test_machine_unavailable_keeps_native_records_absent(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await native_writer(f,monkeypatch);task=await published(f)
            async def inspect(*args):return {'status':'needs-human','code':'ACCOUNT_UNVERIFIED'}
            monkeypatch.setattr(results,'verify_publication',inspect)
            response=await f.call('POST','/publication-check',json=check(task,mode='machine'))
            assert response.status_code==200 and response.json()['publication']['writeback'] is None
            async with f.sessions() as db:assert (await core.one(db,'SELECT count(*) AS n FROM synthetic_native_publications'))['n']==0
    asyncio.run(run())


def test_matching_static_page_is_only_initial_check_without_native_writeback(monkeypatch):
    from app import distribution_publication_verify as verifier
    async def run():
        async with fixture(monkeypatch) as f:
            await native_writer(f,monkeypatch); task=await published(f)
            html=('<style>#js_content {display:none}</style><h1 id="activity-name">' + f.sources.content['title']
                  + '</h1><div id="js_content">' + f.sources.content['body']
                  + '</div><script>\nvar user_name = "gh_test";\n</script>')
            monkeypatch.setattr(verifier,'fetch_public_page',lambda *_:verifier.PublicPage(200,'text/html',html.encode()))
            response=await f.call('POST','/publication-check',json=check(task,mode='machine'))
            assert response.status_code==200
            publication=response.json()['publication']
            assert publication['check']['status']=='needs-human'
            assert publication['check']['code']=='PUBLIC_TEXT_AND_ACCOUNT_MATCHED'
            assert publication['check']['verification'] is None and publication['writeback'] is None
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM synthetic_native_publications'))['n']==0
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publication_writebacks'))['n']==0
    asyncio.run(run())


def test_network_has_no_database_locks_and_permission_change_fences_adoption(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await native_writer(f,monkeypatch);task=await published(f)
            async def inspect(*args):
                # This separate transaction would time out if the named-user
                # read lock from prepare were still held during network I/O.
                async with f.sessions() as db:
                    await db.execute(text('UPDATE users SET is_active=false WHERE id=7'));await db.commit()
                return {'status':'verified','code':'PUBLIC_TEXT_AND_ACCOUNT_MATCHED','verification':'machine-verified'}
            monkeypatch.setattr(results,'verify_publication',inspect)
            assert (await f.call('POST','/publication-check',json=check(task,mode='machine'))).status_code==403
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publication_checks'))['n']==0
    asyncio.run(run())


def test_source_changed_after_report_blocks_writeback_instead_of_using_new_draft(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await native_writer(f,monkeypatch);task=await published(f)
            f.sources.content['body']='新稿，不属于此次冻结发布。'
            response=await f.call('POST','/publication-check',json=check(task));assert response.status_code==200
            assert response.json()['publication']['writeback']['state']=='blocked'
            async with f.sessions() as db:assert (await core.one(db,'SELECT count(*) AS n FROM synthetic_native_publications'))['n']==0
    asyncio.run(run())


def test_publication_source_uses_frozen_text_and_rechecks_scope(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            task=await published(f);original=f.sources.content['body'];f.sources.content['body']='后续新稿'
            query={**SCOPE,'task_id':task['id']}
            response=await f.call('GET','/publication-source',params=query)
            assert response.status_code==200 and response.json()['content']['body']==original
            assert response.json()['external_account_id']=='gh_test'
            assert (await f.call('GET','/publication-source',actor=9,params=query)).status_code==403
            assert (await f.call('GET','/publication-source',params={**query,'scope_id':20})).status_code==403
            f.sources.revoked=True
            assert (await f.call('GET','/publication-source',params=query)).status_code==403
    asyncio.run(run())


def test_publication_images_are_exact_reviewed_bytes_and_never_public_assets(monkeypatch):
    from test_distribution_assets import setup
    from PIL import ImageFile
    async def run():
        async with fixture(monkeypatch) as f:
            device,req,task,_download=await setup(f,'JPEG')
            done=receipt(task,'succeeded','HUMAN_PUBLISHED',evidence='human-reported',url=URL)
            assert (await device_exchange(f,device,[done])).status_code==200
            path=f"/publication-assets/{task['id']}/reviewed_image_1"
            response=await f.call('GET',path,params=SCOPE)
            assert response.status_code==200 and response.content==f.sources.data and response.headers['x-content-type-options']=='nosniff'
            assert (await f.call('GET',path,actor=9,params=SCOPE)).status_code==403
            assert (await f.call('GET',path.replace('reviewed_image_1','foreign_image'),params=SCOPE)).status_code==403
            f.sources.data=b'wrong image'
            assert (await f.call('GET',path,params=SCOPE)).status_code==409
        async with fixture(monkeypatch) as f:
            device,req,task,_download=await setup(f)
            assert (await device_exchange(f,device,[receipt(task,'succeeded','HUMAN_PUBLISHED',evidence='human-reported',url=URL)])).status_code==200
            monkeypatch.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',True)
            assert (await f.call('GET',f"/publication-assets/{task['id']}/reviewed_image_1",params=SCOPE)).status_code==503
            monkeypatch.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',False)
            f.sources.revoked=True
            assert (await f.call('GET',f"/publication-assets/{task['id']}/reviewed_image_1",params=SCOPE)).status_code==403
    asyncio.run(run())


def test_live_monitor_is_scoped_read_only_and_separate_from_initial_writeback(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await native_writer(f,monkeypatch);task=await published(f)
            query={**SCOPE,'task_id':task['id']}
            assert (await f.call('GET','/publication-monitor',params=query)).status_code==409
            written=(await f.call('POST','/publication-check',json=check(task))).json()['publication']['writeback']
            publication_id=written['result']['publication_id']
            adapter=results.result_adapter('seo')
            monkeypatch.setattr(results,'result_adapter',lambda module:adapter)
            current={'module':'seo','publication_id':publication_id,'basis':'page-capture','state':'pending',
                'evidence_source':'auto','observed_at':None,'next_check_at':None,'evidence_id':80,'code':'CAPTURE_PENDING'}
            calls=[]
            async def reader(db,actor,tenant,scope,identity):
                assert (actor,tenant,scope,identity)==(7,4,19,publication_id)
                calls.append(identity);return dict(current)
            monkeypatch.setattr(adapter,'publication_monitor_status',reader,raising=False)
            pending=await f.call('GET','/publication-monitor',params={**query,'publication_id':999})
            assert pending.status_code==200 and pending.json()['monitor']['state']=='pending'
            current.update(state='captured',evidence_source='manual',observed_at=core.now_ms(),code='MANUAL_CAPTURE')
            f.sources.content['body']='later revised draft; observation remains historical'
            captured=await f.call('GET','/publication-monitor',params=query)
            assert captured.status_code==200 and captured.json()['monitor']['evidence_source']=='manual'
            tasks=(await f.call('GET','/tasks',params=SCOPE)).json()['items']
            assert len(tasks)==1 and tasks[0]['publication']['writeback']==written
            assert len(calls)==2
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publication_checks'))['n']==1
                assert (await core.one(db,'SELECT count(*) AS n FROM synthetic_native_publications'))['n']==1
            for actor in (8,9):assert (await f.call('GET','/publication-monitor',actor=actor,params=query)).status_code==403
            assert (await f.call('GET','/publication-monitor',params={**query,'scope_id':20})).status_code==403
            assert (await f.call('GET','/publication-monitor',params={**query,'task_id':str(uuid4())})).status_code==403
            f.sources.revoked=True
            assert (await f.call('GET','/publication-monitor',params=query)).status_code==403
    asyncio.run(run())


def test_live_monitor_failures_are_sanitized_but_permission_denial_propagates(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await native_writer(f,monkeypatch);task=await published(f)
            assert (await f.call('POST','/publication-check',json=check(task))).status_code==200
            query={**SCOPE,'task_id':task['id']}; adapter=results.result_adapter('seo')
            monkeypatch.setattr(results,'result_adapter',lambda module:adapter)
            unavailable=await f.call('GET','/publication-monitor',params=query)
            assert unavailable.status_code==200 and unavailable.json()['monitor']['state']=='unavailable'
            async def broken(db,*args):
                await db.execute(text('SELECT * FROM deliberately_missing_native_monitor'))
            monkeypatch.setattr(adapter,'publication_monitor_status',broken,raising=False)
            failure=await f.call('GET','/publication-monitor',params=query)
            assert failure.status_code==200 and 'deliberately_missing' not in failure.text
            async def forged(db,*args):
                return {'module':'geo','publication_id':999,'secret':'synthetic-private-value'}
            monkeypatch.setattr(adapter,'publication_monitor_status',forged)
            wrong=await f.call('GET','/publication-monitor',params=query)
            assert wrong.status_code==200 and wrong.json()['monitor']['code']=='MONITOR_CONTRACT_MISMATCH'
            assert 'synthetic-private-value' not in wrong.text
            async def denied(db,*args):raise HTTPException(403,{'code':'scope_forbidden'})
            monkeypatch.setattr(adapter,'publication_monitor_status',denied)
            assert (await f.call('GET','/publication-monitor',params=query)).status_code==403
    asyncio.run(run())
