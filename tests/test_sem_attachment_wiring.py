"""Offline production OSS assembly and HTTP fail-closed contracts."""
import asyncio
import builtins
import io
import logging
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.sem_phase1a import production
from app.sem_phase0.oss_attachments import OSSPrivateAttachmentStore
from test_sem_phase1a_slice2 import payload
from test_sem_phase1a_slice5 import prepare, who


VALUES = ('synthetic-sem-attachments', 'https://oss-cn-test.aliyuncs.com',
          'cn-test', 'synthetic-ak-id', 'synthetic-ak-secret')


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    for name in production.ATTACHMENT_OSS_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    # Production intentionally disables SDK diagnostics. Restore shared logging
    # after each test so this suite does not change other tests' observations.
    saved = {name: logger.disabled for name, logger in logging.Logger.manager.loggerDict.items()
             if isinstance(logger, logging.Logger)}
    yield
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if isinstance(logger, logging.Logger):
            logger.disabled = saved.get(name, False)


def complete(monkeypatch):
    for name, value in zip(production.ATTACHMENT_OSS_VARIABLES, VALUES):
        monkeypatch.setenv(name, value)


def sdk_stub(monkeypatch, failure=None):
    calls = []
    logger = logging.getLogger('oss2.api')
    def auth(key_id, secret):
        logger.debug('SDK config %s', VALUES)
        calls.append(('auth', key_id, secret))
        if failure == 'auth':
            raise ValueError(str(VALUES))
        return object()
    class Bucket:
        def __init__(self, auth, endpoint, name, **kwargs):
            logger.debug('SDK config %s', VALUES)
            calls.append(('bucket', endpoint, name, kwargs))
            if failure == 'bucket':
                raise ValueError(str(VALUES))
            self.objects = {}
        def put_object(self, key, data, headers):
            assert key.startswith('sem-sources/')
            assert headers['x-oss-object-acl'] == 'private'
            assert headers['x-oss-server-side-encryption'] == 'AES256'
            self.objects[key] = data
        def get_object(self, key):
            return io.BytesIO(self.objects[key])
    monkeypatch.setitem(sys.modules, 'oss2', SimpleNamespace(AuthV4=auth, Bucket=Bucket))
    return calls


def test_complete_configuration_constructs_private_store_without_network(monkeypatch, caplog):
    complete(monkeypatch)
    calls = sdk_stub(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        store = production.attachment_store_from_environment()
    assert isinstance(store, OSSPrivateAttachmentStore)
    assert calls[0] == ('auth', VALUES[3], VALUES[4])
    assert calls[1] == ('bucket', VALUES[1], VALUES[0],
                        {'region': VALUES[2], 'connect_timeout': (3, 10)})
    assert all(value not in caplog.text for value in VALUES)


@pytest.mark.parametrize('missing', production.ATTACHMENT_OSS_VARIABLES)
@pytest.mark.parametrize('value', [None, '', '   '])
def test_any_missing_configuration_never_constructs_sdk(monkeypatch, missing, value):
    complete(monkeypatch)
    calls = sdk_stub(monkeypatch)
    if value is None:
        monkeypatch.delenv(missing)
    else:
        monkeypatch.setenv(missing, value)
    assert production.attachment_store_from_environment() is None
    assert calls == []


@pytest.mark.parametrize('failure', ['auth', 'bucket', 'adapter', 'import'])
def test_construction_failure_is_silent_and_does_not_abort_startup(monkeypatch, caplog, failure):
    complete(monkeypatch)
    sdk_stub(monkeypatch, failure)
    if failure == 'adapter':
        import app.sem_phase0.oss_attachments as adapter
        def fail(*args):
            raise ValueError(str(VALUES))
        monkeypatch.setattr(adapter, 'OSSPrivateAttachmentStore', fail)
    if failure == 'import':
        original = builtins.__import__
        def fail(name, *args, **kwargs):
            if name == 'oss2':
                raise ImportError(str(VALUES))
            return original(name, *args, **kwargs)
        monkeypatch.setattr(builtins, '__import__', fail)
    with caplog.at_level(logging.DEBUG):
        assert production.attachment_store_from_environment() is None
    assert all(value not in caplog.text for value in VALUES)


def test_real_pinned_sdk_constructor_has_bounded_socket_timeout_and_no_logs(monkeypatch, caplog):
    # Construction only, no bucket administration or object/network operations.
    complete(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        store = production.attachment_store_from_environment()
    assert isinstance(store, OSSPrivateAttachmentStore)
    assert store.bucket.timeout == (3, 10)
    assert store.bucket.region == VALUES[2]
    assert store.bucket.auth.auth_version() == 'v4'
    assert all(value not in caplog.text for value in VALUES)
    store.bucket.session.session.close()


@pytest.mark.parametrize('case', ['complete', 'failure', *production.ATTACHMENT_OSS_VARIABLES])
def test_production_router_injects_or_returns_attachment_503(tmp_path, monkeypatch, caplog, case):
    complete(monkeypatch)
    sdk_stub(monkeypatch, 'bucket' if case == 'failure' else None)
    if case in production.ATTACHMENT_OSS_VARIABLES:
        monkeypatch.delenv(case)
    import app.sem_phase1a.production_principals as principals
    monkeypatch.setattr(principals, 'production_principal_dependency', lambda: who)
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'wiring.sqlite'))
        try:
            async with engine.begin() as db:
                await db.run_sync(prepare)
            app = FastAPI()
            # Execute the real production routers() composition, then exercise
            # the real source router, repository and injected OSS adapter.
            app.include_router(production.routers(engine, SimpleNamespace(begin=None))[0])
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                result = await client.post('/api/v1/sem/phase0/submissions',
                    data={'metadata': payload().model_dump_json()},
                    files={'screenshots': ('synthetic.png', b'\x89PNG\r\n\x1a\nfixture', 'image/png')})
                assert result.status_code == (201 if case == 'complete' else 503)
                if case != 'complete':
                    assert result.json()['detail']['code'] == 'ATTACHMENT_STORAGE_UNAVAILABLE'
                assert all(value not in result.text for value in VALUES)
        finally:
            await engine.dispose()
    with caplog.at_level(logging.DEBUG):
        asyncio.run(run())
    assert all(value not in caplog.text for value in VALUES)
