import asyncio
import json
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
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
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


def binding(**overrides):
    values = {
        "principal_user_id": 41,
        "principal_tenant_id": 7,
        "tenant_id": 901,
        "site_ids": [902],
        "dataset_key": "seo-demo-v1",
        "schema_revision": "0095_adopt_geo_ticket",
        "enabled": True,
    }
    values.update(overrides)
    return values


def settings(**overrides):
    values = {
        "database_url": "postgresql+asyncpg://u:p@primary-db/gsnipers",
        "seo_demo_data_source_enabled": True,
        "seo_demo_principal_user_ids": "41",
        "seo_demo_bindings_json": json.dumps([binding()]),
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
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query.encode(),
            "headers": list(headers),
            "path_params": path_params or {},
        }
    )


def test_only_server_listed_identity_selects_demo_source():
    decision = resolve_seo_data_source(settings(), context())
    assert decision.source == "demo"
    assert decision.binding is not None
    assert decision.binding.tenant_id == 901
    assert resolve_seo_data_source(settings(), context(user_id=42)).source == "primary"
    assert resolve_seo_data_source(settings(), context(user_id=None, tenant_id=None)).source == "primary"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"seo_demo_data_source_enabled": False}, "disabled"),
        ({"seo_demo_bindings_json": "[]"}, "missing"),
        ({"seo_demo_bindings_json": json.dumps([binding(), binding()])}, "ambiguous"),
        ({"seo_demo_bindings_json": json.dumps([binding(enabled=False)])}, "disabled"),
    ],
)
def test_missing_ambiguous_or_disabled_binding_fails_closed(overrides, message):
    with pytest.raises(DemoDataSourceError, match=message):
        resolve_seo_data_source(settings(**overrides), context())


def test_binding_rejects_identity_tenant_mismatch_and_loose_values():
    with pytest.raises(DemoDataSourceError, match="identity tenant"):
        resolve_seo_data_source(settings(), context(tenant_id=8))
    with pytest.raises(DemoDataSourceError, match="positive integer"):
        resolve_seo_data_source(
            settings(seo_demo_bindings_json=json.dumps([binding(principal_user_id=41.0)])),
            context(),
        )
    with pytest.raises(DemoDataSourceError, match="fields"):
        resolve_seo_data_source(
            settings(seo_demo_bindings_json=json.dumps([{**binding(), "database": "prod"}])),
            context(),
        )


def test_demo_auth_rejects_client_routing_write_oauth_and_wrong_scope(monkeypatch):
    monkeypatch.setattr("app.seo_demo_source.get_settings", settings)
    cases = (
        request(query="dataset=other"),
        request(headers=((b"x-seo-database", b"prod"),)),
        request(method="POST"),
        request(path="/api/v1/seo/oauth/status"),
        request(query="tenant_id=7"),
        request(query="tenant_id=901&site_id=999"),
    )
    expected = (400, 400, 403, 403, 403, 403)
    for candidate, status in zip(cases, expected, strict=True):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(require_seo_auth(candidate, context()))
        assert caught.value.status_code == status


def test_demo_auth_maps_only_the_trusted_tenant_and_site(monkeypatch):
    monkeypatch.setattr("app.seo_demo_source.get_settings", settings)
    req = request(query="tenant_id=901&site_id=902")
    mapped = asyncio.run(require_seo_auth(req, context()))
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
        {
            "seo_demo_database_url": "postgresql+asyncpg://u:p@primary-db/gsnipers",
            "seo_demo_database_host_allowlist": "primary-db",
            "seo_demo_database_name": "gsnipers",
        },
    ],
)
def test_demo_database_target_rejects_incomplete_unapproved_or_primary_target(overrides):
    with pytest.raises(DemoDataSourceError):
        _demo_database_target(settings(**overrides))


class Result:
    def __init__(self, *, scalar=None, rows=()):
        self.scalar = scalar
        self.rows = list(rows)

    def scalar_one(self):
        return self.scalar

    def scalars(self):
        return iter(self.rows)

    def all(self):
        return self.rows

    def one(self):
        assert len(self.rows) == 1
        return self.rows[0]


