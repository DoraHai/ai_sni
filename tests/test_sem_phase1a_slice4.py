"""Slice4 local synthetic contracts and existing-CI-only native PostgreSQL."""
import asyncio
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.sem_phase1a.contracts import ApplyRequest
from app.sem_phase1a.errors import ShadowError
from app.sem_phase1a.postgres_store import SQLAlchemyShadowStore, _Records
from app.sem_phase1a.principals import SessionIdentity, principal_dependency
from app.sem_phase1a.service import ShadowService
from app.sem_phase0.store import ScopeDenied
from test_sem_phase1a_slice2 import env, auth_db, adapter, client, principal, generated, ROOT
from test_sem_phase1a_slice3 import migrate


def migrate4(db):
    spec = importlib.util.spec_from_file_location('slice4_migration',
        Path('migrations/versions/0078_sem_phase1a_grants.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(db)):
        module.upgrade()


def base_tables(db):
    for name in ('users', 'tenants', 'advisor_tenant_grants'):
        db.execute(text('CREATE TABLE '+name+'(id BIGINT PRIMARY KEY)'))
    db.execute(text('CREATE TABLE baidu_accounts(id INTEGER PRIMARY KEY,tenant_id BIGINT NOT NULL)'))
    db.execute(text('INSERT INTO users VALUES(1),(2)'))
    db.execute(text('INSERT INTO tenants VALUES(101),(102)'))
    db.execute(text('INSERT INTO baidu_accounts VALUES(201,101),(202,102)'))
    db.execute(text('INSERT INTO advisor_tenant_grants VALUES(10)'))


@pytest.mark.parametrize('statement', [
    'INSERT INTO sem_phase1a_account_grants(user_id,tenant_id,account_id) VALUES(2,102,201)',
    'UPDATE sem_phase1a_account_grants SET tenant_id=102 WHERE user_id=1',
    'UPDATE sem_phase1a_account_grants SET account_id=202 WHERE user_id=1',
    'UPDATE baidu_accounts SET tenant_id=102 WHERE id=201',
])
def test_sqlite_migration_rejects_cross_tenant_binding(tmp_path, statement):
    engine = create_engine('sqlite:///'+str(tmp_path/'integrity.sqlite'))
    with engine.begin() as db:
        db.exec_driver_sql('PRAGMA foreign_keys=ON')
        base_tables(db); migrate(db); migrate4(db)
        db.execute(text('INSERT INTO sem_phase1a_account_grants(user_id,tenant_id,account_id) VALUES(1,101,201)'))
    with pytest.raises(IntegrityError):
        with engine.begin() as db:
            db.execute(text(statement))
    with engine.connect() as db:
        assert db.execute(text('SELECT generation FROM sem_phase1a_account_grants')).scalar_one() == 0
    engine.dispose()


def test_migration_refuses_dirty_existing_binding_and_downgrade(tmp_path):
    engine = create_engine('sqlite:///'+str(tmp_path/'dirty.sqlite'))
    with engine.begin() as db:
        base_tables(db); migrate(db)
        db.execute(text('INSERT INTO sem_phase1a_account_grants(user_id,tenant_id,account_id) VALUES(1,102,201)'))
    with pytest.raises(RuntimeError, match='完整性'):
        with engine.begin() as db:
            migrate4(db)
    engine.dispose()
    spec = importlib.util.spec_from_file_location('slice4_down','migrations/versions/0078_sem_phase1a_grants.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match='downgrade'):
        module.downgrade()


def test_sqlalchemy_sqlite_cleanup_waits_for_apply_transaction(env, tmp_path):
    engine = create_engine('sqlite:///'+str(tmp_path/'cleanup.sqlite'))
    with engine.begin() as db:
        migrate(db)
    service = ShadowService(env[0],SQLAlchemyShadowStore(engine.begin))
    state = generated(service)
    preview = service.preview(principal(),state['plan_id'],service.export(principal(),state['plan_id'],'advisor'),'advisor')
    entered, finished = threading.Event(),threading.Event()
    def clean():
        entered.set()
        result = service.store.cleanup_previews(preview['expires_at']+1)
        finished.set()
        return result
    with ThreadPoolExecutor(max_workers=1) as pool:
        with service.store.transaction() as tx:
            tx.plans.get(state['plan_id'])
            pending = tx.previews.get(preview['preview_id'])
            future = pool.submit(clean)
            assert entered.wait(5) and not finished.wait(.1)
            pending['preview']['applied'] = True
        assert future.result(timeout=10) == 1
    engine.dispose()


@pytest.mark.parametrize('write', [True, False])
def test_api_scope_denied_read_write_fixed_messages(env,auth_db,monkeypatch,write):
    service = env[1]
    def fail(*args):
        raise ScopeDenied('never-echo-untrusted')
    monkeypatch.setattr(service,'create' if write else 'read',fail)
    api = client(service,dependency=principal_dependency(adapter(auth_db),lambda: SessionIdentity(1,'advisor',101,10)))
    response = (api.post(ROOT,json={'tenant_id':101,'account_id':201,'page_id':'synthetic-page','submission_revision':1})
                if write else api.get(ROOT+'/missing'))
    assert response.status_code == 403 and 'never-echo' not in response.text
    assert response.json()['detail']['message'] == ('无该租户账户的顾问提交权限' if write else '无该租户账户的读取权限')


def test_new_management_business_errors_are_shadow_errors():
    from app.sem_phase1a.grant_management import GrantError
    with pytest.raises(ShadowError) as caught:
        raise GrantError('GRANT_ADMIN_REQUIRED',403)
    assert caught.value.code == 'GRANT_ADMIN_REQUIRED'


def test_preview_read_scope_denied_before_reading_attachment(env,auth_db,monkeypatch):
    from starlette.datastructures import UploadFile
    service = env[1]
    def denied(*args):
        raise ScopeDenied('never-echo-untrusted')
    async def unexpected_read(*args):
        pytest.fail('attachment must not be read before account permission check')
    monkeypatch.setattr(service,'read',denied)
    monkeypatch.setattr(UploadFile,'read',unexpected_read)
    api = client(service,dependency=principal_dependency(adapter(auth_db),lambda: SessionIdentity(1,'advisor',101,10)))
    response = api.post(ROOT+'/missing/previews/advisor',files={'file':('internal.xlsx',b'never-echo-untrusted')})
    assert response.status_code == 403
    assert response.json() == {'detail':{'code':'SCOPE_DENIED','message':'无该租户账户的读取权限'}}
    assert 'never-echo' not in response.text


def test_postgres_slice4_cleanup_locked_apply_and_database_tenant_constraint(tmp_path,monkeypatch,capfd):
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.util.concurrency import await_only
    from app.sem_phase0.store import SubmissionStore
    from test_sem_phase1a_slice2 import payload
    url = os.environ.get('SEM_ALERT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('native PostgreSQL runs only on existing disposable CI service')
    parsed = make_url(url)
    assert parsed.drivername == 'postgresql+asyncpg'
    assert parsed.host in {'127.0.0.1','localhost'} and parsed.database == 'sem_writeback_test'
    schema = 'sem_phase1a_slice4_'+uuid4().hex
    submissions = SubmissionStore(tmp_path/'submissions.sqlite')
    submissions.submit(principal(),payload(),[])
    async def run():
        engine = create_async_engine(url,connect_args={'server_settings':{'search_path':schema,'statement_timeout':'15000'}})
        async with engine.begin() as db:
            await db.execute(text('CREATE SCHEMA '+schema))
            await db.run_sync(base_tables)
            await db.run_sync(migrate)
            await db.run_sync(migrate4)
            await db.execute(text('INSERT INTO sem_phase1a_account_grants(user_id,tenant_id,account_id) VALUES(1,101,201)'))
        for statement in (
            'INSERT INTO sem_phase1a_account_grants(user_id,tenant_id,account_id) VALUES(2,102,201)',
            'UPDATE sem_phase1a_account_grants SET tenant_id=102 WHERE user_id=1',
            'UPDATE sem_phase1a_account_grants SET account_id=202 WHERE user_id=1',
            'UPDATE baidu_accounts SET tenant_id=102 WHERE id=201',
        ):
            with pytest.raises(IntegrityError):
                async with engine.begin() as db:
                    await db.execute(text(statement))
        async with engine.connect() as db:
            assert (await db.execute(text('SELECT user_id,tenant_id,account_id,generation FROM sem_phase1a_account_grants'))).all() == [(1,101,201,0)]
        store = SQLAlchemyShadowStore(engine.sync_engine.begin)
        service = ShadowService(submissions,store)
        async def operation(fn):
            async with engine.connect() as db:
                return await db.run_sync(lambda _: fn())
        state = await operation(lambda: generated(service))
        pid = state['plan_id']
        data = await operation(lambda: service.export(principal(),pid,'advisor'))
        preview = await operation(lambda: service.preview(principal(),pid,data,'advisor'))
        spare = await operation(lambda: service.preview(principal(),pid,data,'advisor'))
        locked, release = asyncio.Event(),asyncio.Event()
        original = _Records.get
        def holding_get(self,key):
            result = original(self,key)
            if self.table.endswith('previews') and key == preview['preview_id'] and not release.is_set():
                locked.set()
                await_only(release.wait())
            return result
        with monkeypatch.context() as patch:
            patch.setattr(_Records,'get',holding_get)
            task = asyncio.create_task(operation(lambda: service.apply(principal(),pid,
                ApplyRequest(expected_version=2,preview_id=preview['preview_id']))))
            try:
                await asyncio.wait_for(locked.wait(),10)
                assert await asyncio.wait_for(operation(lambda:store.cleanup_previews(preview['expires_at']+2)),5) == 1
                # Held preview survives; a different expired preview is reclaimed.
                async with engine.connect() as db:
                    ids = set((await db.execute(text('SELECT id FROM sem_phase1a_shadow_previews'))).scalars())
                    assert preview['preview_id'] in ids and spare['preview_id'] not in ids
            finally:
                release.set()
            applied = await asyncio.wait_for(task,10)
            assert applied['version'] == 3
        assert await operation(lambda:store.cleanup_previews(preview['expires_at']+2)) == 1
        assert (await operation(lambda:service.read(principal(),pid)))['version'] == 3
        await engine.dispose()
    asyncio.run(run())
    # Visible evidence even under the existing CI's pytest -q capture settings.
    with capfd.disabled():
        print('SLICE4_NATIVE_PG_EXECUTED: cleanup_locked_apply + composite_tenant_fk PASS',flush=True)
