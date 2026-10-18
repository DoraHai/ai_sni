import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.config import get_settings
from app.models.seo import SeoKeywordAsset
from app.security import advisor_write_commit
from app.security.advisor_tenant_auth import enforce_advisor_request
from app.security.advisor_write_routes import WRITE_ROUTES
from app.security.seo_advisor_audit import install_commit_guard
from app.security.seo_advisor_deletion import DELETIONS
from test_advisor_scoped_writes_objects import object_db, selected  # noqa: F401
from test_advisor_tenant_auth import local_db  # noqa: F401
from test_seo_advisor_work import req


@pytest.mark.parametrize('keyword_id,tenant,enabled', [(20,1,True),(120,1,True),(220,1,True),(320,1,True),(20,2,True),(20,1,False)])
def test_delete_requires_granted_selected_active_project(object_db, monkeypatch, keyword_id, tenant, enabled):
    monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', enabled)
    request = req('DELETE', '/api/v1/seo/keywords/{keyword_id}', {}, query=f'tenant_id={tenant}', keyword_id=keyword_id)
    if (keyword_id,tenant,enabled) == (20,1,True):
        asyncio.run(enforce_advisor_request(request, selected(), object_db[1]))
    else:
        with pytest.raises(HTTPException): asyncio.run(enforce_advisor_request(request, selected(), object_db[1]))


def test_deleted_objects_have_advisor_customer_and_result_records(monkeypatch, caplog):
    ctx, request = selected(), req('DELETE', '/api/v1/seo/keywords/{keyword_id}', keyword_id=20)
    row = SeoKeywordAsset(id=20, tenant_id=1, site_id=1, keyword='fixture')
    session = SimpleNamespace(commit=AsyncMock(), new=[], dirty=[], deleted=[row])
    monkeypatch.setattr(advisor_write_commit, 'recheck_advisor_before_commit', AsyncMock())
    install_commit_guard(session, ctx, request)
    with caplog.at_level('INFO', logger='seo.advisor.operations'): asyncio.run(session.commit())
    event = json.loads(caplog.records[-1].message)
    assert event['changed_objects'] == [{'table': 'seo_keyword_assets', 'id': 20}]
    assert event['user_id'] == 1 and event['tenant_id'] == 1 and event['result'] == 'committed'


def test_deletion_catalog_does_not_grant_assignment_or_credentials():
    assert len(DELETIONS) == 8
    for path in ['/workbench/advisor-assignments/{assignment_id}', '/site/analytics-sources/{source}']:
        assert ('DELETE', '/api/v1/seo' + path) not in WRITE_ROUTES
