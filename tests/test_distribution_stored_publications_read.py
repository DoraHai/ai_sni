"""Owned stored-list fence wiring; no live JWT, PG, TLS or platform writes."""
import ast
import asyncio
import importlib.util
import os
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
import pytest

ROOT = Path(__file__).parents[1]
NATIVE = Path(os.environ.get('NATIVE_SEO_COVER_ROOT', str(ROOT.parent / 'seo-wechat-cover-acceptance-20261012')))
QUERY = 'tenant_id=15&site_id=6&content_id=61'


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('stored_publications_factory_test', ROOT / 'scripts/distribution_server_pilot_native.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def context():
    root = Path('/opt/gsnipers-distribution-acceptance/work/distribution-server-pilot-20261012')
    return root, {'root': str(root), 'production': False, 'platform': 'linux-acceptance',
        'ports': {'pg': 55483, 'seo': 55861, 'geo': 55862},
        'native_heads': {'seo': '3087e62f23e799fe82d279f79f698f0499bf3a27'}}


def request(factory, *, query=QUERY, path=None, method='GET', raw=None, authorization='Bearer routing-only'):
    path = path or factory.STORED_PUBLICATIONS_READ_PATH
    headers = [(b'authorization', authorization.encode())] if authorization is not None else []
    return Request({'type': 'http', 'method': method, 'scheme': 'https', 'server': ('127.0.0.1', 55861),
        'path': path, 'raw_path': raw if raw is not None else path.encode(), 'query_string': query.encode(), 'headers': headers})


def prepared(factory):
    native = APIRouter()
    calls = []
    async def original_session():
        raise AssertionError('original unbound session must not execute')
        yield
    async def owned_session():
        calls.append('owned_session')
        yield object()
    async def scoped(request: Request):
        value = request.headers.get('authorization')
        if value == 'Bearer foreign-tenant': raise HTTPException(403, 'synthetic foreign scope')
        if value != 'Bearer routing-only': raise HTTPException(401, 'synthetic expired JWT')
    @native.get(factory.STORED_PUBLICATIONS_READ_PATH)
    async def list_content_publications(session=Depends(original_session), ctx=Depends(scoped)):
        calls.append('native_read')
        return {'items': [], 'total': 0, 'status_counts': {}}
    @native.post(factory.STORED_PUBLICATIONS_READ_PATH)
    async def forbidden_write(): raise AssertionError('adjacent write must not be mounted')
    app = FastAPI()
    app.dependency_overrides[original_session] = owned_session
    reader = factory.mount_stored_publications_read(app, native, 'seo')
    return app, reader, native, calls


def test_exact_stored_read_does_not_need_any_permit_and_retains_original_binding(factory):
    root, config = context(); app, reader, native, _ = prepared(factory)
    assert factory.readonly_stored_publications(request(factory), root, config, 'seo', app, reader)
    original = next(route for route in native.routes if route.methods == {'GET'})
    mounted = next(route for route in app.routes if getattr(route, 'path', '') == factory.STORED_PUBLICATIONS_READ_PATH)
    assert mounted.endpoint is original.endpoint and type(mounted) is type(original)
    assert [dep.call for dep in mounted.dependant.dependencies] == [dep.call for dep in original.dependant.dependencies]
    before = list(app.routes)
    assert factory.mount_stored_publications_read(app, native, 'seo') is reader
    assert app.routes == before
    assert factory.mount_stored_publications_read(app, native, 'geo') is None
    assert app.routes == before


@pytest.mark.parametrize('change', ['production', 'platform', 'root', 'config_root', 'ports', 'native', 'geo',
    'post', 'head', 'trailing_slash', 'encoded_path', 'attempts', 'manual', 'source', 'check', 'writeback',
    'no_bearer', 'empty_bearer', 'query_key_auth', 'foreign_tenant', 'foreign_site', 'foreign_content',
    'missing_content', 'duplicate', 'unknown_status', 'unknown_url', 'leading_zero', 'no_reader',
    'unmounted', 'changed_endpoint', 'duplicate_route'])
def test_exception_is_exact_and_never_admits_other_scope_or_publication_action(factory, change):
    root, config = context(); app, reader, _, _ = prepared(factory)
    module = 'seo'; kwargs = {}
    if change == 'production': config['production'] = True
    if change == 'platform': config['platform'] = 'production'
    if change == 'root': root = Path('/other')
    if change == 'config_root': config['root'] = '/other'
    if change == 'ports': config['ports'] = {**config['ports'], 'pg': 5432}
    if change == 'native': config['native_heads']['seo'] = 'b4d8387123355348f79e26ea2838585c5106a4b9'
    if change == 'geo': module = 'geo'
    if change in {'post', 'head'}: kwargs['method'] = change.upper()
    if change == 'trailing_slash': kwargs['path'] = factory.STORED_PUBLICATIONS_READ_PATH + '/'
    if change == 'encoded_path': kwargs['raw'] = factory.STORED_PUBLICATIONS_READ_PATH.replace('publications', '%70ublications').encode()
    if change in {'attempts', 'manual'}: kwargs['path'] = factory.STORED_PUBLICATIONS_READ_PATH + ('/1/attempts' if change == 'attempts' else '/manual')
    if change in {'source', 'check', 'writeback'}: kwargs['path'] = '/api/distribution/v1/publication-' + change
    if change == 'no_bearer': kwargs['authorization'] = None
    if change == 'empty_bearer': kwargs['authorization'] = 'Bearer '
    if change == 'query_key_auth': kwargs.update(authorization=None, query=QUERY+'&key=synthetic')
    queries = {'foreign_tenant': 'tenant_id=16&site_id=6&content_id=61',
        'foreign_site': 'tenant_id=15&site_id=7&content_id=61', 'foreign_content': 'tenant_id=15&site_id=6&content_id=60',
        'missing_content': 'tenant_id=15&site_id=6', 'duplicate': QUERY+'&content_id=61',
        'unknown_status': QUERY+'&status=published', 'unknown_url': QUERY+'&url=https://synthetic.invalid',
        'leading_zero': 'tenant_id=015&site_id=6&content_id=61'}
    if change in queries: kwargs['query'] = queries[change]
    mounted = next(route for route in app.routes if getattr(route, 'path', '') == factory.STORED_PUBLICATIONS_READ_PATH)
    if change == 'no_reader': reader = None
    if change == 'unmounted': app.router.routes.remove(mounted)
    if change == 'changed_endpoint': mounted.endpoint = lambda: None
    if change == 'duplicate_route': app.router.routes.append(mounted)
    assert not factory.readonly_stored_publications(request(factory, **kwargs), root, config, module, app, reader)


def test_stored_list_after_fence_expiry_still_requires_native_auth_and_owned_session(factory, monkeypatch):
    async def run():
        monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
        import distribution_single_publication_gate as gate
        root, config = context(); app, reader, native, calls = prepared(factory)
        denied = []
        @app.middleware('http')
        async def expired_fence(req, next_call):
            if gate.publication_request(req) and not factory.readonly_stored_publications(req, root, config, 'seo', app, reader):
                denied.append(req.url.path)
                return JSONResponse(status_code=403, content={'detail': 'expired permit sentinel'})
            return await next_call(req)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://127.0.0.1') as client:
            path = factory.STORED_PUBLICATIONS_READ_PATH+'?'+QUERY
            own = {'authorization': 'Bearer routing-only'}
            assert (await client.get(path, headers=own)).json() == {'items': [], 'total': 0, 'status_counts': {}}
            assert (await client.get(path, headers={'authorization': 'Bearer foreign-tenant'})).status_code == 403
            assert (await client.get(path, headers={'authorization': 'Bearer expired-JWT'})).status_code == 401
            assert (await client.get(path)).status_code == 403
            for other in ('/api/distribution/v1/publication-source', '/api/distribution/v1/publication-check',
                          '/api/distribution/v1/publication-writeback', '/api/distribution/v1/publication-monitor',
                          factory.STORED_PUBLICATIONS_READ_PATH+'/1/attempts'):
                assert (await client.get(other, headers=own)).status_code == 403
            assert (await client.post(path, headers=own)).status_code == 403
        assert calls.count('native_read') == 1
        assert calls.count('owned_session') == 3
        assert len(denied) == 7
    asyncio.run(run())


def test_frozen_native_list_is_scoped_stored_data_and_gate_file_is_not_modified():
    assert NATIVE.is_dir(), 'Frozen native artifact required for inspection'
    source = (NATIVE/'app/api/seo.py').read_text(encoding='utf-8')
    definitions = {node.name: node for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    selected = ('list_content_publications', '_tenant', '_seo_site', '_publication_payload', '_manual_complete_denial',
                '_content_confirmation_schema_ready', '_latest_content_confirmation', '_content_confirmation_status')
    forbidden = {'commit', 'flush', 'add', 'delete', 'publish_content', 'fetch_url', 'reserve_publication_page_capture',
                 '_queue_published_page_verification', 'execute_page_capture', 'sync_publish_status', 'create_task'}
    for name in selected:
        calls = {call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id
                 for call in ast.walk(definitions[name]) if isinstance(call, ast.Call) and isinstance(call.func, (ast.Attribute, ast.Name))}
        assert not calls & forbidden
    body = ast.get_source_segment(source, definitions['list_content_publications'])
    assert 'ctx.ensure_tenant(tenant_id)' in body and 'await _seo_site(session, tenant_id, site_id)' in body
    assert 'Depends(get_session)' in body and 'Depends(require_scoped_auth)' in body
    assert 'dependencies=[Depends(require_seo_module_access)]' in source
    factory_source = (ROOT/'scripts/distribution_server_pilot_native.py').read_text(encoding='utf-8')
    assert 'stored_publications_reader = mount_stored_publications_read(app, native, module)' in factory_source
    assert 'and not readonly_stored_publications(request, root, config, module, app, stored_publications_reader)' in factory_source
    assert 'await single.authorize(request, root, config, sessions, module, payload)' in factory_source
