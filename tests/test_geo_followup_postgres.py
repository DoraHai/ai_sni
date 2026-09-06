"""Real SQL and lock tests in disposable empty schemas; never fetch external pages."""
import asyncio
import os
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import GeoActionTicket, GeoChannelVariant


@pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires isolated PostgreSQL')
@pytest.mark.parametrize('scenario', ['diagnosis_merge','publication_monitor'])
def test_followup_real_concurrency(scenario):
    async def run():
        schema='geo_followup_test_'+uuid4().hex
        admin=create_async_engine(os.environ['GEO_TEST_POSTGRES_URL'])
        engine=None; workers=[]; release=asyncio.Event()
        names=['tenants','geo_audit_runs','geo_action_tickets','geo_content_tasks','geo_channel_variants','geo_publications']
        created=False
        try:
            async with admin.begin() as c:
                await c.execute(text(f'CREATE SCHEMA {schema}'))
                for table in names:
                    await c.execute(text(f'CREATE TABLE {schema}.{table} AS SELECT * FROM public.{table} WITH NO DATA'))
                await c.execute(text(f'CREATE SEQUENCE {schema}.ticket_ids START 100'))
                await c.execute(text(f"ALTER TABLE {schema}.geo_action_tickets ALTER COLUMN id SET DEFAULT nextval('{schema}.ticket_ids')"))
                await c.execute(text(f'INSERT INTO {schema}.tenants(id) VALUES(7)'))
                for aid in [1,2]:
                    await c.execute(text(f"INSERT INTO {schema}.geo_audit_runs(id,tenant_id,url,status) VALUES(:id,7,'https://example.com/a','completed')"),{'id':aid})
                await c.execute(text(f"INSERT INTO {schema}.geo_content_tasks(id,tenant_id,title,status) VALUES(12,7,'Article','published')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_channel_variants(id,task_id,article_version_id,channel,title,body_markdown,status,adapt_meta) VALUES(3,12,16,'website','Title','body','published','{{}}')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_publications(id,variant_id,status,published_url) VALUES(4,3,'published','https://example.com/a')"))
            created=True
            engine=create_async_engine(os.environ['GEO_TEST_POSTGRES_URL'],connect_args={'server_settings':{'search_path':schema,'statement_timeout':'15000'}})
            sessions=async_sessionmaker(engine,expire_on_commit=False)
            started=asyncio.Event(); pids={}
            async def blocked(pid):
                async with admin.connect() as c:
                    for _ in range(100):
                        if await c.scalar(text('SELECT cardinality(pg_blocking_pids(:pid))'),{'pid':pid}):
                            return
                        await asyncio.sleep(.03)
                raise AssertionError('writer did not wait for lock')
            if scenario=='diagnosis_merge':
                from app.geo.routes import materialize_tickets
                from app.geo.diagnosis_merge import audit_ticket_filter
                async def materialize(aid):
                    async with sessions() as s:
                        pids[aid]=await s.scalar(text('SELECT pg_backend_pid()'))
                        if len(pids)==2:started.set()
                        return await materialize_tickets(aid,7,False,NS(ensure_tenant=lambda _:None,user_id=9),s)
                async with sessions() as lock:
                    await lock.execute(text('SELECT id FROM tenants WHERE id=7 FOR UPDATE'))
                    with patch('app.geo.routes.materialize_ticket_specs',return_value=[{'advice_code':'robots','title':'Fix robots'}]):
                        workers=[asyncio.create_task(materialize(i)) for i in [1,2]]
                        await asyncio.wait_for(started.wait(),5)
                        await blocked(pids[1]);await blocked(pids[2]);await lock.commit()
                        result=await asyncio.wait_for(asyncio.gather(*workers),10)
                assert sum(r['created'] for r in result)==1 and sum(r['merged'] for r in result)==1
                async with sessions() as s:
                    rows=list(await s.scalars(select(GeoActionTicket)))
                    assert len(rows)==1 and sorted(rows[0].baseline_snapshot['diagnosis_ids'])==[1,2]
                    assert await s.scalar(select(GeoActionTicket.id).where(audit_ticket_filter(GeoActionTicket,2)))==rows[0].id
            else:
                from app.geo.publication_monitor import check_publication,run_monitor_batch
                calls=[];entered=asyncio.Event()
                async def fetch(url):
                    calls.append(url);entered.set();await asyncio.wait_for(release.wait(),10)
                    return NS(html='html',final_url=url)
                async def check(second=False):
                    if second:await entered.wait()
                    async with sessions() as s:
                        pids[second]=await s.scalar(text('SELECT pg_backend_pid()'))
                        if second:started.set()
                        return await check_publication(s,7,12,4)
                with patch('app.geo.publication_monitor.safe_fetch',side_effect=fetch), \
                     patch('app.geo.publication_monitor.match_publication',return_value={'observed_sha256':'actual'}):
                    workers=[asyncio.create_task(check()),asyncio.create_task(check(True))]
                    await asyncio.wait_for(started.wait(),5);await blocked(pids[True]);release.set()
                    results=await asyncio.wait_for(asyncio.gather(*workers),10)
                assert len(calls)==1 and all(r['state']=='healthy' for r in results)
                async with sessions() as s:
                    v=await s.get(GeoChannelVariant,3)
                    assert len(v.adapt_meta['publication_monitor']['4']['history'])==1
                # Execute the dynamic JSON publication-id lookup on real PostgreSQL.
                with patch('app.database.async_session_factory',sessions), patch('app.geo.publication_monitor.safe_fetch',AsyncMock()) as no_fetch:
                    await run_monitor_batch()
                    no_fetch.assert_not_awaited()
        finally:
            release.set()
            for w in workers:
                if not w.done():w.cancel()
            await asyncio.gather(*workers,return_exceptions=True)
            if engine:await engine.dispose()
            if created:
                async with admin.begin() as c:
                    for table in reversed(names):await c.execute(text(f'DROP TABLE {schema}.{table}'))
                    await c.execute(text(f'DROP SEQUENCE {schema}.ticket_ids'))
                    await c.execute(text(f'DROP SCHEMA {schema}'))
            await admin.dispose()
    asyncio.run(run())
