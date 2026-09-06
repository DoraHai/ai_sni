"""Opt-in native PostgreSQL tests; dedicated loopback test database only."""
import asyncio
import os
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from tests.sem_cockpit_fixtures import make_fixture_tables, seed_fixture
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.sem_cockpit_details import read_keyword_detail, read_keywords, read_search_terms
from app.models import KwReportSnapshot
from app.sem_cockpit_readonly import phone_summary, read_phone_rows, read_report


def test_native_postgres_readonly_contracts():
    url = os.environ.get("SEM_COCKPIT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated SEM_COCKPIT_TEST_DATABASE_URL not configured")
    parsed = make_url(url)
    if (parsed.drivername != "postgresql+asyncpg" or parsed.host != "127.0.0.1"
            or parsed.database != "sem_cockpit_ro_test" or parsed.username != "sem_cockpit_fixture"
            or not parsed.port or parsed.port == 5432):
        pytest.fail("Refusing a database outside the dedicated loopback fixture contract")

    async def run():
        schema = "sem_cockpit_case_" + uuid.uuid4().hex
        engine = create_async_engine(url, poolclass=NullPool,
                                     execution_options={"schema_translate_map": {None: schema}})
        metadata, tables = make_fixture_tables(native_json=True)
        created = False
        raw_cases = [(0,0),("2.0",2),(2,2),(False,None),(True,None),(None,None),
                     ({},None),([],None),(-1,None),(1.5,None),("NaN",None),("Infinity",None),("",None)]
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.run_sync(metadata.create_all)
                await conn.run_sync(lambda sync_conn: seed_fixture(sync_conn, tables))
                for index,(value,_) in enumerate(raw_cases):
                    await conn.execute(tables[KwReportSnapshot].insert().values(
                        tenant_id=3,baidu_account_id=None,keyword_id=200+index,
                        report_date=date(2026,9,1),device=0,cost=0,click=0,impression=0,
                        fetched_at=datetime(2026,9,2),raw_metrics={"ocpcConversionsDetail2":value}))
                await conn.execute(tables[KwReportSnapshot].insert().values(
                    tenant_id=4,baidu_account_id=None,keyword_id=400,report_date=date(2026,9,1),
                    device=0,cost=Decimal("10.01"),click=3,impression=7,fetched_at=datetime(2026,9,2)))
            created = True
            async with AsyncSession(engine) as session:
                await session.execute(text("SET TRANSACTION READ ONLY"))
                assert await session.scalar(text("SHOW transaction_read_only")) == "on"
                for index,(_,expected) in enumerate(raw_cases):
                    source = await read_phone_rows(session,[KwReportSnapshot.tenant_id==3,KwReportSnapshot.keyword_id==200+index])
                    assert phone_summary(source)["value"]==expected
                start, end = date(2026,9,1), date(2026,9,3)
                precision = (await read_report(session,4,start,end,None))["metrics"]
                assert precision == dict(cost=10.01,click=3,impression=7,ctr=0.428571,cpc=3.34)
                assert all(type(precision[k]) is int for k in ("click","impression"))
                assert all(type(precision[k]) is float for k in ("cost","ctr","cpc"))
                report = await read_report(session,1,start,end,11)
                assert "phone_button_clicks" not in report
                assert report["metrics"]["cost"] == 10
                assert report["trend"][1]["cost"] is None
                assert report["trend"][2]["cost"] == 0
                words = await read_keywords(session,1,None,start,end,None,None,1,20)
                values = {(r["baidu_account_id"],r["keyword_id"]):r for r in words["items"]}
                assert values[(11,100)]["metrics"]["cost"] == 10
                assert values[(12,100)]["metrics"]["cost"] == 50
                assert values[(None,100)]["metrics"]["cost"] == 7
                assert values[(11,101)]["metrics"]["cost"] is None
                detail = await read_keyword_detail(session,1,11,100,start,end)
                assert detail["phone_button_clicks"]["known_subtotal"] == 2
                assert detail["phone_button_clicks"]["value"] is None  # JSON false is not 0
                assert detail["phone_button_clicks"]["unknown_rows"] == 1
                region=detail["dimensions"]["region"]
                assert [r["metrics"]["cost"] for r in region["totals_by_level"]] == [10,10]
                assert region["coverage"]["updated_at"] == "2026-09-02T01:00:00+00:00"
                cells=detail["dimensions"]["schedule"]["cells"]
                assert len(cells)==168 and cells[0]["metrics"]["cost"] is None
                assert [c for c in cells if c["status"]=="observed"][0]["metrics"]["cost"]==0
                zero = await read_keyword_detail(session,1,12,100,start,end)
                assert zero["phone_button_clicks"]["value"] == 0
                terms = await read_search_terms(session,1,None,None,None,None,1,1)
                assert terms["total"]==3 and terms["mixed_windows"] and len(terms["windows"])==2
                assert terms["items"][0]["metrics"]["ctr"]==.02
                with pytest.raises(HTTPException) as denied:
                    await read_keyword_detail(session,1,21,100,start,end)
                assert denied.value.status_code==404
                # Prove database enforcement, beyond the SQLite statement guard.
                with pytest.raises(DBAPIError) as blocked:
                    await session.execute(text(f'UPDATE "{schema}".keywords SET keyword = keyword'))
                assert getattr(blocked.value.orig, "sqlstate", None) == "25006"
                await session.rollback()
        finally:
            if created:
                # Only the freshly generated test schema in the guarded test DB.
                assert schema.startswith("sem_cockpit_case_") and len(schema)==49
                async with engine.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(run())
