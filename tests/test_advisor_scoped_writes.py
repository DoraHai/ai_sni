"""GEO scoped-write acceptance contract: real auth, mounted handlers and SQL.

Run with synthetic settings (see ops.run_geo_checks.prepare_environment) and
Settings.model_config['env_file'] = None before importing app.database. PostgreSQL
uses the existing GEO_TEST_POSTGRES_URL convention, validated as loopback geo_ci;
each test owns a disposable schema. No application lifespan/scheduler is started.
Missing implementation is deliberately a failure, not an xfail, in HTTP tests.
"""
import asyncio
import copy
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import BigInteger, MetaData, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.database import Base, get_session
from app.models import (GeoActionTicket, GeoArticleVersion, GeoAsyncJob,
                        GeoChannelVariant, GeoContentTask, GeoFact,
                        GeoOptimizationBusiness, GeoOptimizationUnit, GeoProject,
                        GeoPrompt, GeoTaskFact, GeoVisibilityPatrolSettings,
                        Role, Tenant, TenantModule, User)
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.security.auth import JWT_ALG, require_auth


@compiles(JSONB, 'sqlite')
def _json_sqlite(_type, _compiler, **_kwargs):
    return 'JSON'


@compiles(BigInteger, 'sqlite')
def _bigint_sqlite(_type, _compiler, **_kwargs):
    # SQLite only auto-generates a primary key for the exact INTEGER spelling.
    return 'INTEGER'


PREFIX = '/api/v1/geo'
SIGNING_KEY = 'scoped-write-fixture-only-signing-key'
EDIT = {'geo.assets': 'edit', 'geo.content': 'edit'}
BRAND_PROFILE = {
    'product_name': '测试品牌', 'website': 'https://brand.example.test',
    'summary': '测试品牌简介', 'industry': '测试行业', 'audience': '测试客户', 'cta': '了解产品',
    'honors': ['测试口号'], 'qualifications': ['测试资质'], 'capabilities': ['测试能力'],
    'scenarios': ['测试场景'], 'competitors': ['测试竞品'],
    'recommend_reasons': ['测试理由'], 'banned_claims': ['测试禁用说法'],
}
# Every mandatory method/template has a distinct success test and persisted
# effect assertion. Imports are optional and tested separately below.
CASES = (
    ('POST', '/facts', {'tenant_id': 10, 'business_id': 10, 'title': 'new fact',
                      'statement': 'synthetic source statement', 'source_name': 'fixture source',
                      'trust_level': 'draft'}, 'geo_facts', 'title', 'new fact'),
    ('PATCH', '/facts/{fact_id}', {'title': 'edited fact'}, 'geo_facts', 'title', 'edited fact'),
    ('POST', '/prompts', {'tenant_id': 10, 'unit_id': 10, 'question': 'new manual question?'},
     'geo_prompts', 'question', 'new manual question?'),
    ('PATCH', '/prompts/{prompt_id}', {'question': 'edited manual question?'},
     'geo_prompts', 'question', 'edited manual question?'),
    ('POST', '/optimization-businesses', {'tenant_id': 10, 'name': 'new business'},
     'geo_optimization_businesses', 'name', 'new business'),
    ('PATCH', '/optimization-businesses/{business_id}', {'description': 'edited business'},
     'geo_optimization_businesses', 'description', 'edited business'),
    ('POST', '/optimization-units', {'tenant_id': 10, 'business_id': 10, 'name': 'new unit'},
     'geo_optimization_units', 'name', 'new unit'),
    ('PATCH', '/optimization-units/{unit_id}', {'description': 'edited unit'},
     'geo_optimization_units', 'description', 'edited unit'),
    ('POST', '/content-tasks', {'tenant_id': 10, 'prompt_id': 10, 'fact_ids': [10],
                              'title': 'new manual task', 'target_channels': ['website']},
     'geo_content_tasks', 'title', 'new manual task'),
    ('PATCH', '/content-tasks/{task_id}', {'title': 'edited manual task'},
     'geo_content_tasks', 'title', 'edited manual task'),
    ('PUT', '/content-tasks/{task_id}/facts', {'fact_ids': [11]},
     'geo_task_facts', 'fact_id', 11),
    ('PUT', '/content-tasks/{task_id}/article', {'expected_article_id': 10, 'title': 'edited article',
                                             'body_markdown': 'A manually edited fixture article.'},
     'geo_article_versions', 'title', 'edited article'),
    ('PATCH', '/content-tasks/{task_id}/variants/{channel}', {'title': 'edited variant'},
     'geo_channel_variants', 'title', 'edited variant'),
    ('PATCH', '/optimization-businesses/{business_id}', {'profile': BRAND_PROFILE},
     'geo_optimization_businesses', 'profile', BRAND_PROFILE),
    ('POST', '/content-imports/create-task', {'tenant_id': 10, 'prompt_id': 10,
        'title': 'imported manual task', 'body_markdown': 'An existing manual article.',
        'source_type': 'paste', 'target_channels': ['website']},
     'geo_content_tasks', 'title', 'imported manual task'),
    ('POST', '/content-imports/create-task', {'tenant_id': 10, 'prompt_id': 10,
        'title': 'uploaded manual task', 'body_markdown': 'An uploaded manual article.',
        'source_type': 'file', 'target_channels': ['website']},
     'geo_content_tasks', 'title', 'uploaded manual task'),
)
CASE_IDS = [f'{method} {path}' for method, path, *_ in CASES]
BUSINESS_TABLES = ('geo_facts', 'geo_prompts', 'geo_optimization_businesses',
                   'geo_optimization_units', 'geo_content_tasks', 'geo_task_facts',
                   'geo_article_versions', 'geo_channel_variants', 'geo_publications',
                   'geo_projects', 'geo_async_jobs', 'geo_action_tickets',
                   'geo_visibility_patrol_settings', 'geo_visibility_patrol_runs',
                   'geo_publishing_channels')