class DemoSession:
    def __init__(
        self,
        *,
        revision="0095_adopt_geo_ticket",
        marker="seo-demo-v1",
        server_address="192.0.2.10",
    ):
        self.revision = revision
        self.marker = marker
        self.server_address = server_address

    async def execute(self, statement, parameters=None):
        sql = str(statement)
        if "current_database" in sql:
            return Result(rows=[("gsnipers_demo", self.server_address)])
        if "alembic_version" in sql:
            return Result(rows=[self.revision])
        if "FROM seo_sites" in sql:
            return Result(rows=[(902, 901, self.marker, "true", "true", "true")])
        raise AssertionError(sql)


def test_demo_session_requires_exact_revision_dataset_and_safety_flags():
    reviewed = SeoDemoBinding(**binding(site_ids=(902,)))
    asyncio.run(
        _validate_demo_session(
            DemoSession(), reviewed, "gsnipers_demo", frozenset({"192.0.2.10"})
        )
    )
    with pytest.raises(DemoDataSourceError, match="revision"):
        asyncio.run(
            _validate_demo_session(
                DemoSession(revision="0094_seo_qa_batches"),
                reviewed,
                "gsnipers_demo",
                frozenset({"192.0.2.10"}),
            )
        )
    with pytest.raises(DemoDataSourceError, match="marker"):
        asyncio.run(
            _validate_demo_session(
                DemoSession(marker="seo-demo-v2"),
                reviewed,
                "gsnipers_demo",
                frozenset({"192.0.2.10"}),
            )
        )
    with pytest.raises(DemoDataSourceError, match="identity"):
        asyncio.run(
            _validate_demo_session(
                DemoSession(server_address="192.0.2.11"),
                reviewed,
                "gsnipers_demo",
                frozenset({"192.0.2.10"}),
            )
        )


def test_demo_session_is_read_only_and_always_rolled_back(monkeypatch):
    reviewed = SeoDemoBinding(**binding(site_ids=(902,)))
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
    monkeypatch.setattr(
        "app.seo_demo_source._demo_database_target",
        lambda _settings: (
            "postgresql+asyncpg://u:p@demo-db/gsnipers_demo",
            "gsnipers_demo",
            frozenset({"192.0.2.10"}),
        ),
    )
    monkeypatch.setattr("app.seo_demo_source._demo_session_factory", lambda _url: lambda: session)

    validated = []

    async def validate(
        candidate, candidate_binding, expected_database, expected_server_addresses
    ):
        validated.append(
            (candidate, candidate_binding, expected_database, expected_server_addresses)
        )

    monkeypatch.setattr("app.seo_demo_source._validate_demo_session", validate)

    async def run():
        stream = get_seo_session(req, context())
        yielded = await anext(stream)
        assert yielded is session
        await stream.aclose()

    asyncio.run(run())
    assert session.executed == ["SET TRANSACTION READ ONLY"]
    assert validated == [
        (session, reviewed, "gsnipers_demo", frozenset({"192.0.2.10"}))
    ]
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
        "app/api/seo.py",
        "app/api/seo_backlink_workflow.py",
        "app/api/seo_cockpit.py",
        "app/api/seo_qa.py",
        "app/api/seo_remediation.py",
        "app/api/seo_site_diagnostics.py",
        "app/api/seo_video.py",
    ):
        source = open(os.path.join(root, relative), encoding="utf-8").read()
        assert "get_seo_session as get_session" in source
        assert "from app.database import get_session" not in source
    customer_source = open(
        os.path.join(root, "app/api/customer_modules.py"), encoding="utf-8"
    ).read()
    assert customer_source.count("Depends(get_seo_session)") == 5
    scheduler_source = open(
        os.path.join(root, "app/seo_scheduler.py"), encoding="utf-8"
    ).read()
    assert "seo_demo_database" not in scheduler_source
