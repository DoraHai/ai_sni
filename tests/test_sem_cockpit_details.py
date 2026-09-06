"""Real SELECTs on synthetic SQLite tables; no configured database or network."""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.test_sem_cockpit_readonly import ReadSession  # sets dummy config before app imports
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, JSON, MetaData, Table, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import dashboard, keywords, search_terms
from app.database import get_session
from app.models import BaiduAccount, Keyword, KeywordHourlyReport, KeywordRegionReport, KwReportSnapshot, SearchTermReport
from app.security import auth
from app.sem_cockpit_readonly import phone_summary


def make_fixture_tables(native_json=False):
    metadata = MetaData()
    tables = {}
    # Only synthetic table DDL, never Alembic or application metadata.create_all.
    for model in (BaiduAccount,Keyword,KeywordHourlyReport,KeywordRegionReport,KwReportSnapshot,SearchTermReport):
        tables[model] = Table(model.__tablename__,metadata,*[
            Column(c.name,JSON() if isinstance(c.type,JSONB) and not native_json else c.type,nullable=True) for c in model.__table__.columns])
    return metadata, tables


def seed_fixture(conn, tables):
    stamp = datetime(2026,9,4,1)
    conn.execute(tables[BaiduAccount].insert(),[dict(id=11,tenant_id=1,status="active"),dict(id=12,tenant_id=1,status="inactive"),dict(id=21,tenant_id=2,status="active")])
    for id_,aid,tid in [(1,11,1),(2,12,1),(3,None,1),(4,21,2)]:
        conn.execute(tables[Keyword].insert(),dict(id=id_,tenant_id=tid,baidu_account_id=aid,keyword_id=100,
                     keyword="test%词",campaign_id=7,adgroup_id=8,price=1,pause=False,synced_at=stamp))
    conn.execute(tables[Keyword].insert(),dict(id=5,tenant_id=1,baidu_account_id=11,keyword_id=101,keyword="no report"))
    for aid,tid,cost,raw in [(11,1,10,{"ocpcConversionsDetail2":"2"}),(12,1,50,{"ocpcConversionsDetail2":0}),
                             (None,1,7,{}),(21,2,999,{"ocpcConversionsDetail2":999})]:
        conn.execute(tables[KwReportSnapshot].insert(),dict(tenant_id=tid,baidu_account_id=aid,keyword_id=100,
            report_date=date(2026,9,1),device=0,cost=cost,click=2,impression=100,fetched_at=stamp,raw_metrics=raw))
    conn.execute(tables[KwReportSnapshot].insert(),dict(tenant_id=1,baidu_account_id=11,keyword_id=100,
        report_date=date(2026,9,3),device=1,cost=0,click=0,impression=0,fetched_at=stamp,raw_metrics={"ocpcConversionsDetail2":False}))
    for level,name in [("province","省A"),("city","市A")]:
        conn.execute(tables[KeywordRegionReport].insert(),dict(tenant_id=1,baidu_account_id=11,keyword_id=100,
            report_date=date(2026,9,1),region_level=level,region_name=name,cost=10,click=2,impression=100,
            fetched_at=datetime(2026,9,2,1)))
    conn.execute(tables[KeywordRegionReport].insert(),dict(tenant_id=1,baidu_account_id=12,keyword_id=100,
        report_date=date(2026,9,1),region_level="city",region_name="市B",cost=50,click=2,impression=100,fetched_at=stamp))
    conn.execute(tables[KeywordHourlyReport].insert(),dict(tenant_id=1,baidu_account_id=11,keyword_id=100,
        report_date=date(2026,9,1),report_datetime=datetime(2026,9,1,9),hour=9,cost=0,click=0,impression=0,
        fetched_at=datetime(2026,9,2,2)))
    for id_,aid,start,end,click,imp in [(1,11,date(2026,9,1),date(2026,9,3),2,100),
        (2,12,date(2026,8,1),date(2026,8,31),None,100),(3,11,date(2026,9,1),date(2026,9,3),0,0)]:
        conn.execute(tables[SearchTermReport].insert(),dict(id=id_,tenant_id=1,baidu_account_id=aid,
            query_word="搜索%词" if id_ != 3 else "别词",trigger_keyword="test%词",campaign_id=7,adgroup_id=8,
            window_start=start,window_end=end,synced_at=stamp,click=click,impression=imp,cost=10,ctr=999))


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread":False})
    metadata, tables = make_fixture_tables()
    metadata.create_all(engine)
    with engine.begin() as conn:
        seed_fixture(conn, tables)
    def only_read(conn,cursor,statement,parameters,context,executemany):
        assert statement.lstrip().upper().startswith("SELECT"),statement
    event.listen(engine,"before_cursor_execute",only_read)
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
