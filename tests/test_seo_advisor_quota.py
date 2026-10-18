import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.security.seo_advisor_quota import KEY, LIMIT, admit, request_kind, reserve
from app.seo_ai_operations import _refund
from test_advisor_scoped_writes_objects import object_db  # noqa: F401
from test_advisor_tenant_auth import local_db  # noqa: F401

PATH = "/api/v1/seo/content-ai/assist"
NOW = datetime(2026, 10, 18, 15, 59, tzinfo=timezone.utc)


def test_ten_suggestions_per_advisor_client_day_and_idempotent_recovery():
    config = {"unrelated_setting": "retained"}
    for i in range(10):
        config, receipt = reserve(config, 7, PATH, {"action": "title", "request_id": str(i)}, now=NOW)
        assert receipt["used"] == i + 1
    restored, receipt = reserve(config, 7, PATH, {"action": "title", "request_id": "9"}, now=NOW)
    assert receipt["used"] == 10 and restored == config
    with pytest.raises(HTTPException) as caught:
        reserve(config, 7, PATH, {"action": "title", "request_id": "11"}, now=NOW)
    assert caught.value.status_code == 429
    assert "10 次" in caught.value.detail["message"]
    assert config["unrelated_setting"] == "retained"
    assert reserve(config, 8, PATH, {"request_id": "0"}, now=NOW)[1]["used"] == 1
    # A different client's module JSON is independently empty.
    assert reserve({}, 7, PATH, {"request_id": "0"}, now=NOW)[1]["used"] == 1


def test_shanghai_midnight_resets_and_request_key_cannot_change_payload():
    config, _ = reserve({}, 7, PATH, {"request_id": "one", "action": "title"}, now=NOW)
    with pytest.raises(HTTPException) as caught:
        reserve(config, 7, PATH, {"request_id": "one", "action": "rewrite"}, now=NOW)
    assert caught.value.status_code == 409
    tomorrow = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)
    result, receipt = reserve(config, 7, PATH, {"request_id": "two"}, now=tomorrow)
    assert result[KEY]["date"] == "2026-10-19" and receipt["used"] == 1


def test_generation_has_no_daily_count_but_advice_shares_one_bucket():
    assert request_kind(PATH, {"action": "generate"}) == "generation"
    assert request_kind("/api/v1/seo/qa/research/draft", {}) == "generation"
    assert request_kind(PATH, {"action": "rewrite"}) == "suggestion"
    assert request_kind("/api/v1/seo/site/pages/ai-tdk/generate", {}) == "suggestion"
    assert request_kind("/api/v1/seo/rank-serp/collect", {"use_ai": False}) is None
    session = SimpleNamespace(commit=AsyncMock(), scalar=AsyncMock())
    asyncio.run(admit(session, SimpleNamespace(), SimpleNamespace(template=PATH), {"action": "generate"}))
    session.scalar.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_failed_advisor_operation_never_refunds_another_customers_legacy_budget():
    module = SimpleNamespace(module_settings={"seo_daily_usage": {"date": "2026-10-18", "ai_requests": 8}})
    row = SimpleNamespace(kind="advisor_content_assist", charged_on="2026-10-18")
    _refund(module, row)
    assert module.module_settings["seo_daily_usage"]["ai_requests"] == 8
    assert row.status == "refunded"


@pytest.mark.parametrize('value', ['missing', True, False, 'true', 'false', 0, 1])
@pytest.mark.parametrize('name,path,extra', [
    ('SerpCollectRequest', '/api/v1/seo/rank-serp/collect', {}),
    ('DistributionAdaptRequest', '/api/v1/seo/content-distribution/adapt', {'content_id': 1, 'connection_id': 1}),
    ('DistributionVariantGenerateRequest', '/api/v1/seo/content-distribution/variants/generate', {'pairs': [{'content_id': 1, 'connection_id': 1}]}),
])
def test_quota_boolean_defaults_and_coercions_match_the_real_endpoint_schema(name, path, extra, value):
    from app.api import seo
    body = {'tenant_id': 1, 'site_id': 1, **extra}
    if value != 'missing': body['use_ai'] = value
    validated = getattr(seo, name).model_validate(body)
    assert request_kind(path, body) == ('suggestion' if validated.use_ai else None)


