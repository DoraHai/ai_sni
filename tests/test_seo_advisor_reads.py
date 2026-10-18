import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from app.models.seo import SeoContentAsset, SeoSiteAdvisorAssignment
from app.models.module_workspace import SeoSite
from app.security.seo_advisor_reads import install_query_scope
from app.security.advisor_tenant_auth import check_seo_objects
from test_advisor_scoped_writes_objects import object_db, selected  # noqa: F401
from test_advisor_tenant_auth import local_db  # noqa: F401
from test_seo_advisor_work import req


def test_assignment_filters_lists_totals_aliases_and_core_rows(object_db):
    db, session = object_db
    install_query_scope(session, selected())
    assert list(db.scalars(select(SeoContentAsset.id))) == [1]
    assert db.scalar(select(func.count()).select_from(SeoContentAsset)) == 1
    model = aliased(SeoContentAsset)
    assert list(db.scalars(select(model.id))) == [1]
    assert [row.id for row in db.execute(select(SeoContentAsset.__table__))] == [1]
    assert list(db.scalars(select(SeoSite.id))) == [1]


@pytest.mark.parametrize('kind,object_id', [('content_id', 301), ('site_id', 4), ('content_id', 101), ('content_id', 201)])
def test_explicit_read_rejects_other_projects_and_customers(object_db, kind, object_id):
    request = req('GET', '/api/v1/seo/content-assets', query=f'tenant_id=1&{kind}={object_id}')
    with pytest.raises(HTTPException):
        asyncio.run(check_seo_objects(request, selected(), object_db[1]))


def test_revoked_assignment_and_inactive_site_disappear_from_reads(object_db):
    db, session = object_db
    install_query_scope(session, selected())
    assignment = db.get(SeoSiteAdvisorAssignment, 1)
    assignment.active = False
    db.commit()
    assert list(db.scalars(select(SeoContentAsset.id))) == []


@pytest.mark.parametrize('site_id', [None, 1, 4])
def test_customer_shared_connections_require_an_explicit_assigned_site(object_db, site_id):
    request = req('GET', '/api/v1/seo/content-distribution/connections',
                  query='tenant_id=1' + (f'&site_id={site_id}' if site_id else ''))
    if site_id == 1:
        asyncio.run(check_seo_objects(request, selected(), object_db[1]))
    else:
        with pytest.raises(HTTPException):
            asyncio.run(check_seo_objects(request, selected(), object_db[1]))


@pytest.fixture
def channel_db(object_db):
    from app.database import Base
    from app.models.seo import SeoContentPublication, SeoDistributionConnection, SeoDistributionVariant
    db, session = object_db
    Base.metadata.create_all(db.bind, tables=[m.__table__ for m in
        (SeoDistributionConnection, SeoContentPublication, SeoDistributionVariant)])
    for object_id, binding in [(10, 1), (11, 4), (12, None)]:
        db.add(SeoDistributionConnection(id=object_id, tenant_id=1, platform_code='wordpress',
            name=str(object_id), mode='api', config={} if binding is None else {'advisor_site_id': binding}))
    db.commit()
    return db, session


def test_channel_lists_totals_and_ids_are_bound_to_the_selected_site(channel_db):
    from app.models.seo import SeoDistributionConnection as Connection
    db, session = channel_db
    ctx = selected(); ctx.advisor_read_site_id = 1
    install_query_scope(session, ctx)
    assert list(db.scalars(select(Connection.id))) == [10]
    assert db.scalar(select(func.count()).select_from(Connection)) == 1
    request = req('GET', '/api/v1/seo/content-distribution/connections', query='tenant_id=1&site_id=1&connection_id=11')
    with pytest.raises(HTTPException): asyncio.run(check_seo_objects(request, ctx, session))


def test_unbound_channel_cannot_be_laundered_by_creating_a_variant(channel_db):
    from app.security.advisor_write_routes import match_write_rule
    from app.security.seo_advisor_work import lock_workflow_scope
    body = {'tenant_id': 1, 'site_id': 1, 'content_id': 1, 'connection_id': 12}
    request = req('POST', '/api/v1/seo/content-distribution/variants', body)
    with pytest.raises(HTTPException):
        asyncio.run(lock_workflow_scope(channel_db[1], selected(), request, body, match_write_rule(request)))


def test_prior_usage_is_allowed_but_explicit_revocation_overrides_it(channel_db):
    from app.models.seo import SeoDistributionConnection, SeoDistributionVariant
    from app.security.seo_advisor_connections import ensure_connection_binding
    db, session = channel_db
    db.add(SeoDistributionVariant(id=30, tenant_id=1, content_asset_id=1, connection_id=12,
        platform_code='wordpress', title='fixture', content='fixture'))
    db.commit()
    connection = db.get(SeoDistributionConnection, 12)
    row = {'id': 12, 'config': {}}
    asyncio.run(ensure_connection_binding(session, selected(), [row], 1))
    connection.config = {'advisor_site_id': 0}; db.commit(); row['config'] = connection.config
    with pytest.raises(HTTPException):
        asyncio.run(ensure_connection_binding(session, selected(), [row], 1))


