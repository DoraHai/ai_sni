"""SQL scope, commit revocation and operation-record coverage for daily SEO work."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.models.module_workspace import SeoSite
from app.models.seo import SeoKeywordAsset, SeoSiteAdvisorAssignment
from app.security.advisor_write_routes import WRITE_ROUTES, check_write_fields, match_write_rule
from app.security import advisor_tenant_auth as guard
from app.security.seo_advisor_work import lock_workflow_scope, references
from app.security.seo_advisor_audit import install_commit_guard, operation_audit
from test_advisor_scoped_writes_objects import object_db, selected  # noqa: F401
from test_advisor_tenant_auth import local_db, authenticate, claims  # noqa: F401


def req(method="PATCH", template="/api/v1/seo/keywords/{keyword_id}", body=None, query="tenant_id=1", **ids):
    raw = json.dumps(body or {}).encode()
    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request({"type": "http", "method": method, "path": template.format(**ids),
                    "path_params": ids, "query_string": query.encode(), "headers": [],
                    "route": SimpleNamespace(path=template)}, receive)


@pytest.mark.parametrize("rule", [r for r in WRITE_ROUTES.values() if r.workflow])
def test_every_new_rule_is_exact_and_unknown_fields_are_denied(rule):
    request = req(rule.method, rule.template, **{part[1:-1]: 1 for part in rule.template.split("/") if part.startswith("{")})
    assert match_write_rule(request) is rule
    request.scope["route"] = SimpleNamespace(path=rule.template + "/unreviewed")
    assert match_write_rule(request) is None
    with pytest.raises(HTTPException) as caught:
        check_write_fields(rule, {"future_admin_setting": True})
    assert caught.value.status_code == 403


@pytest.mark.parametrize("query,body", [
    ("tenant_id=2", {}), ("tenant_id=3", {}),
    ("tenant_id=1&tenant_id=2", {}), ("tenant_id=1", {"site_id": 4}),
    ("tenant_id=1", {"keyword_id": 120}),
])
def test_other_unselected_ungranted_and_cross_project_ids_denied(object_db, query, body):
    _, session = object_db
    request = req(query=query, body=body, keyword_id=20)
    rule = match_write_rule(request)
    with pytest.raises(HTTPException):
        asyncio.run(lock_workflow_scope(session, selected(), request, body, rule))


@pytest.mark.parametrize("change", ["inactive_assignment", "other_advisor", "inactive_site", "missing_assignment"])
def test_assignment_must_be_current_and_site_active(object_db, change):
    db, session = object_db
    assignment = db.get(SeoSiteAdvisorAssignment, 1)
    if change == "inactive_assignment": assignment.active = False
    if change == "other_advisor": assignment.advisor_user_id = 99
    if change == "inactive_site": db.get(SeoSite, 1).status = "archived"
    if change == "missing_assignment": db.delete(assignment)
    db.commit()
    request = req(keyword_id=20)
    with pytest.raises(HTTPException):
        asyncio.run(lock_workflow_scope(session, selected(), request, {}, match_write_rule(request)))


def test_matching_scope_is_allowed_without_changing_automatic_plan(object_db):
    db, session = object_db
    request = req(keyword_id=20)
    asyncio.run(lock_workflow_scope(session, selected(), request, {}, match_write_rule(request)))
    assert db.get(SeoSite, 1).site_settings in ({}, None)


def test_nested_references_and_unknown_ids_fail_closed():
    assert references({"expected_facts": [{"id": 30}]}, "/api/v1/seo/qa/answers") == [("fact_id", 30)]
    for body in ({"params": {"owner_user_id": 2}}, {"future_ids": [1]}, {"id": 2}):
        with pytest.raises(HTTPException): references(body, "/api/v1/seo/keywords")


@pytest.mark.parametrize('body,denied', [
    ({}, True), ({'use_ai': True}, True), ({'use_ai': 'true'}, True),
    ({'use_ai': 1}, True), ({'use_ai': None}, True),
    ({'use_ai': False}, False), ({'use_ai': 'false'}, False),
    ({'use_ai': 0}, False),
])
def test_first_batch_serp_ai_defaults_cannot_bypass_unavailable_quota(body, denied):
    request = req('POST', '/api/v1/seo/rank-serp/collect')
    rule = match_write_rule(request)
    if denied:
        with pytest.raises(HTTPException):
            check_write_fields(rule, body)
    else:
        check_write_fields(rule, body)


@pytest.mark.parametrize("enabled", [False, True])
def test_new_write_keeps_switch_and_current_customer_checks(monkeypatch, enabled):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "advisor_scoped_content_writes_enabled", enabled)
    ctx = selected()
    if enabled: ctx.scope_kind = "advisor_identity"
    with pytest.raises(HTTPException):
        asyncio.run(guard.enforce_advisor_request(req(keyword_id=20), ctx, SimpleNamespace()))


def test_commit_guard_rechecks_revocation_and_records_success(object_db, monkeypatch, caplog):
    from app.security import advisor_write_commit
    request, ctx = req(keyword_id=20), selected()
    check = AsyncMock()
    monkeypatch.setattr(advisor_write_commit, "recheck_advisor_before_commit", check)
    session = SimpleNamespace(commit=AsyncMock(), new=[])
    original = session.commit
    install_commit_guard(session, ctx, request)
    with caplog.at_level("INFO", logger="seo.advisor.operations"):
        asyncio.run(session.commit())
    check.assert_awaited_once_with(session, ctx)
    original.assert_awaited_once()
    event = json.loads(caplog.records[-1].message)
    assert (event["user_id"], event["tenant_id"], event["method"], event["object_ids"], event["result"]) == (1, 1, "PATCH", {"keyword_id": 20}, "committed")
    check.side_effect = HTTPException(401, "revoked")
    with pytest.raises(HTTPException): asyncio.run(session.commit())
    assert original.await_count == 1


def test_failure_and_success_both_have_http_operation_records(caplog):
    request, ctx = req(keyword_id=20), selected()
    request.state.seo_advisor_actor = ctx
    with caplog.at_level("INFO", logger="seo.advisor.operations"):
        asyncio.run(operation_audit(request, AsyncMock(return_value=SimpleNamespace(status_code=403))))
    assert json.loads(caplog.records[-1].message)["result"] == 403


@pytest.mark.parametrize("method,path", [
    ("PUT", "/api/v1/seo/workbench/advisor-assignments"),
    ("PUT", "/api/v1/seo/workbench/service-plan"),
    ("POST", "/api/v1/seo/content-distribution/connections"),
    ("PUT", "/api/v1/seo/site/analytics-sources"),
    ("POST", "/api/v1/seo/workbench/content-assets/{content_id}/conversation/messages"),
])
def test_authorization_model_cadence_and_customer_messages_stay_closed(method, path):
    assert match_write_rule(req(method, path, content_id=1)) is None
