"""A selected grant, rather than the legacy default customer, scopes writes."""
import asyncio
import copy

import pytest
from sqlalchemy import select

from app.models import GeoTrackingEngine, GeoVisibilityPatrolRun
from test_advisor_scoped_writes import (
    CASES, CASE_IDS, backend, concrete, fixture_token, write_sandbox,
)
from test_geo_advisor_visibility import visibility_sandbox


@pytest.mark.parametrize('case', CASES, ids=CASE_IDS)
def test_manual_write_to_selected_second_granted_customer(tmp_path, monkeypatch, backend, case):
    async def run():
        method, template, original, table, column, value = case
        body = copy.deepcopy(original)
        for key in ('tenant_id', 'business_id', 'unit_id', 'prompt_id', 'expected_article_id'):
            if key in body:
                body[key] = 20
        if 'fact_ids' in body:
            body['fact_ids'] = [20]
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            params = {'tenant_id': 20}
            if template == '/optimization-businesses':
                params['project_id'] = 20
            response = await env.request(method, concrete(template, ident=20), body=body,
                params=params, auth=fixture_token(tid=20, gid=102))
            assert response.status_code in {200, 201}, response.text
            after = await env.snapshot()
            expected = 20 if column == 'fact_id' else value
            assert any(row[column] == expected for row in after[table])
            for name in ('geo_facts', 'geo_prompts', 'geo_optimization_businesses',
                         'geo_optimization_units', 'geo_content_tasks'):
                assert [r for r in after[name] if r['tenant_id'] != 20] == [
                    r for r in before[name] if r['tenant_id'] != 20]
    asyncio.run(run())


def test_visibility_to_selected_second_granted_customer(tmp_path, monkeypatch, backend):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async with env.factory() as session:
                session.add(GeoTrackingEngine(tenant_id=20, engine_key='deepseek',
                    display_name='selected customer engine', enabled=True))
                await session.commit()
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 20},
                params={'tenant_id': 20}, auth=fixture_token(tid=20, gid=102))
            assert response.status_code == 200, response.text
            row = response.json()['run']
            assert row['tenant_id'] == 20 and row['created_by'] == 1
            assert row['summary']['advisor_visibility_prompt_ids'] == [20]
            assert env.queued[0][1] == (row['id'], 20)
            async with env.factory() as session:
                assert not list(await session.scalars(select(GeoVisibilityPatrolRun).where(
                    GeoVisibilityPatrolRun.tenant_id == 10)))
    asyncio.run(run())
