"""SEO manual-write contract. All implementation modules are required.

Run with test settings (disable Settings.env_file before application imports).
The PostgreSQL companion exercises real mounted handlers and commit races.
"""
import asyncio
from dataclasses import dataclass, FrozenInstanceError
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException, Request

from app.config import Settings, get_settings
from app.models.role import Role
from app.security import advisor_tenant_auth as guard, auth
from test_advisor_tenant_auth import local_db, claims  # noqa: F401 -- shared SQL fixture


@dataclass(frozen=True)
class Case:
    method: str
    template: str
    body: dict
    permission: str

    @property
    def path(self):
        return self.template.format(fact_id=30, asset_id=40, content_id=1, task_id=500)


PREFIX = "/api/v1/seo"
CASES = (
    Case("POST", PREFIX + "/qa/facts", dict(tenant_id=4, site_id=2,
         title="Manual fact", statement="Customer supplied evidence", source_name="fixture"), "seo.content"),
    Case("PATCH", PREFIX + "/qa/facts/{fact_id}", dict(tenant_id=4, site_id=2,
         title="Edited fact", statement="Updated evidence", source_name="fixture", version=1), "seo.content"),
    Case("POST", PREFIX + "/rank-serp/brand-assets", dict(tenant_id=4, site_id=2,
         asset_type="official_domain", name="New rule", match_value="new.example.test"), "seo.keywords"),
    Case("PATCH", PREFIX + "/rank-serp/brand-assets/{asset_id}", dict(name="Edited rule"), "seo.keywords"),
    Case("POST", PREFIX + "/content-assets", dict(tenant_id=4, site_id=2,
         title="Manual article", draft="<p>Written by a person</p>", keyword_ids=[20]), "seo.content"),
    Case("PATCH", PREFIX + "/content-assets/{content_id}", dict(title="Edited article",
         draft="<p>Manual revision</p>", keyword_ids=[20], version_count=1), "seo.content"),
    Case("PUT", PREFIX + "/content-assets/{content_id}/source-page",
         dict(source_page_id=50, version_count=1), "seo.content"),
)
CASE_IDS = [c.method + " " + c.template for c in CASES]
OUTSIDE = (
    ("POST", "/content-assets/{content_id}/submit-review"),
    ("POST", "/content-assets/{content_id}/review"),
    ("POST", "/content-ai/assist"),
    ("POST", "/content-distribution/publish"),
    ("POST", "/content-distribution/variants/generate"),
    ("POST", "/content-assets/offline-handoff/export"),
    ("POST", "/content-assets/offline-handoff/import-receipts"),
    ("PUT", "/workbench/service-plan"),
    ("POST", "/workbench/service-plan/run"),
    ("POST", "/workbench/content-assets/{content_id}/confirmations"),
    ("POST", "/workbench/content-assets/{content_id}/conversation/messages"),
    ("DELETE", "/content-assets/{content_id}"),
    ("POST", "/future-manual-write"),
)
FORBIDDEN = {
    "published_at": "2026-01-01T00:00:00Z", "published": True,
    "page_url": "https://example.test/published", "owner_user_id": 9,
    "advisor_user_id": 9, "verified": True, "public_use_allowed": True,
    "archived": True, "delete": True, "future_field": "ignored?",
}


@pytest.fixture
def routes_contract():
    from app.security import advisor_write_routes
    return advisor_write_routes


@pytest.fixture
def objects_contract():
    from app.security import advisor_write_objects
    return advisor_write_objects


@pytest.fixture
def complete_contract(routes_contract, objects_contract):
    from app.security import advisor_write_commit
    assert callable(advisor_write_commit.recheck_advisor_before_commit)
    return routes_contract


def actor(**changes):
    values = dict(user_id=7, username="test-advisor", role_name="test", tenant_id=4,
                  permissions={"seo.site": "edit", "seo.content": "edit", "seo.keywords": "edit"},
                  is_advisor=True, scope_kind="advisor_tenant", grant_id=10,
                  auth_exp=claims()["auth_exp"], advisor_tenant_ids=frozenset({4, 6}))
    return auth.AuthContext(**{**values, **changes})


def request_for(case=CASES[5], *, body=None, query="tenant_id=4&site_id=2", template=None, method=None):
    payload = json.dumps(case.body if body is None else body).encode()
    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}
    path_params = {name: value for name, value in (("fact_id", 30), ("asset_id", 40),
                   ("content_id", 1)) if "{" + name + "}" in case.template}
    return Request({"type": "http", "method": method or case.method, "path": case.path,
                    "query_string": query.encode(), "headers": [(b"content-type", b"application/json")],
                    "path_params": path_params, "route": SimpleNamespace(path=template or case.template)}, receive)