@pytest.fixture(autouse=True)
def no_external_http_or_background_dispatch(monkeypatch):
    from starlette.background import BackgroundTasks
    calls = []

    async def async_http(*_args, **_kwargs):
        calls.append('async HTTP')
        raise AssertionError('manual content writes cannot call external HTTP')

    def sync_http(*_args, **_kwargs):
        calls.append('sync HTTP/background dispatch')
        raise AssertionError('manual content writes cannot dispatch work')

    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', async_http)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', sync_http)
    monkeypatch.setattr(BackgroundTasks, 'add_task', sync_http)
    yield
    # Also catches handlers that swallow supplier/dispatch exceptions.
    assert calls == [], calls


def fixture_token(uid=1, tid=10, gid=101, *, native=False, **changes):
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {'sub': str(uid), 'iat': now, 'exp': now + 600}
    if not native:
        claims.update(scope_kind='advisor_tenant', aud='advisor-business', tid=tid,
                      gid=gid, auth_exp=now + 600)
    claims.update(changes)
    return jwt.encode(claims, SIGNING_KEY, algorithm=JWT_ALG)


def concrete(template, ident=10):
    return template.format(fact_id=ident, prompt_id=ident, business_id=ident,
                           unit_id=ident, task_id=ident, channel='website')


def assert_denied(response, status=403, code=None):
    assert response.status_code == status, response.text
    if code is not None:
        assert response.json()['detail']['code'] == code, response.text


@pytest.fixture(params=['sqlite', 'postgres'])
def backend(request):
    if request.param == 'postgres' and not os.getenv('GEO_TEST_POSTGRES_URL'):
        pytest.skip('requires explicitly configured isolated PostgreSQL')
    return request.param


