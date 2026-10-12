"""Read-route wiring only; no live JWT/PG/TLS, service or business writes."""
import ast
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import types

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
import httpx
import pytest

ROOT = Path(__file__).parents[1]
NATIVE = Path(os.environ.get('NATIVE_SEO_COVER_ROOT', str(ROOT.parent / 'seo-wechat-cover-acceptance-20261012')))


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('native_read_factory_test',
                                                 ROOT / 'scripts/distribution_server_pilot_native.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_exact_read_preserves_route_dependency_and_does_not_mount_write(factory):
    async def run():
        native = APIRouter(prefix='/api/v1/auth')
        calls = []
        async def auth(request: Request):
            if request.headers.get('authorization') != 'Bearer routing-only':
                raise HTTPException(401, 'routing sentinel')
            calls.append('auth')
            return object()
        @native.get('/tenants')
        async def list_tenants(module: str, ctx=Depends(auth)):
            calls.append('read')
            return {'module': module, 'sentinel_only': True}
        @native.post('/tenants')
        async def create_tenant():
            raise AssertionError('Write was mounted')
        route = next(route for route in native.routes if route.methods == {'GET'})
        app = FastAPI()
        factory.mount_exact_native_read(app, native, 'list_tenants', '/api/v1/auth/tenants')
        factory.mount_exact_native_read(app, native, 'list_tenants', '/api/v1/auth/tenants')
        matches = [route for route in app.routes if getattr(route, 'path', '') == '/api/v1/auth/tenants']
        assert len(matches) == 1 and matches[0].endpoint is route.endpoint and type(matches[0]) is type(route)
        assert matches[0].dependant.dependencies[0].call is auth
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://127.0.0.1') as client:
            assert (await client.get('/api/v1/auth/tenants?module=seo')).status_code == 401
            reply = await client.get('/api/v1/auth/tenants?module=seo', headers={'authorization': 'Bearer routing-only'})
            assert reply.json() == {'module': 'seo', 'sentinel_only': True}
            assert (await client.post('/api/v1/auth/tenants')).status_code == 405
        assert calls == ['auth', 'read']
    asyncio.run(run())


@pytest.mark.parametrize('damage', ['missing', 'method', 'path', 'duplicate', 'conflict'])
def test_absent_changed_or_conflicting_read_fails_before_mount(factory, damage):
    native = APIRouter()
    async def list_tenants(): return {}
    if damage != 'missing':
        native.add_api_route('/api/v1/auth/other' if damage == 'path' else '/api/v1/auth/tenants',
                             list_tenants, methods=['POST' if damage == 'method' else 'GET'])
    if damage == 'duplicate':
        native.add_api_route('/api/v1/auth/tenants', list_tenants, methods=['GET'])
    app = FastAPI()
    if damage == 'conflict':
        @app.get('/api/v1/auth/tenants')
        async def different(): return {}
    before = list(app.routes)
    with pytest.raises(RuntimeError):
        factory.mount_exact_native_read(app, native, 'list_tenants', '/api/v1/auth/tenants')
    assert app.routes == before


def test_seo_only_existing_auth_and_sites_contracts_without_generated_scope():
    # Static provenance: the existing central handler supplies the real module
    # contract; the frozen native sites handler retains permission/SQL filtering.
    source = (ROOT / 'scripts/distribution_server_pilot_native.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'application')
    mounts = [node for node in ast.walk(function) if isinstance(node, ast.If)
              and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name)
              and node.test.left.id == 'module' and isinstance(node.test.comparators[0], ast.Constant)
              and node.test.comparators[0].value == 'seo'
              and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                      and call.func.id == 'mount_exact_native_read' for branch in node.body for call in ast.walk(branch))]
    assert len(mounts) == 2
    assert "modules_auth.router, 'list_tenants', '/api/v1/auth/tenants'" in ast.get_source_segment(source, mounts[0])
    assert "'list_seo_workbench_sites'" in ast.get_source_segment(source, mounts[1])
    for node in mounts:
        assert not any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                       and call.func.id == 'mount_exact_native_read' for branch in node.orelse for call in ast.walk(branch))
    auth_source = (ROOT / 'app/api/auth.py').read_text(encoding='utf-8')
    auth = next(node for node in ast.parse(auth_source).body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'list_tenants')
    body = ast.get_source_segment(auth_source, auth)
    assert 'ctx.can_view(*_MODULE_PERMISSION_KEYS[module])' in body
    assert 'await list_module_tenants(session, ctx, module)' in body and '"module": module' in body
    if not NATIVE.is_dir(): pytest.skip('Read-only frozen SEO artifact required')
    customer_source = (NATIVE / 'app/api/customer_modules.py').read_text(encoding='utf-8')
    sites = next(node for node in ast.parse(customer_source).body
                 if isinstance(node, ast.AsyncFunctionDef) and node.name == 'list_seo_workbench_sites')
    body = ast.get_source_segment(customer_source, sites)
    for clause in ('Depends(require_seo_scoped_auth)', 'Depends(get_seo_session)',
                   '_require_seo_workbench_site_permission(ctx)', 'await ensure_module_access(session, ctx, tenant_id, "seo")',
                   'SeoSite.tenant_id == tenant_id'):
        assert clause in body