@pytest.mark.parametrize('change', [None, 'grant', 'role', 'assignment', 'switch'])
def test_queued_generation_uses_selected_customer_and_fresh_authorization(object_db, monkeypatch, change):
    from app.config import get_settings
    from app.database import Base
    from app.models.advisor_tenant_grant import AdvisorTenantGrant
    from app.models.seo import SeoSiteAdvisorAssignment
    from app.models.seo_qa import SeoQaBatch
    from app.models.user import User
    from app.seo_qa_batches import current_actor
    db, session = object_db
    Base.metadata.create_all(db.bind, tables=[SeoQaBatch.__table__])
    grant = db.query(AdvisorTenantGrant).filter_by(user_id=1, tenant_id=2).one()
    batch = SeoQaBatch(id=10, tenant_id=2, site_id=2, actor='1', request_key='batch-advisor',
                      request_hash='fixture', items=[{'_advisor_scope': {'grant_id': grant.id,
                      'auth_exp': int(datetime.now(timezone.utc).timestamp()) + 3600}}])
    assignment = SeoSiteAdvisorAssignment(id=2, tenant_id=2, site_id=2, advisor_user_id=1, active=True)
    db.add_all([batch, assignment]); db.commit()
    monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', change != 'switch')
    if change == 'grant':
        grant.revoked_at = datetime.now(timezone.utc)
        grant.revoked_by = 3
        grant.revoke_reason = 'admin_uncheck'
    if change == 'role': db.get(User, 1).role_id = 2
    if change == 'assignment': assignment.active = False
    db.commit()
    if change:
        with pytest.raises(HTTPException): asyncio.run(current_actor(session, batch))
    else:
        ctx = asyncio.run(current_actor(session, batch))
        assert ctx.is_advisor and ctx.tenant_id == 2 and ctx.grant_id == grant.id
        assert session._seo_advisor_ai_kind == 'generation'
        assert session._seo_advisor_commit_guard


def test_reusing_an_id_for_a_different_onsite_task_is_not_a_free_replay():
    path = '/api/v1/seo/workbench/onsite-tasks/{task_id}/ai-proposal'
    body = {'request_id': 'same', 'tenant_id': 1, 'site_id': 1, 'mode': 'initial'}
    config, _ = reserve({}, 7, path, body, now=NOW, path_params={'task_id': 1})
    with pytest.raises(HTTPException) as caught:
        reserve(config, 7, path, body, now=NOW, path_params={'task_id': 2})
    assert caught.value.status_code == 409


def test_a_generation_operation_id_cannot_skip_onsite_suggestion_quota(object_db):
    from app.database import Base
    from app.models.seo import SeoAiOperation
    from app.models.module_workspace import TenantModule
    from test_advisor_scoped_writes_objects import selected
    from test_seo_advisor_work import req
    db, session = object_db
    Base.metadata.create_all(db.bind, tables=[SeoAiOperation.__table__])
    db.add(SeoAiOperation(id='00000000-0000-0000-0000-000000000001', tenant_id=1, site_id=1,
        request_key='shared-request', request_hash='fixture', actor='1', kind='advisor_content_assist',
        status='succeeded', charged_on='2026-10-18', expires_at=datetime.now(timezone.utc)))
    db.commit()
    path = '/api/v1/seo/workbench/onsite-tasks/{task_id}/ai-proposal'
    body = {'request_id': 'shared-request', 'tenant_id': 1, 'site_id': 1, 'mode': 'initial'}
    ctx = selected(); request = req('POST', path, body, task_id=1)
    rule = SimpleNamespace(template=path)
    ctx.advisor_write_scope = (request, body, rule)
    asyncio.run(admit(session, ctx, rule, body))
    assert len(db.get(TenantModule, 1).module_settings[KEY]['actors']['1']) == 1
