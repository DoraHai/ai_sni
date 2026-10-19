"""Full auth/commit regression in CI-owned fixtures; never run against production."""
import asyncio
import json
import logging
from unittest.mock import AsyncMock

import pytest

from test_advisor_scoped_writes import backend, fixture_token, write_sandbox


@pytest.mark.parametrize('tid,gid', [(10, 101), (20, 102)])
@pytest.mark.parametrize('action', ['variants', 'publications', 'import-receipts'])
def test_selected_customer_operations_succeed_and_audit(tmp_path, monkeypatch, backend, caplog, tid, gid, action):
    from starlette.background import BackgroundTasks
    queued = []
    monkeypatch.setattr(BackgroundTasks, 'add_task', lambda _self, fn, *a, **kw: queued.append(a))
    caplog.set_level(logging.INFO, logger='geo.advisor.operations')

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            # Publishing gates/providers are independent of the real auth, assignment and commit guards.
            monkeypatch.setattr('app.geo.content.routes.ensure_geo_entitlement', AsyncMock())
            monkeypatch.setattr('app.geo.content.routes.assert_can_publish', lambda *_a, **_kw: None)
            monkeypatch.setattr('app.geo.content.routes._build_rule_input', AsyncMock(return_value=None))
            params = {'tenant_id': tid}
            kw = {'auth': fixture_token(tid=tid, gid=gid), 'params': params}
            if action == 'variants':
                kw['body'] = {'channels': ['website'], 'use_llm': False}
            elif action == 'publications':
                kw['body'] = {'tenant_id': tid, 'channel': 'website',
                    'published_url': 'https://published.example.test/retest'}
            else:
                params.update(project_id=tid, dry_run='false')
                kw['files'] = {'file': ('receipt.json', json.dumps([{'article_id': tid,
                    'platform': 'website', 'public_url': 'https://published.example.test/retest'}]).encode(), 'application/json')}
            response = await env.request('POST', f'/content-tasks/{tid}/{action}', **kw)
            assert response.status_code == 200, response.text
            if action == 'import-receipts':
                assert response.json()['committed'] and response.json()['changed'] == 1
            if action == 'variants':
                assert queued
    asyncio.run(run())
    assert any(json.loads(r.message).get('result') == 'committed' for r in caplog.records
        if r.name == 'geo.advisor.operations')


@pytest.mark.parametrize('action', ['variants', 'publications', 'import-receipts'])
@pytest.mark.parametrize('failure', ['unselected', 'ungranted', 'unassigned'])
def test_denied_operations_leave_content_unchanged(tmp_path, monkeypatch, backend, action, failure):
    from app.models import GeoProject
    from test_advisor_scoped_writes import mutate

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            tid = 20 if failure == 'unselected' else 30 if failure == 'ungranted' else 10
            if failure == 'unassigned':
                await mutate(env, GeoProject, 10, project_settings={
                    'geo_business_scope': {'business_ids': [10]},
                    'geo_service_plan': {'advisor_user_id': 3}})
            before = await env.snapshot()
            params = {'tenant_id': tid}
            kw = {'params': params}
            if action == 'variants':
                kw['body'] = {'channels': ['website'], 'use_llm': False}
            elif action == 'publications':
                kw['body'] = {'tenant_id': tid, 'channel': 'website',
                    'published_url': 'https://published.example.test/denied'}
            else:
                params.update(project_id=tid, dry_run='false')
                kw['files'] = {'file': ('receipt.json', json.dumps([{'article_id': tid,
                    'platform': 'website', 'public_url': 'https://published.example.test/denied'}]).encode(), 'application/json')}
            response = await env.request('POST', f'/content-tasks/{tid}/{action}', **kw)
            assert response.status_code == 403, response.text
            if failure == 'unassigned':
                assert '项目顾问' in response.json()['detail']['message']
            assert await env.snapshot() == before
    asyncio.run(run())