@asynccontextmanager
async def write_sandbox(tmp_path, monkeypatch, *, backend='sqlite', enabled=True):
    from app.config import get_settings
    from app.geo.content.routes import router, geo_read_session
    import app.database as database
    import app.geo.tenant_scope as entitlement
    import app.security.auth as auth
    from app.security.geo_advisor_delivery import AdvisorDeliveryMiddleware

    settings = get_settings()
    monkeypatch.setitem(settings.__dict__, 'advisor_scoped_content_writes_enabled', enabled)
    # Old flag must never confer rights, including when the scoped flag is off.
    monkeypatch.setitem(settings.__dict__, 'advisor_high_risk_writes_enabled', True)
    monkeypatch.setattr(auth, '_jwt_secret', lambda: SIGNING_KEY)
    schema = 'geo_scoped_writes_' + uuid4().hex
    admin = None
    metadata = MetaData()
    names = set(BUSINESS_TABLES) | {'geo_tracking_engines', 'geo_answer_snapshots', 'roles', 'users', 'tenants', 'tenant_modules',
        'advisor_tenant_grants', 'geo_optimization_periods'}
    # Copy only GEO/auth tables and their FK dependencies, no shared/public data.
    pending = list(names)
    while pending:
        name = pending.pop()
        for foreign_key in Base.metadata.tables[name].foreign_keys:
            target = foreign_key.column.table.name
            if target not in names:
                names.add(target)
                pending.append(target)
    for name in sorted(names):
        Base.metadata.tables[name].to_metadata(metadata)
    if backend == 'postgres':
        from ops.run_geo_checks import validate_ci_database
        url = os.environ['GEO_TEST_POSTGRES_URL']
        validate_ci_database(url)
        admin = create_async_engine(url)
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_async_engine(url, connect_args={'server_settings': {
            'search_path': schema, 'statement_timeout': '10000', 'lock_timeout': '5000'}})
    else:
        engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / (schema + '.sqlite')))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        async with factory() as session:
            session.add_all([Role(id=1, name='顾问', is_system=False, permissions=EDIT),
                             Role(id=2, name='管理员', is_system=True,
                                  permissions={**EDIT, 'settings.accounts': 'edit'}),
                             Role(id=3, name='客户管理员', is_system=False,
                                  permissions={**EDIT, 'settings.customers': 'edit'})])
            session.add_all([Tenant(id=tid, name=f'fixture tenant {tid}') for tid in (10, 20, 30)])
            await session.flush()
            session.add_all([User(id=uid, username=f'fixture-{uid}', role_id=uid, tenant_id=10 if uid != 2 else None,
                                  is_active=True, password_hash='unused-fixture-hash') for uid in (1, 2, 3)])
            for tid in (10, 20, 30):
                session.add(TenantModule(id=tid, tenant_id=tid, module_code='geo', status='active'))
                session.add(GeoOptimizationBusiness(id=tid, tenant_id=tid, name=f'business {tid}'))
            await session.flush()
            for tid in (10, 20, 30):
                session.add(GeoOptimizationUnit(id=tid, tenant_id=tid, business_id=tid, name=f'unit {tid}'))
                session.add(GeoProject(id=tid, tenant_id=tid, tenant_module_id=tid, name=f'project {tid}',
                    primary_domain=f'{tid}.example.test', canonical_domain=f'{tid}.example.test', status='active',
                    project_settings={'geo_business_scope': {'revision': 1, 'business_ids': [tid]},
                        'geo_service_plan': {'revision': 1, 'enabled': False, 'status': 'paused',
                                             'advisor_user_id': 1, 'prompt_ids': [], 'interval_days': 7}}))
                session.add(GeoVisibilityPatrolSettings(tenant_id=tid, enabled=False))
                session.add(GeoFact(id=tid, tenant_id=tid, business_id=tid, title=f'fact {tid}',
                    statement='synthetic evidence statement', source_name='fixture source', trust_level='draft'))
            session.add(GeoFact(id=11, tenant_id=10, business_id=10, title='second fact',
                statement='second synthetic evidence statement', source_name='fixture source', trust_level='draft'))
            session.add_all([Grant(id=101, user_id=1, tenant_id=10, grant_source='backfill'),
                             Grant(id=102, user_id=1, tenant_id=20, grant_source='backfill')])
            await session.flush()
            for tid in (10, 20, 30):
                session.add(GeoPrompt(id=tid, tenant_id=tid, unit_id=tid, question=f'fixture question {tid}?'))
            await session.flush()
            for tid in (10, 20, 30):
                session.add(GeoContentTask(id=tid, tenant_id=tid, business_id=tid, prompt_id=tid,
                    title=f'fixture task {tid}', status='editing', target_channels=['website'],
                    brief={}, owner_user_id=1, review_status='approved', rule_result={'ready': True}))
                # Deliberately collide task IDs with a different tenant's action
                # ticket: content task_id MUST resolve to geo_content_tasks.
                session.add(GeoActionTicket(id=tid, tenant_id=30 if tid == 10 else tid,
                    title='unrelated action ticket', status='open'))
            await session.flush()
            for tid in (10, 20, 30):
                session.add(GeoArticleVersion(id=tid, task_id=tid, version_no=1, title=f'article {tid}',
                    body_markdown='Original fixture article.', outline={}))
                session.add(GeoTaskFact(task_id=tid, fact_id=tid))
            await session.flush()
            for tid in (10, 20, 30):
                session.add(GeoChannelVariant(id=tid, task_id=tid, article_version_id=tid,
                    channel='website', title='Original variant', body_markdown='Original fixture variant.', status='draft'))
            await session.commit()

        async def session_dependency():
            async with factory() as session:
                try:
                    yield session
                except BaseException:
                    await session.rollback()
                    raise

        async def production(*_args, **_kwargs):
            # Existing advisor fixture substitutes only PostgreSQL demo binding
            # lookup; actual tenant module, grants, objects and assignments stay real.
            return SimpleNamespace(is_demo=False, read_only=False)

        monkeypatch.setattr(entitlement, 'ensure_geo_entitlement', production)
        monkeypatch.setattr(database, 'async_session_factory', factory)
        app = FastAPI()
        app.add_middleware(AdvisorDeliveryMiddleware)
        app.include_router(router, prefix=PREFIX)

        @app.post(PREFIX + '/not-reviewed')
        async def unknown(_ctx=Depends(require_auth)):
            pytest.fail('unknown write handler must never execute')

        app.dependency_overrides[get_session] = session_dependency
        app.dependency_overrides[geo_read_session] = session_dependency
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            async def request(method, path, *, body=None, auth=None, params=None, **kwargs):
                return await client.request(method, PREFIX + path,
                    params={'tenant_id': 10, **(params or {})},
                    headers={'Authorization': 'Bearer ' + (auth or fixture_token())},
                    **({'json': body} if body is not None else {}), **kwargs)

            async def snapshot():
                async with factory() as session:
                    result = {}
                    for name in BUSINESS_TABLES:
                        table = Base.metadata.tables[name]
                        rows = (await session.execute(select(table).order_by(*table.primary_key.columns))).mappings().all()
                        result[name] = copy.deepcopy([dict(row) for row in rows])
                    return result

            yield SimpleNamespace(request=request, factory=factory, snapshot=snapshot, app=app, engine=engine)
    finally:
        if admin is not None:
            async with engine.begin() as connection:
                await connection.run_sync(metadata.drop_all)
            await engine.dispose()
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA {schema}'))
            await admin.dispose()
        else:
            await engine.dispose()


