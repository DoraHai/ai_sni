import asyncio

import pytest
from sqlalchemy import event

from app.models import GeoOptimizationBusiness
from test_advisor_scoped_writes import backend, write_sandbox


@pytest.mark.parametrize('website', ['javascript:document.title=String(1)', 'data:text/html,fixture',
    'https://user:pass@brand.example.test', 'java\nscript:fixture', 'http://['])
def test_advisor_rejects_unsafe_website(tmp_path, monkeypatch, backend, website):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request('PATCH', '/optimization-businesses/10', body={'profile': {'website': website}})
            assert response.status_code == 403, response.text
            assert '官网地址要以 http:// 或 https:// 开头' in response.json()['detail']['message']
            assert await env.snapshot() == before
    asyncio.run(run())


def test_profile_merge_preserves_concurrent_admin_fields(tmp_path, monkeypatch, backend):
    if backend != 'postgres':
        pytest.skip('native PostgreSQL row locks required')
    async def run():
        import app.geo.content.business_profile as profile
        original = profile.normalize_profile
        reached = asyncio.Event()

        def normalized(raw):
            if raw == {'summary': 'advisor summary'}:
                reached.set()  # Old unlocked handler has already read its stale profile.
            return original(raw)

        def before_cursor(_conn, _cursor, statement, _params, _context, _many):
            if ('FROM geo_optimization_businesses' in statement and 'FOR UPDATE' in statement
                    and 'geo_optimization_businesses.tenant_id =' in statement):
                reached.set()  # Fixed handler waits here for the admin's row lock.

        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as admin:
                row = await admin.get(GeoOptimizationBusiness, 10, with_for_update=True)
                row.profile = {**(row.profile or {}), 'geo_scope': 'admin protected scope',
                               'capabilities': ['admin capability']}
                await admin.flush()
                monkeypatch.setattr(profile, 'normalize_profile', normalized)
                event.listen(env.engine.sync_engine, 'before_cursor_execute', before_cursor)
                task = asyncio.create_task(env.request('PATCH', '/optimization-businesses/10',
                    body={'profile': {'summary': 'advisor summary'}}))
                try:
                    await asyncio.wait_for(reached.wait(), 5)
                    await admin.commit()
                    response = await asyncio.wait_for(task, 10)
                    assert response.status_code == 200, response.text
                finally:
                    event.remove(env.engine.sync_engine, 'before_cursor_execute', before_cursor)
                    if not task.done():
                        task.cancel()
            async with env.factory() as session:
                row = await session.get(GeoOptimizationBusiness, 10)
                assert row.profile['geo_scope'] == 'admin protected scope'
                assert row.profile['capabilities'] == ['admin capability']
                assert row.profile['summary'] == 'advisor summary'
    asyncio.run(run())
