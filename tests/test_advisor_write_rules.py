"""A's admission/commit contract; object ownership matrix is supplied by C.

SQLite proves rollback and fresh reads, not PostgreSQL lock scheduling.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from starlette.requests import Request

from app.config import Settings, get_settings
from app.models.user import User
from app.security import advisor_tenant_auth as guard
from app.security.advisor_write_commit import recheck_advisor_before_commit
from app.security.advisor_write_routes import WRITE_ROUTES, check_write_fields, match_write_rule
from test_advisor_tenant_auth import local_db, authenticate, claims, Grant, Role


def request(rule, body, query=b"tenant_id=1"):
    raw = json.dumps(body).encode()
    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    path_params = {key: 1 for key in ("content_id", "asset_id", "fact_id") if "{" + key + "}" in rule.template}
    return Request({"type": "http", "method": rule.method,
        "path": rule.template.format(**path_params), "query_string": query,
        "headers": [(b"content-type", b"application/json")], "path_params": path_params,
        "route": SimpleNamespace(path=rule.template)}, receive)


def body_for(rule):
    if "/facts" in rule.template:
        return dict(tenant_id=1, site_id=1, title="fact", statement="source text", source_name="manual", **({"version": 1} if rule.method == "PATCH" else {}))
    if "/brand-assets" in rule.template:
        return dict(name="brand", **({"tenant_id":1, "site_id":1, "asset_type":"official_domain", "match_value":"example.test"} if rule.method == "POST" else {}))
    if rule.method == "PUT":
        return {"source_page_id":1, "version_count":1}
    return dict(title="draft", **({"tenant_id":1, "site_id":1} if rule.method == "POST" else {"version_count":1}))


@pytest.fixture
def object_contract(monkeypatch):
    module = ModuleType("app.security.advisor_write_objects")
    module.check_write_objects = AsyncMock()
    module.ensure_advisor_assignment = AsyncMock()
    module.lock_manual_write_scope = AsyncMock()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr("app.module_scope.ensure_module_access", AsyncMock())
    return module


def test_new_flag_defaults_closed_and_old_flag_is_independent():
    assert Settings.model_fields["advisor_scoped_content_writes_enabled"].default is False


@pytest.mark.parametrize("rule", WRITE_ROUTES.values())
def test_all_seven_rules_require_new_switch_and_preserve_cached_body(local_db, object_contract, monkeypatch, rule):
    settings = get_settings()
    monkeypatch.setattr(settings, "advisor_high_risk_writes_enabled", True)
    monkeypatch.setattr(settings, "advisor_scoped_content_writes_enabled", False)
    async def run():
        ctx = await authenticate(local_db[1], claims())
        ctx.permissions["seo.keywords"] = "edit"
        req = request(rule, body_for(rule))
        with pytest.raises(HTTPException) as denied:
            await guard.enforce_advisor_request(req, ctx, local_db[1])
        assert denied.value.detail["code"] == "ADVISOR_HIGH_RISK_WRITES_DISABLED"
        object_contract.check_write_objects.assert_not_called()
        monkeypatch.setattr(settings, "advisor_scoped_content_writes_enabled", True)
        await guard.enforce_advisor_request(req, ctx, local_db[1])
        assert req.state.advisor_scoped_write is rule and ctx.advisor_write_rule is rule
        assert await req.json() == body_for(rule)
        assert json.loads(await req.body()) == body_for(rule)
        object_contract.check_write_objects.assert_awaited_once_with(local_db[1], ctx, req, body_for(rule), rule)
        object_contract.ensure_advisor_assignment.assert_awaited_once()
    asyncio.run(run())


@pytest.mark.parametrize("rule", WRITE_ROUTES.values())
@pytest.mark.parametrize("field", ["owner_user_id", "advisor_user_id", "published_at", "verified", "public_use_allowed", "unknown"])
def test_forbidden_and_unknown_fields_fail_closed(rule, field):
    with pytest.raises(HTTPException) as denied:
        check_write_fields(rule, body_for(rule) | {field: None})
    assert denied.value.status_code == 403
    assert denied.value.detail["code"] == "ADVISOR_WRITE_FIELD_FORBIDDEN"


@pytest.mark.parametrize("value", [{"content_id":2}, [{"owner_user_id":2}], [[2]]])
def test_nested_objects_cannot_hide_inside_flat_fields(value):
    rule = WRITE_ROUTES[("PATCH", "/api/v1/seo/content-assets/{content_id}")]
    for field in ("title", "keyword_ids"):
        with pytest.raises(HTTPException) as denied:
            check_write_fields(rule, {"version_count":1, field:value})
        assert denied.value.status_code == 403


@pytest.mark.parametrize("status", ["review", "ready", "published", "archived", "retired", None])
def test_only_manual_draft_states_allowed(status):
    for key in [("POST", "/api/v1/seo/content-assets"), ("POST", "/api/v1/seo/qa/facts")]:
        with pytest.raises(HTTPException) as denied:
            check_write_fields(WRITE_ROUTES[key], {"status":status})
        assert denied.value.status_code == 403


@pytest.mark.parametrize("rule", [r for r in WRITE_ROUTES.values() if r.method != "POST" and ("version" in r.fields or "version_count" in r.fields)])
def test_versions_are_unconditionally_required(rule):
    with pytest.raises(HTTPException) as denied:
        check_write_fields(rule, {})
    assert denied.value.status_code == 422


def test_no_prefix_or_concrete_url_fallback():
    rule = next(iter(WRITE_ROUTES.values()))
    req = request(rule, {})
    req.scope.pop("route")
    assert match_write_rule(req) is None
    req.scope["route"] = SimpleNamespace(path=rule.template + "/publish")
    assert match_write_rule(req) is None


def test_brand_edit_permission_is_not_content_edit(local_db, object_contract, monkeypatch):
    monkeypatch.setattr(get_settings(), "advisor_scoped_content_writes_enabled", True)
    async def run():
        ctx = await authenticate(local_db[1], claims())
        rule = WRITE_ROUTES[("POST", "/api/v1/seo/rank-serp/brand-assets")]
        with pytest.raises(HTTPException) as denied:
            await guard.enforce_advisor_request(request(rule, body_for(rule)), ctx, local_db[1])
        assert denied.value.detail["code"] == "ADVISOR_WRITE_PERMISSION_REQUIRED"
        object_contract.check_write_objects.assert_not_called()
    asyncio.run(run())


@pytest.mark.parametrize("change, code", [("revoke", "ADVISOR_GRANT_REVOKED"), ("disable", "ADVISOR_GRANT_REVOKED"), ("permission", "ADVISOR_WRITE_PERMISSION_REQUIRED"), ("role", "ADVISOR_ROLE_CHANGED")])
def test_fresh_authorization_failure_rolls_back_pending_business_write(local_db, change, code):
    db, adapter = local_db
    class CommitSession:
        no_autoflush = db.no_autoflush
        scalar = adapter.scalar
        scalars = adapter.scalars
        async def rollback(self):
            db.rollback()
    async def run():
        ctx = await authenticate(adapter, claims())
        ctx.advisor_write_rule = WRITE_ROUTES[("POST", "/api/v1/seo/content-assets")]
        if change == "revoke":
            g = db.get(Grant, 10)
            g.revoked_at = datetime.now(timezone.utc)
            g.revoked_by, g.revoke_reason = 3, "admin_uncheck"
        elif change == "disable":
            db.get(User,1).is_active = False
        elif change == "permission":
            db.get(Role,1).permissions = {"geo.assets":"edit", "geo.content":"edit"}
        else:
            db.get(User,1).role_id = 2
        db.commit()  # Revocation committed after authentication/guard snapshot.
        db.execute(text("CREATE TABLE manual_write_probe (id INTEGER PRIMARY KEY)"))
        db.commit()
        db.execute(text("INSERT INTO manual_write_probe VALUES (1)"))
        with pytest.raises(HTTPException) as denied:
            await recheck_advisor_before_commit(CommitSession(), ctx)
        assert denied.value.detail["code"] == code
        assert db.scalar(text("SELECT count(*) FROM manual_write_probe")) == 0
    asyncio.run(run())


def test_valid_commit_and_non_advisor_noop(local_db):
    db, adapter = local_db
    session = SimpleNamespace(no_autoflush=db.no_autoflush, scalar=adapter.scalar, scalars=adapter.scalars, rollback=AsyncMock())
    async def run():
        ctx = await authenticate(adapter, claims())
        ctx.advisor_write_rule = WRITE_ROUTES[("POST", "/api/v1/seo/content-assets")]
        await recheck_advisor_before_commit(session, ctx)
        session.rollback.assert_not_called()
        await recheck_advisor_before_commit(None, SimpleNamespace(is_advisor=False))
    asyncio.run(run())


@pytest.mark.parametrize('method,path', [
    ('POST', '/qa/facts'), ('PATCH', '/qa/facts/{fact_id}'),
    ('POST', '/rank-serp/brand-assets'), ('PATCH', '/rank-serp/brand-assets/{asset_id}'),
    ('POST', '/content-assets'), ('PATCH', '/content-assets/{content_id}'),
    ('PUT', '/content-assets/{content_id}/source-page'),
])
def test_write_audit_records_only_actor_scope_operation_and_result(caplog, method, path):
    from app.security.advisor_write_commit import record_advisor_write
    ctx = SimpleNamespace(is_advisor=True, user_id=7, username='private-account')
    row = SimpleNamespace(id=42, tenant_id=1, __tablename__='seo_content_assets',
                          draft='private-body', payload_hash='private-hash')
    record_advisor_write(ctx, row, method, '/api/v1/seo' + path)
    event = json.loads(caplog.records[-1].getMessage().split(' ', 1)[1])
    assert event == {'user_id': 7, 'tenant_id': 1, 'method': method,
                     'path': '/api/v1/seo' + path, 'object_type': 'seo_content_assets',
                     'object_ids': [42], 'result': 'succeeded', 'time': event['time']}
    assert datetime.fromisoformat(event['time']).utcoffset().total_seconds() == 0
    assert 'private-' not in caplog.text


def test_write_audit_preserves_ordinary_editor_behavior(caplog):
    from app.security.advisor_write_commit import record_advisor_write
    record_advisor_write(SimpleNamespace(is_advisor=False), None, 'PATCH', '/unused')
    assert not caplog.records


@pytest.mark.parametrize('commit_fails', [False, True])
def test_write_audit_fact_handler_emits_success_only_after_commit(monkeypatch, caplog, commit_fails):
    from app.api import seo_qa as api
    from unittest.mock import MagicMock
    rows = []
    async def commit():
        assert not caplog.records
        if commit_fails:
            raise RuntimeError('synthetic commit failure')
        rows[0].id = 42
    session = SimpleNamespace(add=MagicMock(side_effect=rows.append),
                              commit=AsyncMock(side_effect=commit), refresh=AsyncMock())
    monkeypatch.setattr(api, 'access', AsyncMock())
    monkeypatch.setattr(api, 'recheck_advisor_before_commit', AsyncMock())
    ctx = SimpleNamespace(is_advisor=True, user_id=7)
    req = api.FactInput(tenant_id=1, site_id=2, title='synthetic', statement='private-body', source_name='manual')
    if commit_fails:
        with pytest.raises(RuntimeError, match='synthetic commit failure'):
            asyncio.run(api.create_fact(req, ctx, session))
        assert not caplog.records
    else:
        response = asyncio.run(api.create_fact(req, ctx, session))
        event = json.loads(caplog.records[-1].getMessage().split(' ', 1)[1])
        assert response['id'] == 42 and event['object_ids'] == [42]
        assert event['object_type'] == 'seo_qa_facts' and event['result'] == 'succeeded'
    assert 'private-body' not in caplog.text