def switches(monkeypatch, *, enabled=True, old=True):
    """Use only the test process' settings; never load an env file here."""
    import sys
    settings = get_settings().model_copy(update={"advisor_scoped_content_writes_enabled": enabled,
                                                "advisor_high_risk_writes_enabled": old})
    for name, module in tuple(sys.modules.items()):
        if name.startswith("app.") and hasattr(module, "get_settings"):
            monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "_jwt_secret", lambda: "scoped-write-test-signing-key-only")
    return settings


def bearer(**changes):
    return {"Authorization": "Bearer " + jwt.encode(claims(**{"sub": "7", "tid": 4, "gid": 10, **changes}),
            "scoped-write-test-signing-key-only", algorithm=auth.JWT_ALG)}


def denied(exc, status=403, code=None):
    assert exc.status_code == status
    if code:
        assert exc.detail["code"] == code


def test_switch_defaults_to_false(routes_contract, monkeypatch):
    monkeypatch.delenv("ADVISOR_SCOPED_CONTENT_WRITES_ENABLED", raising=False)
    field = Settings.model_fields["advisor_scoped_content_writes_enabled"]
    assert field.default is False
    assert Settings(_env_file=None, database_url="postgresql+asyncpg://test:test@127.0.0.1:1/test",
                    baidu_app_id="test", baidu_secret_key="test",
                    crypto_master_key_b64="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=").advisor_scoped_content_writes_enabled is False


def test_exactly_seven_scoped_routes(routes_contract):
    assert {(c.method, c.template) for c in CASES} <= set(routes_contract.WRITE_ROUTES)
    for case in CASES:
        rule = routes_contract.WRITE_ROUTES[(case.method, case.template)]
        assert (rule.method, rule.template) == (case.method, case.template)
        assert isinstance(rule.fields, frozenset) and isinstance(rule.forbidden, frozenset)
        assert rule.edit_all == (case.permission,)
        assert rule.assignment == "site"
        with pytest.raises(FrozenInstanceError):
            rule.method = "DELETE"


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_rule_matches_route_template_and_accepts_safe_fields(routes_contract, case):
    rule = routes_contract.match_write_rule(request_for(case))
    assert rule is routes_contract.WRITE_ROUTES[(case.method, case.template)]
    routes_contract.check_write_fields(rule, dict(case.body))


@pytest.mark.parametrize("index,extra", [
    (0, {"source_url": "https://evidence.example.test/report", "expires_at": "2099-01-01T00:00:00Z"}),
    (1, {"source_url": "https://evidence.example.test/report", "expires_at": "2099-01-01T00:00:00Z"}),
    (2, {"platform": "website"}),
    (3, {"match_value": "edited.example.test", "platform": "website"}),
    (4, {"outline": "Manual outline", "humanized_content": "Manual prose", "source_text": "Source notes",
         "keyword_id": 20, "source_page_id": 50, "content_type": "landing", "status": "drafting"}),
    (5, {"outline": "Manual outline", "humanized_content": "Manual prose", "source_text": "Source notes",
         "keyword_id": 20, "source_page_id": 50}),
])
def test_documented_optional_manual_fields_are_accepted(routes_contract, index, extra):
    case = CASES[index]
    rule = routes_contract.WRITE_ROUTES[(case.method, case.template)]
    routes_contract.check_write_fields(rule, {**case.body, **extra})


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("variant", ["delete", "suffix", "unresolved"])
def test_rule_never_uses_prefix_or_raw_url(routes_contract, case, variant):
    request = request_for(case, method="DELETE" if variant == "delete" else None,
                          template=case.template + "/extra" if variant == "suffix" else None)
    if variant == "unresolved":
        request.scope.pop("route")
    assert routes_contract.match_write_rule(request) is None


@pytest.mark.parametrize("method,suffix", OUTSIDE)
def test_adjacent_and_high_risk_routes_not_matched(routes_contract, method, suffix):
    case = Case(method, PREFIX + suffix, {}, "seo.content")
    assert routes_contract.match_write_rule(request_for(case)) is None


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("field,value", FORBIDDEN.items())
def test_rule_rejects_forbidden_and_unknown_fields(routes_contract, case, field, value):
    rule = routes_contract.WRITE_ROUTES[(case.method, case.template)]
    with pytest.raises(HTTPException) as caught:
        routes_contract.check_write_fields(rule, {**case.body, field: value})
    denied(caught.value, code="ADVISOR_WRITE_FIELD_FORBIDDEN")


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("old", [False, True])
def test_switch_off_keeps_all_writes_closed(monkeypatch, case, old):
    switches(monkeypatch, enabled=False, old=old)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(guard.enforce_advisor_request(request_for(case), actor(), SimpleNamespace()))
    denied(caught.value, code="ADVISOR_HIGH_RISK_WRITES_DISABLED")


