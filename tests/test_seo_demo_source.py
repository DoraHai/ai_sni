import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@primary-db/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.security.auth import AuthContext
from app.seo_demo_source import (
    DemoDataSourceError,
    SeoDataSourceDecision,
    SeoDemoBinding,
    _demo_database_target,
    _validate_demo_session,
    get_seo_session,
    require_seo_auth,
    resolve_seo_data_source,
)


def binding_row(**overrides):
    values = {
        "tenant_id": 7,
        "demo_tenant_id": 901,
        "dataset_key": "seo-demo-v1",
        "dataset_version": "tiger-20260909-v1",
        "status": "active",
        "disabled_at": None,
        "version": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def reviewed_binding(**overrides):
    values = {
        "principal_tenant_id": 7,
        "tenant_id": 901,
        "dataset_key": "seo-demo-v1",
        "dataset_version": "tiger-20260909-v1",
        "binding_version": 1,
    }
    values.update(overrides)
    return SeoDemoBinding(**values)


def settings(**overrides):
    values = {
        "database_url": "postgresql+asyncpg://u:p@primary-db/gsnipers",
        "seo_demo_data_source_enabled": True,
        "seo_demo_database_url": "postgresql+asyncpg://u:p@demo-db/gsnipers_demo",
        "seo_demo_database_host_allowlist": "demo-db",
        "seo_demo_database_server_addr_allowlist": "192.0.2.10",
        "seo_demo_database_name": "gsnipers_demo",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def context(*, user_id=41, tenant_id=7):
    return AuthContext(
        user_id=user_id,
        username="demo-reader",
        role_name="viewer",
        tenant_id=tenant_id,
        permissions={"seo.dashboard": "view", "seo.content": "view"},
    )


def request(method="GET", path="/api/v1/seo/overview", query="", headers=(), path_params=None):
    return Request({"type": "http", "method": method, "path": path, "query_string": query.encode(), "headers": list(headers), "path_params": path_params or {}})


class Result:
    def __init__(self, *, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return iter(self.rows)

    def all(self):
        return self.rows

    def one(self):
        assert len(self.rows) == 1
        return self.rows[0]


class PrimarySession:
    def __init__(self, rows=(), error=None):
        self.rows = list(rows)
        self.error = error
        self.executed = []

    async def execute(self, statement, parameters=None):
        self.executed.append((str(statement), parameters))
        if self.error:
            raise self.error
        return Result(rows=self.rows)


def resolve(ctx=None, *, rows=(), configured=None, error=None):
    return asyncio.run(resolve_seo_data_source(configured or settings(), ctx or context(), PrimarySession(rows, error)))


def test_active_primary_tenant_binding_selects_demo_source():
    decision = resolve(rows=[binding_row()])
    assert decision.source == "demo"
    assert decision.binding is not None
    assert decision.binding.tenant_id == 901
    assert decision.binding.schema_revision == "0098_demo_binding_no_truncate"
    assert decision.binding.dataset_version == "tiger-20260909-v1"


def test_non_user_disabled_feature_and_unbound_tenant_stay_primary():
    assert resolve(ctx=context(user_id=None, tenant_id=None), rows=[binding_row()]).source == "primary"
    assert resolve(configured=settings(seo_demo_data_source_enabled=False), rows=[binding_row()]).source == "primary"
    assert resolve(rows=[]).source == "primary"


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([binding_row(), binding_row()], "ambiguous"),
        ([binding_row(status="disabled", disabled_at=object())], "disabled"),
        ([binding_row(dataset_version="")], "incomplete"),
        ([binding_row(version=1.0)], "positive integer"),
    ],
)
def test_invalid_trusted_binding_fails_closed(rows, message):
    with pytest.raises(DemoDataSourceError, match=message):
        resolve(rows=rows)


def test_binding_lookup_failure_fails_closed():
    with pytest.raises(DemoDataSourceError, match="lookup failed"):
        resolve(error=RuntimeError("primary unavailable"))


def test_demo_auth_rejects_client_routing_write_oauth_and_wrong_tenant(monkeypatch):
    monkeypatch.setattr("app.seo_demo_source.get_settings", settings)
    primary = PrimarySession([binding_row()])
    cases = (
        request(query="dataset=other"),
        request(headers=((b"x-seo-database", b"prod"),)),
        request(method="POST"),
        request(path="/api/v1/seo/oauth/status"),
        request(query="tenant_id=7"),
    )
    for candidate, status in zip(cases, (400, 400, 403, 403, 403), strict=True):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(require_seo_auth(candidate, context(), primary))
        assert caught.value.status_code == status


def test_demo_auth_maps_only_the_trusted_tenant(monkeypatch):
    monkeypatch.setattr("app.seo_demo_source.get_settings", settings)
    req = request(query="tenant_id=901&site_id=902")
    mapped = asyncio.run(require_seo_auth(req, context(), PrimarySession([binding_row()])))
    assert mapped.tenant_id == 901
    assert mapped.user_id == 41
    assert mapped.is_superadmin is False
    assert req.state.seo_data_source_decision.source == "demo"


@pytest.mark.parametrize(
    "overrides",
    [
        {"seo_demo_database_url": ""},
        {"seo_demo_database_host_allowlist": "*"},
        {"seo_demo_database_url": "postgresql+asyncpg://u:p@primary-db/gsnipers_demo"},
        {"seo_demo_database_url": "postgresql+asyncpg://u:p@demo-db/gsnipers"},
        {"seo_demo_database_url": "postgresql+asyncpg://u:p@primary-db/gsnipers", "seo_demo_database_host_allowlist": "primary-db", "seo_demo_database_name": "gsnipers"},
    ],
)
def test_demo_database_target_rejects_incomplete_unapproved_or_primary_target(overrides):
    with pytest.raises(DemoDataSourceError):
        _demo_database_target(settings(**overrides))


class DemoSession:
    def __init__(self, *, revision="0098_demo_binding_no_truncate", marker="seo-demo-v1", dataset_version="tiger-20260909-v1", server_address="192.0.2.10", sites=(902,)):
        self.revision = revision
        self.marker = marker
        self.dataset_version = dataset_version
        self.server_address = server_address
        self.sites = sites

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        if "current_database" in sql:
            return Result(rows=[("gsnipers_demo", self.server_address)])
        if "alembic_version" in sql:
            return Result(rows=[self.revision])
        if "FROM seo_sites" in sql:
            return Result(rows=[(site_id, 901, self.marker, self.dataset_version, "true", "true", "true") for site_id in self.sites])
        raise AssertionError(sql)


def test_demo_session_requires_exact_revision_dataset_and_safety_flags():
    reviewed = reviewed_binding()
    asyncio.run(_validate_demo_session(DemoSession(), reviewed, "gsnipers_demo", frozenset({"192.0.2.10"})))
    failures = (
        (DemoSession(revision="0097_demo_tenant_bindings"), "revision"),
        (DemoSession(marker="seo-demo-v2"), "marker"),
        (DemoSession(dataset_version="tiger-old"), "marker"),
        (DemoSession(server_address="192.0.2.11"), "identity"),
        (DemoSession(sites=()), "marker"),
    )
    for candidate, message in failures:
        with pytest.raises(DemoDataSourceError, match=message):
            asyncio.run(_validate_demo_session(candidate, reviewed, "gsnipers_demo", frozenset({"192.0.2.10"})))


def test_demo_session_is_read_only_and_always_rolled_back(monkeypatch):
    reviewed = reviewed_binding()
    req = request(query="tenant_id=901&site_id=902")
    req.state.seo_data_source_decision = SeoDataSourceDecision("demo", reviewed)

    class SessionContext:
        def __init__(self):
            self.executed = []
            self.rolled_back = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement, parameters=None):
            self.executed.append(str(statement))

        async def rollback(self):
            self.rolled_back = True

    session = SessionContext()
    monkeypatch.setattr("app.seo_demo_source._demo_database_target", lambda _settings: ("postgresql+asyncpg://u:p@demo-db/gsnipers_demo", "gsnipers_demo", frozenset({"192.0.2.10"})))
    monkeypatch.setattr("app.seo_demo_source._demo_session_factory", lambda _url: lambda: session)
    validated = []

    async def validate(candidate, candidate_binding, expected_database, expected_server_addresses):
        validated.append((candidate, candidate_binding, expected_database, expected_server_addresses))

    monkeypatch.setattr("app.seo_demo_source._validate_demo_session", validate)

    async def run():
        stream = get_seo_session(req, context())
        yielded = await anext(stream)
        assert yielded is session
        await stream.aclose()

    asyncio.run(run())
    assert session.executed == ["SET TRANSACTION READ ONLY"]
    assert validated == [(session, reviewed, "gsnipers_demo", frozenset({"192.0.2.10"}))]
    assert session.rolled_back is True


def test_primary_decision_reuses_authenticated_primary_session():
    req = request()
    req.state.seo_data_source_decision = SeoDataSourceDecision("primary")
    primary_session = object()

    async def run():
        stream = get_seo_session(req, context(user_id=42), primary_session)
        assert await anext(stream) is primary_session
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(run())


def test_every_router_mounted_by_seo_service_uses_the_resolved_session():
    root = os.path.dirname(os.path.dirname(__file__))
    for relative in (
        "app/api/seo.py", "app/api/seo_backlink_workflow.py", "app/api/seo_cockpit.py",
        "app/api/seo_qa.py", "app/api/seo_remediation.py", "app/api/seo_site_diagnostics.py", "app/api/seo_video.py",
    ):
        source = open(os.path.join(root, relative), encoding="utf-8").read()
        assert "get_seo_session as get_session" in source
        assert "from app.database import get_session" not in source
    customer_source = open(os.path.join(root, "app/api/customer_modules.py"), encoding="utf-8").read()
    assert customer_source.count("Depends(get_seo_session)") == 5
    scheduler_source = open(os.path.join(root, "app/seo_scheduler.py"), encoding="utf-8").read()
    assert "seo_demo_database" not in scheduler_source