def test_advisor_cannot_change_bindings_or_customer_wide_brand_fields(channel_db):
    from types import SimpleNamespace
    from app.api.seo import _set_customer_brand_name
    from app.models.seo import SeoDistributionConnection
    from app.security.seo_advisor_connections import set_connection_binding
    db, session = channel_db
    with pytest.raises(HTTPException):
        asyncio.run(set_connection_binding(session, selected(), db.get(SeoDistributionConnection, 12), 1, 1))
    tenant = SimpleNamespace(name='Shared brand', brand_terms=['Existing term'])
    with pytest.raises(HTTPException): _set_customer_brand_name(selected(), tenant, 'Other brand')
    _set_customer_brand_name(selected(), tenant, 'Shared brand')
    assert tenant.name == 'Shared brand' and tenant.brand_terms == ['Existing term']


def test_admin_binding_uses_existing_config_and_rejects_foreign_customer_site(channel_db):
    from app.models.seo import SeoDistributionConnection
    from app.security.auth import AuthContext
    from app.security.seo_advisor_connections import set_connection_binding
    db, session = channel_db
    admin = AuthContext(3, 'fixture', '管理员', None, {}, is_superadmin=True)
    row = db.get(SeoDistributionConnection, 12)
    asyncio.run(set_connection_binding(session, admin, row, 1, 1))
    assert row.config == {'advisor_site_id': 1}
    with pytest.raises(HTTPException): asyncio.run(set_connection_binding(session, admin, row, 1, 2))
    assert row.config == {'advisor_site_id': 1}
    asyncio.run(set_connection_binding(session, admin, row, 1, None))
    assert row.config == {'advisor_site_id': 0}


@pytest.mark.parametrize('domain', ['changed.example', 'shared.example'])
def test_brand_profile_handler_does_not_modify_global_or_sibling_homepage(object_db, monkeypatch, domain):
    """Exercise the real request guard and handler, including existing globals."""
    from unittest.mock import AsyncMock
    from app.api.seo import BrandProfileUpdate, update_brand_profile
    from app.config import get_settings
    from app.models.role import Role
    from app.models.seo import SeoBrandAsset, SeoSitePage
    from app.models.tenant import Tenant
    from app.security.advisor_tenant_auth import enforce_advisor_request
    db, session = object_db
    own, sibling = db.get(SeoBrandAsset, 40), db.get(SeoBrandAsset, 340)
    for row, value in [(own, 'own.example'), (sibling, 'sibling.example')]:
        row.asset_type, row.name, row.match_value = 'official_domain', '主官网', value
    global_asset = SeoBrandAsset(id=80, tenant_id=1, site_id=None,
        asset_type='official_domain', name='主官网', match_value='shared.example', status='active')
    db.add_all([global_asset, SeoSiteAdvisorAssignment(id=4, tenant_id=1, site_id=4,
                                                    advisor_user_id=1, active=True)])
    db.get(SeoSitePage, 50).url = 'https://' + domain
    role = db.get(Role, 1)
    role.permissions = {**role.permissions, 'seo.keywords': 'edit'}
    db.commit()
    session.no_autoflush = db.no_autoflush
    session.rollback = AsyncMock(side_effect=db.rollback)
    session.refresh = AsyncMock(side_effect=db.refresh)
    monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', True)
    body = {'tenant_id': 1, 'site_id': 1, 'brand_name': 'tenant1', 'website': 'https://' + domain}
    ctx = selected()
    request = req('PATCH', '/api/v1/seo/rank-serp/brand-profile', body, query='tenant_id=1&site_id=1')
    async def operation():
        await enforce_advisor_request(request, ctx, session)
        return await update_brand_profile(BrandProfileUpdate(**body), session, ctx)
    response = asyncio.run(operation())
    # Read the evidence without the request filter; unrelated rows really exist.
    install_query_scope(session, None)
    db.expire_all()
    assert db.get(SeoBrandAsset, 40).match_value == domain
    assert (db.get(SeoBrandAsset, 80).match_value, db.get(SeoBrandAsset, 80).status) == ('shared.example', 'active')
    assert (db.get(SeoBrandAsset, 340).match_value, db.get(SeoBrandAsset, 340).status) == ('sibling.example', 'active')
    assert db.get(Tenant, 1).name == 'tenant1'
    assert response['official_domains'] == [domain]
