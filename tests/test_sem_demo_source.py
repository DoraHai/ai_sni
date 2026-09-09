"""Offline security contracts for the SEM same-site demo adapter."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:1/test")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ.setdefault("ADMIN_API_KEY", "local-test-only")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdef")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")

from app import sem_demo_source as source
from app.security import auth
from app.security.auth import AuthContext

BASE = Path(__file__).resolve().parents[1]
REVISION = "0098_demo_binding_no_truncate"
MANIFEST = "a" * 64


def settings(**overrides):
    values = {
        "database_url": "postgresql+asyncpg://prod@prod-db:5432/sem_prod",
        "sem_demo_data_source_enabled": True,
        "sem_demo_principal_tenant_ids": "16",
        "sem_demo_binding_schema_revision": REVISION,
        "sem_demo_database_url": "postgresql+asyncpg://sem_demo_app@demo-db:5432/gsnipers_demo",
        "sem_demo_database_name": "gsnipers_demo",
        "sem_demo_database_user": "sem_demo_app",
        "sem_demo_database_host_allowlist": "demo-db",
        "sem_demo_database_server_addr_allowlist": "10.0.0.18",
        "sem_demo_database_schema_revision": REVISION,
        "sem_demo_dataset_key": "gsnipers-sem-demo-v1",
        "sem_demo_dataset_version": "demo-20260909-v1",
        "sem_demo_manifest_sha256": MANIFEST,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def context(tenant_id=16, permissions=None, superadmin=False):
    return AuthContext(
        5, "reader", "viewer", tenant_id,
        permissions or {"monitor.dashboard": "view"}, superadmin,
    )


def request(path, query="", method="GET", headers=()):
    return Request({
        "type": "http", "http_version": "1.1", "method": method,
        "scheme": "https", "path": path, "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        "client": ("127.0.0.1", 1234), "server": ("example.test", 443),
    })


class ScalarRows:
    def __init__(self, values): self.values = values
    def __iter__(self): return iter(self.values)


class Result:
    def __init__(self, *, rows=(), scalars=(), one=None):
        self.rows = list(rows); self.scalar_values = list(scalars); self.one_value = one
    def scalars(self): return ScalarRows(self.scalar_values)
    def mappings(self): return SimpleNamespace(all=lambda: list(self.rows))
    def all(self): return list(self.rows)
    def one(self): return self.one_value
    def one_or_none(self): return self.one_value


def binding_row(**overrides):
    row = {
        "tenant_id": 16, "demo_tenant_id": 990000001,
        "dataset_key": "gsnipers-sem-demo-v1",
        "dataset_version": "demo-20260909-v1",
        "status": "active", "version": 1,
    }
    row.update(overrides)
    return row


def binding():
    return source.SemDemoBinding(
        16, 990000001, "gsnipers-sem-demo-v1", "demo-20260909-v1", 1
    )


class PrimarySession:
    def __init__(self, rows=None, revisions=None, all_states=None):
        self.rows = [binding_row()] if rows is None else rows
        self.revisions = [REVISION] if revisions is None else revisions
        self.all_states = (
            [{"tenant_id": row["tenant_id"], "status": row["status"]} for row in self.rows]
            if all_states is None else all_states
        )
        self.calls = []
    async def execute(self, statement, params=None):
        sql = str(statement); self.calls.append((sql, params))
        if "alembic_version" in sql: return Result(scalars=self.revisions)
        if "WHERE tenant_id" in sql and "demo_tenant_bindings" in sql:
            tenant_id = params["tenant_id"]
            return Result(rows=[r for r in self.rows if r["tenant_id"] == tenant_id])
        if "demo_tenant_bindings" in sql: return Result(rows=self.all_states)
        raise AssertionError(sql)


def run(coro): return asyncio.run(coro)


def test_production_without_binding_is_unchanged_and_disabled_feature_does_not_probe():
    session = PrimarySession(rows=[])
    decision = run(source.resolve_sem_data_source(
        settings(sem_demo_data_source_enabled=False, sem_demo_principal_tenant_ids=""),
        context(15), session,
    ))
    assert decision.source == "primary" and session.calls == []
    session = PrimarySession(rows=[])
    assert run(source.resolve_sem_data_source(settings(), context(15), session)).source == "primary"


@pytest.mark.parametrize(
    "rows,revisions",
    [([], None), ([binding_row(status="disabled")], None),
     ([binding_row(), binding_row()], None), (None, ["0097_demo_tenant_bindings"])],
)
def test_protected_tenant_requires_exact_0098_active_binding(rows, revisions):
    with pytest.raises(source.SemDemoSourceError):
        run(source.resolve_sem_data_source(
            settings(), context(), PrimarySession(rows=rows, revisions=revisions)
        ))


def test_active_binding_requires_server_approved_dataset():
    with pytest.raises(source.SemDemoSourceError):
        run(source.resolve_sem_data_source(
            settings(sem_demo_dataset_version="other"), context(), PrimarySession()
        ))


def test_binding_failure_is_generic_503_and_never_falls_back_to_primary():
    req = request("/api/v1/dashboard/cockpit", "tenant_id=16")
    req.state.sem_effective_tenant_id = 16
    with pytest.raises(HTTPException) as error:
        run(source.enforce_sem_demo_access(
            settings(), req, context(), PrimarySession(rows=[])
        ))
    assert error.value.status_code == 503
    assert not hasattr(req.state, "sem_data_source_decision")


@pytest.mark.parametrize("path", [
    "/api/v1/dashboard/cockpit", "/api/v1/keywords/cockpit",
    "/api/v1/keywords/cockpit/900000001", "/api/v1/search-terms/cockpit",
])
def test_only_four_business_gets_are_allowed(path):
    req = request(path, "tenant_id=16")
    req.state.sem_effective_tenant_id = 16
    assert run(source.enforce_sem_demo_access(settings(), req, context(), PrimarySession())) == context()
    assert req.state.sem_data_source_decision.source == "demo"


@pytest.mark.parametrize(
    "query", ["", "tenant_id=16&tenant_id=16", "tenant_id=990000001", "tenant_id=15"]
)
def test_demo_read_requires_one_production_principal_tenant(query):
    req = request("/api/v1/dashboard/cockpit", query)
    req.state.sem_effective_tenant_id = 16
    with pytest.raises(HTTPException) as error:
        run(source.enforce_sem_demo_access(settings(), req, context(), PrimarySession()))
    assert error.value.status_code in {403, 422}


@pytest.mark.parametrize("path,method", [
    ("/api/v1/dashboard/today", "GET"), ("/api/v1/reports/monthly", "GET"),
    ("/api/v1/oauth/baidu/status", "GET"), ("/api/v1/oauth/baidu/authorize", "POST"),
    ("/api/v1/dashboard/cockpit", "HEAD"), ("/api/v1/ai/analyze", "POST"),
    ("/api/v1/sem/tasks", "POST"),
])
def test_active_binding_blocks_nonapproved_route(path, method):
    req = request(path, "tenant_id=16", method)
    req.state.sem_effective_tenant_id = 16
    with pytest.raises(HTTPException) as error:
        run(source.enforce_sem_demo_access(settings(), req, context(), PrimarySession()))
    assert error.value.status_code == 403


@pytest.mark.parametrize("req", [
    request("/api/v1/dashboard/cockpit", "tenant_id=16&database=gsnipers_demo"),
    request("/api/v1/dashboard/cockpit", "tenant_id=16", headers=(("X-Dataset-Key", "x"),)),
    request("/api/v1/dashboard/cockpit", "tenant_id=16", headers=(("X-Tenant-ID", "16"),)),
])
def test_client_cannot_select_source(req):
    req.state.sem_effective_tenant_id = 16
    session = PrimarySession()
    with pytest.raises(HTTPException) as error:
        run(source.enforce_sem_demo_access(settings(), req, context(), session))
    assert error.value.status_code == 400 and session.calls == []


def test_superadmin_effective_tenant_can_resolve_only_after_scope():
    req = request("/api/v1/dashboard/cockpit", "tenant_id=16")
    req.state.sem_effective_tenant_id = 16
    ctx = context(None, superadmin=True)
    assert run(source.enforce_sem_demo_access(settings(), req, ctx, PrimarySession())) == ctx


@pytest.mark.parametrize("overrides", [
    {"sem_demo_binding_schema_revision": "0097_demo_tenant_bindings"},
    {"sem_demo_database_schema_revision": "0097_demo_tenant_bindings"},
    {"sem_demo_database_user": "other"},
    {"sem_demo_database_url": "postgresql+psycopg://sem_demo_app@demo-db/gsnipers_demo"},
    {"sem_demo_database_host_allowlist": "other-db"},
    {"sem_demo_database_server_addr_allowlist": "*"},
    {"sem_demo_manifest_sha256": "bad"},
])
def test_target_rejects_revision_downgrade_and_untrusted_configuration(overrides):
    with pytest.raises(source.SemDemoSourceError): source._demo_database_target(settings(**overrides))


def test_startup_configuration_is_atomic_and_0098_fixed():
    source.validate_sem_demo_source_settings(settings(
        sem_demo_data_source_enabled=False, sem_demo_principal_tenant_ids=""
    ))
    with pytest.raises(RuntimeError): source.validate_sem_demo_source_settings(settings(sem_demo_principal_tenant_ids=""))
    with pytest.raises(RuntimeError): source.validate_sem_demo_source_settings(settings(sem_demo_data_source_enabled=False))
    source.validate_sem_demo_source_settings(settings())


class DemoSession:
    def __init__(self, *, identity=None, role=None, grants=None, receipt=None, marker=None, accounts=None):
        now = datetime.now(timezone.utc)
        self.identity = identity or ("gsnipers_demo", "sem_demo_app", "10.0.0.18", "on")
        self.role = role or (False, False, False, False, False, True)
        self.grants = iter((False, False, False, False) if grants is None else grants)
        self.receipt = [(
            "gsnipers-sem-demo-v1", "demo-20260909-v1", MANIFEST, REVISION,
            990000001, "ready", now, now,
        )] if receipt is None else receipt
        self.marker = [
            ("active", "demo", "gsnipers-sem-demo-v1", "demo-20260909-v1")
        ] if marker is None else marker
        self.accounts = [
            (990000101, "disabled", "demo", "disabled"),
            (990000102, "disabled", "demo", "disabled"),
        ] if accounts is None else accounts
        self.info = {}
    async def execute(self, statement, params=None):
        sql = str(statement)
        if "current_database" in sql: return Result(one=self.identity)
        if "pg_roles" in sql: return Result(one=self.role)
        if "alembic_version" in sql: return Result(scalars=[REVISION])
        if source.FIXTURE_REGISTRY_TABLE in sql: return Result(rows=self.receipt)
        if "tenant_modules" in sql: return Result(rows=self.marker)
        if "baidu_accounts" in sql: return Result(rows=self.accounts)
        if sql.startswith("SET TRANSACTION"): return Result()
        raise AssertionError(sql)
    async def scalar(self, _statement): return next(self.grants)
    async def rollback(self): self.rolled_back = True


def validate_demo(session):
    return run(source._validate_demo_session(
        session, binding(), source._demo_database_target(settings())
    ))
def test_demo_session_validates_registry_role_privileges_and_disabled_accounts():
    alias_to_id, id_to_alias = validate_demo(DemoSession())
    assert set(alias_to_id.values()) == {990000101, 990000102}
    assert {id_to_alias[v] for v in alias_to_id.values()} == set(alias_to_id)
    bad = [
        DemoSession(identity=("gsnipers_demo", "wrong", "10.0.0.18", "on")),
        DemoSession(role=(True, False, False, False, False, True)),
        DemoSession(role=(False, True, False, False, False, True)),
        DemoSession(role=(False, False, True, False, False, True)),
        DemoSession(role=(False, False, False, True, False, True)),
        DemoSession(role=(False, False, False, False, True, True)),
        DemoSession(role=(False, False, False, False, False, False)),
        DemoSession(grants=(True, False, False, False)),
        DemoSession(grants=(False, True, False, False)),
        DemoSession(grants=(False, False, True, False)),
        DemoSession(grants=(False, False, False, True)),
        DemoSession(receipt=[]),
        DemoSession(receipt=[("gsnipers-sem-demo-v1", "demo-20260909-v1", "b"*64, REVISION, 990000001, "ready", 1, 1)]),
        DemoSession(marker=[("active", "demo", "wrong", "demo-20260909-v1")]),
        DemoSession(accounts=[(990000101, "active", "demo", "disabled")]),
    ]
    for session in bad:
        with pytest.raises(source.SemDemoSourceError): validate_demo(session)


def test_account_aliases_map_request_and_all_public_response_ids():
    req = request("/api/v1/dashboard/cockpit", "tenant_id=16")
    req.state.sem_data_source_decision = source.SemDataSourceDecision("demo", binding())
    alias = source._account_alias(binding(), 990000101)
    req.state.sem_demo_account_alias_to_id = {alias: 990000101}
    req.state.sem_demo_account_id_to_alias = {990000101: alias}
    assert source.resolve_sem_data_account_id(req, alias) == 990000101
    with pytest.raises(HTTPException): source.resolve_sem_data_account_id(req, 990000101)
    result = source.present_sem_read_result(req, 16, {
        "tenant_id": 990000001,
        "account_scope": {"baidu_account_id": 990000101, "configured_account_ids": [990000101]},
        "accounts": [{"baidu_account_id": 990000101}],
    })
    assert result["tenant_id"] == 16 and result["is_demo"] is True
    assert result["accounts"][0]["baidu_account_id"] == alias
    assert result["account_scope"]["configured_account_ids"] == [alias]


def test_demo_account_scope_reads_disabled_accounts_by_internal_mapping():
    from app.sem_cockpit_readonly import resolve_account_scope

    rows = [
        SimpleNamespace(id=990000101, status="disabled"),
        SimpleNamespace(id=990000102, status="disabled"),
    ]

    class Session:
        info = {"sem_demo_read": True}

        async def execute(self, _statement):
            return SimpleNamespace(all=lambda: rows)

    payload, selected, by_id = run(resolve_account_scope(Session(), 990000001, None))
    assert selected == [990000101, 990000102]
    assert payload["configured_account_ids"] == selected
    assert payload["excluded_non_active_account_ids"] == []
    assert by_id == {990000101: "disabled", 990000102: "disabled"}


def test_action_guard_blocks_active_and_expected_missing_binding():
    with pytest.raises(source.SemDemoActionBlockedError):
        run(source.ensure_sem_production_action_allowed(settings(), PrimarySession(), 16))
    with pytest.raises(source.SemDemoActionBlockedError):
        run(source.ensure_sem_production_action_allowed(settings(), PrimarySession(rows=[]), 16))
    run(source.ensure_sem_production_action_allowed(
        settings(sem_demo_data_source_enabled=False, sem_demo_principal_tenant_ids=""), PrimarySession(rows=[]), 15
    ))


class DemoSessionContext:
    def __init__(self): self.session = DemoSession(); self.open = False
    async def __aenter__(self): self.open = True; return self.session
    async def __aexit__(self, *_args): self.open = False


def test_demo_reader_sets_readonly_before_validation_and_keeps_session_open(monkeypatch):
    req = request("/api/v1/dashboard/cockpit", "tenant_id=16")
    req.state.sem_data_source_decision = source.SemDataSourceDecision("demo", binding())
    cm = DemoSessionContext(); calls = []
    original_execute = cm.session.execute
    async def execute(statement, params=None): calls.append(str(statement)); return await original_execute(statement, params)
    cm.session.execute = execute
    monkeypatch.setattr(source, "get_settings", lambda: settings())
    monkeypatch.setattr(source, "_demo_session_factory", lambda _url: lambda: cm)
    async def exercise():
        dependency = source.get_sem_read_session(req, context(), PrimarySession())
        yielded = await anext(dependency)
        assert yielded is cm.session and cm.open is True and yielded.info["sem_demo_read"] is True
        await dependency.aclose()
    run(exercise())
    assert calls[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert cm.open is False and cm.session.rolled_back is True


def test_scoped_auth_orders_scope_rbac_entitlement_identity_before_binding(monkeypatch):
    req = request("/api/v1/dashboard/cockpit", "tenant_id=16")
    events = []
    async def module(*_args): events.append("module")
    async def identity(*_args): events.append("identity")
    async def binding_gate(*_args):
        assert req.state.sem_effective_tenant_id == 16
        events.append("binding")
    monkeypatch.setattr(auth, "ensure_module_access", module)
    monkeypatch.setattr(auth, "ensure_sem_identity_access", identity)
    monkeypatch.setattr(source, "enforce_sem_demo_access", binding_gate)
    ctx = context(16)
    assert run(auth.require_scoped_auth(req, ctx, object())) == ctx
    assert events == ["module", "identity", "binding"]


def test_source_gates_cover_claim_transport_oauth_scheduler_and_workers():
    files = {
        "app/baidu/sync.py": "ensure_sem_production_action_allowed",
        "app/baidu/writeback.py": "ensure_sem_production_action_allowed",
        "app/baidu/oauth.py": "ensure_sem_production_action_allowed",
        "app/api/oauth_baidu.py": "ensure_sem_production_action_allowed",
        "app/scheduler.py": "blocked_sem_demo_tenant_ids",
        "app/rules/engine.py": "ensure_sem_production_action_allowed",
        "app/suggestions/engine.py": "ensure_sem_production_action_allowed",
    }
    for relative, marker in files.items():
        assert marker in (BASE / relative).read_text(encoding="utf-8")
    for relative, expected in {
        "app/api/dashboard.py": 1, "app/api/keywords.py": 2,
        "app/api/search_terms.py": 1,
    }.items():
        assert (BASE / relative).read_text(encoding="utf-8").count(
            "Depends(get_sem_read_session)"
        ) == expected


def test_external_client_helpers_recheck_binding_immediately(monkeypatch):
    from app.baidu import sync, writeback

    events = []
    account = SimpleNamespace(tenant_id=16)

    async def guard(_settings, session, tenant_id):
        events.append((session, tenant_id))

    monkeypatch.setattr(sync, "ensure_sem_production_action_allowed", guard)
    monkeypatch.setattr(sync, "get_settings", lambda: settings())
    monkeypatch.setattr(sync, "_account_client", lambda _account: "sync-client")
    assert run(sync._guarded_account_client("sync-session", account)) == "sync-client"

    monkeypatch.setattr(writeback, "ensure_sem_production_action_allowed", guard)
    monkeypatch.setattr(writeback, "get_settings", lambda: settings())
    monkeypatch.setattr(writeback, "_account_client", lambda _account: "write-client")
    assert run(writeback._writeback_account_client(
        "write-session", 16, SimpleNamespace()
    )) == "write-client"
    assert events == [("sync-session", 16), ("write-session", 16)]