async def mutate(env, model, ident, **values):
    async with env.factory() as session:
        key = model.tenant_id if model is GeoVisibilityPatrolSettings else model.id
        await session.execute(update(model).where(key == ident).values(**values))
        await session.commit()


@pytest.mark.parametrize('case', CASES, ids=CASE_IDS)
@pytest.mark.parametrize('actor', ['advisor', 'administrator'])
def test_every_allowed_mounted_handler_persists_only_manual_content(tmp_path, monkeypatch, backend, case, actor):
    async def run():
        method, template, body, table, column, value = case
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            params = {'project_id': 10} if template == '/optimization-businesses' else {}
            response = await env.request(method, concrete(template), body=body, params=params,
                auth=fixture_token(uid=2, native=True) if actor == 'administrator' else None)
            assert response.status_code in {200, 201}, response.text
            after = await env.snapshot()
            expected = value
            if column == 'profile' and actor == 'administrator':
                from app.geo.content.business_profile import normalize_profile
                expected = normalize_profile(value)
            assert any(row[column] == expected for row in after[table]), (table, expected)
            # Response success alone cannot hide dispatch, publication or changes
            # to the action-ticket table with the colliding task_id.
            for untouched in ('geo_publications', 'geo_async_jobs', 'geo_action_tickets',
                              'geo_visibility_patrol_settings', 'geo_visibility_patrol_runs',
                              'geo_publishing_channels'):
                assert after[untouched] == before[untouched], untouched
            if template.endswith('/article'):
                assert len(after[table]) == len(before[table]) + 1
                assert after['geo_content_tasks'][0]['review_status'] != 'approved'
            if '/variants/' in template:
                assert len(after[table]) == len(before[table])
                assert after['geo_content_tasks'][0]['review_status'] != 'approved'
            if actor == 'advisor' and template == '/content-tasks/{task_id}/facts':
                assert after['geo_content_tasks'][0]['review_status'] != 'approved'
            if actor == 'advisor' and template == '/optimization-businesses':
                created = next(row for row in after[table] if row['name'] == value)
                project = next(row for row in after['geo_projects'] if row['id'] == 10)
                assert created['id'] in project['project_settings']['geo_business_scope']['business_ids']
            # No other customer's content can change even on the success path.
            for name in ('geo_facts', 'geo_prompts', 'geo_optimization_businesses',
                         'geo_optimization_units', 'geo_content_tasks'):
                assert [r for r in after[name] if r['tenant_id'] != 10] == [
                    r for r in before[name] if r['tenant_id'] != 10]
    asyncio.run(run())


