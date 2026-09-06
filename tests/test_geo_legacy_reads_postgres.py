"""Approved legacy query fixes, exercised with real SQL and fixture identity."""
import asyncio
import os

import pytest
from sqlalchemy import select

from test_geo_read_http_postgres import environment

pytestmark = pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires isolated PostgreSQL')


def test_readiness_reports_orphans_without_assigning_and_write_helper_still_assigns():
    from app.models import GeoFact, GeoOptimizationBusiness, GeoVisibilityPatrolSettings
    from app.geo.content.onboarding import attach_orphan_onboarding_facts

    async def run():
        async with environment(extra_models=(GeoFact, GeoOptimizationBusiness, GeoVisibilityPatrolSettings),
                               legacy_routes=True) as (client, engine, tables, identity):
            facts = [dict(id=i, tenant_id=1, business_id=None, status='active',
                          trust_level='verified', meta={'from_onboarding': True}) for i in range(1, 7)]
            facts[2]['meta'] = {'from_onboarding': False}
            facts[3]['status'] = 'inactive'
            facts[4]['tenant_id'] = 2
            facts[5]['business_id'] = 99
            async with engine.begin() as conn:
                await conn.execute(tables['tenants'].insert(), [{'id': 1, 'name': 'fixture'}, {'id': 2, 'name': 'other'}])
                await conn.execute(tables['tenant_modules'].insert().values(tenant_id=1, module_code='geo', status='active'))
                await conn.execute(tables['geo_optimization_businesses'].insert().values(id=42, tenant_id=1, status='active'))
                await conn.execute(tables['geo_facts'].insert(), facts)
                before = (await conn.execute(select(tables['geo_facts']).order_by(tables['geo_facts'].c.id))).mappings().all()
            url = '/api/v1/geo/onboarding/readiness'
            result = await client.get(url, params={'tenant_id': 1})
            assert result.status_code == 200, result.text
            payload = result.json()
            assert {'items', 'ready_count', 'total', 'ready', 'blocking', 'tenant_name'} <= payload.keys()
            assert payload['unassigned_onboarding_facts']['count'] == 2
            assert payload['unassigned_onboarding_facts']['automatic_assignment'] is False
            async with engine.connect() as conn:
                after = (await conn.execute(select(tables['geo_facts']).order_by(tables['geo_facts'].c.id))).mappings().all()
            assert after == before
            # Normal submission still owns this write helper; no new background backfill.
            async with identity['sessions']() as session:
                assert await attach_orphan_onboarding_facts(session, tenant_id=1, business_id=42) == 2
                await session.commit()
            again = await client.get(url, params={'tenant_id': 1})
            assert again.json()['unassigned_onboarding_facts']['count'] == 0
            async with engine.connect() as conn:
                values = dict((await conn.execute(select(tables['geo_facts'].c.id, tables['geo_facts'].c.business_id))).all())
            assert values == {1: 42, 2: 42, 3: None, 4: None, 5: None, 6: 99}
            assert (await client.get(url, params={'tenant_id': 2})).status_code == 403
    asyncio.run(run())
