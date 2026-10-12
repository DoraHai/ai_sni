"""Real PG claims, recovery, current authority and read-only JWT monitoring.

Only the external renderer is synthetic. No production data/network is used.
"""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import os
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Depends, HTTPException
from fastapi import BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine, async_sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from app import seo_publication_monitor as jobs
from app import seo_distribution_results as results
from app.api import seo_page_captures as api
from app.config import get_settings
from app.models.seo_page_capture import SeoPageCapture
from app.models.user import User
from app.seo_page_capture import CaptureResult
from app.security.auth import issue_token, require_auth
from app.database import get_session
from test_seo_distribution_results_postgres import database, event, record, counts
from test_seo_workflow_postgres import ADVISOR

pytestmark=pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'),reason='isolated local PG required')


class Renderer:
    def __init__(self): self.calls=0;self.failure=None;self.callback=None
    async def capture_page(self,**kw):
        self.calls+=1
        if self.callback: await self.callback()
        return CaptureResult(tenant_id=kw['tenant_id'],site_id=kw['site_id'],relation_type=kw['relation_type'],
            relation_id=kw['relation_id'],source_url=kw['url'],captured_at=datetime.now(timezone.utc),
            status='failed' if self.failure else 'succeeded',error_code=self.failure,http_status=503 if self.failure else 200,
            viewport_width=800,viewport_height=600,sha256=None if self.failure else 'a'*64,
            storage_key=None if self.failure else 'a'*32+'.png',image_width=800,image_height=600)


@pytest.fixture(autouse=True)
def settings(monkeypatch,tmp_path):
    for name,value in {'seo_page_capture_enabled':True,'seo_scheduler_enabled':True,
        'seo_external_actions_enabled':True,'seo_page_capture_storage_dir':str(tmp_path)}.items():
        monkeypatch.setattr(get_settings(),name,value)
    async def forbidden(*a,**k): pytest.fail('No external HTTP')
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',forbidden)


@asynccontextmanager
async def environment(monkeypatch,*,commit=True,central=True):
    async with database() as sessions:
        if central:
            raw=subprocess.check_output(['git','-C','D:/SNIPERS国内版/ai_sni-worktrees/distribution-control-20261011',
                'show','729af3c4071d6f410ef12ecb88de6ca6a3559f13:scripts/distribution_control_schema.sql'])
            async with sessions.begin() as db:
                conn=await db.connection();wire=await conn.get_raw_connection()
                await wire.driver_connection.execute(raw.decode())
                await db.execute(text("INSERT INTO distribution_controls(tenant_id,module,scope_id,owner_user_id,state) VALUES(4,'seo',2,7,'running')"))
        renderer=Renderer()
        monkeypatch.setattr(api,'_capture_service',lambda:renderer)
        monkeypatch.setattr(api,'async_session_factory',sessions)
        monkeypatch.setattr(jobs,'async_session_factory',sessions)
        payload=await event(sessions)
        async with sessions() as db:
            result=await record(db,payload)
            if commit: await db.commit()
            yield SimpleNamespace(sessions=sessions,renderer=renderer,result=result,db=db,
                publication_id=result['publication_id'],capture_id=result['page_check']['capture_id'])


async def monitor(f):
    async with f.sessions() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        value=await results.publication_monitor_status(db,7,4,2,f.publication_id)
        assert set(value)=={'module','publication_id','basis','state','evidence_source','observed_at','next_check_at','evidence_id','code'}
        assert value['code'].isascii() and 0<len(value['code'])<=64
        assert 'http' not in str(value) and 'storage_key' not in str(value)
        return value


async def update(f,sql,params=None):
    async with f.sessions.begin() as db: await db.execute(text(sql),params or {})