@pytest.mark.parametrize('case', CASES, ids=CASE_IDS)
def test_switch_off_even_with_old_flag_rejects_without_writes(tmp_path, monkeypatch, backend, case):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend, enabled=False) as env:
            before = await env.snapshot()
            response = await env.request(case[0], concrete(case[1]), body=case[2])
            assert_denied(response, code='ADVISOR_HIGH_RISK_WRITES_DISABLED')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('tid', [20, 30], ids=['granted-but-not-selected', 'not-granted'])
@pytest.mark.parametrize('case', CASES, ids=CASE_IDS)
def test_other_customer_query_and_body_never_write(tmp_path, monkeypatch, backend, case, tid):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            body = {**case[2], **({'tenant_id': tid} if 'tenant_id' in case[2] else {})}
            response = await env.request(case[0], concrete(case[1], tid), body=body, params={'tenant_id': tid})
            assert_denied(response, code='ADVISOR_TENANT_NOT_GRANTED')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('path,body', [
    ('/facts', {**CASES[0][2], 'business_id': 20}),
    ('/prompts', {**CASES[2][2], 'unit_id': 20}),
    ('/optimization-units', {**CASES[6][2], 'business_id': 20}),
    ('/content-tasks', {**CASES[8][2], 'prompt_id': 20}),
    ('/content-tasks', {**CASES[8][2], 'fact_ids': [10, 20]}),
], ids=['business', 'unit', 'unit-business', 'prompt', 'fact-array'])
def test_cross_customer_body_ids_return_403_and_rollback(tmp_path, monkeypatch, backend, path, body):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            assert_denied(await env.request('POST', path, body=body), code='ADVISOR_TENANT_NOT_GRANTED')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('change', [
    {'status': 'published'}, {'status': 'ready'}, {'status': 'archived'},
    {'owner_user_id': 2}, {'advisor_user_id': 2}, {'tenant_id': 20},
    {'project_id': 20}, {'published_at': '2026-10-18T00:00:00'}, {'unknown_field': 'x'},
])
def test_task_patch_forbidden_fields_are_403_before_handler(tmp_path, monkeypatch, backend, change):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            assert_denied(await env.request('PATCH', '/content-tasks/10', body={'title': 'must not persist', **change}),
                          code='ADVISOR_WRITE_FIELD_FORBIDDEN')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('method,path,change', [
    ('POST', '/facts', {'trust_level': 'verified'}),
    ('PATCH', '/facts/10', {'trust_level': 'verified'}),
    ('PATCH', '/facts/10', {'meta': {'public_use_allowed': True}}),
    ('PATCH', '/facts/10', {'meta': {'verified_by': 2}}),
    ('PATCH', '/facts/10', {'status': 'archived'}),
    ('PATCH', '/facts/10', {'business_id': 20}),
    ('PATCH', '/prompts/10', {'status': 'archived'}),
    ('PATCH', '/prompts/10', {'is_brand_probe': True}),
    ('PATCH', '/prompts/10', {'unit_id': 20}),
    ('PATCH', '/optimization-businesses/10', {'status': 'archived'}),
    ('PATCH', '/optimization-units/10', {'business_id': 20}),
    ('PATCH', '/optimization-units/10', {'status': 'archived'}),
    ('PATCH', '/content-tasks/10/variants/website', {'status': 'published'}),
])
def test_protected_resource_fields_cannot_be_injected(tmp_path, monkeypatch, backend, method, path, change):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            body = {**(CASES[0][2] if method == 'POST' else {}), **change}
            assert_denied(await env.request(method, path, body=body))
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('project_change', [
    {'status': 'archived'},
    {'project_settings': {'geo_business_scope': {'business_ids': [10]},
                          'geo_service_plan': {'enabled': False, 'advisor_user_id': 2}}},
    {'project_settings': {'geo_business_scope': {'business_ids': []},
                          'geo_service_plan': {'enabled': False, 'advisor_user_id': 1}}},
    {'project_settings': {}},
])
def test_missing_or_wrong_project_assignment_rejects(tmp_path, monkeypatch, backend, project_change):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await mutate(env, GeoProject, 10, **project_change)
            before = await env.snapshot()
            response = await env.request('PATCH', '/content-tasks/10', body={'title': 'must not persist'})
            assert_denied(response, code='ADVISOR_ASSIGNMENT_REQUIRED')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('method,path', [
    ('POST', '/not-reviewed'), ('DELETE', '/content-tasks/10'),
     ('POST', '/content-tasks/10/variants'),
    ('POST', '/content-tasks/10/publications'), ('POST', '/content-tasks/10/submit-review'),
    ('POST', '/content-tasks/10/review'), 
     
     ('POST', '/content-tasks/10/push'),
    ('POST', '/content-tasks/10/push-batch'), ('POST', '/answer-snapshots/probe'),
    ('POST', '/answer-snapshots/probe-batch'),
])
def test_outside_exact_write_list_stays_closed(tmp_path, monkeypatch, backend, method, path):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            assert_denied(await env.request(method, path, body={'tenant_id': 10}),
                          code='ADVISOR_HIGH_RISK_WRITES_DISABLED')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('path', ['/api/v1/roles/1', '/api/v1/users/1'])
