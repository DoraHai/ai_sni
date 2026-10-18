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


@pytest.mark.parametrize('change', [None, 'grant', 'role', 'account', 'assignment',
                                   'switch', 'expired', 'job-permission', 'foreign-site'])
def test_manual_rerun_captures_selected_customer_and_rechecks_each_step(object_db, monkeypatch, change):
    from datetime import datetime, timezone
    from app.database import Base
    from app.models.advisor_tenant_grant import AdvisorTenantGrant
    from app.models.role import Role
    from app.models.user import User
    from app.models.seo import SeoAutomationRun, SeoSiteAdvisorAssignment
    from app.security.seo_advisor_execution import capture_manual_automation_scope, check_manual_automation_scope
    from test_advisor_tenant_auth import authenticate, claims
    db, session = object_db
    session.no_autoflush = db.no_autoflush
    session.rollback = AsyncMock(side_effect=db.rollback)
    Base.metadata.create_all(db.bind, tables=[SeoAutomationRun.__table__])
    role = db.get(Role, 1)
    role.permissions = {**role.permissions, 'seo.dashboard': 'edit', 'seo.links': 'edit'}
    assignment = SeoSiteAdvisorAssignment(id=2, tenant_id=2, site_id=2, advisor_user_id=1, active=True)
    db.add(assignment); db.commit()
    monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', True)
    ctx = asyncio.run(authenticate(session, claims(tid=2, gid=20)))
    body = {'tenant_id': 2, 'site_id': 2, 'job_type': 'backlink'}
    request = req('POST', '/api/v1/seo/overview/automation-runs/trigger', body, query='tenant_id=2&site_id=2')
    asyncio.run(enforce_advisor_request(request, ctx, session))
    proof = capture_manual_automation_scope(ctx)
    row = SeoAutomationRun(id=500, tenant_id=2, site_id=2, job_type='backlink',
                           requested_by=1, trigger_type='manual')
    row._advisor_scope = proof
    if change == 'grant':
        grant = db.get(AdvisorTenantGrant, 20)
        grant.revoked_at = datetime.now(timezone.utc); grant.revoked_by = 3
        grant.revoke_reason = 'admin_uncheck'
    elif change == 'role': db.get(User, 1).role_id = 2
    elif change == 'account': db.get(User, 1).is_active = False
    elif change == 'assignment': assignment.active = False
    elif change == 'switch': monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', False)
    elif change == 'expired': proof['auth_exp'] = 1
    elif change == 'job-permission': role.permissions = {**role.permissions, 'seo.links': 'view'}
    elif change == 'foreign-site': row.site_id = 1
    db.commit()
    if change:
        with pytest.raises(HTTPException): asyncio.run(check_manual_automation_scope(session, row))
    else:
        asyncio.run(check_manual_automation_scope(session, row))
        assert row._advisor_actor.tenant_id == 2
        assert 'seo.links' in row._advisor_actor.advisor_write_rule.edit_all
        # A role change after enforcement is also caught by the fresh commit check.
        role.permissions = {**role.permissions, 'seo.links': 'view'}; db.commit()
        session.no_autoflush = db.no_autoflush
        with pytest.raises(HTTPException):
            asyncio.run(advisor_write_commit.recheck_advisor_before_commit(session, row._advisor_actor))


@pytest.mark.parametrize('revoke_at', [2, 3])
def test_background_backlink_revoke_blocks_provider_or_result_save(monkeypatch, revoke_at):
    from contextlib import asynccontextmanager
    from app import seo_manual_automation as worker
    candidate = SimpleNamespace(id=5, tenant_id=1, site_id=1, status='active',
                                source_url='https://source.invalid/', target_url='https://target.invalid/')
    sessions = []
    @asynccontextmanager
    async def factory():
        session = SimpleNamespace(scalars=AsyncMock(return_value=[candidate]),
                                  get=AsyncMock(return_value=candidate), commit=AsyncMock())
        sessions.append(session)
        yield session
    checks = AsyncMock(side_effect=[None] * (revoke_at - 1) + [HTTPException(403, 'revoked')])
    fetch, apply = AsyncMock(return_value=SimpleNamespace()), AsyncMock()
    monkeypatch.setattr(worker, 'async_session_factory', factory)
    monkeypatch.setattr(worker, 'check_manual_automation_scope', checks)
    monkeypatch.setattr(worker, 'seo_site_is_operational', AsyncMock(return_value=True))
    monkeypatch.setattr(worker, 'fetch_url', fetch)
    monkeypatch.setattr(worker, 'apply_backlink_evidence', apply)
    row = SimpleNamespace(tenant_id=1, site_id=1, planned_count=1)
    assert asyncio.run(worker._run_backlinks(row))[:3] == (0, 1, 0)
    assert fetch.await_count == (1 if revoke_at == 3 else 0)
    apply.assert_not_called()
    assert all(session.commit.await_count == 0 for session in sessions)


def test_ready_landing_content_can_bind_its_site_page_with_version(monkeypatch):
    from app.api import seo
    from app.models.seo import SeoContentAsset, SeoSitePage
    row = SeoContentAsset(id=1, tenant_id=1, site_id=1, title='Reviewed landing',
                          content_type='landing', status='ready', version_count=2)
    page = SeoSitePage(id=50, tenant_id=1, site_id=1, url='https://landing.example/')
    session = SimpleNamespace(get=AsyncMock(return_value=row), commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(seo, '_require_resource_operational_site', AsyncMock())
    monkeypatch.setattr(seo, '_site_page', AsyncMock(return_value=page))
    monkeypatch.setattr(seo, '_content_task_for_source_page', AsyncMock(return_value=None))
    monkeypatch.setattr(seo, 'recheck_advisor_before_commit', AsyncMock())
    result = asyncio.run(seo.bind_content_source_page(1, 1,
        seo.ContentSourcePageBinding(source_page_id=50, version_count=2), session, selected()))
    assert result['source_page_id'] == 50 and row.status == 'ready' and row.version_count == 3
    session.commit.assert_awaited_once()