def test_frozen_seo_primary_alias_uses_owned_override_and_cached_session(factory, monkeypatch):
    """Execute frozen session-router helper with explicit in-memory dependencies.

    This proves dependency identity/primary session selection only, not JWT/PG.
    No database module top level or SQL engine is initialized in this test.
    """
    async def run():
        if not NATIVE.is_dir(): pytest.skip('Read-only frozen SEO artifact required')
        owned_database = object()
        calls = []
        async def original_session():
            raise AssertionError('Unpatched database getter called')
            yield
        async def owned_session():
            calls.append('owned_session')
            yield owned_database
        async def require_auth():
            return types.SimpleNamespace(user_id=100007, tenant_id=15)
        async def enforce_scoped_request(request, ctx):
            return ctx
        dependencies = {
            'app.config': types.SimpleNamespace(get_settings=lambda: types.SimpleNamespace(seo_demo_data_source_enabled=False)),
            'app.database': types.SimpleNamespace(get_session=original_session),
            'app.models.demo_tenant_binding': types.SimpleNamespace(DemoTenantBinding=type('DemoTenantBinding', (), {})),
            'app.security.auth': types.SimpleNamespace(AuthContext=object, require_auth=require_auth,
                                                      enforce_scoped_request=enforce_scoped_request),
        }
        for name, module in dependencies.items(): monkeypatch.setitem(sys.modules, name, module)
        spec = importlib.util.spec_from_file_location('app.native_read_seo_demo_test', NATIVE / 'app/seo_demo_source.py')
        native = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, native)
        spec.loader.exec_module(native)
        def no_engine(*args, **kwargs): raise AssertionError('Alternate engine forbidden')
        native.create_async_engine = no_engine
        native._demo_session_factory = no_engine
        assert native.get_primary_session is original_session
        native_router = APIRouter()
        @native_router.get('/api/v1/seo/workbench/sites')
        async def list_seo_workbench_sites(request: Request, session=Depends(native.get_seo_session),
                                          ctx=Depends(native.require_seo_scoped_auth)):
            assert session is owned_database and ctx.tenant_id == 15
            assert request.state.seo_data_source_decision.source == 'primary'
            return {'in_memory_session_binding_only': True}
        app = FastAPI()
        app.dependency_overrides[original_session] = owned_session
        factory.mount_exact_native_read(app, native_router, 'list_seo_workbench_sites', '/api/v1/seo/workbench/sites')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://127.0.0.1') as client:
            reply = await client.get('/api/v1/seo/workbench/sites?tenant_id=15')
            assert reply.status_code == 200 and reply.json() == {'in_memory_session_binding_only': True}
        assert calls == ['owned_session']
    asyncio.run(run())

