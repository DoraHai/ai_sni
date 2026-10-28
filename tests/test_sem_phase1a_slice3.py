"""Slice3: synthetic authorization, API, migration and transaction regressions."""
import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations
from openpyxl import load_workbook
from sqlalchemy import create_engine, text, inspect

from test_sem_phase1a_slice2 import (auth_db, env, adapter, client, generated, principal, ROOT)
from app.sem_phase0.store import ScopeDenied, RevisionConflict
from app.sem_phase1a.principals import SessionIdentity, LocalGrantPrincipalAdapter, principal_dependency
from app.sem_phase1a.contracts import ApplyRequest, ApprovalRequest, StructureRequest
from app.sem_phase1a.errors import ShadowError
from app.sem_phase1a.service import ShadowService
from app.sem_phase1a.postgres_store import SQLAlchemyShadowStore


def migrate(connection):
    spec = importlib.util.spec_from_file_location('slice3_migration',
        Path('migrations/versions/0077_sem_phase1a_shadow.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


@pytest.mark.parametrize('role,user_id,grant', [('advisor', 1, 10), ('customer', 2, None)])
def test_partial_account_authorization(auth_db, role, user_id, grant):
    with closing(sqlite3.connect(auth_db)) as db, db:
        db.execute("INSERT INTO baidu_accounts VALUES(204,101,'active')")
    who = adapter(auth_db).resolve(SessionIdentity(user_id, role, 101, grant))
    assert who.readable_accounts == frozenset({(101, 201)})
    assert who.writable_accounts == (who.readable_accounts if role == 'advisor' else frozenset())
    from app.sem_phase0.store import check_scope
    check_scope(who, 101, 201, write=False)
    for write in (True, False):
        with pytest.raises(ScopeDenied):
            check_scope(who, 101, 204, write=write)


@pytest.mark.parametrize('sql', [
    "UPDATE users SET role='customer' WHERE id=1",
    "UPDATE users SET role='advisor' WHERE id=2",
    "UPDATE sem_phase1a_account_grants SET revoked_at='2026-10-29'",
    "DELETE FROM sem_phase1a_account_grants",
    "UPDATE sem_phase1a_account_grants SET advisor_grant_id=20 WHERE user_id=1",
    "UPDATE sem_phase1a_account_grants SET tenant_id=102",
    "UPDATE baidu_accounts SET status='archived' WHERE id=201",
])
def test_identity_and_binding_changes_fail_closed(auth_db, sql):
    with closing(sqlite3.connect(auth_db)) as db, db:
        db.execute(sql)
    for identity in (SessionIdentity(1, 'advisor', 101, 10), SessionIdentity(2, 'customer', 101)):
        if 'id=2' in sql and identity.user_id == 1:
            continue
        if 'id=1' in sql and identity.user_id == 2:
            continue
        if 'user_id=1' in sql and identity.user_id == 2:
            continue
        try:
            who = adapter(auth_db).resolve(identity)
        except ScopeDenied:
            continue
        assert not who.readable_accounts and not who.writable_accounts


def test_naive_clock_rejected(auth_db):
    with pytest.raises(ScopeDenied, match='时区'):
        LocalGrantPrincipalAdapter(auth_db, clock=lambda: datetime(2026, 10, 29)).resolve(
            SessionIdentity(1, 'advisor', 101, 10))


def advisor_api(service, auth_db):
    return client(service, dependency=principal_dependency(adapter(auth_db),
        lambda: SessionIdentity(1, 'advisor', 101, 10)))


def test_all_advisor_api_paths_through_auth_adapter(env, auth_db):
    _, service = env
    api = advisor_api(service, auth_db)
    create = {'tenant_id': 101, 'account_id': 201, 'page_id': 'synthetic-page', 'submission_revision': 1}
    state = api.post(ROOT, json=create).json()
    batch = api.post(ROOT + '/batch', json={'tenant_id': 101, 'account_id': 201,
        'pages': [{'page_id': 'synthetic-page', 'submission_revision': 1}]} )
    assert batch.status_code == 201
    pid = state['plan_id']
    response = api.post(f'{ROOT}/{pid}/rulings', json={'expected_version': 1, 'reason': '合成裁定'})
    assert response.status_code == 200
    state = response.json()
    assert api.get(f'{ROOT}/{pid}').status_code == 200
    response = api.post(f'{ROOT}/{pid}/structure', json={'expected_version': 2, 'reason': '合成改名',
        'operations': [{'action': 'update', 'row_id': 'r-2', 'text': '合成方案改名'}]})
    assert response.status_code == 200
    state = response.json()
    data = api.get(f'{ROOT}/{pid}/excel/advisor')
    assert data.status_code == 200
    preview = api.post(f'{ROOT}/{pid}/previews/advisor', files={'file': ('internal.xlsx', data.content)})
    assert preview.status_code == 200
    response = api.post(f'{ROOT}/{pid}/apply-preview', json={'expected_version': 3,
        'preview_id': preview.json()['preview_id']})
    assert response.status_code == 200
    state = response.json()
    response = api.post(f'{ROOT}/{pid}/approvals', json={'expected_version': 4, 'reason': '合成演练逐项复核',
        'row_ids': [r['row_id'] for r in state['rows']]})
    assert response.status_code == 200
    state = response.json()
    assert state['advisor_review_complete'] and not state['executable'] and not state['go_live_allowed']
    assert state['rehearsal_only_blockers'] and '不可执行、不可上线' in state['review_status_label']
    data = api.get(f'{ROOT}/{pid}/excel/customer')
    assert data.status_code == 200
    book = load_workbook(io.BytesIO(data.content))
    assert '不可执行、不可上线' in book['内部规划']['H5'].value
    metadata = dict(book['演练绑定'].values)
    assert metadata['executable'] is False and metadata['go_live_allowed'] is False
    assert json.loads(metadata['rehearsal_only_blockers'])
    book.close()
    preview = api.post(f'{ROOT}/{pid}/previews/customer', files={'file': ('internal.xlsx', data.content)})
    assert preview.status_code == 200 and not preview.json()['executable']
    response = api.post(f'{ROOT}/{pid}/apply-preview', json={'expected_version': 4,
        'preview_id': preview.json()['preview_id']})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'PREVIEW_AUDIENCE_ADVISOR_ONLY'
    assert api.get(f'{ROOT}/{pid}/expiry-suggestions').status_code == 200
    # Every route resolves the same DB identity again, without a cached grant.
    with closing(sqlite3.connect(auth_db)) as db, db:
        db.execute("UPDATE users SET role='customer' WHERE id=1")
    assert api.get(f'{ROOT}/{pid}').status_code == 403


@pytest.mark.parametrize('exception,code,status', [
    (PermissionError('never-echo-untrusted'), 'OPERATION_FORBIDDEN', 403),
    (ValueError('never-echo-untrusted'), 'CONTRACT_INVALID', 422),
    (ShadowError('RULING_REQUIRED', 'never-echo-untrusted'), 'RULING_REQUIRED', 422)])
def test_error_mapping_sanitized(env, auth_db, monkeypatch, exception, code, status):
    _, service = env
    def fail(*args):
        raise exception
    monkeypatch.setattr(service, 'read', fail)
    response = advisor_api(service, auth_db).get(ROOT + '/some-id')
    assert response.status_code == status and response.json()['detail']['code'] == code
    assert 'never-echo' not in response.text


def test_structure_step_indices_and_simultaneous_requests(env, auth_db):
    _, service = env
    state = generated(service)
    api = advisor_api(service, auth_db)
    barrier = threading.Barrier(2)
    def change(label):
        barrier.wait(timeout=10)
        return api.post(f"{ROOT}/{state['plan_id']}/structure", json={'expected_version': 2, 'reason': '合成并发',
            'operations': [{'action': 'update', 'row_id': 'r-2', 'text': label},
                           {'action': 'update', 'row_id': 'r-3', 'text': '合成单元'}]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(change, ['合成一', '合成二']))
    assert sorted(r.status_code for r in responses) == [200, 409]
    events = [e for e in service.read(principal(), state['plan_id'])['audit'] if e['action'] == 'structure_edited']
    assert [e['details']['step_index'] for e in events] == [1, 2]


def test_cleanup_waits_for_transaction_lock(env):
    _, service = env
    state = generated(service)
    preview = service.preview(principal(), state['plan_id'], service.export(principal(), state['plan_id'], 'advisor'), 'advisor')
    entered = threading.Event()
    finished = threading.Event()
    def clean():
        entered.set()
        result = service.store.cleanup_previews(preview['expires_at'] + 1)
        finished.set()
        return result
    with ThreadPoolExecutor(max_workers=1) as pool:
        with service.store.transaction() as tx:
            pending = tx.previews.get(preview['preview_id'])
            future = pool.submit(clean)
            assert entered.wait(5)
            assert not finished.wait(.1)
            pending['preview']['applied'] = True
        assert future.result(timeout=10) == 1
    with service.store.transaction() as tx:
        assert tx.previews.get(preview['preview_id']) is None


def test_unique_migration_head_and_empty_local_upgrade(tmp_path):
    cfg = Config(); cfg.set_main_option('script_location', 'migrations')
    scripts = ScriptDirectory.from_config(cfg)
    assert scripts.get_heads() == ['0077_sem_phase1a_shadow']
    assert scripts.get_revision('0077_sem_phase1a_shadow').down_revision == '0076_oauth_rebind_intent'
    engine = create_engine('sqlite:///' + str(tmp_path / 'migration.sqlite'))
    with engine.begin() as db:
        migrate(db)
        names = inspect(db).get_table_names()
        assert sorted(names) == ['sem_phase1a_account_grants', 'sem_phase1a_shadow_plans', 'sem_phase1a_shadow_previews']
    engine.dispose()


def test_sqlalchemy_store_restart_cas_once_and_rollback(env, tmp_path):
    submissions, _ = env
    engine = create_engine('sqlite:///' + str(tmp_path / 'sqlalchemy.sqlite'))
    with engine.begin() as db:
        migrate(db)
    service = ShadowService(submissions, SQLAlchemyShadowStore(engine.begin))
    state = generated(service)
    exported = service.export(principal(), state['plan_id'], 'advisor')
    preview = service.preview(principal(), state['plan_id'], exported, 'advisor')
    service = ShadowService(submissions, SQLAlchemyShadowStore(engine.begin))
    assert service.read(principal(), state['plan_id'])['version'] == 2
    request = ApplyRequest(expected_version=2, preview_id=preview['preview_id'])
    service.apply(principal(), state['plan_id'], request)
    with pytest.raises(RevisionConflict):
        service.apply(principal(), state['plan_id'], request)
    with pytest.raises(RuntimeError):
        with service.store.transaction() as tx:
            tx.plans.get(state['plan_id'])['version'] = 999
            raise RuntimeError('synthetic failure')
    assert service.read(principal(), state['plan_id'])['version'] == 3
    # Deliberate stale internal revision must fail, leaving all writes rolled back.
    with pytest.raises(RevisionConflict):
        with service.store.transaction() as tx:
            tx.plans.get(state['plan_id'])['version'] = 999
            tx.plans.loaded[state['plan_id']][0] = 999
    assert service.read(principal(), state['plan_id'])['version'] == 3
    # Fail during the second flush, after the plan UPDATE executed: both the
    # plan write and preview consumption must roll back together.
    with pytest.raises(RevisionConflict):
        with service.store.transaction() as tx:
            tx.plans.get(state['plan_id'])['version'] = 999
            pending = tx.previews.get(preview['preview_id'])
            pending['preview']['applied'] = False
            tx.previews.loaded[preview['preview_id']][0] = 999
    assert service.read(principal(), state['plan_id'])['version'] == 3
    with service.store.transaction() as tx:
        assert tx.previews.get(preview['preview_id'])['preview']['applied']
    assert service.store.cleanup_previews(preview['expires_at'] + 1) == 1
    engine.dispose()


def test_real_session_bridge_in_isolated_local_process():
    # Separate interpreter avoids replacing the shared application's database module
    # in the rest of pytest. The runner forbids .env/config/network access.
    result = subprocess.run([sys.executable, '-X', 'utf8', 'tests/sem_phase1a_session_fixture.py'],
                            capture_output=True, text=True, encoding='utf-8', timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'session bridge checks passed' in result.stdout

def test_postgres_existing_ci_service_once_concurrency_and_rollback(tmp_path):
    import asyncio
    import os
    from uuid import uuid4
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.sem_phase0.store import SubmissionStore
    from test_sem_phase1a_slice2 import payload
    url = os.environ.get('SEM_ALERT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('native PostgreSQL runs only on existing disposable CI service')
    parsed = make_url(url)
    assert parsed.drivername == 'postgresql+asyncpg'
    assert parsed.host in {'127.0.0.1', 'localhost'}
    assert parsed.database == 'sem_writeback_test'
    schema = 'sem_phase1a_slice3_' + uuid4().hex
    submissions = SubmissionStore(tmp_path / 'submissions.sqlite')
    submissions.submit(principal(), payload(), [])

    async def run():
        engine = create_async_engine(url, connect_args={'server_settings': {
            'search_path': schema, 'statement_timeout': '15000'}})
        async with engine.begin() as db:
            await db.execute(text('CREATE SCHEMA ' + schema))
            for name in ('users', 'tenants', 'baidu_accounts', 'advisor_tenant_grants'):
                await db.execute(text('CREATE TABLE ' + name + '(id BIGINT PRIMARY KEY)'))
            await db.run_sync(migrate)
        # Use separate pooled connections in independent transactions. run_sync
        # supplies greenlet context for the existing asyncpg CI driver.
        store = SQLAlchemyShadowStore(engine.sync_engine.begin)
        service = ShadowService(submissions, store)
        async def operation(fn):
            async with engine.connect() as db:
                return await db.run_sync(lambda _: fn())
        state = await operation(lambda: generated(service))
        pid = state['plan_id']
        data = await operation(lambda: service.export(principal(), pid, 'advisor'))
        preview = await operation(lambda: service.preview(principal(), pid, data, 'advisor'))
        def apply():
            try:
                service.apply(principal(), pid, ApplyRequest(expected_version=2, preview_id=preview['preview_id']))
                return 'applied'
            except RevisionConflict:
                return 'conflict'
        assert sorted(await asyncio.gather(operation(apply), operation(apply))) == ['applied', 'conflict']
        state = await operation(lambda: service.read(principal(), pid))
        assert state['version'] == 3
        assert len([e for e in state['audit'] if e['action'] == 'advisor_preview_applied']) == 1
        def change():
            try:
                service.edit_structure(principal(), pid, StructureRequest(expected_version=3, reason='synthetic race',
                    operations=[{'action':'update', 'row_id':'r-2', 'text':'synthetic plan'}]))
                return 'edited'
            except RevisionConflict:
                return 'conflict'
        assert sorted(await asyncio.gather(operation(change), operation(change))) == ['conflict', 'edited']
        def rollback():
            with pytest.raises(RuntimeError):
                with store.transaction() as tx:
                    tx.plans.get(pid)['version'] = 999
                    raise RuntimeError('synthetic rollback')
            assert service.read(principal(), pid)['version'] == 4
        await operation(rollback)
        assert await operation(lambda: store.cleanup_previews(preview['expires_at']+1)) == 1
        # The CI service is disposable. No DROP/DELETE of application tables,
        # no production URL and no permissions/role grants are used here.
        await engine.dispose()
    asyncio.run(run())


def test_slice3_demo_evidence(tmp_path):
    from app.sem_phase1a.demo_slice3 import run
    names = run(tmp_path / 'output')
    assert len(names) == 4
    auth = json.loads((tmp_path / 'output/slice3-auth.internal.json').read_text(encoding='utf-8'))
    assert auth['ungranted_active_account_excluded'] and auth['db_session_role_mismatch_denied']
    view = json.loads((tmp_path / 'output/slice3-review.internal.json').read_text(encoding='utf-8'))
    assert view['advisor_review_complete'] and view['rehearsal_only_blockers']
    assert not view['executable'] and not view['go_live_allowed']
