"""SQL integration against isolated in-memory SQLite, never a configured DB."""
import asyncio
import os
from datetime import date
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:1/test")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ.setdefault("ADMIN_API_KEY", "local-test-only")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import dashboard, leads
from app.database import get_session
from app.models import Lead
from app.security import auth
from app.sem_cockpit_readonly import read_report, validate_window

START, END = date(2026, 9, 1), date(2026, 9, 3)


class ReadSession:
    def __init__(self, session):
        self.session = session

    async def execute(self, stmt):
        return self.session.execute(stmt)

    async def scalar(self, stmt):
        return self.session.scalar(stmt)

    async def scalars(self, stmt):
        return self.session.scalars(stmt)


@pytest.fixture
def db(request):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE baidu_accounts (id INTEGER, tenant_id INTEGER, status TEXT)"))
        conn.execute(text("INSERT INTO baidu_accounts VALUES (11,1,'active'),(12,1,'inactive'),(21,2,'active')"))
        conn.execute(text("CREATE TABLE kw_report_snapshots (tenant_id INTEGER, baidu_account_id INTEGER, report_date DATE, device INTEGER, cost NUMERIC, click INTEGER, impression INTEGER, fetched_at DATETIME)"))
        conn.execute(text("""INSERT INTO kw_report_snapshots VALUES
          (1,11,'2026-09-01',0,10,2,100,'2026-09-02 01:00:00'),
          (1,12,'2026-09-01',1,30,3,100,'2026-09-02 02:00:00'),
          (1,NULL,'2026-09-01',9,5,1,0,'2026-09-02 03:00:00'),
          (1,11,'2026-09-03',0,0,0,0,'2026-09-04 01:00:00'),
          (2,21,'2026-09-01',0,999,99,999,'2026-09-02 01:00:00')"""))
        Lead.__table__.create(conn)
    with Session(engine) as session:
        for id_, tenant, status, day, campaign in [
            (1,1,"new",START,7), (2,1,"won",START,7), (3,1,"invalid",START,7),
            (4,1,"following",END,8), (5,1,"won",date(2025,1,1),7),
            (6,2,"won",START,7), (7,1,"new",None,None),
        ]:
            session.add(Lead(id=id_, tenant_id=tenant, status=status, lead_time=day,
                             campaign_id=campaign, deal_amount=(100 if status == "won" and not getattr(request,"param",False) else None),
                             phone="PRIVATE_PHONE", contact_name="PRIVATE_NAME"))
        session.commit()
        def only_select(conn, cursor, statement, parameters, context, executemany):
            assert statement.lstrip().upper().startswith("SELECT"), statement
        event.listen(engine, "before_cursor_execute", only_select)
        yield ReadSession(session)
    engine.dispose()


def test_report_accounts_missing_days_units_and_privacy(db):
    result = asyncio.run(read_report(db, 1, START, END, None))
    assert result["metrics"] == dict(cost=45, click=6, impression=200, ctr=.03, cpc=7.5)
    assert [a["baidu_account_id"] for a in result["accounts"]] == [11,12,None]
    assert result["coverage"]["missing_dates"] == ["2026-09-02"]
    assert result["coverage"]["completeness"] == "unknown"
    assert result["trend"][1]["cost"] is None
    assert result["trend"][2]["cost"] == 0
    assert result["trend"][2]["ctr"] is None
    assert result["coverage"]["updated_at"] == "2026-09-04T01:00:00+00:00"
    assert result["accounts"][1]["coverage"]["missing_dates"] == ["2026-09-02", "2026-09-03"]
    assert result["devices"][2]["label"] == "未知"
    assert "token" not in str(result) and "PRIVATE" not in str(result)


def test_single_account_and_empty_window(db):
    result = asyncio.run(read_report(db, 1, START, END, 12))
    assert result["metrics"]["cost"] == 30
    assert len(result["accounts"]) == 1
    result = asyncio.run(read_report(db, 1, END, END, 12))
    assert result["metrics"]["cost"] is None
    assert result["coverage"]["updated_at"] is None


@pytest.mark.parametrize("account", [21,999])
def test_foreign_or_unknown_account(db, account):
    with pytest.raises(HTTPException) as err:
        asyncio.run(read_report(db, 1, START, END, account))
    assert err.value.status_code == 404


@pytest.mark.parametrize("start,end", [(END,START),(date(2025,1,1),END)])
def test_invalid_windows(start,end):
    with pytest.raises(HTTPException):
        validate_window(start,end)


