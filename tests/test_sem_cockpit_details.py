"""Real SELECTs on synthetic SQLite tables; no configured database or network."""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.sem_cockpit_fixtures import ReadSession, make_fixture_tables, seed_fixture, make_sqlite_engine, only_select
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api import dashboard, keywords, search_terms
from app.database import get_session
from app.models import BaiduAccount, Keyword, KeywordHourlyReport, KeywordRegionReport, KwReportSnapshot, SearchTermReport
from app.security import auth
from app.sem_cockpit_readonly import phone_summary


@pytest.fixture
def client(monkeypatch):
    engine = make_sqlite_engine()
    metadata, tables = make_fixture_tables()
    metadata.create_all(engine)
    with engine.begin() as conn:
        seed_fixture(conn, tables)
    event.listen(engine,"before_cursor_execute",only_select)
    from app.baidu.client import BaiduAPIClient
    from app.ai import monthly_report
    blocked = AsyncMock(side_effect=AssertionError("No external calls permitted"))
    monkeypatch.setattr(BaiduAPIClient,"call",blocked)
    monkeypatch.setattr(monthly_report,"generate_narrative",blocked)
    with Session(engine) as session:
        app = FastAPI()
        for router in (dashboard.router,keywords.router,search_terms.router):
            app.include_router(router)
        ctx = auth.AuthContext(1,"test","reader",1,{"monitor.dashboard":"view","optimize.keywords":"view","optimize.searchterms":"view"})
        app.dependency_overrides[get_session] = lambda: ReadSession(session)
        app.dependency_overrides[auth.require_auth] = lambda: ctx
        module,identity = AsyncMock(),AsyncMock()
        monkeypatch.setattr(auth,"ensure_module_access",module)
        monkeypatch.setattr(auth,"ensure_sem_identity_access",identity)
        with TestClient(app) as http:
            yield http,ctx,module,identity
        blocked.assert_not_awaited()
    engine.dispose()


PARAMS = dict(tenant_id=1,start_date="2026-09-01",end_date="2026-09-03")


def get(client,path,**params):
    response=client[0].get("/api/v1/"+path,params=params)
    assert response.status_code==200,response.text
    return response.json()


def test_detail_phone_is_known_subtotal_not_fabricated_total(client):
    data=get(client,"keywords/cockpit/100",**PARAMS)
    phone=data["phone_button_clicks"]
    assert phone["value"] is None and phone["known_subtotal"]==2
    assert (phone["stored_rows"],phone["known_rows"],phone["unknown_rows"])==(4,2,2)
    single=get(client,"keywords/cockpit/100",**PARAMS,baidu_account_id=12)
    assert single["phone_button_clicks"]["value"]==0


def test_A_report_does_not_query_or_expose_phone_metrics(client, monkeypatch):
    from app import sem_cockpit_readonly
    blocked=AsyncMock(side_effect=AssertionError("A must not query raw phone fields"))
    monkeypatch.setattr(sem_cockpit_readonly,"read_phone_rows",blocked)
    data=get(client,"dashboard/cockpit",**PARAMS)
    assert "phone_button_clicks" not in data
    assert all("phone_button_clicks" not in a for a in data["accounts"])
    assert "phone_button_clicks" in data["unavailable"]
    blocked.assert_not_awaited()


@pytest.mark.parametrize("value",[None,False,True,"", "no",-1,"-0.1","1.5","NaN","Infinity","1e1000000",{},[]])
def test_phone_rejects_invalid_source_values(value):
    assert phone_summary([SimpleNamespace(raw_value=value,raw_type="boolean" if isinstance(value,bool) else "number",row_count=1)])["value"] is None


@pytest.mark.parametrize("value",[0,"0",2,"2.0"])
def test_phone_keeps_explicit_integers(value):
    assert phone_summary([SimpleNamespace(raw_value=value,raw_type="string" if isinstance(value,str) else "number",row_count=2)])["value"] == int(float(value))*2


def test_phone_sql_compiles_to_postgres_field_extraction():
    from sqlalchemy.dialects import postgresql
    from app.sem_cockpit_readonly import read_phone_rows
    session=AsyncMock()
    session.execute.return_value.all=lambda: []
    asyncio.run(read_phone_rows(session,[KwReportSnapshot.tenant_id==1]))
    sql=str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect(),compile_kwargs={"literal_binds":True}))
    assert "jsonb_typeof" in sql and "->>" in sql and "ocpcConversionsDetail2" in sql
    assert "GROUP BY" in sql


def test_keywords_exact_account_join_and_asset_without_report(client):
    data=get(client,"keywords/cockpit",**PARAMS)
    assert data["total"]==4
    assert [r["metrics"]["cost"] for r in data["items"]]==[10,50,7,None]
    assert data["items"][0]["metrics"]["ctr"]==.02
    assert data["items"][0]["coverage"]["missing_dates"]==["2026-09-02"]
    assert data["items"][3]["coverage"]["status"]=="no_data"
    single=get(client,"keywords/cockpit",**PARAMS,baidu_account_id=12)
    assert single["total"]==1 and single["items"][0]["metrics"]["cost"]==50