def test_advisor_cannot_change_account_or_role_permissions(tmp_path, monkeypatch, backend, path):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            # Mount an authenticated sentinel: a forbidden permission route must
            # be rejected by the advisor guard before any handler can run.
            async def permission_handler(_ctx=Depends(require_auth)):
                pytest.fail('advisor reached a permission-changing handler')

            env.app.add_api_route(path, permission_handler, methods=['PATCH'])
            before = await env.snapshot()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url='http://fixture') as client:
                response = await client.patch(path, json={'permissions': {'settings.accounts': 'edit'}},
                    headers={'Authorization': 'Bearer ' + fixture_token()})
            assert_denied(response, code='ADVISOR_HIGH_RISK_WRITES_DISABLED')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('uid', [2, 3], ids=['administrator', 'native-customer-editor'])
def test_non_advisor_existing_write_behavior_unchanged(tmp_path, monkeypatch, backend, uid):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend, enabled=False) as env:
            response = await env.request('POST', '/facts', body=CASES[0][2], auth=fixture_token(uid=uid, native=True))
            assert response.status_code in {200, 201}, response.text
            assert any(r['title'] == 'new fact' for r in (await env.snapshot())['geo_facts'])
    asyncio.run(run())


@pytest.mark.parametrize('change', ['grant', 'inactive', 'locked', 'role', 'no-grants'])
def test_revoked_or_changed_identity_cannot_write_or_use_default_tenant(tmp_path, monkeypatch, backend, change):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            if change in {'grant', 'no-grants'}:
                for gid in ([101, 102] if change == 'no-grants' else [101]):
                    await mutate(env, Grant, gid, revoked_at=datetime.now(timezone.utc),
                                 revoked_by=2, revoke_reason='fixture_revocation')
            elif change == 'inactive':
                await mutate(env, User, 1, is_active=False)
            elif change == 'locked':
                await mutate(env, User, 1, locked_until=datetime.now() + timedelta(hours=1))
            else:
                await mutate(env, User, 1, role_id=3)
            before = await env.snapshot()
            response = await env.request('POST', '/facts', body=CASES[0][2])
            assert response.status_code in {401, 403}, response.text
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('which', ['patrol', 'cycle'])
@pytest.mark.parametrize('case', [CASES[0], CASES[2]], ids=['fact', 'prompt'])
def test_new_material_cannot_feed_enabled_execution_chain(tmp_path, monkeypatch, backend, which, case):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            if which == 'patrol':
                await mutate(env, GeoVisibilityPatrolSettings, 10, enabled=True)
            else:
                async with env.factory() as session:
                    project = await session.get(GeoProject, 10)
                    settings = copy.deepcopy(project.project_settings)
                settings['geo_service_plan'].update(enabled=True, status='active', prompt_ids=[10])
                await mutate(env, GeoProject, 10, project_settings=settings)
            before = await env.snapshot()
            assert_denied(await env.request(case[0], case[1], body=case[2]))
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('expected,accepted', [('missing', False), (None, True), (20, False)])
def test_first_article_requires_explicit_null_base(tmp_path, monkeypatch, backend, expected, accepted):
    async def run():
        from sqlalchemy import delete
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as session:
                await session.execute(delete(GeoChannelVariant).where(GeoChannelVariant.task_id == 10))
                await session.execute(delete(GeoArticleVersion).where(GeoArticleVersion.task_id == 10))
                await session.commit()
            before = await env.snapshot()
            body = {'title': 'first article', 'body_markdown': 'First manual article.'}
            if expected != 'missing':
                body['expected_article_id'] = expected
            response = await env.request('PUT', '/content-tasks/10/article', body=body)
            if accepted:
                assert response.status_code in {200, 201}, response.text
                assert len((await env.snapshot())['geo_article_versions']) == len(before['geo_article_versions']) + 1
            else:
                assert response.status_code in {403, 409, 422}, response.text
                assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('variant_state', ['published', 'missing'])
