"""Pilot GET/fence wiring; synthetic route/auth sentinels, no live JWT/PG/TLS."""
import ast
import asyncio
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
import pytest

ROOT = Path(__file__).parents[1]
NATIVE = Path(os.environ.get('NATIVE_SEO_COVER_ROOT', str(ROOT.parent / 'seo-wechat-cover-acceptance-20261012')))


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('customer_readonly_factory_test', ROOT / 'scripts/distribution_server_pilot_native.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def native_router(factory):
    router = APIRouter()
    calls = []
    async def scoped(request: Request):
        header = request.headers.get('authorization')
        if header == 'Bearer foreign-tenant':
            raise HTTPException(403, 'sentinel scope denial')
        if header != 'Bearer routing-only':
            raise HTTPException(401, 'sentinel authentication denial')
    def endpoint(name):
        async def read(ctx=Depends(scoped)):
            calls.append(name)
            return {'stored_read_sentinel': name}
        read.__name__ = name
        return read
    for name, path in factory.CUSTOMER_READS:
        router.add_api_route(path, endpoint(name), methods=['GET'])
        router.add_api_route(path, endpoint('forbidden_write_' + name), methods=['POST'])
    return router, calls


def context():
    root = Path('/opt/gsnipers-distribution-acceptance/work/distribution-server-pilot-20261012')
    return root, {'root': str(root), 'production': False, 'platform': 'linux-acceptance',
        'ports': {'pg': 55483, 'seo': 55861, 'geo': 55862},
        'native_heads': {'seo': '3087e62f23e799fe82d279f79f698f0499bf3a27'}}


def request(factory, *, path=None, method='GET', query='tenant_id=15&site_id=6', raw=None, bearer=True):
    path = path or factory.EVIDENCE_READ_PATH
    headers = [(b'authorization', b'Bearer routing-only')] if bearer else []
    return Request({'type': 'http', 'method': method, 'scheme': 'https', 'server': ('127.0.0.1', 55861),
        'path': path, 'raw_path': raw if raw is not None else path.encode(), 'query_string': query.encode(), 'headers': headers})


def prepared(factory):
    native, calls = native_router(factory)
    app = FastAPI()
    reader = factory.mount_seo_customer_reads(app, native, 'seo')
    return app, reader, calls


def test_five_gets_keep_original_dependencies_and_exclude_all_writes(factory):
    async def run():
        native, calls = native_router(factory)
        app = FastAPI()
        reader = factory.mount_seo_customer_reads(app, native, 'seo')
        originals = {route.path: route for route in native.routes if route.methods == {'GET'}}
        mounted = [route for route in app.routes if getattr(route, 'path', '') in originals]
        assert len(mounted) == 5 and all(route.methods == {'GET'} for route in mounted)
        for route in mounted:
            assert route.endpoint is originals[route.path].endpoint
            assert type(route) is type(originals[route.path])
            assert route.dependant.dependencies[0].call is originals[route.path].dependant.dependencies[0].call
        assert reader is originals[factory.EVIDENCE_READ_PATH].endpoint
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://127.0.0.1') as client:
            for name, path in factory.CUSTOMER_READS:
                assert (await client.get(path)).status_code == 401
                assert (await client.get(path, headers={'authorization': 'Bearer foreign-tenant'})).status_code == 403
                reply = await client.get(path, headers={'authorization': 'Bearer routing-only'})
                assert reply.json() == {'stored_read_sentinel': name}
                assert (await client.post(path)).status_code == 405
        assert calls == [name for name, path in factory.CUSTOMER_READS]
    asyncio.run(run())


def test_missing_route_fails_before_partial_mount_and_geo_has_no_new_routes(factory):
    native, _ = native_router(factory)
    native.routes.remove(next(route for route in native.routes if route.path == factory.EVIDENCE_READ_PATH and route.methods == {'GET'}))
    app = FastAPI(); before = list(app.routes)
    with pytest.raises(RuntimeError): factory.mount_seo_customer_reads(app, native, 'seo')
    assert app.routes == before
    assert factory.mount_seo_customer_reads(app, native, 'geo') is None
    assert app.routes == before


@pytest.mark.parametrize('query', ['tenant_id=15&site_id=6',
    'tenant_id=15&site_id=6&page=1&page_size=20',
    'tenant_id=15&site_id=6&page=10000&page_size=100&content_id=61&publication_id=2'])
def test_exact_owned_stored_evidence_list_is_readable_without_permit(factory, query):
    root, config = context(); app, reader, _ = prepared(factory)
    assert factory.readonly_publication_evidence(request(factory, query=query), root, config, 'seo', app, reader)


@pytest.mark.parametrize('change', ['production', 'platform', 'root', 'config_root', 'ports', 'native', 'geo',
    'post', 'head', 'trailing_slash', 'encoded_path', 'other_source', 'other_check', 'other_monitor', 'other_native_publications',
    'no_bearer', 'foreign_tenant', 'foreign_site', 'missing_scope', 'duplicate', 'unknown_action', 'unknown_url',
    'invalid_page', 'oversized_page', 'oversized_page_size', 'float_page', 'leading_zero', 'invalid_content', 'no_reader',
    'unmounted', 'changed_endpoint', 'duplicate_route'])
def test_readonly_exception_does_not_expand_publication_or_scope_gate(factory, change):
    root, config = context(); app, reader, _ = prepared(factory)
    params = {}; module = 'seo'
    if change == 'production': config['production'] = True
    if change == 'platform': config['platform'] = 'production'
    if change == 'root': root = Path('/other')
    if change == 'config_root': config['root'] = '/other'
    if change == 'ports': config['ports'] = {**config['ports'], 'pg': 5432}
    if change == 'native': config['native_heads'] = {'seo': 'b4d8387123355348f79e26ea2838585c5106a4b9'}
    if change == 'geo': module = 'geo'
    if change in ('post', 'head'): params['method'] = change.upper()
    if change == 'trailing_slash': params['path'] = factory.EVIDENCE_READ_PATH + '/'
    if change == 'encoded_path': params['raw'] = factory.EVIDENCE_READ_PATH.replace('publication', '%70ublication').encode()
    if change in ('other_source', 'other_check', 'other_monitor'):
        params['path'] = '/api/distribution/v1/publication-' + change[6:]
    if change == 'other_native_publications': params['path'] = '/api/v1/seo/content-distribution/publications'
    if change == 'no_bearer': params['bearer'] = False
    queries = {'foreign_tenant': 'tenant_id=16&site_id=6', 'foreign_site': 'tenant_id=15&site_id=7',
        'missing_scope': 'tenant_id=15', 'duplicate': 'tenant_id=15&site_id=6&tenant_id=15',
        'unknown_action': 'tenant_id=15&site_id=6&action=publish', 'unknown_url': 'tenant_id=15&site_id=6&url=https://synthetic.invalid',
        'invalid_page': 'tenant_id=15&site_id=6&page=0', 'oversized_page': 'tenant_id=15&site_id=6&page=10001',
        'oversized_page_size': 'tenant_id=15&site_id=6&page_size=101', 'float_page': 'tenant_id=15&site_id=6&page=1.0',
        'leading_zero': 'tenant_id=15&site_id=6&page=01', 'invalid_content': 'tenant_id=15&site_id=6&content_id=-1'}
    if change in queries: params['query'] = queries[change]
    target = next(route for route in app.routes if getattr(route, 'path', '') == factory.EVIDENCE_READ_PATH)
    if change == 'no_reader': reader = None
    if change == 'unmounted': app.router.routes.remove(target)
    if change == 'changed_endpoint': target.endpoint = lambda: None
    if change == 'duplicate_route': app.router.routes.append(target)
    assert not factory.readonly_publication_evidence(request(factory, **params), root, config, module, app, reader)


def test_middleware_exception_still_runs_native_auth_and_other_paths_remain_fenced(factory, monkeypatch):
    async def run():
        monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
        import distribution_single_publication_gate as gate
        root, config = context(); app, reader, calls = prepared(factory)
        rejected = []
        @app.middleware('http')
        async def fence(req, call_next):
            if gate.publication_request(req) and not factory.readonly_publication_evidence(req, root, config, 'seo', app, reader):
                rejected.append(req.url.path)
                return JSONResponse(status_code=403, content={'detail': 'original fence sentinel'})
            return await call_next(req)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://127.0.0.1') as client:
            path = factory.EVIDENCE_READ_PATH + '?tenant_id=15&site_id=6&page=1&page_size=20'
            assert (await client.get(path, headers={'authorization': 'Bearer routing-only'})).status_code == 200
            assert (await client.get(path, headers={'authorization': 'Bearer foreign-tenant'})).status_code == 403
            assert (await client.get(path)).status_code == 403
            for other in ('/api/distribution/v1/publication-source', '/api/distribution/v1/publication-monitor',
                          '/api/v1/seo/content-distribution/publications'):
                assert (await client.get(other, headers={'authorization': 'Bearer routing-only'})).status_code == 403
            assert (await client.post(factory.EVIDENCE_READ_PATH, headers={'authorization': 'Bearer routing-only'})).status_code == 403
        assert calls == ['list_workbench_publication_page_evidence']
        assert len(rejected) == 5
    asyncio.run(run())


def test_original_native_gets_are_stored_projections_and_factory_keeps_scope_deps():
    if not NATIVE.is_dir(): pytest.skip('Frozen native artifact required for read-only inspection')
    definitions = {}
    sources = {}
    for name in ('seo.py', 'seo_service_workflows.py', 'seo_onsite.py'):
        source = (NATIVE / 'app/api' / name).read_text(encoding='utf-8')
        sources[name] = source
        definitions[name] = {node.name: node for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    selected = {'seo.py': ['get_workbench_service_status', 'list_site_pages', 'list_workbench_publication_page_evidence'],
        'seo_service_workflows.py': ['list_executions', 'read_scope', 'can_operate'], 'seo_onsite.py': ['list_tasks', 'scope']}
    forbidden = {'commit', 'flush', 'add', 'delete', 'fetch_url', 'capture_page', 'create_task',
                 'advance_service_workflow', 'reserve_service_workflow', 'execute_diagnosis_page'}
    for filename, names in selected.items():
        for name in names:
            node = definitions[filename][name]
            calls = {call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id
                     for call in ast.walk(node) if isinstance(call, ast.Call) and isinstance(call.func, (ast.Attribute, ast.Name))}
            assert not calls & forbidden
    for name in ('get_workbench_service_status', 'list_workbench_publication_page_evidence'):
        body = ast.get_source_segment(sources['seo.py'], definitions['seo.py'][name])
        assert 'ctx.ensure_tenant(tenant_id)' in body
        assert 'ctx.can_view("seo.content")' in body and 'ctx.can_view("seo.site")' in body
        assert 'await ensure_module_access(session, ctx, tenant_id, "seo")' in body
    # Site-pages relies on the composite router's scoped module guard; retain it
    # by selecting the original APIRoute, not reconstructing a bare endpoint.
    assert 'dependencies=[Depends(require_seo_module_access)]' in sources['seo.py']
    factory_source = (ROOT / 'scripts/distribution_server_pilot_native.py').read_text(encoding='utf-8')
    assert 'evidence_reader = mount_seo_customer_reads(app, native, module)' in factory_source
    assert 'if single.publication_request(request, payload) and not readonly_publication_evidence(' in factory_source
    assert 'await single.authorize(request, root, config, sessions, module, payload)' in factory_source

