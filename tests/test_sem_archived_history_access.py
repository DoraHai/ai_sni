"""Archived bindings must not expose tenant-labelled historical SEM data.

Uses the actual HTTP handlers and scoped identity dependency with synthetic rows.
No database, JWT, Baidu request, or provider is involved.
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api import auth as auth_api, keywords, reports, sem_metrics, sem_tasks
from app.database import get_session
from app.models import BaiduAccount, Keyword, Tenant
from app.models.sem_task import SemTask
from app.security import advisor_request, auth
from app.security.advisor_scope import AdvisorScope
from app.security.sem_identity import evaluate_sem_identity_states


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class HistorySession:
    """Return fixtures by SQL entity; record all business-data reads."""

    def __init__(self, status="archived", rebound=False):
        self.accounts = [SimpleNamespace(id=11, tenant_id=1, baidu_ucid=101, status=status)]
        if rebound:
            self.accounts.append(SimpleNamespace(id=12, tenant_id=1, baidu_ucid=102, status="active"))
        self.keyword = Keyword(id=21, tenant_id=1, baidu_account_id=11,
                               keyword_id=301, keyword="synthetic-other-customer-keyword",
                               category="normal", category_source="auto", total_impression=8)
        self.business_reads = []
        self.task = SimpleNamespace(id=9, tenant_id=1, module="sem", action_type="metric_target",
            title="synthetic historical task", params={"metric_key": "sem.accounts.active_count",
            "direction": "up", "target_value": 2}, status="open", created_by="user:7",
            assignee_role="operator", baseline_snapshot={"synthetic": True}, completion_evidence=None,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))

    async def scalars(self, query):
        if query.column_descriptions[0]["entity"] is BaiduAccount:
            # The fixture UCIDs are unique. No live cross-customer conflict is
            # needed to reproduce the archived-history disclosure.
            if "baidu_accounts.status =" in str(query):
                return Rows([row for row in self.accounts if row.status == "active"])
            return Rows(self.accounts)
        self.business_reads.append(str(query))
        return Rows([self.task] if query.column_descriptions[0]["entity"] is SemTask else [])

    async def scalar(self, query):
        self.business_reads.append(str(query))
        if query.column_descriptions[0]["entity"] is SemTask:
            return self.task
        if "max(" in str(query):
            return None
        return 1

    async def execute(self, query):
        self.business_reads.append(str(query))
        entity = query.column_descriptions[0]["entity"]
        if entity is Keyword:
            return Rows([("normal", 1)] if "GROUP BY" in str(query) else [(self.keyword,)])
        if len(query.column_descriptions) == 4:
            return Rows([(date.today() - timedelta(days=1), 123.45, 1, 1)])
        return Rows([(2026, 8, 123.45)])

    async def get(self, model, ident):
        assert model is Tenant
        return SimpleNamespace(id=ident, monthly_budget=1000)


def client_for(monkeypatch, session, advisor=False):
    ctx = auth.AuthContext(7, "fixture", "reader", 1,
        {key: "view" for key in ("optimize.keywords", "delivery.report",
                                "monitor.dashboard", "verify.adjustments")},
        advisor_scope=AdvisorScope(frozenset({1}), 1, 17) if advisor else None)
    app = FastAPI()
    for router in (keywords.router, reports.router, sem_metrics.router, sem_tasks.router):
        app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    # Keep require_scoped_auth and ensure_sem_identity_access real.
    async def identity(request: Request):
        if advisor:
            await advisor_request.guard_advisor_request(session, ctx, request, {"scope_kind": "advisor_tenant"})
        return ctx
    app.dependency_overrides[auth.require_auth] = identity
    app.dependency_overrides[sem_tasks.enabled] = lambda: None
    monkeypatch.setattr(auth, "ensure_module_access", AsyncMock())
    monkeypatch.setattr(sem_metrics, "ensure_module_access", AsyncMock())
    monkeypatch.setattr(sem_tasks, "ensure_module_access", AsyncMock())
    monkeypatch.setattr(advisor_request, "ensure_module_access", AsyncMock())
    return TestClient(app)


@pytest.mark.parametrize("advisor", [False, True])
@pytest.mark.parametrize("path", ["/api/v1/keywords", "/api/v1/reports/monthly/available-months"])
@pytest.mark.parametrize("rebound", [False, True])
def test_archived_history_is_blocked_before_keyword_or_report_reads(monkeypatch, advisor, path, rebound):
    session = HistorySession(rebound=rebound)
    with client_for(monkeypatch, session, advisor) as client:
        response = client.get(path, params={"tenant_id": 1})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "SEM_ACCOUNT_IDENTITY_CONFLICT"
    assert session.business_reads == []


@pytest.mark.parametrize("path,key", [("/api/v1/keywords", "keywords"),
    ("/api/v1/reports/monthly/available-months", "months")])
def test_unique_active_binding_keeps_keyword_and_report_reads(monkeypatch, path, key):
    session = HistorySession(status="active")
    with client_for(monkeypatch, session) as client:
        response = client.get(path, params={"tenant_id": 1})
    assert response.status_code == 200, response.text
    assert len(response.json()[key]) == 1
    if key == "keywords":
        assert response.json()[key][0]["keyword"] == session.keyword.keyword
    else:
        assert response.json()[key][0]["cost"] == 123.45
    assert session.business_reads


def test_archived_metric_snapshot_redacts_business_values(monkeypatch):
    session = HistorySession()
    with client_for(monkeypatch, session) as client:
        response = client.get("/api/v1/sem/metrics/snapshot?tenant_id=1")
    assert response.status_code == 200, response.text
    metrics = {row["metric_key"]: row for row in response.json()["items"]}
    assert metrics.pop("sem.identity.conflict_tenant_count")["value"] == 1
    assert all(row["value"] is None and row["data_status"] == "identity_blocked" for row in metrics.values())
    assert session.business_reads == []


@pytest.mark.parametrize("path", ["/api/v1/sem/tasks", "/api/v1/sem/tasks/9"])
@pytest.mark.parametrize("status", ["archived", "identity_conflict"])
def test_task_history_requires_identity_access(monkeypatch, path, status):
    session = HistorySession(status=status)
    with client_for(monkeypatch, session) as client:
        response = client.get(path, params={"tenant_id": 1})
    assert response.status_code == 409, response.text
    assert session.business_reads == []


def test_archiving_is_not_proof_of_clean_historical_ownership():
    archived = SimpleNamespace(tenant_id=1, baidu_ucid=101, status="archived")
    replacement = SimpleNamespace(tenant_id=1, baidu_ucid=102, status="active")
    states = evaluate_sem_identity_states([1, 2], [archived, replacement], [replacement])
    assert states[1]["status"] == "blocked"
    assert states[2]["status"] == "unbound"  # New customers remain able to onboard.
    from app.security.sem_identity import public_sem_identity_state
    public = public_sem_identity_state(states[1])
    assert set(public) == {"status", "code", "message"}


def test_switcher_evaluates_archived_rows_without_displaying_them():
    import asyncio
    from app.security.sem_identity import SEM_IDENTITY_BLOCKED_CODE
    archived = SimpleNamespace(id=11, tenant_id=1, baidu_ucid=101, status="archived")
    session = SimpleNamespace(scalars=AsyncMock(side_effect=[
        Rows([SimpleNamespace(id=1, name="synthetic-customer")]), Rows([archived]), Rows([])]))
    ctx = auth.AuthContext(7, "fixture", "admin", None, {"settings.customers": "view"})
    result = asyncio.run(auth_api.list_tenants(module=None, ctx=ctx, session=session))
    assert result["tenants"][0]["sem_accounts"] == []
    assert result["tenants"][0]["sem_identity"]["code"] == SEM_IDENTITY_BLOCKED_CODE
    assert result["tenants"][0]["sem_identity"]["status"] == "blocked"
    query = str(session.scalars.await_args_list[1].args[0])
    assert "baidu_accounts.status !=" not in query