def test_channel_edit_never_creates_or_overwrites_published_variant(tmp_path, monkeypatch, backend, variant_state):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            if variant_state == 'published':
                await mutate(env, GeoChannelVariant, 10, status='published')
            before = await env.snapshot()
            channel = 'website' if variant_state == 'published' else 'wechat'
            response = await env.request('PATCH', f'/content-tasks/10/variants/{channel}', body={'title': 'cannot save'})
            assert response.status_code in ({403, 409} if variant_state == 'published' else {404}), response.text
            assert await env.snapshot() == before
    asyncio.run(run())


def test_stale_article_version_cannot_append_or_overwrite(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            # A stale version is an existing older version of this task, not
            # a nonexistent ID (which correctly returns 404 at object lookup).
            async with env.factory() as session:
                session.add(GeoArticleVersion(id=9, task_id=10, version_no=0,
                    title='older article', body_markdown='Older manual version.', outline={}))
                await session.commit()
            before = await env.snapshot()
            response = await env.request('PUT', '/content-tasks/10/article', body={
                'expected_article_id': 9, 'title': 'stale edit', 'body_markdown': 'must not persist'})
            assert_denied(response, status=409)
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('body_tid', [20, 30])
def test_body_tenant_cannot_override_selected_query_tenant(tmp_path, monkeypatch, backend, body_tid):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request('POST', '/facts', body={**CASES[0][2], 'tenant_id': body_tid})
            assert_denied(response, code='ADVISOR_TENANT_NOT_GRANTED')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('token_changes', [
    {'scope_kind': 'advisor_identity', 'aud': 'advisor-session'}, {'gid': 999},
    {'auth_exp': 1}, {'exp': 1}, {'aud': 'wrong-audience'}, {'tid': 20, 'gid': 101},
])
def test_invalid_business_identity_never_reaches_a_write(tmp_path, monkeypatch, backend, token_changes):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request('POST', '/facts', body=CASES[0][2], auth=fixture_token(**token_changes))
            assert response.status_code in {401, 403, 409}, response.text
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('brief', [
    {'source_opportunity': {'prompt_id': 20}},
    {'nested': [{'fact_ids': [10, 20]}]},
    {'nested': {'future_object_id': 10}},
])
def test_raw_nested_body_is_checked_before_schema_drops_unknown_keys(tmp_path, monkeypatch, backend, brief):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request('PATCH', '/content-tasks/10', body={
                'title': 'must not persist', 'brief': brief})
            assert_denied(response, code='ADVISOR_OBJECT_UNAVAILABLE' if 'future_object_id' in str(brief)
                          else 'ADVISOR_TENANT_NOT_GRANTED')
            assert await env.snapshot() == before
    asyncio.run(run())


def test_manual_brief_edit_invalidates_old_customer_review(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            response = await env.request('PATCH', '/content-tasks/10', body={
                'brief': {'audience': 'new fixture audience', 'notes': 'manual editorial change'}})
            assert response.status_code in {200, 201}, response.text
            async with env.factory() as session:
                task = await session.get(GeoContentTask, 10)
                assert task.brief['audience'] == 'new fixture audience'
                assert task.review_status != 'approved'
    asyncio.run(run())


@pytest.mark.parametrize('method,path,body,params', [
    ('PATCH', '/facts/20', {'title': 'must not persist'}, {}),
    ('PATCH', '/content-tasks/20', {'title': 'must not persist'}, {}),
    ('PATCH', '/content-tasks/20/variants/website', {'title': 'must not persist'}, {}),
    ('PUT', '/content-tasks/10/facts', {'fact_ids': [10, 20]}, {}),
    ('PUT', '/content-tasks/10/article', {'expected_article_id': 20, 'title': 'must not persist',
                                       'body_markdown': 'foreign article base'}, {}),
    ('PATCH', '/content-tasks/10', {'title': 'must not persist'}, {'business_id': 20}),
])
def test_foreign_path_query_or_article_base_cannot_hide_behind_current_tenant(tmp_path, monkeypatch, backend, method, path, body, params):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request(method, path, body=body, params=params)
            assert_denied(response, code='ADVISOR_TENANT_NOT_GRANTED')
            assert await env.snapshot() == before
    asyncio.run(run())
