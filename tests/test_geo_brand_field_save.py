"""Brand PATCH regression using mocked persistence only: no DB or login tokens."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.database import get_session
from app.geo.content.business_profile import PROFILE_LABELS, normalize_profile
from app.geo.content.routes import router, _business_payload
from app.geo.content.schemas import OptimizationBusinessCreate, OptimizationBusinessUpdate
from app.security.advisor_scope import AdvisorScope
from app.security.auth import require_scoped_auth


@pytest.fixture(autouse=True)
def forbid_database(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('This test must never connect to a database')
    monkeypatch.setattr(AsyncEngine, 'connect', forbidden)
    monkeypatch.setattr(AsyncEngine, 'begin', forbidden)


async def exercise(body, *, advisor=False, tenant_id=15):
    original = {'product_name': '原品牌', 'website': 'https://old.example.test',
                'summary': '保留简介', 'industry': '原行业', 'honors': ['原口号'],
                'qualifications': ['原证书'], 'geo_scope': '保留区域'}
    row = NS(id=10, tenant_id=15, name='业务名称', description='旧业务描述',
             status='active', sort_order=0, profile=deepcopy(original), created_at=None, updated_at=None)
    session = NS(scalar=AsyncMock(return_value=row), commit=AsyncMock(), refresh=AsyncMock())
    scope = AdvisorScope(frozenset({15}), tenant_id=15, grant_id=101) if advisor else None
    ctx = NS(advisor_scope=scope, ensure_tenant=scope.ensure_tenant if scope else lambda _tid: None)
    app = FastAPI()
    app.include_router(router, prefix='/api/v1/geo')
    app.dependency_overrides[require_scoped_auth] = lambda: ctx
    app.dependency_overrides[get_session] = lambda: session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://mock') as client:
        response = await client.patch('/api/v1/geo/optimization-businesses/10',
                                      params={'tenant_id': tenant_id}, json=body)
    return response, row, original, session


@pytest.mark.parametrize('advisor', [False, True])
def test_six_fields_round_trip_and_partial_clear(advisor):
    fields = dict(product_name='新品牌', website='https://brand.example.test/path',
                  industry='制造业', summary='简介😀', honors='甲，乙', qualifications='一；二')
    response, row, original, session = asyncio.run(exercise({'profile': fields}, advisor=advisor))
    assert response.status_code == 200, response.text
    expected = {**original, **fields, 'honors': ['甲', '乙'], 'qualifications': ['一', '二']}
    assert row.profile == expected
    assert response.json()['profile'] == _business_payload(row)['profile'] == normalize_profile(expected)
    session.commit.assert_awaited_once()
    response, row, original, session = asyncio.run(exercise({'profile': {'website': '', 'summary': ''}}, advisor=advisor))
    assert response.status_code == 200
    assert row.profile == {**original, 'website': '', 'summary': ''}


@pytest.mark.parametrize('advisor', [False, True])
@pytest.mark.parametrize('site', ['javascript:alert(1)', 'data:text/html,x', 'ftp://example.test',
                                'example.test', '//example.test', 'http:/example.test',
                                'https://user:pass@example.test', 'http://['])
def test_invalid_site_rejects_whole_patch(advisor, site):
    response, row, original, session = asyncio.run(exercise(
        {'name': '不应保存', 'profile': {'industry': '不应保存', 'website': site}}, advisor=advisor))
    assert response.status_code in {403, 422}, response.text
    assert '官网地址要以 http:// 或 https:// 开头' in response.text
    assert row.profile == original and row.name == '业务名称'
    session.commit.assert_not_awaited()


@pytest.mark.parametrize('advisor', [False, True])
@pytest.mark.parametrize('field', list(PROFILE_LABELS))
def test_overlong_fields_rejected_before_any_mutation(advisor, field):
    response, row, original, session = asyncio.run(exercise(
        {'profile': {'industry': '不应保存', field: '字' * 501}}, advisor=advisor))
    assert response.status_code in {403, 422}, response.text
    # geo_scope remains deliberately forbidden to advisors.
    if not (advisor and field == 'geo_scope'):
        assert '500 字，现在 501 字' in response.text
        assert PROFILE_LABELS[field] in response.text
    assert row.profile == original
    session.commit.assert_not_awaited()


def test_advisor_cannot_patch_another_customer():
    response, row, original, session = asyncio.run(exercise({'profile': {'summary': '越权'}}, advisor=True, tenant_id=17))
    assert response.status_code == 403
    assert row.profile == original
    session.scalar.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize('schema', [OptimizationBusinessCreate, OptimizationBusinessUpdate])
def test_create_and_update_schemas_enforce_same_bounds(schema):
    base = {'tenant_id': 15, 'name': '业务'} if schema is OptimizationBusinessCreate else {}
    assert schema(**base, profile={'summary': '😀' * 500}).profile['summary'] == '😀' * 500
    for profile in ({'summary': '😀' * 501}, {'honors': ['一'] * 21}, None):
        with pytest.raises(ValueError):
            schema(**base, profile=profile)


def test_read_normalization_never_silently_truncates_legacy_values():
    assert normalize_profile({'summary': '字' * 501})['summary'] == '字' * 501
