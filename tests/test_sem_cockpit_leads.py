"""All original lead summary and permission test cases retained."""
import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest
from tests.sem_cockpit_fixtures import START, END, make_sqlite_engine, readonly_session
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.database import get_session
from app.security import auth

from sqlalchemy.orm import Session
from app.api import leads
from app.models import Lead


@pytest.fixture
def db(request):
    engine = make_sqlite_engine()
    with engine.begin() as conn:
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
    with readonly_session(engine) as session:
        yield session


@pytest.fixture
def client(db,monkeypatch):
    app = FastAPI()
    app.include_router(leads.router)
    ctx = auth.AuthContext(1,"test","reader",1,
                           {"verify.leads":"view"})
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[auth.require_auth] = lambda: ctx
    module = AsyncMock()
    identity = AsyncMock()
    monkeypatch.setattr(auth,"ensure_module_access",module)
    monkeypatch.setattr(auth,"ensure_sem_identity_access",identity)
    with TestClient(app) as client:
        yield client,ctx,module,identity


@pytest.mark.parametrize("status,campaign,total", [(None,None,4),("won",None,1),(None,7,3),("following",7,0)])
def test_lead_list_summary_shares_filters_and_ignores_pagination(db,status,campaign,total):
    result = asyncio.run(leads.list_leads(tenant_id=1,status=status,campaign_id=campaign,
        start_date=START,end_date=END,page=1,page_size=1,session=db))
    assert result["total"] == result["summary"]["total"] == total
    assert len(result["leads"]) == min(1,total)
    assert result["summary"]["deal_amount"] == (100 if total else 0)


@pytest.mark.parametrize("path", ['leads/cockpit-summary'])
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


@pytest.mark.parametrize("path", ['leads/cockpit-summary'])
@pytest.mark.parametrize("guard", ["module","identity"])
def test_guard_rejection_propagates(client,path,guard):
    http,_,module,identity = client
    (module if guard == "module" else identity).side_effect = HTTPException(403,"blocked")
    assert http.get(f"/api/v1/{path}",params=dict(tenant_id=1,start_date=str(START),end_date=str(END))).status_code == 403


@pytest.mark.parametrize("path", ['leads/cockpit-summary'])
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