@pytest.mark.parametrize("status,campaign,total", [(None,None,4),("won",None,1),(None,7,3),("following",7,0)])
def test_lead_list_summary_shares_filters_and_ignores_pagination(db,status,campaign,total):
    result = asyncio.run(leads.list_leads(tenant_id=1,status=status,campaign_id=campaign,
        start_date=START,end_date=END,page=1,page_size=1,session=db))
    assert result["total"] == result["summary"]["total"] == total
    assert len(result["leads"]) == min(1,total)
    assert result["summary"]["deal_amount"] == (100 if total else 0)


@pytest.fixture
def client(db,monkeypatch):
    app = FastAPI()
    app.include_router(dashboard.router)
    app.include_router(leads.router)
    ctx = auth.AuthContext(1,"test","reader",1,
                           {"monitor.dashboard":"view", "verify.leads":"view"})
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[auth.require_auth] = lambda: ctx
    module = AsyncMock()
    identity = AsyncMock()
    monkeypatch.setattr(auth,"ensure_module_access",module)
    monkeypatch.setattr(auth,"ensure_sem_identity_access",identity)
    with TestClient(app) as client:
        yield client,ctx,module,identity


@pytest.mark.parametrize("path", ["dashboard/cockpit","leads/cockpit-summary"])
def test_http_scope_guards(client,path):
    http,ctx,module,identity = client
    params = dict(tenant_id=1,start_date=str(START),end_date=str(END))
    assert http.get(f"/api/v1/{path}",params=params).status_code == 200
    module.assert_awaited()
    identity.assert_awaited()
    assert http.get(f"/api/v1/{path}",params={**params,"tenant_id":2}).status_code == 403
    ctx.permissions = {}
    assert http.get(f"/api/v1/{path}",params=params).status_code == 403


def test_summary_has_no_personal_data_and_rejects_account_filter(client):
    http,_,_,_ = client
    params = dict(tenant_id=1,start_date=str(START),end_date=str(END))
    result = http.get("/api/v1/leads/cockpit-summary",params=params).json()
    assert result["metrics"]["received_leads"] == 4
    assert result["metrics"]["not_invalid"] == 3
    assert result["metrics"]["valid_consultations"] is None
    assert "PRIVATE" not in str(result)
    assert "phone" not in str(result)
    assert http.get("/api/v1/leads/cockpit-summary",params={**params,"baidu_account_id":11}).status_code == 422


@pytest.mark.parametrize("params", [{"status":"bogus"},{"start_date":"2026-10-01"}])
def test_lead_invalid_filters(client,params):
    http,_,_,_ = client
    response = http.get("/api/v1/leads",params={"tenant_id":1,"start_date":str(START),"end_date":str(END),**params})
    assert response.status_code in (400,422)


@pytest.mark.parametrize("path", ["dashboard/cockpit","leads/cockpit-summary"])
@pytest.mark.parametrize("guard", ["module","identity"])
def test_guard_rejection_propagates(client,path,guard):
    http,_,module,identity = client
    (module if guard == "module" else identity).side_effect = HTTPException(403,"blocked")
    assert http.get(f"/api/v1/{path}",params=dict(tenant_id=1,start_date=str(START),end_date=str(END))).status_code == 403


@pytest.mark.parametrize("suffix", ["&q=demo","&tenant_id=1","&campaign_id=7"])
def test_report_rejects_silently_ignored_filters(client,suffix):
    http,_,_,_ = client
    assert http.get("/api/v1/dashboard/cockpit?tenant_id=1&start_date=2026-09-01&end_date=2026-09-03"+suffix).status_code == 422


def test_window_boundary():
    validate_window(date(2024,1,1),date(2024,12,31))
    with pytest.raises(HTTPException):
        validate_window(date(2024,1,1),date(2025,1,1))


@pytest.mark.parametrize("path", ["dashboard/cockpit","leads/cockpit-summary"])
def test_unauthenticated_request_rejected(client,path):
    http,_,_,_ = client
    del http.app.dependency_overrides[auth.require_auth]
    assert http.get(f"/api/v1/{path}",params=dict(tenant_id=1,start_date=str(START),end_date=str(END))).status_code == 401


@pytest.mark.parametrize("db", [True], indirect=True)
def test_missing_won_amount_is_not_zero(client,db):
    http,_,_,_ = client
    result = http.get("/api/v1/leads/cockpit-summary",params=dict(tenant_id=1,start_date=str(START),end_date=str(END))).json()
    assert result["metrics"]["won"] == 1
    assert result["metrics"]["deal_amount"] is None
    assert result["deal_amount_coverage"] == {"won":1,"with_amount":0}
