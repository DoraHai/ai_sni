"""Offline contracts for trusted SEM binding and the isolated demo reader."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.security.auth import AuthContext
from app import sem_demo_source as source


BASE = Path(__file__).resolve().parents[1]


def settings(**overrides):
    values = {
        "database_url": "postgresql+asyncpg://prod@prod-db:5432/sem_prod",
        "sem_demo_data_source_enabled": True,
        "sem_demo_principal_tenant_ids": "16",
        "sem_demo_binding_schema_revision": "0098_demo_binding_no_truncate",
        "sem_demo_database_url": "postgresql+asyncpg://reader@demo-db:5432/sem_demo",
        "sem_demo_database_name": "sem_demo",
        "sem_demo_database_host_allowlist": "demo-db",
        "sem_demo_database_server_addr_allowlist": "10.0.0.18",
        "sem_demo_database_schema_revision": "0097_sem_demo_fixture",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def context(tenant_id=16):
    return AuthContext(5, "reader", "viewer", tenant_id, {"monitor.dashboard": "view"})


def request(path, query="", method="GET", headers=()):
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers],
            "client": ("127.0.0.1", 1234),
            "server": ("example.test", 443),
        }
    )


class ScalarRows:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)


class Result:
    def __init__(self, *, rows=(), scalars=(), one=None):
        self._rows = list(rows)
        self._scalars = list(scalars)
        self._one = one

    def scalars(self):
        return ScalarRows(self._scalars)

    def mappings(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def all(self):
        return list(self._rows)

    def one(self):
        return self._one


class PrimarySession:
    def __init__(self, rows=None, revisions=None):
        self.rows = [binding_row()] if rows is None else rows
        self.revisions = ["0098_demo_binding_no_truncate"] if revisions is None else revisions
        self.calls = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params))
        if "alembic_version" in sql:
            return Result(scalars=self.revisions)
        if "demo_tenant_bindings" in sql:
            return Result(rows=self.rows)
        raise AssertionError(sql)


def binding_row(**overrides):
    row = {
        "tenant_id": 16,
        "demo_tenant_id": 990000016,
        "dataset_key": "gsnipers-sem-demo-v1",
        "dataset_version": "2026-09-08-v1",
        "status": "active",
        "version": 1,
    }
    row.update(overrides)
    return row


def binding():
    return source.SemDemoBinding(16, 990000016, "gsnipers-sem-demo-v1", "2026-09-08-v1", 1)


def run(coro):
    return asyncio.run(coro)


def test_unprotected_identity_stays_primary_without_binding_query():
    session = PrimarySession()
    decision = run(source.resolve_sem_data_source(settings(), context(15), session))
    assert decision == source.SemDataSourceDecision(source="primary")
    assert session.calls == []


@pytest.mark.parametrize(
    ("rows", "revisions"),
    [([], None), ([binding_row(status="disabled")], None), ([binding_row(), binding_row()], None), (None, ["0097_old"])],
)
def test_protected_identity_requires_one_active_binding_at_exact_revision(rows, revisions):
    session = PrimarySession(rows=rows, revisions=revisions)
    with pytest.raises(source.SemDemoSourceError):
        run(source.resolve_sem_data_source(settings(), context(), session))


def test_binding_failure_is_generic_503_and_never_primary_fallback():
    req = request("/api/v1/dashboard/cockpit", "tenant_id=16")
    with pytest.raises(HTTPException) as error:
        run(source.enforce_sem_demo_access(settings(), req, context(), PrimarySession(rows=[])))
    assert error.value.status_code == 503
    assert not hasattr(req.state, "sem_data_source_decision")


@pytest.mark.parametrize(
    "path,query",
    [
        ("/api/v1/dashboard/cockpit", "tenant_id=16"),
        ("/api/v1/keywords/cockpit", "tenant_id=16"),
        ("/api/v1/keywords/cockpit/900000001", "tenant_id=16"),
        ("/api/v1/search-terms/cockpit", "tenant_id=16"),
        ("/api/v1/auth/me", ""),
        ("/api/v1/auth/modules", ""),
        ("/api/v1/auth/tenants", "module=sem"),
    ],
)
def test_bound_identity_allows_only_approved_reads(path, query):
    req = request(path, query)
    assert run(source.enforce_sem_demo_access(settings(), req, context(), PrimarySession())) == context()
    assert req.state.sem_data_source_decision.source == "demo"


@pytest.mark.parametrize(
    "path,method,query",
    [
        ("/api/v1/dashboard/today", "GET", "tenant_id=16"),
        ("/api/v1/reports/monthly", "GET", "tenant_id=16"),
        ("/api/v1/oauth/baidu/status", "GET", "tenant_id=16"),
        ("/api/v1/oauth/baidu/authorize", "POST", "tenant_id=16"),
        ("/api/v1/dashboard/cockpit", "HEAD", "tenant_id=16"),
        ("/api/v1/sync/run", "POST", "tenant_id=16"),
        ("/api/v1/ai/analyze", "POST", "tenant_id=16"),
        ("/api/v1/sem/tasks", "POST", "tenant_id=16"),
        ("/api/v1/auth/tenants", "GET", "module=seo"),
    ],
)
def test_bound_identity_blocks_every_nonapproved_route(path, method, query):
    with pytest.raises(HTTPException) as error:
        run(source.enforce_sem_demo_access(settings(), request(path, query, method), context(), PrimarySession()))
    assert error.value.status_code in {403, 400}


@pytest.mark.parametrize(
    "req",
    [
        request("/api/v1/dashboard/cockpit", "tenant_id=16&database=sem_demo"),
        request("/api/v1/dashboard/cockpit", "tenant_id=16", headers=(("X-Dataset-Key", "x"),)),
        request("/api/v1/dashboard/cockpit", "tenant_id=16", headers=(("X-Tenant-ID", "16"),)),
    ],
)
def test_client_cannot_select_source(req):
    session = PrimarySession()
    with pytest.raises(HTTPException) as error:
        run(source.enforce_sem_demo_access(settings(), req, context(), session))
    assert error.value.status_code == 400
    assert session.calls == []


@pytest.mark.parametrize("query", ["", "tenant_id=16&tenant_id=16", "tenant_id=990000016", "tenant_id=15"])
def test_business_read_requires_one_production_principal_tenant(query):
    with pytest.raises(HTTPException) as error:
        run(source.enforce_sem_demo_access(settings(), request("/api/v1/dashboard/cockpit", query), context(), PrimarySession()))
    assert error.value.status_code in {403, 422}


def test_internal_tenant_translation_and_public_identity_are_consistent():
    req = request("/api/v1/dashboard/cockpit", "tenant_id=16")
    req.state.sem_data_source_decision = source.SemDataSourceDecision("demo", binding())
    assert source.resolve_sem_data_tenant_id(req, 16) == 990000016
    result = source.present_sem_read_result(req, 16, {"tenant_id": 990000016, "metrics": {}})
    assert result == {"tenant_id": 16, "metrics": {}}
    with pytest.raises(HTTPException) as error:
        source.present_sem_read_result(req, 16, {"tenant_id": 17})
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "overrides",
    [
        {"sem_demo_database_url": "postgresql+psycopg://reader@demo-db/sem_demo"},
        {"sem_demo_database_host_allowlist": "other-db"},
        {"sem_demo_database_name": "sem_prod", "sem_demo_database_url": "postgresql+asyncpg://reader@prod-db/sem_prod"},
        {"sem_demo_database_server_addr_allowlist": "*"},
        {"sem_demo_database_schema_revision": ""},
    ],
)
def test_demo_database_target_rejects_untrusted_configuration(overrides):
    with pytest.raises(source.SemDemoSourceError):
        source._demo_database_target(settings(**overrides))


def test_startup_configuration_is_atomic():
    source.validate_sem_demo_source_settings(settings(sem_demo_data_source_enabled=False, sem_demo_principal_tenant_ids=""))
    with pytest.raises(RuntimeError):
        source.validate_sem_demo_source_settings(settings(sem_demo_data_source_enabled=True, sem_demo_principal_tenant_ids=""))
    with pytest.raises(RuntimeError):
        source.validate_sem_demo_source_settings(settings(sem_demo_data_source_enabled=False))
    source.validate_sem_demo_source_settings(settings())


class DemoSession:
    def __init__(self, *, readonly="on", marker=None, accounts=(1, 0, 0), unsafe_table=False, unsafe_sequence=False):
        self.readonly = readonly
        self.marker = marker or [("active", "demo", "gsnipers-sem-demo-v1", "2026-09-08-v1")]
        self.accounts = accounts
        self.unsafe = iter((unsafe_table, unsafe_sequence))

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "current_database" in sql:
            return Result(one=("sem_demo", "10.0.0.18", self.readonly))
        if "alembic_version" in sql:
            return Result(scalars=["0097_sem_demo_fixture"])
        if "tenant_modules" in sql:
            return Result(rows=self.marker)
        if "baidu_accounts" in sql:
            return Result(one=self.accounts)
        raise AssertionError(sql)

    async def scalar(self, statement):
        return next(self.unsafe)


def validate_demo(session):
    return run(source._validate_demo_session(session, binding(), "sem_demo", frozenset({"10.0.0.18"}), "0097_sem_demo_fixture"))


def test_demo_session_requires_readonly_role_matching_marker_and_disabled_accounts():
    validate_demo(DemoSession())
    for session in (
        DemoSession(readonly="off"),
        DemoSession(marker=[("active", "demo", "wrong", "2026-09-08-v1")]),
        DemoSession(accounts=(0, 0, 0)),
        DemoSession(accounts=(1, 1, 0)),
        DemoSession(accounts=(1, 0, 1)),
        DemoSession(unsafe_table=True),
        DemoSession(unsafe_sequence=True),
    ):
        with pytest.raises(source.SemDemoSourceError):
            validate_demo(session)


class DemoSessionContext:
    def __init__(self):
        self.session = SimpleNamespace(execute=self.execute, rollback=self.rollback)
        self.open = False
        self.rolled_back = False

    async def execute(self, statement):
        assert str(statement) == "SET TRANSACTION READ ONLY"

    async def rollback(self):
        self.rolled_back = True

    async def __aenter__(self):
        self.open = True
        return self.session

    async def __aexit__(self, *_args):
        self.open = False


def test_demo_reader_keeps_verified_session_open_through_handler_and_rolls_back(monkeypatch):
    req = request("/api/v1/dashboard/cockpit", "tenant_id=16")
    req.state.sem_data_source_decision = source.SemDataSourceDecision("demo", binding())
    context_manager = DemoSessionContext()
    monkeypatch.setattr(source, "get_settings", lambda: settings())
    monkeypatch.setattr(source, "_demo_session_factory", lambda _url: lambda: context_manager)

    async def accept(*_args):
        return None

    monkeypatch.setattr(source, "_validate_demo_session", accept)

    async def exercise():
        dependency = source.get_sem_read_session(req, context(), PrimarySession())
        yielded = await anext(dependency)
        assert yielded is context_manager.session
        assert context_manager.open is True
        await dependency.aclose()

    run(exercise())
    assert context_manager.rolled_back is True
    assert context_manager.open is False


def test_only_approved_handlers_import_the_demo_session_and_workers_cannot_reach_it():
    handlers = {
        "app/api/dashboard.py": 1,
        "app/api/keywords.py": 2,
        "app/api/search_terms.py": 1,
    }
    for relative, expected in handlers.items():
        body = (BASE / relative).read_text(encoding="utf-8")
        assert body.count("Depends(get_sem_read_session)") == expected
    for relative in ("app/scheduler.py", "app/baidu", "app/ai"):
        path = BASE / relative
        bodies = [path.read_text(encoding="utf-8")] if path.is_file() else [item.read_text(encoding="utf-8") for item in path.rglob("*.py")]
        assert all("sem_demo_source" not in body and "_demo_session_factory" not in body for body in bodies)
