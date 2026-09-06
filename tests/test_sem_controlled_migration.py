"""Controlled runner tests; native tests create only disposable loopback databases."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("controlled_test", ROOT / 'ops/sem-task-migration/controlled.py')
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)


def approval():
    now = datetime.now(timezone.utc)
    a = {k: 'a' * 40 for k in ('checkout_commit', 'seo_release_commit', 'seo_rollback_commit')}
    a.update({k: 'b' * 64 for k in ('manifest_sha256','baseline_sha256','schema_sha256',
                                  'seo_release_sha256','seo_rollback_sha256')})
    a.update({k: 'test-evidence' for k in ('change_id','operator','reviewer','backup_evidence',
             'restore_evidence','pause_evidence','seo_compatibility_evidence','schema_review_evidence')})
    a.update(confirmation='MIGRATE_SEM_TASKS_0095', schema='public', start_revision=ctl.bundle.START,
             target_revision=ctl.bundle.TARGET, application_role='sem_test',
             not_before=(now-timedelta(minutes=1)).isoformat(), expires_at=(now+timedelta(minutes=10)).isoformat(),
             database=dict(host='127.0.0.1', port=55449, name='test-only', role='sem_test',
                           server_address='127.0.0.1', server_port=55449))
    return a


@pytest.mark.parametrize('key,value', [
    ('target_revision','head'), ('start_revision','0093_seo_qa'), ('schema','other'),
    ('confirmation','DEPLOY_SEM'), ('checkout_commit','main'), ('manifest_sha256',''),
    ('backup_evidence',''), ('restore_evidence','UNKNOWN'), ('pause_evidence','TBD'),
    ('application_role','different_role'), ('expires_at','2000-01-01T00:00:00+00:00'),
    ('not_before','2099-01-01T00:00:00+00:00'), ('expires_at','2099-01-01T00:00:00'),
])
def test_refuses_unapproved_contract(key,value):
    a=approval(); a[key]=value
    with pytest.raises((ValueError, KeyError)):
        ctl.validate_approval(a)


def test_accepts_complete_attestation_not_proof_of_external_actions():
    ctl.validate_approval(approval())


def test_baseline_digest_cannot_be_silently_replaced(tmp_path):
    p=tmp_path/'baseline.json'; p.write_text('{}')
    with pytest.raises(ValueError): ctl.checked_json(p,'0'*64)


def test_checkout_must_match_and_be_clean(monkeypatch):
    monkeypatch.setattr(ctl.subprocess,'check_output',lambda *a,**k:b'wrong')
    with pytest.raises(ValueError): ctl.verify_checkout('a'*40)


@pytest.mark.parametrize('commit_error',[False,True])
def test_commit_acknowledgement_is_not_assumed(monkeypatch,commit_error):
    import sqlalchemy.ext.asyncio as sa_async
    class Tx:
        async def __aenter__(self): return object()
        async def __aexit__(self,*args):
            if commit_error: raise ConnectionError('simulated lost commit reply')
    class Engine:
        def begin(self): return Tx()
        async def dispose(self): pass
    monkeypatch.setattr(sa_async,'create_async_engine',lambda *a,**k:Engine())
    monkeypatch.setattr(ctl,'migrate_transaction',AsyncMock())
    phases=[]
    if commit_error:
        with pytest.raises(ConnectionError): asyncio.run(ctl.apply(approval(),{},None,None,phases.append))
        assert phases==['transaction_started','ready_to_commit']
    else:
        asyncio.run(ctl.apply(approval(),{},None,None,phases.append))
        assert phases==['transaction_started','ready_to_commit','commit_acknowledged']


def test_credentials_are_not_taken_from_application_environment():
    source=(ROOT/'ops/sem-task-migration/controlled.py').read_text(encoding='utf-8')
    assert 'os.environ' not in source
    assert 'os.O_NOFOLLOW' in source and 'ssl.create_default_context()' in source
    assert 'choices=["fingerprint", "check", "apply"]' in source
    assert 'command.upgrade(cfg, bundle.TARGET)' in source
    assert 'command.stamp' not in source and 'command.downgrade' not in source


@pytest.mark.parametrize('url',[
    'postgresql+asyncpg://sem_test:fake@other:55449/test-only',
    'postgresql+asyncpg://sem_test:fake@127.0.0.1:55449/other',
    'postgresql+asyncpg://other:fake@127.0.0.1:55449/test-only',
    'postgresql+asyncpg://sem_test@127.0.0.1:55449/test-only',
    'postgresql+asyncpg://sem_test:fake@127.0.0.1:55449/test-only?ssl=disable',
])
def test_connection_override_refused(url):
    with pytest.raises(ValueError): ctl.validate_url(url,approval())


@pytest.mark.skipif(os.name!='posix',reason='production adapter is POSIX-only')
def test_credential_file_permissions_and_links(tmp_path):
    p=tmp_path/'credential'
    p.write_text('postgresql+asyncpg://sem_test:fake@127.0.0.1:55449/test-only')
    p.chmod(0o644)
    with pytest.raises(ValueError): ctl.credential_url(p,approval())
    p.chmod(0o600)
    assert ctl.credential_url(p,approval()).username=='sem_test'
    link=tmp_path/'link'; link.symlink_to(p)
    with pytest.raises(OSError): ctl.credential_url(link,approval())


@pytest.fixture(scope='module')
def native_bundle(tmp_path_factory):
    url=os.environ.get('SEM_TASK_MIGRATION_TEST_DATABASE_URL')
    if not url: pytest.skip('explicit disposable loopback PostgreSQL required')
    ctl.bundle.validate_local_url(url,'sem_migration_test_'+'a'*32)
    dest=tmp_path_factory.mktemp('controlled-source')/'bundle'
    r=subprocess.run([sys.executable,'-I','-B',str(ROOT/'ops/sem-task-migration/bundle.py'),
                      'build',str(dest)],capture_output=True,text=True)
    assert r.returncode==0, r.stderr
    return dest


@pytest.mark.parametrize('scenario',['success','repeat','drift','wrong_revision','collision','after_create_failure','identity'])
def test_controlled_native_transaction(native_bundle,scenario):
    r=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),str(native_bundle),scenario],
                     capture_output=True,text=True,timeout=45)
    assert r.returncode==0,r.stdout+r.stderr
    assert 'controlled-native=passed' in r.stdout


async def native(path,scenario):
    from sqlalchemy import text, event
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    url=ctl.bundle.validate_local_url(os.environ['SEM_TASK_MIGRATION_TEST_DATABASE_URL'],
                                      'sem_migration_test_'+'a'*32)
    dbname='sem_controlled_test_'+uuid.uuid4().hex
    admin=create_async_engine(url,poolclass=NullPool,isolation_level='AUTOCOMMIT')
    created=False; engine=None
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{dbname}"'))
            created=True
        engine=create_async_engine(url.set(database=dbname),poolclass=NullPool,hide_parameters=True)
        async with engine.begin() as conn:
            await conn.execute(text('CREATE TABLE public.tenants(id BIGINT PRIMARY KEY, name TEXT)'))
            await conn.execute(text("INSERT INTO public.tenants VALUES (9007199254740993,'preserve')"))
            await conn.execute(text('CREATE TABLE public.alembic_version(version_num VARCHAR(32) PRIMARY KEY)'))
            await conn.execute(text("INSERT INTO public.alembic_version VALUES ('0094_seo_qa_batches')"))
        async with engine.begin() as conn:
            await conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            await conn.execute(text('SET LOCAL search_path=pg_catalog,public,pg_temp'))
            baseline=await ctl.snapshot(conn)
        a=approval(); a['database'].update(name=dbname,role=url.username,port=url.port,
                                          server_address=baseline['server_address'],server_port=baseline['server_port'])
        a['application_role']=url.username
        a['schema_sha256']=ctl.sha(ctl.canonical(ctl.structural(baseline)))
        ctl.validate_approval(a); ctl.checked_baseline(a,baseline)
        cfg=ctl.configuration(path)
        if scenario in ('drift','wrong_revision','collision'):
            async with engine.begin() as conn:
                sql={'drift':'ALTER TABLE public.tenants ADD COLUMN extra TEXT',
                     'wrong_revision':"UPDATE public.alembic_version SET version_num='0093_seo_qa'",
                     'collision':'CREATE SEQUENCE public.sem_tasks_id_seq'}[scenario]
                await conn.execute(text(sql))
        if scenario=='identity': a['database']['name']='wrong'
        if scenario=='after_create_failure':
            def fault(c,cu,statement,p,ctx,many):
                if statement.startswith('CREATE INDEX ix_sem_tasks_'):
                    raise RuntimeError('test-injected-after-create')
            event.listen(engine.sync_engine,'before_cursor_execute',fault)
        failed=False
        try:
            async with engine.begin() as conn:
                await ctl.migrate_transaction(conn,cfg,a,baseline)
        except (ValueError,RuntimeError) as e:
            failed=True
            if scenario=='after_create_failure': assert str(e)=='test-injected-after-create'
        assert failed == (scenario not in ('success','repeat'))
        if scenario=='repeat':
            with pytest.raises(ValueError):
                async with engine.begin() as conn: await ctl.migrate_transaction(conn,cfg,a,baseline)
        async with engine.connect() as conn:
            assert await conn.scalar(text('SELECT name FROM public.tenants'))=='preserve'
            assert await conn.scalar(text('SELECT version_num FROM public.alembic_version')) == (
                ctl.bundle.TARGET if not failed else '0093_seo_qa' if scenario=='wrong_revision' else ctl.bundle.START)
            assert bool(await conn.scalar(text("SELECT to_regclass('public.sem_tasks')"))) == (not failed)
            if scenario=='after_create_failure':
                for name in ctl.TARGETS:
                    assert await conn.scalar(text('SELECT to_regclass(:n)'),{'n':'public.'+name}) is None
            if not failed:
                await conn.execute(text('SET LOCAL search_path=pg_catalog,public,pg_temp'))
                after=await ctl.snapshot(conn)
                for category in ('columns','constraints','indexes'):
                    broken=deepcopy(after)
                    broken[category]=[r for r in broken[category] if r['relname']!='sem_tasks']
                    with pytest.raises(ValueError): ctl.postconditions(a,baseline,broken)
        print('controlled-native=passed')
    finally:
        if engine: await engine.dispose()
        if created:
            # This freshly-created random test DB is the ONLY drop target.
            assert dbname.startswith('sem_controlled_test_') and len(dbname)==52
            async with admin.connect() as conn: await conn.execute(text(f'DROP DATABASE "{dbname}"'))
        await admin.dispose()


if __name__=='__main__':
    asyncio.run(native(sys.argv[1],sys.argv[2]))
