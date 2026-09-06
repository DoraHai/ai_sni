"""A report only, no lead router or lead schema."""
import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest
from tests.sem_cockpit_fixtures import START, END, make_sqlite_engine, readonly_session
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.database import get_session
from app.security import auth

from tests.sem_cockpit_fixtures import seed_report_fixture
from app.api import dashboard
from app.sem_cockpit_readonly import read_report, validate_window


@pytest.fixture
def db():
    engine = make_sqlite_engine()
    with engine.begin() as conn:
        seed_report_fixture(conn)
    with readonly_session(engine) as session:
        yield session


@pytest.fixture
def client(db,monkeypatch):
    app = FastAPI()
    app.include_router(dashboard.router)
    ctx = auth.AuthContext(1,"test","reader",1,
                           {"monitor.dashboard":"view"})
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[auth.require_auth] = lambda: ctx
    module = AsyncMock()
    identity = AsyncMock()
    monkeypatch.setattr(auth,"ensure_module_access",module)
    monkeypatch.setattr(auth,"ensure_sem_identity_access",identity)
    with TestClient(app) as client:
        yield client,ctx,module,identity


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


@pytest.mark.parametrize("path", ['dashboard/cockpit'])
def test_http_scope_guards(client,path):
    http,ctx,module,identity = client
    params = dict(tenant_id=1,start_date=str(START),end_date=str(END))
    assert http.get(f"/api/v1/{path}",params=params).status_code == 200
    module.assert_awaited()
    identity.assert_awaited()
    assert http.get(f"/api/v1/{path}",params={**params,"tenant_id":2}).status_code == 403
    ctx.permissions = {}
    assert http.get(f"/api/v1/{path}",params=params).status_code == 403


@pytest.mark.parametrize("path", ['dashboard/cockpit'])
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


@pytest.mark.parametrize("path", ['dashboard/cockpit'])
def test_unauthenticated_request_rejected(client,path):
    http,_,_,_ = client
    del http.app.dependency_overrides[auth.require_auth]
    assert http.get(f"/api/v1/{path}",params=dict(tenant_id=1,start_date=str(START),end_date=str(END))).status_code == 401