@pytest.mark.parametrize("method,suffix", OUTSIDE)
def test_enabled_switch_still_denies_non_allowlisted_writes(monkeypatch, routes_contract, method, suffix):
    switches(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(guard.enforce_advisor_request(request_for(Case(method, PREFIX + suffix, {}, "seo.content")),
                                                  actor(), SimpleNamespace()))
    denied(caught.value, code="ADVISOR_HIGH_RISK_WRITES_DISABLED")


@pytest.mark.parametrize("superadmin", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_non_advisor_guard_behavior_unchanged(monkeypatch, superadmin, enabled):
    switches(monkeypatch, enabled=enabled)
    ctx = actor(is_advisor=False, is_superadmin=superadmin)
    asyncio.run(guard.enforce_advisor_request(request_for(), ctx, SimpleNamespace()))


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("permission", ["edit", "view", "missing"])
def test_guard_pipeline_preserves_body_and_requires_each_edit(monkeypatch, complete_contract,
                                                              objects_contract, case, permission):
    """SQL object checks have their own suite; here verify guard wiring/order."""
    switches(monkeypatch)
    from app import module_scope
    from sqlalchemy.ext.asyncio import AsyncSession
    check_objects = AsyncMock()
    check_assignment = AsyncMock()
    monkeypatch.setattr(objects_contract, "check_write_objects", check_objects)
    monkeypatch.setattr(objects_contract, "ensure_advisor_assignment", check_assignment)
    monkeypatch.setattr(objects_contract, "lock_manual_write_scope", AsyncMock())
    # Also replace module-scope aliases, if the implementation uses those.
    for name, replacement in (("check_write_objects", check_objects),
                              ("ensure_advisor_assignment", check_assignment)):
        if hasattr(guard, name):
            monkeypatch.setattr(guard, name, replacement)
    monkeypatch.setattr(module_scope, "ensure_module_access", AsyncMock())
    monkeypatch.setattr(guard, "check_seo_objects", AsyncMock())
    ctx = actor()
    if permission == "missing":
        ctx.permissions.pop(case.permission)
    else:
        ctx.permissions[case.permission] = permission
    request = request_for(case)
    async def run():
        async with AsyncSession() as session:
            if permission == "edit":
                await guard.enforce_advisor_request(request, ctx, session)
                assert request.state.advisor_scoped_write is complete_contract.WRITE_ROUTES[(case.method, case.template)]
                assert await request.json() == case.body
                assert await request.json() == case.body  # A handler can still read cached JSON.
                check_objects.assert_awaited_once()
                check_assignment.assert_awaited_once()
                called = check_objects.await_args
                assert (called.args[3] if len(called.args) > 3 else called.kwargs["body"]) == case.body
            else:
                with pytest.raises(HTTPException) as caught:
                    await guard.enforce_advisor_request(request, ctx, session)
                denied(caught.value)
                check_objects.assert_not_awaited()
                check_assignment.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_real_auth_http_switch_off_never_reaches_handler(local_db, monkeypatch, case):
    """Actual SQL user/grant + signed fake JWT + FastAPI require_auth dependency."""
    switches(monkeypatch, enabled=False)
    db, session = local_db
    db.get(Role, 1).permissions = {"seo.site": "edit", "seo.content": "edit", "seo.keywords": "edit"}
    db.commit()
    app, called = FastAPI(), []
    async def local_session():
        yield session
    from app.database import get_session
    app.dependency_overrides[get_session] = local_session
    async def handler(ctx=Depends(auth.require_auth)):
        called.append(ctx)
        return {"saved": True}
    app.add_api_route(case.template, handler, methods=[case.method])
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local.test") as client:
            headers = {"Authorization": "Bearer " + jwt.encode(claims(),
                       "scoped-write-test-signing-key-only", algorithm=auth.JWT_ALG)}
            response = await client.request(case.method, case.path + "?tenant_id=1", json=case.body, headers=headers)
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "ADVISOR_HIGH_RISK_WRITES_DISABLED"
            assert not called
    asyncio.run(run())
