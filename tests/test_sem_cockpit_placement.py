import asyncio
from datetime import date, datetime
import pytest
from fastapi import HTTPException
from sqlalchemy import insert, text
from tests.sem_cockpit_fixtures import make_sqlite_engine, readonly_session, seed_report_fixture, make_fixture_tables
from app.models import KeywordRegionReport, KeywordHourlyReport
from app.sem_cockpit_placement import read_placement, province_code


def test_customer_dimension_scope_overlap_and_missing_hours():
    engine = make_sqlite_engine()
    with engine.begin() as conn:
        seed_report_fixture(conn)
        conn.execute(text("UPDATE baidu_accounts SET status='active' WHERE id=12"))
        _, tables = make_fixture_tables()
        for model in (KeywordRegionReport, KeywordHourlyReport):
            tables[model].create(conn)
        for i, (tenant, account, name, level, clicks) in enumerate([
            (1,11,'江苏省','province',10),(1,11,'苏州','city',10),
            (1,12,'北京','city',4),(2,21,'广东','province',999),
            (1,13,'上海','province',777),(1,11,'未知','province',3),
        ], 1):
            conn.execute(insert(KeywordRegionReport).values(id=i,tenant_id=tenant,baidu_account_id=account,
                report_date=date(2026,9,1),keyword_id=i,region_name=name,region_level=level,click=clicks,
                cost=0,impression=clicks,fetched_at=datetime(2026,9,2)))
        for i, (tenant, account, clicks) in enumerate([(1,11,7),(2,21,999),(1,13,777)], 1):
            conn.execute(insert(KeywordHourlyReport).values(id=i,tenant_id=tenant,baidu_account_id=account,
                report_date=date(2026,9,1),report_datetime=datetime(2026,9,1,9),hour=9,keyword_id=i,
                click=clicks,cost=0,impression=clicks,fetched_at=datetime(2026,9,2)))
    with readonly_session(engine) as session:
        result = asyncio.run(read_placement(session,1,date(2026,9,1),date(2026,9,3),None))
        assert result['region']['total'] == 14
        assert result['region']['unmapped_clicks'] == 3
        assert result['hourly']['total'] == 7
        assert result['hourly']['cells'][24+9]['clicks'] == 7
        assert result['hourly']['cells'][24+8]['clicks'] is None
        assert result['region']['coverage']['missing_dates'] == ['2026-09-02','2026-09-03']
        only = asyncio.run(read_placement(session,1,date(2026,9,1),date(2026,9,1),12))
        assert only['region']['total'] == 4
        assert only['hourly']['coverage']['status'] == 'no_data'
        with pytest.raises(HTTPException):
            asyncio.run(read_placement(session,1,date(2026,9,1),date(2026,9,1),21))


def test_province_alias_and_unknown():
    assert province_code('江苏省') == '320000'
    assert province_code('苏州市') == '320000'
    assert province_code('广西壮族自治区') == '450000'
    assert province_code('unknown') is None
    assert province_code('江苏-苏州') == '320000'
    assert province_code('上海-上海') == '310000'
    assert province_code('广东-深圳') == '440000'
    assert province_code('未知-苏州') is None


def test_http_guards_reject_cross_tenant_and_unprivileged_requests(monkeypatch):
    from unittest.mock import AsyncMock
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.dashboard import router
    from app.database import get_session
    from app.security import auth
    from app import sem_cockpit_placement
    app = FastAPI()
    app.include_router(router)
    ctx = auth.AuthContext(1,'test','reader',1,{'monitor.dashboard':'view'})
    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[auth.require_auth] = lambda: ctx
    module, identity = AsyncMock(), AsyncMock()
    monkeypatch.setattr(auth,'ensure_module_access',module)
    monkeypatch.setattr(auth,'ensure_sem_identity_access',identity)
    read = AsyncMock(return_value={'ok':True})
    monkeypatch.setattr(sem_cockpit_placement,'read_placement',read)
    with TestClient(app) as client:
        path='/api/v1/dashboard/cockpit/placement'
        params={'tenant_id':1,'start_date':'2026-09-01','end_date':'2026-09-03'}
        assert client.get(path,params=params).status_code == 200
        module.assert_awaited(); identity.assert_awaited()
        assert client.get(path,params={**params,'tenant_id':2}).status_code == 403
        assert client.get(path,params={**params,'unsupported':'x'}).status_code == 422
        ctx.permissions={}
        assert client.get(path,params=params).status_code == 403
        assert read.await_count == 1
