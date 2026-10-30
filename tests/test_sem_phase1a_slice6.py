"""Offline adapter faults, rollback and serialized grant protection contracts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import threading
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from app.sem_phase0.oss_attachments import OSSPrivateAttachmentStore
from app.sem_phase0.store import AttachmentUnavailable
from app.sem_phase0.screenshots import Screenshot, MAX_IMAGE_BYTES
from app.sem_phase0.postgres_store import SQLAlchemySubmissionStore
from test_sem_phase1a_slice5 import prepare, who
from test_sem_phase1a_slice2 import payload


class ObjectError(Exception):
    def __init__(self, status):
        self.status = status


class MemoryOSS:
    """Test-only SDK-shaped immutable bucket. No cloud/config/network access."""
    def __init__(self):
        self.objects, self.headers = {}, []
        self.lock = threading.Lock()
        self.read_fail = False
        self.lost_response = False
        self.reads = []

    def put_object(self, key, data, headers):
        assert headers['x-oss-forbid-overwrite'] == 'true'
        assert headers['x-oss-object-acl'] == 'private'
        assert headers['x-oss-server-side-encryption'] == 'AES256'
        self.headers.append(headers)
        with self.lock:
            if key in self.objects:
                raise ObjectError(409)
            self.objects[key] = data
        if self.lost_response:
            raise TimeoutError('synthetic hidden backend error')

    def get_object(self, key):
        if self.read_fail:
            raise ObjectError(503)
        if key not in self.objects:
            raise ObjectError(404)
        owner = self
        class Stream(io.BytesIO):
            def read(self, n=-1):
                assert 0 < n <= 65536
                owner.reads.append(n)
                return super().read(n)
        return Stream(self.objects[key])


def object_key(data, page='synthetic-page'):
    digest = hashlib.sha256(data).hexdigest()
    return f'sem-sources/101/201/{page}/1/1-{digest}', digest


def test_adapter_put_read_idempotency_and_ambiguous_response():
    data = b'\x89PNG\r\n\x1a\nsynthetic'
    key, digest = object_key(data)
    bucket = MemoryOSS(); bucket.lost_response = True
    store = OSSPrivateAttachmentStore(bucket, sleep=lambda _: None)
    store.put_if_absent(key, data, digest)
    store.put_if_absent(key, data, digest)
    assert store.read(key, MAX_IMAGE_BYTES+1) == data
    assert len(bucket.objects) == 1
    assert bucket.reads


@pytest.mark.parametrize('case', ['conflict','wrong_digest','key_digest','oversize','bad_path','read_fail'])
def test_adapter_rejects_without_overwrite(case):
    data = b'\x89PNG\r\n\x1a\nsynthetic'
    key, digest = object_key(data)
    bucket = MemoryOSS(); store = OSSPrivateAttachmentStore(bucket, sleep=lambda _: None)
    if case == 'conflict': bucket.objects[key] = b'other'
    if case == 'read_fail': bucket.read_fail = True
    if case == 'wrong_digest': digest = '0'*64
    if case == 'key_digest': key = key[:-64] + '0'*64
    if case == 'oversize': data = b'x'*(MAX_IMAGE_BYTES+1)
    if case == 'bad_path': key = key.replace('synthetic-page','../other')
    with pytest.raises(AttachmentUnavailable):
        store.put_if_absent(key, data, digest)
    if case == 'conflict': assert bucket.objects[key] == b'other'
    if case not in ('conflict','read_fail'): assert not bucket.objects


def test_adapter_read_bounded_and_closes_stream():
    bucket = MemoryOSS(); store = OSSPrivateAttachmentStore(bucket)
    key, _ = object_key(b'a'); bucket.objects[key] = b'x'*(MAX_IMAGE_BYTES+100)
    assert len(store.read(key, 20)) == 20
    assert bucket.reads == [20]
    with pytest.raises(AttachmentUnavailable): store.read(key, MAX_IMAGE_BYTES+2)


def test_adapter_retry_only_transient_and_attempt_budget():
    bucket = MemoryOSS(); data = b'a'; key, digest = object_key(data)
    attempts = []
    def failure(*args, **kwargs):
        attempts.append(1); raise ObjectError(503)
    bucket.put_object = failure
    pauses = []
    store = OSSPrivateAttachmentStore(bucket, sleep=pauses.append)
    with pytest.raises(AttachmentUnavailable): store.put_if_absent(key,data,digest)
    assert len(attempts) == 3 and pauses == [.3, 1.]
    attempts.clear()
    def denied(*args, **kwargs):
        attempts.append(1); raise ObjectError(403)
    bucket.put_object = denied
    with pytest.raises(AttachmentUnavailable): store.put_if_absent(key,data,digest)
    assert len(attempts) == 1


def test_adapter_same_key_concurrent_writes_are_idempotent():
    bucket = MemoryOSS(); store = OSSPrivateAttachmentStore(bucket)
    data=b'a'; key,digest=object_key(data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: store.put_if_absent(key,data,digest), range(2)))
    assert bucket.objects == {key:data}


def test_adapter_readback_failure_rolls_back_all_metadata(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'source.sqlite'))
    with engine.begin() as db: prepare(db)
    bucket=MemoryOSS(); bucket.read_fail=True
    repo=SQLAlchemySubmissionStore(engine.begin,OSSPrivateAttachmentStore(bucket))
    with pytest.raises(AttachmentUnavailable):
        repo.submit(who(),payload(),[Screenshot('synthetic-page','','',b'\x89PNG\r\n\x1a\nfixture')])
    with engine.connect() as db:
        for table in ('sem_phase0_pages','sem_phase0_submissions','sem_phase0_attachments'):
            assert db.execute(text('SELECT COUNT(*) FROM '+table)).scalar_one() == 0
    assert len(bucket.objects)==1  # No request-path delete of orphan evidence.
    engine.dispose()


def test_adapter_partial_multiple_images_roll_back_metadata_without_deletion(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'partial.sqlite'))
    with engine.begin() as db: prepare(db)
    bucket=MemoryOSS()
    original=bucket.put_object
    def fail_second(key,data,headers):
        if '/2-' in key: raise ObjectError(403)
        return original(key,data,headers)
    bucket.put_object=fail_second
    repo=SQLAlchemySubmissionStore(engine.begin,OSSPrivateAttachmentStore(bucket))
    images=[Screenshot('synthetic-page','','',b'\x89PNG\r\n\x1a\n'+bytes([i])) for i in (1,2)]
    with pytest.raises(AttachmentUnavailable): repo.submit(who(),payload(),images)
    with engine.connect() as db:
        for table in ('sem_phase0_pages','sem_phase0_submissions','sem_phase0_attachments'):
            assert db.execute(text('SELECT COUNT(*) FROM '+table)).scalar_one()==0
    assert len(bucket.objects)==1
    engine.dispose()


def test_account_list_checks_scope_and_returns_only_metadata(tmp_path):
    from app.sem_phase1a.service import ShadowService
    from app.sem_phase1a.postgres_store import SQLAlchemyShadowStore
    from app.sem_phase1a.contracts import CreateRequest
    from app.sem_phase0.store import ScopeDenied
    engine=create_engine('sqlite:///'+str(tmp_path/'list.sqlite'))
    with engine.begin() as db: prepare(db)
    repo=SQLAlchemySubmissionStore(engine.begin)
    repo.submit(who(),payload(),[])
    service=ShadowService(repo,SQLAlchemyShadowStore(engine.begin),submitted_only=True)
    p=service.create(who(),CreateRequest(tenant_id=101,account_id=201,page_id='synthetic-page',submission_revision=1))
    rows=service.list_plans(who(),101,201)
    assert [r['plan_id'] for r in rows] == [p['plan_id']]
    assert rows[0]['validation']=='detail_required' and rows[0]['execution_enabled'] is False
    assert set(rows[0])=={'plan_id','version','pages','product_line_id','validation','execution_enabled'}
    assert service.list_plans(who(),101,201,1,50)==[]
    with pytest.raises(ScopeDenied): service.list_plans(who(),102,202)
    engine.dispose()


async def grant_checks(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.sem_phase1a.production import ProductionAccountGrantService
    from app.sem_phase1a.grant_management import GrantError
    from app.security.auth import AuthContext
    from app.permissions import ALL_EDIT
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async with engine.begin() as db:
        for sql in (
            'CREATE TABLE roles(id INTEGER PRIMARY KEY,name TEXT,is_system BOOLEAN,permissions TEXT)',
            'CREATE TABLE users(id INTEGER PRIMARY KEY,is_active BOOLEAN,locked_until TIMESTAMP WITH TIME ZONE,tenant_id INTEGER,role_id INTEGER)',
            'CREATE TABLE tenants(id INTEGER PRIMARY KEY)',
            'CREATE TABLE baidu_accounts(id INTEGER PRIMARY KEY,tenant_id INTEGER,status TEXT)',
            'CREATE TABLE tenant_modules(tenant_id INTEGER,module_code TEXT,status TEXT,expires_at DATE)',
            'CREATE TABLE advisor_tenant_grants(id INTEGER PRIMARY KEY,user_id INTEGER,tenant_id INTEGER,revoked_at TIMESTAMP WITH TIME ZONE)',
            'CREATE TABLE sem_phase1a_account_grants(user_id INTEGER,tenant_id INTEGER,account_id INTEGER,advisor_grant_id INTEGER,generation INTEGER,revoked_at TIMESTAMP WITH TIME ZONE,PRIMARY KEY(user_id,account_id))',
            'CREATE TABLE sem_phase1a_grant_audit(id TEXT PRIMARY KEY,actor_id INTEGER,user_id INTEGER,tenant_id INTEGER,account_id INTEGER,advisor_grant_id INTEGER,generation INTEGER,action TEXT,occurred_at TIMESTAMP WITH TIME ZONE)',
        ): await db.execute(text(sql))
        for rid,name,system,perms in ((1,'合成顾问',False,{'seo.site':'edit','seo.content':'edit'}),(2,'合成客户',False,{'monitor.dashboard':'view'}),(9,'管理员',True,ALL_EDIT)):
            await db.execute(text('INSERT INTO roles VALUES(:id,:name,:system,:perms)'),{'id':rid,'name':name,'system':system,'perms':json.dumps(perms)})
        for uid,rid,tid in ((1,1,101),(6,1,101),(2,2,101),(9,9,None)):
            await db.execute(text('INSERT INTO users VALUES(:uid,:active,NULL,:tid,:rid)'),{'uid':uid,'active':True,'tid':tid,'rid':rid})
        for sql in ('INSERT INTO tenants VALUES(101)',"INSERT INTO baidu_accounts VALUES(201,101,'active'),(204,101,'active')",
                    "INSERT INTO tenant_modules VALUES(101,'sem','active',NULL)",
                    'INSERT INTO advisor_tenant_grants VALUES(10,1,101,NULL),(16,6,101,NULL)',
                    'INSERT INTO sem_phase1a_account_grants VALUES(1,101,201,10,1,NULL)'):
            await db.execute(text(sql))
    service=ProductionAccountGrantService(factory.begin)
    ctx=AuthContext(9,'','管理员',None,permissions=ALL_EDIT)
    async def sql(statement):
        async with engine.begin() as db: await db.execute(text(statement))
    async def snapshot():
        async with engine.connect() as db:
            result=[]
            for q in ('SELECT * FROM sem_phase1a_account_grants ORDER BY user_id',
                      'SELECT * FROM sem_phase1a_grant_audit ORDER BY id'):
                result.append(tuple((await db.execute(text(q))).all()))
            return tuple(result)
    async def denied(code):
        before=await snapshot()
        with pytest.raises(GrantError) as caught: await service.change(ctx,101,201,1,revoke=True)
        assert caught.value.code==code and caught.value.status==409
        assert await snapshot()==before
    await denied('LAST_GRANT_PROTECTED')
    await sql('INSERT INTO sem_phase1a_account_grants VALUES(2,101,201,NULL,1,NULL)')
    await denied('LAST_WRITABLE_ADVISOR_PROTECTED')
    await sql('INSERT INTO sem_phase1a_account_grants VALUES(6,101,201,16,1,NULL)')
    # A merely unrevoked row is insufficient: current user, role, grant and
    # default-tenant grant must all still be valid before accepting it as writer.
    for mutation,restore in (
        ('UPDATE users SET is_active=FALSE WHERE id=6','UPDATE users SET is_active=TRUE WHERE id=6'),
        ("UPDATE users SET locked_until='2099-01-01' WHERE id=6",'UPDATE users SET locked_until=NULL WHERE id=6'),
        ('UPDATE users SET role_id=2 WHERE id=6','UPDATE users SET role_id=1 WHERE id=6'),
        ("UPDATE advisor_tenant_grants SET revoked_at=CURRENT_TIMESTAMP WHERE id=16",'UPDATE advisor_tenant_grants SET revoked_at=NULL WHERE id=16'),
        ('UPDATE users SET tenant_id=102 WHERE id=6','UPDATE users SET tenant_id=101 WHERE id=6'),
    ):
        await sql(mutation); await denied('LAST_WRITABLE_ADVISOR_PROTECTED'); await sql(restore)
    # No bootstrap path was added, including when another account has grants.
    with pytest.raises(GrantError) as caught: await service.change(ctx,101,204,1,10)
    assert caught.value.code=='GRANT_ACCOUNT_NOT_INITIALIZED'
    async def revoke(uid):
        try: return await service.change(ctx,101,201,uid,revoke=True)
        except GrantError as exc: return exc.code
    results=await asyncio.gather(revoke(1),revoke(6))
    assert sum(isinstance(r,dict) and r['changed'] for r in results)==1
    assert 'LAST_WRITABLE_ADVISOR_PROTECTED' in results
    bindings,audits=await snapshot()
    assert len(audits)==1 and audits[0][-2]=='revoke'
    assert sum(row[3] is not None and row[-1] is None for row in bindings)==1
    # Customer removal succeeds with the final usable advisor preserved.
    assert (await service.change(ctx,101,201,2,revoke=True))['changed']
    before=await snapshot()
    assert not (await service.change(ctx,101,201,2,revoke=True))['changed']
    assert await snapshot()==before


def test_grant_protection_and_concurrent_revoke_sqlite(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    async def run():
        engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'grants.sqlite'))
        try: await grant_checks(engine)
        finally: await engine.dispose()
    asyncio.run(run())


def test_grant_protection_native_pg(capfd):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.engine import make_url
    url=os.environ.get('SEM_ALERT_TEST_DATABASE_URL')
    if not url: pytest.skip('requires existing disposable CI PostgreSQL')
    parsed=make_url(url)
    assert parsed.drivername=='postgresql+asyncpg' and parsed.host in ('127.0.0.1','localhost') and parsed.database=='sem_writeback_test'
    schema='sem_slice6_'+uuid4().hex
    async def run():
        engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema,'statement_timeout':'15000'}})
        try:
            async with engine.begin() as db: await db.execute(text('CREATE SCHEMA '+schema))
            await grant_checks(engine)
        finally: await engine.dispose()
    asyncio.run(run())
    with capfd.disabled():
        print('SLICE6_NATIVE_PG_EXECUTED: last grant + usable advisor + concurrent revoke PASS',flush=True)