def test_committed_scheduler_executes_once_and_live_state_survives_later_edit(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            assert (await monitor(f))['state']=='pending'
            stats=await jobs.run_publication_captures()
            assert stats['checked']==1 and f.renderer.calls==1
            value=await monitor(f)
            assert value['state']=='captured' and value['evidence_source']=='auto' and value['observed_at']
            assert value['next_check_at'] is None and value['evidence_id']==f.capture_id
            await jobs.run_publication_captures();await api.execute_page_capture(f.capture_id)
            assert f.renderer.calls==1
            await update(f,"UPDATE seo_distribution_variants SET status='draft',content='selection changed' WHERE id=60")
            assert (await monitor(f))['state']=='captured'
            async with f.sessions() as db:
                assert await counts(db)==(1,1,1)
                row=await db.get(SeoPageCapture,f.capture_id)
                assert jobs.metadata(row)['attempts']==1
                assert jobs.META not in api._payload(row)['warnings']
    asyncio.run(scenario())


def test_uncommitted_and_rolled_back_reservations_never_execute(monkeypatch):
    async def scenario():
        async with environment(monkeypatch,commit=False) as f:
            assert (await jobs.run_publication_captures())['checked']==0
            await api.execute_page_capture(f.capture_id)
            assert f.renderer.calls==0
            await f.db.rollback()
            assert (await jobs.run_publication_captures())['checked']==0
    asyncio.run(scenario())


@pytest.mark.parametrize('change',[
    "UPDATE distribution_controls SET state='paused'",
    "UPDATE distribution_controls SET state='ended'",
    "UPDATE distribution_controls SET owner_user_id=8",
    "UPDATE seo_site_advisor_assignments SET active=false WHERE id=3",
    "UPDATE users SET is_active=false WHERE id=7",
    "UPDATE roles SET permissions='{}' WHERE id=5",
    "UPDATE tenant_modules SET status='paused' WHERE id=1",
    "UPDATE tenant_modules SET expires_at='2020-01-01' WHERE id=1",
    "UPDATE seo_sites SET status='archived' WHERE id=2",
    "UPDATE seo_distribution_variants SET status='draft' WHERE id=60",
    "UPDATE seo_content_confirmations SET decision='reject' WHERE id=70",
    "UPDATE seo_page_captures SET source_url='http://127.0.0.1/private'",
])
def test_current_execution_gates_before_renderer(monkeypatch,change):
    async def scenario():
        async with environment(monkeypatch) as f:
            await update(f,change)
            await jobs.run_publication_captures()
            await api.execute_page_capture(f.capture_id)
            assert f.renderer.calls==0
            async with f.sessions() as db: assert await counts(db)==(1,1,1)
    asyncio.run(scenario())


def test_paused_project_resumes_original_capture_and_backlink_metadata_cannot_bypass(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            await update(f,"UPDATE seo_content_publications SET link_discovery='{}'")
            await update(f,"UPDATE distribution_controls SET state='paused'")
            await api.execute_page_capture(f.capture_id)
            assert f.renderer.calls==0
            await update(f,"UPDATE distribution_controls SET state='running'")
            await jobs.run_publication_captures()
            assert f.renderer.calls==1 and (await monitor(f))['state']=='captured'
    asyncio.run(scenario())


def test_concurrent_claims_and_expired_lease_do_not_overlap_live_worker(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            started=asyncio.Event();finish=asyncio.Event()
            async def hold(): started.set();await finish.wait()
            f.renderer.callback=hold
            worker=asyncio.create_task(api.execute_page_capture(f.capture_id))
            await asyncio.wait_for(started.wait(),5)
            assert (await monitor(f))['state']=='running'
            await update(f,"UPDATE seo_page_captures SET warnings=jsonb_set(warnings,'{_publication_dispatch,lease_until}','1')")
            await asyncio.gather(*(api.execute_page_capture(f.capture_id) for _ in range(8)))
            assert f.renderer.calls==1
            finish.set();await worker
            assert (await monitor(f))['state']=='captured'
    asyncio.run(scenario())


def test_process_cancellation_releases_lock_and_recovers_same_capture(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            started=asyncio.Event()
            async def crash(): started.set();await asyncio.Event().wait()
            f.renderer.callback=crash
            task=asyncio.create_task(api.execute_page_capture(f.capture_id))
            await asyncio.wait_for(started.wait(),5);task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert (await monitor(f))['state']=='running'
            await update(f,"UPDATE seo_page_captures SET warnings=jsonb_set(warnings,'{_publication_dispatch,lease_until}','1')")
            f.renderer.callback=None
            await jobs.run_publication_captures()
            assert f.renderer.calls==2 and (await monitor(f))['state']=='captured'
            async with f.sessions() as db:
                assert await counts(db)==(1,1,1)
                assert jobs.metadata(await db.get(SeoPageCapture,f.capture_id))['attempts']==2
    asyncio.run(scenario())


def test_timeout_backoff_and_attempt_budget_are_persistent(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            f.renderer.failure='timeout'
            for attempt in range(1,4):
                await jobs.run_publication_captures()
                assert f.renderer.calls==attempt
                value=await monitor(f)
                assert value['state']=='failed'
                assert bool(value['next_check_at'])==(attempt<3)
                await jobs.run_publication_captures()
                assert f.renderer.calls==attempt
                if attempt<3:
                    await update(f,"UPDATE seo_page_captures SET warnings=jsonb_set(warnings,'{_publication_dispatch,next_attempt_at}','1')")
            await api.execute_page_capture(f.capture_id)
            assert f.renderer.calls==3
            assert (await monitor(f))['code']=='PAGE_CHECK_RETRY_EXHAUSTED'
            async with f.sessions() as db: assert await counts(db)==(1,1,1)
    asyncio.run(scenario())


def test_no_capture_is_not_queued_and_stale_completion_cannot_overwrite_claim(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            async with f.sessions.begin() as db:
                # Synthetic second publication with no capture; no platform action.
                from app.models.seo import SeoContentPublication
                publication=SeoContentPublication(tenant_id=4,content_asset_id=40,platform_code='wechat_official',
                    platform_name='synthetic',publish_mode='manual',status='published',source_version=3,
                    page_url='https://mp.weixin.qq.com/s/uncaptured')
                db.add(publication);await db.flush()
            async with f.sessions() as db:
                value=await results.publication_monitor_status(db,7,4,2,publication.id)
                assert value['state']=='not_queued' and value['evidence_source']=='none' and value['evidence_id'] is None
            async def replace_claim():
                await update(f,"UPDATE seo_page_captures SET warnings=jsonb_set(warnings,'{_publication_dispatch,token}','\"replacement\"')")
            f.renderer.callback=replace_claim
            await api.execute_page_capture(f.capture_id)
            async with f.sessions() as db:
                row=await db.get(SeoPageCapture,f.capture_id)
                assert row.status=='running' and row.sha256 is None and jobs.metadata(row)['token']=='replacement'
    asyncio.run(scenario())


def test_cancellation_after_lock_acquisition_cannot_leak_pool_lock(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            original=AsyncConnection.commit
            interrupted=False
            async def cancel_commit(connection):
                nonlocal interrupted
                await original(connection)
                if not interrupted:
                    interrupted=True
                    raise asyncio.CancelledError()
            monkeypatch.setattr(AsyncConnection,'commit',cancel_commit)
            with pytest.raises(asyncio.CancelledError): await jobs.run_capture(f.capture_id)
            monkeypatch.setattr(AsyncConnection,'commit',original)
            unsigned=int.from_bytes(hashlib.sha256(f'seo-publication-capture:{f.capture_id}'.encode()).digest()[:8],'big')
            async with f.sessions() as db:
                assert await db.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND granted "
                    "AND classid=:high AND objid=:low AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"),
                    {'high':unsigned>>32,'low':unsigned&0xffffffff})==0
            assert f.renderer.calls==0
            await jobs.run_capture(f.capture_id)
            assert f.renderer.calls==1 and (await monitor(f))['state']=='captured'
    asyncio.run(scenario())


@pytest.mark.parametrize('sql',[
    "UPDATE seo_distribution_variants SET status='draft' WHERE id=60",
    "UPDATE seo_site_advisor_assignments SET active=false WHERE id=3",
    "UPDATE distribution_controls SET state='paused'",
])
def test_authority_change_during_render_discards_result(monkeypatch,sql):
    async def scenario():
        async with environment(monkeypatch) as f:
            async def changed():await update(f,sql)
            f.renderer.callback=changed
            await api.execute_page_capture(f.capture_id)
            assert f.renderer.calls==1
            async with f.sessions() as db:
                row=await db.get(SeoPageCapture,f.capture_id)
                assert row.status==('pending' if 'distribution_controls' in sql else 'failed')
                assert row.sha256 is None and row.storage_key is None
                if 'distribution_controls' in sql:
                    assert jobs.metadata(row)['attempts']==0 and not jobs.metadata(row)['terminal']
            if 'distribution_controls' in sql:
                f.renderer.callback=None
                await update(f,"UPDATE distribution_controls SET state='running'")
                await jobs.run_publication_captures()
                assert f.renderer.calls==2 and (await monitor(f))['state']=='captured'
                async with f.sessions() as db:
                    assert await counts(db)==(1,1,1)
                    assert jobs.metadata(await db.get(SeoPageCapture,f.capture_id))['attempts']==1
    asyncio.run(scenario())


@pytest.mark.parametrize('waiting',['retry','lease','legacy-lease'])
def test_due_filter_precedes_batch_limit_so_waiting_rows_cannot_starve_new_work(monkeypatch,waiting):
    async def scenario():
        async with environment(monkeypatch) as f:
            now=datetime.now(timezone.utc)
            captured=now-timedelta(seconds=1 if waiting=='legacy-lease' else 86400)
            warnings={jobs.META:{'attempts':1,'terminal':False,
                'next_attempt_at':jobs.now_ms()+300000 if waiting=='retry' else None,
                'lease_until':jobs.now_ms()+300000 if waiting=='lease' else None}}
            if waiting=='legacy-lease': warnings={}
            async with f.sessions.begin() as db:
                original=await db.get(SeoPageCapture,f.capture_id)
                original.status='failed' if waiting=='retry' else 'running'
                original.error_code='timeout' if waiting=='retry' else None
                original.warnings=warnings;original.captured_at=captured
                for i in range(20):
                    last=i==19
                    row=SeoPageCapture(tenant_id=4,site_id=2,relation_type='publication',relation_id=f.publication_id,
                        source_url=original.source_url,source='auto',status='pending' if last else original.status,
                        error_code=None if last else original.error_code,captured_at=now if last else captured,
                        warnings={} if last else warnings,redirect_chain=[],viewport_width=800,viewport_height=600)
                    db.add(row)
                await db.flush();due_id=row.id
            stats=await jobs.run_publication_captures()
            assert stats['checked']==1 and f.renderer.calls==1
            async with f.sessions() as db:
                assert (await db.get(SeoPageCapture,due_id)).status=='succeeded'
                assert (await db.get(SeoPageCapture,f.capture_id)).status==original.status
    asyncio.run(scenario())


@pytest.mark.parametrize('value',['not-a-number',[1,2],{},1.25,10**30])
def test_malformed_due_metadata_cannot_break_sql_or_block_eligible_work(monkeypatch,value):
    async def scenario():
        async with environment(monkeypatch) as f:
            await update(f,'UPDATE seo_page_captures SET warnings=CAST(:data AS jsonb)',
                {'data':json.dumps({jobs.META:{'next_attempt_at':value,'lease_until':value}})})
            stats=await jobs.run_publication_captures()
            assert stats['state']=='ready' and f.renderer.calls==1
            assert (await monitor(f))['state']=='captured'
    asyncio.run(scenario())


def test_post_render_database_gate_error_removes_actual_artifact_and_recovers(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            actual=jobs.gate;calls=0
            async def unavailable_after_render(*args,**kwargs):
                nonlocal calls
                calls+=1
                if calls==3: raise SQLAlchemyError('synthetic gate database failure')
                return await actual(*args,**kwargs)
            monkeypatch.setattr(jobs,'gate',unavailable_after_render)
            artifact=Path(get_settings().seo_page_capture_storage_dir)/('a'*32+'.png')
            async def rendered():artifact.write_bytes(b'synthetic artifact')
            f.renderer.callback=rendered
            assert await jobs.run_capture(f.capture_id)=='unavailable'
            assert not artifact.exists()
            async with f.sessions() as db:
                row=await db.get(SeoPageCapture,f.capture_id)
                assert row.status=='running' and row.storage_key is None
            monkeypatch.setattr(jobs,'gate',actual)
            await update(f,"UPDATE seo_page_captures SET warnings=jsonb_set(warnings,'{_publication_dispatch,lease_until}','1')")
            await jobs.run_publication_captures()
            assert f.renderer.calls==2 and (await monitor(f))['state']=='captured'
    asyncio.run(scenario())


def test_second_native_automatic_capture_is_also_recovered_after_interruption(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            await api.execute_page_capture(f.capture_id)
            await update(f,"UPDATE seo_page_captures SET captured_at=clock_timestamp()-interval '120 seconds'")
            async with f.sessions() as db:
                queued=await api.create_page_capture(api.CaptureCreate(tenant_id=4,site_id=2,
                    relation_type='publication',relation_id=f.publication_id),BackgroundTasks(),db,ADVISOR)
            assert queued['id']!=f.capture_id
            started=asyncio.Event()
            async def crash(): started.set();await asyncio.Event().wait()
            f.renderer.callback=crash
            worker=asyncio.create_task(api.execute_page_capture(queued['id']))
            await asyncio.wait_for(started.wait(),5);worker.cancel()
            with pytest.raises(asyncio.CancelledError):await worker
            await update(f,"UPDATE seo_page_captures SET warnings=jsonb_set(warnings,'{_publication_dispatch,lease_until}','1') WHERE id=:id",{'id':queued['id']})
            f.renderer.callback=None
            await jobs.run_publication_captures()
            async with f.sessions() as db:
                assert (await db.get(SeoPageCapture,queued['id'])).status=='succeeded'
                assert await counts(db)==(1,1,2)
            assert (await monitor(f))['evidence_id']==queued['id'] and f.renderer.calls==3
    asyncio.run(scenario())


@pytest.mark.parametrize('management',['disabled','ended'])
def test_management_stop_during_render_is_a_hold_without_failure_budget(monkeypatch,management):
    async def scenario():
        async with environment(monkeypatch) as f:
            async def stop():
                if management=='disabled': monkeypatch.setattr(get_settings(),'seo_external_actions_enabled',False)
                else: await update(f,"UPDATE distribution_controls SET state='ended'")
            f.renderer.callback=stop
            await api.execute_page_capture(f.capture_id)
            value=await monitor(f)
            assert value['state']=='pending' and value['observed_at'] is None
            async with f.sessions() as db:
                meta=jobs.metadata(await db.get(SeoPageCapture,f.capture_id))
                assert meta['attempts']==0 and meta['terminal'] is False
            await jobs.run_publication_captures()
            assert f.renderer.calls==1
            if management=='disabled':
                monkeypatch.setattr(get_settings(),'seo_external_actions_enabled',True)
                f.renderer.callback=None
                await jobs.run_publication_captures()
                assert f.renderer.calls==2 and (await monitor(f))['state']=='captured'
    asyncio.run(scenario())


@pytest.mark.parametrize('pool_size',[1,2])
def test_small_pool_many_entrypoints_do_not_self_block_and_busy_rows_recover(monkeypatch,pool_size):
    async def scenario():
        async with environment(monkeypatch) as f:
            async with f.sessions.begin() as db:
                schema_name=await db.scalar(text('SELECT current_schema()'))
                primary=await db.get(SeoPageCapture,f.capture_id)
                ids=[f.capture_id]
                for _ in range(7):
                    row=SeoPageCapture(tenant_id=4,site_id=2,relation_type='publication',relation_id=f.publication_id,
                        source_url=primary.source_url,status='pending',source='auto',captured_at=datetime.now(timezone.utc),
                        warnings={},redirect_chain=[],viewport_width=800,viewport_height=600)
                    db.add(row);await db.flush();ids.append(row.id)
            assert schema_name.startswith('seo_workflow_test_')
            label='capture-pool-'+schema_name[-32:]
            engine=create_async_engine(f.sessions.kw['bind'].url,pool_size=pool_size,max_overflow=0,pool_timeout=0.5,
                connect_args={'server_settings':{'search_path':schema_name,'application_name':label}})
            small=async_sessionmaker(engine,expire_on_commit=False)
            monkeypatch.setattr(jobs,'async_session_factory',small)
            rendering_pid=ContextVar('rendering_pid')
            original_worker=api._execute_page_capture
            async def tracked_worker(*args,sessions=None,**kwargs):
                raw=await sessions.kw['bind'].get_raw_connection()
                token=rendering_pid.set(raw.driver_connection.get_server_pid())
                try:return await original_worker(*args,sessions=sessions,**kwargs)
                finally:rendering_pid.reset(token)
            monkeypatch.setattr(api,'_execute_page_capture',tracked_worker)
            async def observe():
                async with f.sessions() as db:
                    states=(await db.execute(text('SELECT state FROM pg_stat_activity WHERE application_name=:name AND pid=:pid'),
                        {'name':label,'pid':rendering_pid.get()})).scalars().all()
                    assert states==['idle']
                await asyncio.sleep(0.04)
            f.renderer.callback=observe
            try:
                states=await asyncio.wait_for(asyncio.gather(*(jobs.run_capture(i) for i in ids)),5)
                assert states.count('busy')==6 and states.count('succeeded')==2
                assert f.renderer.calls==2
                await asyncio.wait_for(jobs.run_publication_captures(),5)
                assert f.renderer.calls==8
                async with f.sessions() as db:
                    assert await counts(db)==(1,1,8)
                    assert await db.scalar(text("SELECT count(*) FROM seo_page_captures WHERE status='succeeded'"))==8
            finally:
                await engine.dispose()
    asyncio.run(scenario())


@pytest.mark.parametrize('legacy_partial',[False,True])
def test_third_attempt_pause_commit_then_crash_refunds_once_and_resumes(monkeypatch,legacy_partial):
    async def scenario():
        async with environment(monkeypatch) as f:
            original=api._execute_page_capture
            if legacy_partial:
                await update(f,"UPDATE seo_page_captures SET status='pending',error_code='project_paused',warnings=CAST(:meta AS jsonb)",
                    {'meta':json.dumps({jobs.META:{'attempts':3,'token':'legacy-unsettled-token','terminal':False}})})
                await update(f,"UPDATE distribution_controls SET state='paused'")
            else:
                await update(f,"UPDATE seo_page_captures SET status='failed',error_code='timeout',warnings=CAST(:meta AS jsonb)",
                    {'meta':json.dumps({jobs.META:{'attempts':2,'next_attempt_at':1,'terminal':False}})})
                async def pause():await update(f,"UPDATE distribution_controls SET state='paused'")
                f.renderer.callback=pause
                async def crash_after_committed_pause(*args,**kwargs):
                    await original(*args,**kwargs)
                    raise asyncio.CancelledError()
                monkeypatch.setattr(api,'_execute_page_capture',crash_after_committed_pause)
                with pytest.raises(asyncio.CancelledError): await jobs.run_capture(f.capture_id)
                monkeypatch.setattr(api,'_execute_page_capture',original)
            for _ in range(3):
                assert await jobs.run_capture(f.capture_id)=='paused'
                async with f.sessions() as db:
                    row=await db.get(SeoPageCapture,f.capture_id);meta=jobs.metadata(row)
                    assert row.status=='pending' and meta['attempts']==2 and meta['token'] is None and not meta['terminal']
            await update(f,"UPDATE distribution_controls SET state='running'")
            f.renderer.callback=None
            assert await jobs.run_capture(f.capture_id)=='succeeded'
            async with f.sessions() as db:
                assert jobs.metadata(await db.get(SeoPageCapture,f.capture_id))['attempts']==3
                assert await counts(db)==(1,1,1)
            assert f.renderer.calls==(1 if legacy_partial else 2)
    asyncio.run(scenario())


def test_missing_central_structure_and_runtime_disable_do_not_execute(monkeypatch):
    async def scenario():
        async with environment(monkeypatch,central=False) as f:
            assert (await jobs.run_publication_captures())['state']=='unavailable'
            assert (await monitor(f))['state']=='unavailable'
            await api.execute_page_capture(f.capture_id)
            assert f.renderer.calls==0
        async with environment(monkeypatch) as f:
            monkeypatch.setattr(get_settings(),'seo_external_actions_enabled',False)
            assert (await jobs.run_publication_captures())['state']=='disabled'
            await api.execute_page_capture(f.capture_id)
            assert f.renderer.calls==0
    asyncio.run(scenario())


def test_live_latest_manual_failed_and_no_capture_results(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            await api.execute_page_capture(f.capture_id)
            async with f.sessions.begin() as db:
                row=SeoPageCapture(tenant_id=4,site_id=2,relation_type='publication',relation_id=f.publication_id,
                    source_url='https://mp.weixin.qq.com/s/synthetic_article',status='succeeded',source='manual',uploaded_by=7,
                    uploaded_at=datetime.now(timezone.utc),captured_at=datetime.now(timezone.utc)+timedelta(seconds=1),
                    redirect_chain=[],warnings={},sha256='b'*64,storage_key='b'*32+'.png',viewport_width=800,viewport_height=600)
                db.add(row)
            value=await monitor(f)
            assert value['state']=='captured' and value['evidence_source']=='manual' and value['evidence_id']==row.id
            await update(f,"UPDATE seo_page_captures SET status='failed',error_code='timeout',http_status=503 WHERE id=:id",{'id':row.id})
            assert (await monitor(f))['state']=='failed'
            await update(f,"UPDATE seo_page_captures SET source_url='https://example.com/changed' WHERE id=:id",{'id':row.id})
            assert (await monitor(f))['state']=='mismatch'
            # Unrelated site's newer record must never win the lookup.
            await update(f,"UPDATE seo_page_captures SET site_id=9 WHERE id=:id",{'id':row.id})
            assert (await monitor(f))['evidence_id']==f.capture_id
    asyncio.run(scenario())


def test_read_has_no_flush_safe_missing_columns_and_real_jwt_scope(monkeypatch):
    async def scenario():
        async with environment(monkeypatch) as f:
            async with f.sessions() as db:
                actor=await db.get(User,7);token=issue_token(actor);actor.is_active=False
                value=await results.publication_monitor_status(db,7,4,2,f.publication_id)
                assert value['state']=='pending' and await db.scalar(text('SELECT is_active FROM users WHERE id=7')) is True
                await db.rollback()
            app=FastAPI()
            async def sessions():
                async with f.sessions() as db: yield db
            app.dependency_overrides[get_session]=sessions
            @app.get('/test-read')
            async def read(tenant_id:int=4,site_id:int=2,ctx=Depends(require_auth),db=Depends(get_session)):
                return await results.publication_monitor_status(db,ctx.user_id,tenant_id,site_id,f.publication_id)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://synthetic') as client:
                headers={'Authorization':'Bearer '+token}
                assert (await client.get('/test-read',headers=headers)).status_code==200
                assert (await client.get('/test-read',headers=headers,params={'tenant_id':9})).status_code==403
                assert (await client.get('/test-read')).status_code in {401,403}
                await update(f,"UPDATE roles SET permissions='{}' WHERE id=5")
                assert (await client.get('/test-read',headers=headers)).status_code==403
            await update(f,"UPDATE roles SET permissions='{"+'"seo.content":"edit","seo.site":"edit"'+"}' WHERE id=5")
            await update(f,'ALTER TABLE seo_page_captures DROP COLUMN http_status')
            async with f.sessions() as db:
                assert (await results.publication_monitor_status(db,7,4,2,f.publication_id))['state']=='unavailable'
                assert await db.scalar(text('SELECT 1'))==1
    asyncio.run(scenario())
