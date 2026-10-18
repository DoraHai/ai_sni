"""Audit the real mounted auth/commit paths, using only fixture identities."""
import asyncio
import json
import logging

import pytest

from app.security.advisor_write_audit import AdvisorWriteAuditMiddleware
from test_advisor_scoped_writes import backend, fixture_token, write_sandbox


@pytest.mark.parametrize('case', ['update', 'create', 'forbidden', 'no-grant', 'identity', 'preview'])
def test_write_records_actor_scope_objects_and_result(tmp_path, monkeypatch, backend, caplog, case):
    async def run():
        caplog.set_level(logging.INFO, logger='uvicorn.error')
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            # The fixture mounts the same router/middleware explicitly and
            # intentionally does not start the independent app's lifespan.
            env.app.add_middleware(AdvisorWriteAuditMiddleware)
            if case == 'update':
                response = await env.request('PATCH', '/facts/10', body={'statement': 'private fixture text'})
            elif case == 'create':
                response = await env.request('POST', '/facts', body={'tenant_id': 10, 'business_id': 10,
                    'title': 'private fixture title', 'statement': 'private fixture text', 'source_name': 'fixture source'})
            elif case == 'preview':
                response = await env.request('POST', '/content-imports/preview-file',
                    files={'file': ('fixture.txt', b'private fixture text', 'text/plain')})
            elif case == 'no-grant':
                response = await env.request('PATCH', '/facts/10', body={'statement': 'private fixture text'},
                    auth=fixture_token(tid=30, gid=999))
            elif case == 'identity':
                response = await env.request('PATCH', '/facts/10', body={'statement': 'private fixture text'},
                    auth=fixture_token(scope_kind='advisor_identity', aud='advisor-session'))
            else:
                response = await env.request('PUT', '/ai-settings',
                    body={'tenant_id': 10, 'model': 'fixture-protected-model'})
            messages = [r.getMessage() for r in caplog.records if r.getMessage().startswith('geo_advisor_write ')]
            assert len(messages) == 1
            raw = messages[0]
            record = json.loads(raw.removeprefix('geo_advisor_write '))
            assert record['user_id'] == 1
            assert record['tenant_id'] == (None if case == 'identity' else 30 if case == 'no-grant' else 10)
            assert record['status'] == response.status_code
            assert record['at'] and len(record['request_id']) == 32
            assert 'private fixture' not in raw and 'Bearer' not in raw and fixture_token() not in raw
            if case in {'create', 'update'}:
                assert response.status_code == 200, response.text
                assert record['result'] == 'committed' and record['committed']
                assert record['objects']['geo_facts']
                if case == 'update':
                    assert record['path_ids'] == {'fact_id': '10'}
                    assert record['objects']['geo_facts'] == [10]
            elif case == 'preview':
                assert response.status_code == 200, response.text
                assert record['result'] == 'completed' and not record['committed']
            else:
                assert response.status_code in {401, 403, 409}, response.text
                assert record['result'] == 'rejected' and not record['committed']
    asyncio.run(run())


def test_independent_app_installs_audit_middleware():
    from app.geo_main import app
    assert any(m.cls is AdvisorWriteAuditMiddleware for m in app.user_middleware)


def test_savepoint_release_does_not_claim_outer_commit():
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.security.advisor_write_audit import KEY, bind_write_changes
    record = {'objects': {}, 'committed': False}
    request = SimpleNamespace(scope={KEY: record})
    engine = create_engine('sqlite://')
    try:
        with Session(engine) as sync:
            bind_write_changes(SimpleNamespace(sync_session=sync, info=sync.info), request)
            with sync.begin_nested():
                pass
            sync.rollback()
            assert not record['committed'], 'SAVEPOINT release is not a durable outer commit'
            sync.commit()
            assert record['committed']
    finally:
        engine.dispose()