def test_keywords_default_window_selected_scope_and_literal_filter(client):
    data=get(client,"keywords/cockpit",tenant_id=1,baidu_account_id=12,q="%")
    assert data["window"]["start"]=="2026-08-26"
    assert data["window"]["end"]=="2026-09-01"
    assert data["window"]["mode"]=="latest_report_7d"
    assert data["total"]==1


def test_keyword_detail_independent_evidence_and_no_double_region_total(client):
    data=get(client,"keywords/cockpit/100",**PARAMS,baidu_account_id=11)
    assert data["metrics"]["cost"]==10
    assert data["keyword_assets"][0]["keyword"]=="test%词"
    assert data["keyword_assets"][0]["baidu_account_id"]==11
    region,schedule=data["dimensions"]["region"],data["dimensions"]["schedule"]
    assert region["coverage"]["updated_at"]=="2026-09-02T01:00:00+00:00"
    assert schedule["coverage"]["updated_at"]=="2026-09-02T02:00:00+00:00"
    assert "metrics" not in region  # no overlapping province + city total
    assert [r["metrics"]["cost"] for r in region["totals_by_level"]]==[10,10]
    cells=schedule["cells"]
    assert len(cells)==168
    observed=[c for c in cells if c["status"]=="observed"]
    assert len(observed)==1 and observed[0]["weekday"]==2 and observed[0]["hour"]==9
    assert observed[0]["metrics"]["cost"]==0
    assert cells[0]["metrics"]["cost"] is None
    assert "search_queries" not in data and "bid_trend" not in data


def test_detail_empty_period_does_not_call_sync(client):
    data=get(client,"keywords/cockpit/100",tenant_id=1,baidu_account_id=11,start_date="2025-01-01",end_date="2025-01-01")
    assert data["metrics"]["cost"] is None
    assert data["dimensions"]["region"]["rows"]==[]
    assert data["phone_button_clicks"]["status"]=="no_data"


def test_search_windows_cover_all_filtered_pages_without_summing(client):
    data=get(client,"search-terms/cockpit",tenant_id=1,page_size=1)
    assert data["total"]==3 and len(data["items"])==1
    assert data["mixed_windows"] and len(data["windows"])==2
    assert data["items"][0]["metrics"]["ctr"]==.02  # never trust stored 999
    assert "summary" not in data
    filtered=get(client,"search-terms/cockpit",tenant_id=1,baidu_account_id=12)
    assert len(filtered["windows"])==1
    assert filtered["items"][0]["metrics"]["ctr"] is None


PATHS=["keywords/cockpit","keywords/cockpit/100","search-terms/cockpit"]


@pytest.mark.parametrize("path",PATHS)
def test_cross_account_and_tenant_rejected(client,path):
    params=dict(tenant_id=1) if path.startswith("search") else PARAMS
    assert client[0].get("/api/v1/"+path,params={**params,"baidu_account_id":21}).status_code==404
    assert client[0].get("/api/v1/"+path,params={**params,"tenant_id":2}).status_code==403


@pytest.mark.parametrize("path",PATHS)
@pytest.mark.parametrize("guard",["permission","module","identity","login"])
def test_security_guards_fail_closed(client,path,guard):
    http,ctx,module,identity=client
    params=dict(tenant_id=1) if path.startswith("search") else PARAMS
    if guard=="permission": ctx.permissions={}
    elif guard=="login": del http.app.dependency_overrides[auth.require_auth]
    else: (module if guard=="module" else identity).side_effect=HTTPException(403,"blocked")
    assert http.get("/api/v1/"+path,params=params).status_code==(401 if guard=="login" else 403)


@pytest.mark.parametrize("path,extra",[("keywords/cockpit",{"start_date":"2026-09-01"}),
    ("keywords/cockpit",{"force":True}), ("keywords/cockpit/100",{"force":True}),
    ("search-terms/cockpit",{"start_date":"2026-09-01"}), ("search-terms/cockpit",{"page":0})])
def test_unsupported_or_invalid_parameters(client,path,extra):
    params=PARAMS if path.endswith("/100") else dict(tenant_id=1)
    assert client[0].get("/api/v1/"+path,params={**params,**extra}).status_code==422


def test_new_detail_requires_keyword_permission_and_unknown_keyword_is_404(client):
    assert client[0].get("/api/v1/keywords/cockpit/999",params=PARAMS).status_code==404
    client[1].permissions={"monitor.dashboard":"view"}
    assert client[0].get("/api/v1/keywords/cockpit/100",params=PARAMS).status_code==403
