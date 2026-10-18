import asyncio
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.config import get_settings
from app.security.advisor_tenant_auth import enforce_advisor_request
from app.security.advisor_write_routes import WRITE_ROUTES, check_write_fields
from app.security.seo_advisor_reviews import content_evidence, prepare_review_evidence
from app.models.seo import SeoContentAsset
from test_advisor_scoped_writes_objects import object_db, selected  # noqa: F401
from test_advisor_tenant_auth import local_db  # noqa: F401
from test_seo_advisor_work import req

CONFIRM = '/api/v1/seo/workbench/content-assets/{content_id}/confirmations'


@pytest.mark.parametrize('content_id,tenant,enabled', [(1, 1, True), (101, 1, True), (201, 1, True), (301, 1, True), (1, 2, True), (1, 1, False)])
def test_confirmation_requires_selected_granted_assigned_active_scope(object_db, monkeypatch, content_id, tenant, enabled):
    monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', enabled)
    body = {'version_count': 1, 'payload_hash': 'a'*64, 'decision': 'approve', 'actor_mode': 'advisor_proxy'}
    request = req('POST', CONFIRM, body, query=f'tenant_id={tenant}', content_id=content_id)
    if (content_id, tenant, enabled) == (1, 1, True):
        asyncio.run(enforce_advisor_request(request, selected(), object_db[1]))
        assert request.state.seo_advisor_evidence['requested_content_hash'] == 'a'*64
    else:
        with pytest.raises(HTTPException): asyncio.run(enforce_advisor_request(request, selected(), object_db[1]))


def test_customer_impersonation_is_denied():
    with pytest.raises(HTTPException):
        check_write_fields(WRITE_ROUTES[('POST', CONFIRM)], {'actor_mode': 'customer_direct'})


def test_confirmation_audit_uses_actual_saved_version_hash_and_note(object_db):
    db, session = object_db
    row = db.get(SeoContentAsset, 1)
    row.draft = 'Approved actual copy'
    row.version_count = 2
    session.flush = AsyncMock(side_effect=db.flush)
    request = req('POST', CONFIRM, content_id=1)
    ctx = selected()
    ctx.advisor_write_scope = (request, {'decision': 'approve', 'note': '微信确认'}, WRITE_ROUTES[('POST', CONFIRM)])
    evidence = asyncio.run(prepare_review_evidence(session, ctx, [row]))
    assert evidence['reviewed_versions'] == [content_evidence(row)]
    assert evidence['reviewed_versions'][0]['version'] == 2
    assert len(evidence['reviewed_versions'][0]['content_hash']) == 64
    assert evidence['consent_note'] == '微信确认' and evidence['actor_mode'] == 'advisor_proxy'


@pytest.mark.parametrize('suffix', ['submit-review', 'review'])
@pytest.mark.parametrize('version', [None, 0, -1, True, '1', 1])
def test_review_admission_requires_an_explicit_positive_version(suffix, version):
    path = '/api/v1/seo/content-assets/{content_id}/' + suffix
    body = {} if version is None else {'version_count': version}
    if suffix == 'review': body['decision'] = 'approve'
    if type(version) is int and version > 0:
        check_write_fields(WRITE_ROUTES[('POST', path)], body)
    else:
        with pytest.raises(HTTPException) as caught:
            check_write_fields(WRITE_ROUTES[('POST', path)], body)
        assert caught.value.status_code == 422


@pytest.mark.parametrize('action', ['submit', 'review'])
@pytest.mark.parametrize('version', [None, 1])
def test_review_handler_rejects_missing_or_stale_version_without_writes(monkeypatch, action, version):
    from types import SimpleNamespace
    from app.api import seo
    row = SeoContentAsset(id=1, tenant_id=1, site_id=1, title='newer copy',
                          draft='updated after the reviewer loaded it', status='review', version_count=2)
    session = SimpleNamespace(get=AsyncMock(return_value=row), commit=AsyncMock())
    monkeypatch.setattr(seo, '_require_resource_operational_site', AsyncMock())
    if action == 'submit':
        handler, payload = seo.submit_content_review, seo.ContentReviewSubmit(version_count=version)
    else:
        handler, payload = seo.decide_content_review, seo.ContentReviewDecision(decision='approve', version_count=version)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handler(1, 1, payload, session, selected()))
    assert caught.value.status_code == (422 if version is None else 409)
    assert row.status == 'review' and row.version_count == 2
    session.commit.assert_not_awaited()
    if version is None:
        session.get.assert_not_awaited()
    else:
        session.get.assert_awaited_once_with(SeoContentAsset, 1, with_for_update=True, populate_existing=True)
