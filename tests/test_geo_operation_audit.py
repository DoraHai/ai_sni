import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.security.geo_operation_audit import audit_geo_operation
from test_geo_receipt_import import fixture, row


@pytest.mark.parametrize('status', [200, 403, 500])
def test_decorator_records_outcome_without_request_body(caplog, status):
    caplog.set_level(logging.INFO, logger='uvicorn.error')
    @audit_geo_operation('PUT', '/api/v1/geo/projects/{project_id}/search-visibility/config')
    async def write(project_id, tenant_id, req, ctx):
        if status == 403:
            raise HTTPException(403, 'fixture denial')
        if status == 500:
            raise RuntimeError('private fixture error')
        return {'config': req}
    async def run():
        try:
            await write(2, 7, {'website': 'private fixture URL'}, SimpleNamespace(user_id=9))
        except (HTTPException, RuntimeError):
            pass
    asyncio.run(run())
    messages = [r.getMessage() for r in caplog.records if r.getMessage().startswith('geo_operation ')]
    assert len(messages) == 1 and 'private fixture' not in messages[0]
    record = json.loads(messages[0].removeprefix('geo_operation '))
    assert record['user_id'] == 9 and record['tenant_id'] == 7
    assert record['objects'] == {'project_id': 2} and record['status'] == status
    assert record['at'] and record['method'] == 'PUT'


def test_real_receipt_route_records_actor_task_project_and_commit(fixture, caplog):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_session
    from app.geo.content import routes
    from app.security.auth import require_scoped_auth
    caplog.set_level(logging.INFO, logger='uvicorn.error')
    app = FastAPI()
    app.include_router(routes.router, prefix='/api/v1/geo')
    app.dependency_overrides[require_scoped_auth] = lambda: fixture.ctx
    app.dependency_overrides[get_session] = lambda: fixture.session
    with TestClient(app) as client:
        response = client.post('/api/v1/geo/content-tasks/12/import-receipts',
            params={'tenant_id': 7, 'project_id': 5, 'dry_run': 'false'},
            files={'file': ('fixture.json', json.dumps([row()]).encode(), 'application/json')})
    assert response.status_code == 200, response.text
    records = [json.loads(r.getMessage().removeprefix('geo_operation ')) for r in caplog.records
               if r.getMessage().startswith('geo_operation ')]
    assert len(records) == 1
    record = records[0]
    assert record['committed'] and record['changed'] == 1 and not record['dry_run']
    assert record['user_id'] == 9 and record['tenant_id'] == 7
    assert record['objects'] == {'task_id': 12, 'project_id': 5}
