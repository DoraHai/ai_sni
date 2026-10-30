"""Slice5 actual-main matrix and versioned source/attachment PG contracts."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text, event
from sqlalchemy.exc import IntegrityError, DBAPIError

from app.sem_phase0.store import AdvisorPrincipal, AttachmentUnavailable, RevisionConflict, ScopeDenied
from app.sem_phase0.postgres_store import SQLAlchemySubmissionStore, sha, canonical
from app.sem_phase0.screenshots import Screenshot, MAX_IMAGE_BYTES, MAX_IMAGES, MAX_TOTAL_BYTES
from app.sem_phase1a.production import ProductionServices
from app.sem_phase1a.contracts import CreateRequest, RulingRequest
from test_sem_phase1a_slice2 import payload
from test_sem_phase1a_slice3 import migrate
from test_sem_phase1a_slice4 import migrate4, base_tables


STATES = ('inventory','anonymous','empty_1','empty_2','empty_7','empty_8','empty_9','cross_tenant',
          'customer_readonly','unbound_account','scheduler_not_started',
          'attachment_fail_closed','revoked','db_role_changed','new_source_invalidates','closed_routes') + tuple(
          state+'_'+str(uid) for state in ('suspended','closed','expired_trial','expired_active') for uid in (1,2,8,9))


@pytest.fixture(scope='module')
def main_matrix(tmp_path_factory):
    output = tmp_path_factory.mktemp('slice5-matrix')/'results.json'
    result = subprocess.run([sys.executable,'-X','utf8','tests/sem_phase1a_main_fixture.py',str(output)],
                            capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'SLICE5_MAIN_MATRIX_EXECUTED' in result.stdout
    return json.loads(output.read_text(encoding='utf-8'))


MATRIX_STATES = ('anonymous','empty_1','empty_2','empty_7','empty_8','empty_9','cross_tenant',
                 'customer_readonly','revoked','db_role_changed','advisor_bound','admin_8','admin_9') + tuple(
                 state+'_'+str(uid) for state in ('suspended','closed','expired_trial','expired_active') for uid in (1,2,8,9))


@pytest.mark.parametrize('state', MATRIX_STATES)
@pytest.mark.parametrize('endpoint', range(16))
def test_actual_main_all_mounted_endpoint_matrix(main_matrix, state, endpoint):
    expected = 401 if state == 'anonymous' else 403
    if state == 'customer_readonly' and endpoint in (2,9,14,15):
        expected = 200
    if state == 'advisor_bound':
        expected = (403 if endpoint in (10,11,12) else 422 if endpoint == 8
                    else 201 if endpoint in (0,1,13) else 200)
    if state in ('admin_8','admin_9') and endpoint in (10,11,12):
        expected = 200
    assert len(main_matrix[state]) == 16
    assert main_matrix[state][endpoint] == expected


@pytest.mark.parametrize('state', ('first_binding_8','first_binding_9'))
@pytest.mark.parametrize('endpoint', range(3))
def test_actual_main_production_grant_initialization_is_closed(main_matrix, state, endpoint):
    # Fixture verifies fixed error codes and unchanged complete grants/audit snapshots.
    assert len(main_matrix[state]) == 3
    assert main_matrix[state][endpoint] == 403


@pytest.mark.parametrize('state', sorted(set(STATES)-set(MATRIX_STATES)-
                                       {'attachment_fail_closed','new_source_invalidates','closed_routes'}))
def test_actual_main_positive_and_inventory_checks(main_matrix,state):
    assert main_matrix[state] == {'inventory':16,'unbound_account':26,'scheduler_not_started':1}[state]


def test_actual_main_attachment_default_and_new_source_endpoints(main_matrix):
    assert main_matrix['attachment_fail_closed'] == {'status':503,'code':'ATTACHMENT_STORAGE_UNAVAILABLE'}
    assert main_matrix['new_source_invalidates'] == {'source_status':201,'plan_status':409}
    assert set(main_matrix['closed_routes']) == {'execute','upload-to-baidu','enable','customer-confirm','future-write'}
    assert all(status in (403,404) for status in main_matrix['closed_routes'].values())


@pytest.mark.parametrize('endpoint', range(3))
def test_actual_main_management_rechecks_current_db_role(main_matrix, endpoint):
    assert main_matrix['management_db_role_changed'][endpoint] == 403


@pytest.fixture(scope='module')
def main_attachments(tmp_path_factory):
    output = tmp_path_factory.mktemp('slice5-attachments')/'results.json'
    result = subprocess.run([sys.executable,'-X','utf8','tests/sem_phase1a_main_fixture.py',
                             str(output),'--attachment-backend'],
                            capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'SLICE5_MAIN_MATRIX_EXECUTED' in result.stdout
    return json.loads(output.read_text(encoding='utf-8'))


@pytest.mark.parametrize(('operation','status'), [('upload',201),('read_hash',200),('customer_read',200),
                         ('scope_denied',403),('tampered',422),('backend_unavailable',503)])
def test_actual_main_with_injected_private_attachment_backend(main_attachments, operation, status):
    assert main_attachments[operation] == status


def migrate5(db):
    spec = importlib.util.spec_from_file_location('slice5','migrations/versions/0079_sem_phase0_sources.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(db)):
        module.upgrade()


def prepare(db):
    base_tables(db)
    db.execute(text("ALTER TABLE baidu_accounts ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"))
    migrate(db); migrate4(db); migrate5(db)


def who(account=201, tenant=101):
    # Trusted setup for repository unit tests only; HTTP uses real auth above.
    return AdvisorPrincipal('1','advisor',frozenset({(tenant,account)}))


class MemoryAttachments:
    """Test-only in-memory immutable backend. Never wired to production."""
    def __init__(self):
        self.objects = {}
        self.fail_at = None
    def put_if_absent(self, key, data, digest):
        if self.fail_at is not None and len(self.objects) >= self.fail_at:
            raise RuntimeError('never-echo-backend')
        assert sha(data) == digest
        assert key not in self.objects or self.objects[key] == data
        self.objects[key] = data
    def read(self, key, max_bytes):
        return self.objects[key][:max_bytes]


@pytest.fixture
def source_db(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'sources.sqlite'))
    @event.listens_for(engine,'connect')
    def foreign_keys(db, _):
        db.execute('PRAGMA foreign_keys=ON')
    with engine.begin() as db:
        prepare(db)
    yield engine
    engine.dispose()


def test_source_repository_restart_hash_scope_append_and_fail_closed(source_db):
    store=SQLAlchemySubmissionStore(source_db.begin)
    p=payload()
    result=store.submit(who(),p,[])
    assert result['revision']==1
    reopened=SQLAlchemySubmissionStore(source_db.begin)
    assert reopened.read(who(),101,201,p.landing_page_id,1)['payload_sha256']==result['payload_sha256']
    with pytest.raises(RevisionConflict):
        reopened.submit(who(),p,[])
    with pytest.raises(ScopeDenied):
        reopened.read(who(),102,202,p.landing_page_id,1)
    with pytest.raises(AttachmentUnavailable):
        store.submit(who(),payload(expected_revision=1),[Screenshot(p.landing_page_id,'never-echo','',b'bad')])
    assert store.read(who(),101,201,p.landing_page_id,2) is None
    # Untrusted newly inserted evidence must still fail the contract/hash recheck.
    with source_db.begin() as db:
        db.execute(text('INSERT INTO sem_phase0_submissions(tenant_id,account_id,page_id,revision,actor_id,'
            'submitted_at,payload,payload_sha256,attachments_sha256) '
            'VALUES(101,201,:page,2,1,:at,:payload,:hash,:manifest)'),
            {'page':p.landing_page_id,'at':'2026-10-29T00:00:00+00:00','payload':canonical(payload(expected_revision=1).model_dump(mode='json')),
             'hash':'0'*64,'manifest':sha(b'[]')})
    with pytest.raises(ValueError,match='存储校验'):
        store.read(who(),101,201,p.landing_page_id,2)


@pytest.mark.parametrize('statement',[
    "INSERT INTO sem_phase0_pages VALUES(102,201,'bad','p','https://example.invalid')",
    "INSERT INTO sem_phase0_pages VALUES(101,202,'bad','p','https://example.invalid')",
    "UPDATE baidu_accounts SET tenant_id=102 WHERE id=201",
    "UPDATE sem_phase0_pages SET url='https://example.invalid/changed'",
    'DELETE FROM sem_phase0_pages',
    "UPDATE sem_phase0_submissions SET payload_sha256='bad'",
    'DELETE FROM sem_phase0_submissions',
    "INSERT INTO sem_phase0_attachments VALUES(102,201,'synthetic-page',1,1,'bad','{}')",
])
def test_database_scope_and_immutable_sources(source_db,statement):
    SQLAlchemySubmissionStore(source_db.begin).submit(who(),payload(),[])
    with pytest.raises(IntegrityError):
        with source_db.begin() as db:
            db.execute(text(statement))


def test_private_attachment_integrity_atomicity_and_no_key_exposure(source_db):
    backend=MemoryAttachments()
    store=SQLAlchemySubmissionStore(source_db.begin,backend)
    p=payload()
    shot=Screenshot(p.landing_page_id,'untrusted-name.png','image/png',b'\x89PNG\r\n\x1a\nopaque-data')
    backend.fail_at=1
    with pytest.raises(AttachmentUnavailable):
        store.submit(who(),p,[shot,shot])
    assert store.read(who(),101,201,p.landing_page_id,1) is None
    backend.fail_at=None
    store.submit(who(),p,[shot])
    view=store.read(who(),101,201,p.landing_page_id,1)
    assert view['screenshots'][0]['sha256']==sha(shot.data)
    assert 'object_key' not in canonical(view) and 'untrusted-name' not in canonical(view)
    assert view['screenshots'][0]['validation']=='signature_only_untrusted'
    key=next(iter(backend.objects))
    backend.objects[key]=b'\x89PNG\r\n\x1a\ncorrupt'
    with pytest.raises(ValueError,match='存储校验'):
        store.read(who(),101,201,p.landing_page_id,1)
    backend.objects[key]=shot.data
    for statement in ('UPDATE sem_phase0_attachments SET metadata=\'{}\'', 'DELETE FROM sem_phase0_attachments'):
        with pytest.raises(IntegrityError):
            with source_db.begin() as db:
                db.execute(text(statement))


def test_database_failure_after_blob_write_rolls_back_all_metadata(source_db):
    backend=MemoryAttachments()
    store=SQLAlchemySubmissionStore(source_db.begin,backend)
    p=payload()
    shot=Screenshot(p.landing_page_id,'','',b'\x89PNG\r\n\x1a\nopaque')
    invalid_actor=AdvisorPrincipal('999','advisor',who().writable_accounts)
    with pytest.raises(IntegrityError):
        store.submit(invalid_actor,p,[shot])
    assert len(backend.objects)==1  # Private orphan, unreachable from the API.
    with source_db.connect() as db:
        for table in ('sem_phase0_pages','sem_phase0_submissions','sem_phase0_attachments'):
            assert db.execute(text('SELECT count(*) FROM '+table)).scalar_one()==0


@pytest.mark.parametrize('data,count,page',[(b'<script>never-echo</script>',1,'synthetic-page'),
    (b'\x89PNG\r\n\x1a\n',MAX_IMAGES+1,'synthetic-page'),
    (b'\x89PNG\r\n\x1a\n',1,'other-page'),
    (b'\x89PNG\r\n\x1a\n'+b'0'*MAX_IMAGE_BYTES,1,'synthetic-page'),
    (b'\xff\xd8\xff'+b'0'*(8*1024*1024),4,'synthetic-page')],
    ids=['invalid_type','too_many','cross_page','per_file_limit','total_limit'])
def test_attachment_bounds_reject_before_backend(source_db,data,count,page):
    backend=MemoryAttachments()
    with pytest.raises(ValueError):
        SQLAlchemySubmissionStore(source_db.begin,backend).submit(who(),payload(),[Screenshot(page,'','',data)]*count)
    assert not backend.objects


def test_slice5_downgrade_refused():
    spec=importlib.util.spec_from_file_location('slice5','migrations/versions/0079_sem_phase0_sources.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(RuntimeError,match='downgrade'):
        module.downgrade()


def test_native_pg_sources_transactions_and_scope(capfd):
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    url=os.environ.get('SEM_ALERT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('native PostgreSQL only on existing disposable CI service')
    parsed=make_url(url)
    assert parsed.drivername=='postgresql+asyncpg'
    assert parsed.host in {'localhost','127.0.0.1'} and parsed.database=='sem_writeback_test'
    schema='sem_slice5_'+uuid4().hex
    async def run():
        engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema,'statement_timeout':'15000'}})
        async with engine.begin() as connection:
            await connection.execute(text('CREATE SCHEMA '+schema))
            await connection.run_sync(prepare)
        backend=MemoryAttachments()
        services=ProductionServices(engine,backend)
        p=payload(page_content='product: 合成原生PG\nbenefit: 来源持久化\nkeywords: 原生测试')
        async def submit():
            try:
                await services.call('sources','submit',who(),p,[])
                return 'submitted'
            except RevisionConflict:
                return 'conflict'
        assert sorted(await asyncio.gather(submit(),submit()))==['conflict','submitted']
        state=await services.call('shadow','create',who(),CreateRequest(tenant_id=101,account_id=201,
            page_id=p.landing_page_id,submission_revision=1))
        pid=state['plan_id']
        assert state['backend']=='submitted_only' and not state['executable']
        # DB rejection occurs after private bytes are written: metadata is atomic.
        orphan=p.model_copy(update={'landing_page_id':'orphan-page'})
        invalid_actor=AdvisorPrincipal('999','advisor',who().writable_accounts)
        with pytest.raises(IntegrityError):
            await services.call('sources','submit',invalid_actor,orphan,
                [Screenshot('orphan-page','','',b'\x89PNG\r\n\x1a\nopaque')])
        assert await services.call('sources','read',who(),101,201,'orphan-page',1) is None
        await services.call('shadow','rule',who(),pid,RulingRequest(expected_version=1,reason='合成PG裁定'))
        assert (await ProductionServices(engine).call('shadow','read',who(),pid))['version']==2
        index = await services.call('shadow','list_plans',who(),101,201,0,50)
        assert [item['plan_id'] for item in index] == [pid]
        assert await services.call('shadow','list_plans',who(),101,201,1,50) == []
        with pytest.raises(ScopeDenied):
            await services.call('shadow','list_plans',who(),102,202,0,50)
        # Real database rejects every cross-scope write and evidence mutation.
        for statement in (
            "INSERT INTO sem_phase0_pages VALUES(102,201,'bad','p','https://example.invalid')",
            "INSERT INTO sem_phase0_pages VALUES(101,202,'bad','p','https://example.invalid')",
            'UPDATE baidu_accounts SET tenant_id=102 WHERE id=201',
            "UPDATE sem_phase0_submissions SET payload_sha256='bad'",
            'DELETE FROM sem_phase0_submissions',
            "INSERT INTO sem_phase0_attachments VALUES(102,201,'synthetic-page',1,1,'bad','{}')"):
            with pytest.raises(DBAPIError):
                async with engine.begin() as db:
                    await db.execute(text(statement))
        # Source write failure must roll back page + revision, including outer UOW.
        shot=Screenshot(p.landing_page_id,'','',b'\x89PNG\r\n\x1a\nopaque')
        backend.fail_at=0
        with pytest.raises(AttachmentUnavailable):
            await services.call('sources','submit',who(),payload(expected_revision=1),[shot])
        assert await services.call('sources','read',who(),101,201,p.landing_page_id,2) is None
        backend.fail_at=None
        await services.call('sources','submit',who(),p.model_copy(update={'expected_revision':1}),[shot])
        with pytest.raises(RevisionConflict):
            await services.call('shadow','read',who(),pid)
        assert (await services.call('sources','read',who(),101,201,p.landing_page_id,2))['screenshots'][0]['sha256']==sha(shot.data)
        with pytest.raises(AttachmentUnavailable):
            await ProductionServices(engine).call('sources','read',who(),101,201,p.landing_page_id,2)
        await engine.dispose()
    asyncio.run(run())
    with capfd.disabled():
        print('SLICE5_NATIVE_PG_EXECUTED: sources + attachments + transactions + composite_scope PASS',flush=True)
        print('SLICE6_LIST_NATIVE_PG_EXECUTED: exact account + metadata + pagination PASS',flush=True)


def test_actual_main_last_binding_and_writable_advisor_protection(main_matrix):
    assert main_matrix['last_binding_protected'] == 409
    assert main_matrix['last_advisor_protected'] == 409
