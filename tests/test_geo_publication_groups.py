"""Synthetic SQL/HTTP contract, isolation, revision and native KPI regression."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import event, select

from test_geo_project_client import env, SelectOnly, NOW, get, Task, Article, Variant, Publication
from app.models import TenantModule, GeoProject, User, Role
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.models.distribution_inbox import DistributionInboxReceipt as Receipt
from app.geo import publication_groups as groups
from app.geo.content import inbox_routes, inbox_policy
from app.geo.project_client_store import client_read_session
from app.security.auth import require_auth


def receipt(i, **kw):
    return Receipt(id=str(UUID(int=i)), owner_user_id=9, device_id=str(UUID(int=990)),
        event_id=str(UUID(int=i+10000)), payload_digest='0'*64, received_at=NOW,
        occurred_at=NOW, platform='公众号', title='公开回传标题', public_url='https://example.com/shared',
        reported_account='PRIVATE_ACCOUNT', content_bytes=0, tenant_id=101, module='geo',
        scope_id=1, state='active', label_state='active', revision=1, result='success',
        **kw)


@pytest.fixture
def data(env):
    env.monkeypatch.setattr('app.geo.tenant_scope.ensure_geo_entitlement', AsyncMock(return_value=NS(is_demo=False)))
    event.remove(env.engine, 'before_cursor_execute', env.guard)
    for model in (Receipt, TenantModule, User, Role, Grant):
        model.__table__.create(env.engine)
    event.listen(env.engine, 'before_cursor_execute', env.guard)
    env.http.app.add_middleware(inbox_routes.GeoInboxBoundaryMiddleware)
    env.http.app.include_router(inbox_routes.router)
    env.http.app.dependency_overrides[require_auth] = lambda: env.ctx
    env.http.app.dependency_overrides[client_read_session] = lambda: SelectOnly(env.session)
    env.save(TenantModule(id=101, tenant_id=101, module_code='geo', status='active'),
        Role(id=1, name='管理员', is_system=True, permissions={'geo.content': 'edit'}),
        User(id=9, tenant_id=101, role_id=1, username='fixture', password_hash='synthetic', is_active=True))
    # Existing tasks permit legacy NULL business IDs for client reads. Internal
    # inbox article authorization requires the exact business chain.
    for i in (1, 2, 3):
        task = env.session.get(Task, i)
        task.business_id = 11
        env.save(task)
    env.save(receipt(1, article_id=1, article_version=1), receipt(2, article_id=1, article_version=1),
        receipt(3), receipt(4, article_id=999, article_version=1),
        Publication(id=101, variant_id=1, channel='website', status='pending',
            published_url='https://example.com/shared', updated_at=NOW))
    return env


def internal(data, **kw):
    return data.http.get(groups.INTERNAL, params={'tenant_id': 101, 'scope_id': 1, **kw})


def client(data, **kw):
    return get(data, '/publication-groups', **kw)


def snapshot(data):
    return {m.__name__: [dict(r) for r in data.session.execute(select(m.__table__)).mappings()]
        for m in (Task, Article, Variant, Publication, Receipt)}


def test_sources_preserve_native_counts_and_original_delivery_exports(data):
    before = snapshot(data)
    deliveries = get(data, '/deliveries').json()['data']
    for call in (internal, client):
        response = call(data)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['read_only'] and body['counts']['native_records'] == 4
        assert body['counts']['article_groups'] == 3
        assert body['counts']['unlinked_records'] == 1
        assert body['counts']['external_records'] == (4 if call is internal else 3)
        one = next(g for g in body['items'] if g['task_id'] == 1)
        assert (one['native_count'], one['external_count']) == (2, 2)
        detail = call(data, article_id=1).json()['items']
        assert len(detail) == 4
        assert [r['source'] for r in detail] == ['native', 'native', 'external_report', 'external_report']
        assert len({r['source_key'] for r in detail}) == 4  # Same URL preserved.
        assert all(not r['verification']['evidence_valid'] for r in detail)
        assert call(data, bucket='unlinked').json()['counts']['unlinked_records'] == 1
    assert snapshot(data) == before
    after = get(data, '/deliveries').json()['data']
    assert deliveries['counts'] == after['counts']
    assert deliveries['counts']['receipt_records'] == 3  # Legacy push receipts preserved.
    assert deliveries['counts']['publication_records'] == 4
    assert deliveries['counts']['published_records'] == 3
    assert all('FOR UPDATE' not in sql.upper() for sql in data.statements)
    assert not data.session.new and not data.session.dirty and not data.session.deleted


def test_task_identity_differs_from_version_and_numeric_collision(data):
    data.save(Article(id=888, task_id=1, version_no=2, kind='master', title='新母稿', body_markdown='test', created_at=NOW),
        Variant(id=888, task_id=1, article_version_id=888, channel='website', title='v2', body_markdown='test', created_at=NOW),
        Publication(id=888, variant_id=888, channel='website', status='published', updated_at=NOW))
    result = internal(data, article_id=1).json()['items']
    newest = next(r for r in result if r['native_publication_id'] == 888)
    assert newest['group_article_id'] == newest['task_id'] == 1
    assert newest['article_version_id'] == 888 and newest['article_version_no'] == 2
    # Existing task 2 and old version row 2 must not become task 1's identity.
    assert all(r['group_article_id'] == 1 for r in result)
    assert internal(data, article_id=888).status_code == 404
    # Current master changed without fresh rule checks: customer sees no task 1.
    assert client(data, article_id=1).status_code == 404
    assert client(data).json()['counts']['external_records'] == 1  # Only truly unlinked.


def test_invalid_and_unlinked_are_disjoint_and_client_safe(data):
    invalid = internal(data, bucket='invalid').json()['items']
    unlinked = internal(data, bucket='unlinked').json()['items']
    assert [r['external_receipt_id'] for r in invalid] == [str(UUID(int=4))]
    assert [r['external_receipt_id'] for r in unlinked] == [str(UUID(int=3))]
    assert 'title' not in invalid[0] and invalid[0]['task_id'] is None
    for body in (client(data).text, client(data, bucket='unlinked').text, client(data, article_id=1).text):
        for forbidden in ('PRIVATE', 'owner_user_id', 'device_id', 'history', 'article_digest', 'can_label', 'payload'):
            assert forbidden not in body
    assert client(data, bucket='invalid').status_code == 422


@pytest.mark.parametrize('call', [internal, client])
def test_independent_detail_and_article_pagination(data, call):
    first = call(data, limit=1).json()
    assert first['items'][0]['task_id'] == 3 and first['has_more']
    second = call(data, limit=1, cursor=first['next_cursor']).json()
    assert second['items'][0]['task_id'] == 2
    assert call(data, limit=1, article_id=1, cursor=first['next_cursor']).status_code == 400
    all_rows, cursor = [], None
    while True:
        body = call(data, article_id=1, limit=1, **({'cursor': cursor} if cursor else {})).json()
        all_rows += body['items']
        cursor = body['next_cursor']
        if not cursor:
            break
    assert len(all_rows) == len({r['source_key'] for r in all_rows}) == 4


@pytest.mark.parametrize('change', ['add', 'delete', 'relabel', 'binding', 'status', 'permissions'])
def test_pagination_revision_requires_refresh(data, change):
    first = internal(data, limit=1).json()
    if change == 'add':
        data.save(receipt(55, article_id=1, article_version=1))
    elif change == 'delete':
        row = data.session.get(Receipt, str(UUID(int=1))); row.deleted_at = NOW; data.save(row)
    elif change == 'relabel':
        row = data.session.get(Receipt, str(UUID(int=1))); row.article_id = 2; row.revision += 1; data.save(row)
    elif change == 'binding':
        project = data.session.get(GeoProject, 1)
        project.project_settings = {'geo_business_scope': {'revision': 2, 'business_ids': [11]}}
        data.save(project)
    elif change == 'status':
        row = data.session.get(Publication, 101); row.status = 'published'; data.save(row)
    else:
        data.ctx.permissions = {'geo.content': 'edit', 'geo.assets': 'view'}
    assert internal(data, limit=1, cursor=first['next_cursor']).status_code in {400, 409}


@pytest.mark.parametrize('extra', [{'scope_id': 2}, {'tenant_id': 202}, {'article_id': 4}])
def test_wrong_project_tenant_task(data, extra):
    assert internal(data, **{'article_id': 1, **extra}).status_code in {403, 404}
    assert client(data, project=2, article_id=1).status_code == 404


@pytest.mark.parametrize('suffix', ['?tenant_id=101&scope_id=1&scope_id=1', '?tenant_id=101',
    '?tenant_id=101&scope_id=1&site_id=1', '?tenant_id=101&scope_id=1&article_id=9007199254740992',
    '?tenant_id=101&scope_id=1&bucket=unlinked&article_id=1', '?tenant_id=101&scope_id=1&limit=101'])
def test_strict_internal_query(data, suffix):
    assert data.http.get(groups.INTERNAL + suffix).status_code == 422


@pytest.mark.parametrize('suffix', ['?tenant_id=101&scope_id=1', '?tenant_id=101&tenant_id=101',
    '?tenant_id=101&ownerUserId=9', '?tenant_id=101&bucket=invalid', '?tenant_id=101&article_id=0'])
def test_strict_client_query(data, suffix):
    response = data.http.get('/api/v1/geo/projects/1/client/publication-groups' + suffix)
    assert response.status_code == 422 and 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('path', [groups.INTERNAL, '/api/v1/geo/projects/1/client/publication-groups'])
def test_exact_paths_and_methods(data, path):
    for bad in (path+'/', path.replace('publication', '%70ublication')):
        assert data.http.get(bad, follow_redirects=False).status_code == 404
    for method in ('POST', 'HEAD', 'DELETE', 'PATCH'):
        assert data.http.request(method, path).status_code == 404


def test_client_cannot_use_internal_actor_and_read_only_customer_no_label(data):
    data.ctx.role_name = 'customer'
    user = data.session.get(User, 9)
    data.save(Role(id=2, name='客户', is_system=False, permissions={'geo.content': 'view'}))
    user.role_id = 2; data.save(user)
    assert internal(data).status_code == 403
    assert client(data).status_code == 200


@pytest.mark.parametrize('change', ['revoked', 'default_revoked', 'reassigned', 'disabled', 'role', 'expired'])
def test_fresh_advisor_authority_rechecked_on_every_page(data, change):
    from app.security.advisor_scope import AdvisorScope
    data.save(Role(id=3, name='顾问', is_system=False, permissions={'geo.assets': 'edit', 'geo.content': 'edit'}),
        Grant(id=1, user_id=9, tenant_id=101, grant_source='backfill', granted_at=NOW),
        Grant(id=2, user_id=9, tenant_id=202, grant_source='backfill', granted_at=NOW))
    user = data.session.get(User, 9); user.role_id = 3; user.tenant_id = 202; data.save(user)
    project = data.session.get(GeoProject, 1)
    project.project_settings = {**project.project_settings, 'geo_service_plan': {'advisor_user_id': 9}}
    data.save(project)
    data.ctx.advisor_scope = AdvisorScope(frozenset({101, 202}), 101, 1)
    data.ctx.permissions = {'geo.assets': 'edit', 'geo.content': 'edit'}
    first = internal(data, limit=1)
    assert first.status_code == 200, first.text
    if change in {'revoked', 'default_revoked'}:
        grant = data.session.get(Grant, 1 if change == 'revoked' else 2)
        grant.revoked_at = NOW + timedelta(days=1); grant.revoked_by = 9; grant.revoke_reason = 'fixture'
        data.save(grant)
    elif change == 'reassigned':
        project.project_settings = {**project.project_settings, 'geo_service_plan': {'advisor_user_id': 88}}
        data.save(project)
    elif change == 'disabled':
        user.is_active = False; data.save(user)
    elif change == 'role':
        role = data.session.get(Role, 3); role.permissions = {'geo.content': 'view'}; data.save(role)
    else:
        data.ctx.inbox_exp = 1
    assert internal(data, limit=1, cursor=first.json()['next_cursor']).status_code == 403


def test_large_scope_5101_and_article_101_and_budget_failure(data, monkeypatch):
    # 5,101 external-only groups, no offset cap; SQL UNION selects the page.
    tasks = [Task(id=i, tenant_id=101, business_id=11, prompt_id=1, title='同名文章', status='ready', updated_at=NOW)
        for i in range(1000, 6101)]
    data.save(*tasks, *(receipt(i+1000, article_id=i, article_version=1) for i in range(1000, 6101)),
        *(Publication(id=10000+i, variant_id=1, channel='website', status='published', updated_at=NOW) for i in range(101)))
    body = internal(data, limit=100).json()
    assert body['counts']['article_groups'] == 5104
    assert len(body['items']) == 100 and body['items'][0]['task_id'] == 6100
    ids = [r['task_id'] for r in body['items']]
    while body['has_more']:
        body = internal(data, limit=100, cursor=body['next_cursor']).json()
        ids.extend(r['task_id'] for r in body['items'])
    assert len(ids) == len(set(ids)) == 5104
    assert set(ids) == {1, 2, 3, *range(1000, 6101)}
    first = internal(data, article_id=1, limit=100).json()
    assert first['has_more'] and len(first['items']) == 100
    second = internal(data, article_id=1, limit=100, cursor=first['next_cursor']).json()
    assert len(second['items']) == 5 and not second['has_more']
    monkeypatch.setattr(groups, 'ROW_BUDGET', 100)
    response = internal(data)
    assert response.status_code == 503 and 'counts' not in response.json()


def test_unlinked_tied_times_have_stable_uuid_pages_and_safe_urls(data):
    data.save(*(receipt(i) for i in range(100, 201)))
    first = client(data, bucket='unlinked', limit=100).json()
    second = client(data, bucket='unlinked', limit=100, cursor=first['next_cursor']).json()
    ids = [r['external_receipt_id'] for r in first['items'] + second['items']]
    assert len(ids) == len(set(ids)) == 102 and ids == sorted(ids)
    row = data.session.get(Receipt, str(UUID(int=3)))
    row.public_url = 'javascript:alert(1)'; data.save(row)
    assert client(data, bucket='unlinked').json()['items'][0]['url'] is None
    assert client(data, bucket='linked', cursor=first['next_cursor'], limit=100).status_code == 400
