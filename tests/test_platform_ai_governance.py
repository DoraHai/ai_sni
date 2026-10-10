"""AI governance contract, scope and missing-schema behavior."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ai_governance as governance
from app.api import platform_ai_governance as api
from app.security.auth import AuthContext, require_auth


def admin():
    return AuthContext(
        7, "platform-admin", "管理员", None,
        {"settings.accounts": "edit", "settings.customers": "edit"},
    )


def tenant_user():
    return AuthContext(
        8, "tenant-user", "客户", 3,
        {"settings.accounts": "edit", "settings.customers": "edit"},
    )


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeSession:
    def __init__(self, *, metering=False, controls=False, control_rows=False):
        self.metering = metering
        self.controls = controls
        self.control_rows = control_rows

    async def scalar(self, statement, params=None):
        sql = str(statement)
        name = (params or {}).get("name")
        if "to_regclass" in sql:
            if name == ".api_usage_events":
                return self.metering
            return self.controls
        raise AssertionError(sql)

    async def execute(self, statement, params=None):
        sql = str(statement)
        if sql.startswith("SET "):
            return Rows([])
        if "FROM api_control_settings" in sql:
            return Rows([{
                "key": "budget:global", "kind": "budget", "revision": 3,
                "value": {"daily_calls": 100, "daily_cny": "20", "private": "DROP"},
            }]) if self.control_rows else Rows([])
        if "FROM api_control_bindings" in sql:
            return Rows([{
                "module": "seo", "label": "connection:seo.dashscope",
                "host": "dashscope.aliyuncs.com", "model": "qwen3.8-max",
                "configured": True, "seen_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
            }]) if self.control_rows else Rows([])
        if "FROM api_control_audit" in sql:
            return Rows([
                {"resource": "alert:one", "after_value": {"status": "resolved"}},
                {"resource": "alert:two", "after_value": {"status": "in_progress"}},
            ]) if self.control_rows else Rows([])
        if "GROUP BY module,provider,model" in sql:
            return Rows([{
                "module": "seo", "provider": "dashscope.aliyuncs.com", "model": "qwen3.8-max",
                "total": 2, "failed": 1, "unknown": 1, "pending": 0, "unpriced": 2,
                "tenant_attributed": 2, "user_attributed": 1, "scope_attributed": 2,
                "known_amount": Decimal("0"),
            }])
        if "GROUP BY module,operation" in sql:
            return Rows([{
                "module": "seo", "operation": "onsite.ai_proposal", "total": 2,
                "failed": 1, "unknown": 1, "pending": 0, "unpriced": 2,
                "tenant_attributed": 2, "user_attributed": 1, "scope_attributed": 2,
                "known_amount": Decimal("0"),
            }])
        if "GROUP BY module ORDER BY module" in sql:
            return Rows([{
                "module": "seo", "total": 2, "failed": 1, "unknown": 1,
                "pending": 0, "unpriced": 2, "tenant_attributed": 2,
                "user_attributed": 1, "scope_attributed": 2,
                "known_amount": Decimal("0"),
            }])
        raise AssertionError(sql)


def settings(**changes):
    values = {
        "dashscope_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "dashscope_model": "qwen3.8-max",
        "dashscope_api_key": "",
        "deepseek_base_url": "https://api.deepseek.com/v1",
        "deepseek_model": "deepseek-chat",
        "deepseek_api_key": "SECRET-DO-NOT-RETURN",
        "baidu_write_dry_run": True,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_missing_controls_schema_does_not_hide_real_metering(monkeypatch):
    monkeypatch.setattr(governance.api_metering, "enabled", lambda: True)
    monkeypatch.setattr(governance.api_controls, "enabled", lambda: False)
    result = asyncio.run(governance.read_ai_governance(
        FakeSession(metering=True, controls=False),
        now=datetime(2026, 10, 10, tzinfo=timezone.utc), settings=settings(),
    ))
    assert result["state"] == "available"
    assert result["controls"] == {
        "schema": "schema_pending", "enabled": False, "editing": "disabled",
        "note": "控制结构未经人工审核或未启用时仅提供只读计量，不开放编辑。",
    }
    seo = next(item for item in result["modules"] if item["module"] == "seo")
    assert seo["configured"] is None
    assert seo["calls"]["failed"] == 1
    assert seo["calls"]["unknown"] == 1
    assert seo["calls"]["estimated_amount"] is None
    assert seo["calls"]["known_amount"] == "0"
    assert seo["calls"]["features"][0]["feature"] == "onsite.ai_proposal"
    assert seo["limits"][0]["kind"] == "calls"
    assert seo["limits"][0]["key"] == "module_autonomous"
    assert seo["limits"][0]["state"] == "unavailable"
    assert seo["limits"][1]["state"] == "schema_pending"
    assert result["capabilities"]["website_execution"] == {"enabled": False, "status": "reserved"}
    assert "SECRET-DO-NOT-RETURN" not in str(result)


def test_sem_runtime_configuration_matches_ai_client_provider_priority():
    dash = governance._runtime_sem_configuration(settings(
        dashscope_api_key="DASH-SECRET", deepseek_api_key="DEEP-SECRET",
    ))
    assert dash == {
        "state": "available", "source": "sem_runtime",
        "provider": "dashscope.aliyuncs.com", "model": "qwen3.8-max",
        "configured": True,
    }
    deep = governance._runtime_sem_configuration(settings(
        dashscope_api_key="", deepseek_api_key="DEEP-SECRET",
    ))
    assert deep["provider"] == "api.deepseek.com"
    assert deep["model"] == "deepseek-chat"
    assert deep["configured"] is True
    missing = governance._runtime_sem_configuration(settings(
        dashscope_api_key="", deepseek_api_key="",
    ))
    assert missing["provider"] is None
    assert missing["model"] is None
    assert missing["configured"] is False


def test_missing_metering_schema_returns_null_not_invented_zero(monkeypatch):
    monkeypatch.setattr(governance.api_metering, "enabled", lambda: False)
    monkeypatch.setattr(governance.api_controls, "enabled", lambda: False)
    result = asyncio.run(governance.read_ai_governance(
        FakeSession(), now=datetime(2026, 10, 10, tzinfo=timezone.utc), settings=settings(deepseek_api_key=""),
    ))
    assert result["state"] == "schema_pending"
    for module in result["modules"]:
        assert module["calls"]["state"] == "schema_pending"
        assert module["calls"]["total"] is None
        assert module["calls"]["failed"] is None
        assert module["calls"]["unknown"] is None


def test_present_metering_schema_with_no_module_events_returns_real_zero(monkeypatch):
    monkeypatch.setattr(governance.api_metering, "enabled", lambda: True)
    monkeypatch.setattr(governance.api_controls, "enabled", lambda: False)
    result = asyncio.run(governance.read_ai_governance(
        FakeSession(metering=True),
        now=datetime(2026, 10, 10, tzinfo=timezone.utc), settings=settings(),
    ))
    sem = next(item for item in result["modules"] if item["module"] == "sem")
    assert sem["calls"]["state"] == "available"
    assert sem["calls"]["total"] == 0
    assert sem["calls"]["failed"] == 0
    assert sem["calls"]["unknown"] == 0
    assert sem["calls"]["known_amount"] == "0"
    assert sem["calls"]["estimated_amount"] == "0"


def test_non_ai_provider_binding_is_not_reported_as_ai_configuration():
    assert governance._is_ai_binding({"label": "connection:sem.deepseek"}) is True
    assert governance._is_ai_binding({"label": "connection:geo.qwen"}) is True
    assert governance._is_ai_binding({"label": "connection:sem.baidu"}) is False
    assert governance._is_ai_binding({"label": "connection:seo.chinaz"}) is False


def test_effective_platform_limit_and_resolved_incident_are_preserved(monkeypatch):
    monkeypatch.setattr(governance.api_metering, "enabled", lambda: True)
    monkeypatch.setattr(governance.api_controls, "enabled", lambda: True)
    result = asyncio.run(governance.read_ai_governance(
        FakeSession(metering=True, controls=True, control_rows=True),
        now=datetime(2026, 10, 10, tzinfo=timezone.utc), settings=settings(),
    ))
    seo = next(item for item in result["modules"] if item["module"] == "seo")
    assert seo["configured"] is True
    assert seo["configuration"]["source"] == "api_control_bindings"
    daily_calls = next(limit for limit in seo["limits"] if limit.get("key") == "global.daily_calls")
    daily_budget = next(limit for limit in seo["limits"] if limit.get("key") == "global.daily_cny")
    assert daily_calls == {
        "kind": "calls", "key": "global.daily_calls", "scope": "global",
        "state": "enabled", "value": 100, "source": "api_control_settings",
    }
    assert daily_budget["kind"] == "budget"
    assert daily_budget["state"] == "enabled"
    assert daily_budget["value"] == "20"
    assert result["incidents"]["resolved"] == 1
    assert result["incidents"]["in_progress"] == 1


def test_governance_path_is_not_wrapped_in_business_runtime_config(monkeypatch):
    from app.api_metering import MeteringScopeMiddleware
    from app import api_connection_config

    calls = []

    @asynccontextmanager
    async def tracked(module):
        calls.append(module)
        yield

    monkeypatch.setattr(api_connection_config, "runtime_scope", tracked)
    inner = FastAPI()

    @inner.get("/api/v1/platform/probe")
    async def probe():
        return {"ok": True}

    @inner.get("/api/v1/platform/ai-governance")
    async def governance_probe():
        return {"ok": True}

    app = MeteringScopeMiddleware(inner, module="sem")
    with TestClient(app) as client:
        assert client.get("/api/v1/platform/ai-governance").json() == {"ok": True}
        assert calls == []
        assert client.get("/api/v1/platform/probe").json() == {"ok": True}
        assert calls == ["sem"]


def test_route_rejects_anonymous_and_tenant_users_before_database_access():
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        assert client.get("/api/v1/platform/ai-governance").status_code == 401
    app.dependency_overrides[require_auth] = tenant_user
    with TestClient(app) as client:
        assert client.get("/api/v1/platform/ai-governance").status_code == 403


def test_superadmin_route_is_read_only_and_no_store(monkeypatch):
    session = FakeSession()

    @asynccontextmanager
    async def factory():
        yield session

    async def snapshot(_session):
        return {"schema": 1, "state": "schema_pending", "secret": None}

    monkeypatch.setattr(api, "async_session_factory", factory)
    monkeypatch.setattr(api, "read_ai_governance", snapshot)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_auth] = admin
    with TestClient(app) as client:
        response = client.get("/api/v1/platform/ai-governance")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["vary"] == "Authorization"
    assert response.json()["state"] == "schema_pending"
