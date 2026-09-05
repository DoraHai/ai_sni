"""Opt-in real PostgreSQL lock test, with disposable isolated schema and rows.

GEO_TEST_POSTGRES_URL must point to an explicitly authorized PostgreSQL server.
Only the disposable schema is written; source table structure is read via LIKE.
"""
import asyncio
import os
from types import SimpleNamespace as NS
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.geo.integration import TaskUpdate, update_task, ticket
from test_geo_integration import task, state


@pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires explicitly configured PostgreSQL')
@pytest.mark.parametrize('second_status', ['done', 'cancelled', 'open'])
def test_concurrent_completion_preserves_terminal_evidence(second_status):
    async def run():
        url = os.environ['GEO_TEST_POSTGRES_URL']
        schema = 'geo_contract_test_' + uuid4().hex
        admin = create_async_engine(url)
        engine = None
        created = False
        try:
            async with admin.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA {schema}'))
                # No defaults or foreign keys: never consume production sequences.
                await conn.execute(text(f'CREATE TABLE {schema}.geo_action_tickets (LIKE public.geo_action_tickets)'))
            created = True
            engine = create_async_engine(url, connect_args={'server_settings': {'search_path': schema, 'statement_timeout': '10000'}})
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                session.add(task())
                await session.commit()
            entered, release, second_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
            pids = {}

            async def observed_snapshot(*args):
                entered.set()
                await asyncio.wait_for(release.wait(), 10)
                return state()

            async def first():
                async with sessions() as session:
                    pids['first'] = await session.scalar(text('SELECT pg_backend_pid()'))
                    return await update_task(10, TaskUpdate(status='done'), 7, NS(ensure_tenant=lambda _: None), session)

            async def second():
                await entered.wait()
                async with sessions() as session:
                    pids['second'] = await session.scalar(text('SELECT pg_backend_pid()'))
                    second_ready.set()
                    try:
                        return await update_task(10, TaskUpdate(status=second_status), 7, NS(ensure_tenant=lambda _: None), session)
                    except HTTPException as exc:
                        return exc.status_code

            with patch('app.geo.integration.snapshot', AsyncMock(side_effect=observed_snapshot)) as snapshot:
                a, b = asyncio.create_task(first()), asyncio.create_task(second())
                try:
                    await asyncio.wait_for(second_ready.wait(), 10)
                    async with admin.connect() as conn:
                        for _ in range(100):
                            blockers = await conn.scalar(text('SELECT pg_blocking_pids(:pid)'), {'pid': pids['second']})
                            if pids['first'] in blockers:
                                break
                            await asyncio.sleep(.05)
                        else:
                            raise AssertionError('second writer did not wait on the first row lock')
                    release.set()
                    first_result, second_result = await asyncio.wait_for(asyncio.gather(a, b), 10)
                finally:
                    release.set()
                    await asyncio.gather(a, b, return_exceptions=True)
                assert first_result['status'] == 'done'
                if second_status == 'done':
                    assert second_result == first_result
                else:
                    assert second_result == 409
                snapshot.assert_awaited_once()
            async with sessions() as session:
                stored = await ticket(session, 7, 10)
                assert stored.status == 'done'
                assert stored.progress['completion_evidence']['delta'] == 12
                with pytest.raises(HTTPException) as exc:
                    await ticket(session, 8, 10)
                assert exc.value.status_code == 404
        finally:
            if engine:
                await engine.dispose()
            if created:
                async with admin.begin() as conn:
                    await conn.execute(text(f'DROP TABLE {schema}.geo_action_tickets'))
                    await conn.execute(text(f'DROP SCHEMA {schema}'))
            await admin.dispose()
    asyncio.run(run())
