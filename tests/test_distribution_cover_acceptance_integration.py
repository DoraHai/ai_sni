"""Acceptance wiring only; no services, SQL, native approval or platform writes.

The frozen native router is loaded below with explicit dependency sentinels to
prove route/dependency binding. It does not prove live native JWT/PG permissions.
"""
import ast
import asyncio
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import types

from fastapi import FastAPI, HTTPException, Request
import httpx
import pytest

ROOT = Path(__file__).parents[1]
SEO_PIN = '3087e62f23e799fe82d279f79f698f0499bf3a27'
GEO_PIN = '46dacbd805afc00f37eba344306fde004039efed'
MEDIA_FILES = ('app/seo_distribution_sources.py', 'app/seo_distribution_media.py',
               'app/api/seo_distribution_media.py', 'scripts/seo_distribution_media_schema.sql')


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('cover_acceptance_factory_test',
                                                 ROOT / 'scripts/distribution_server_pilot_native.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def native_root():
    root = Path(os.environ.get('NATIVE_SEO_COVER_ROOT',
               str(ROOT.parent / 'seo-wechat-cover-acceptance-20261012')))
    if not root.is_dir():
        pytest.skip('Frozen native cover artifact required for read-only wiring inspection')
    pin = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    assert pin == SEO_PIN
    assert subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True).strip() == ''
    return root


def test_linux_native_pin_and_reviewed_factory_allowlist(factory):
    spec = importlib.util.spec_from_file_location('cover_linux_entry_test', ROOT / 'scripts/distribution_linux_acceptance.py')
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    assert entry.NATIVE == {'seo': SEO_PIN, 'geo': GEO_PIN}
    assert SEO_PIN in factory.REVIEWED_ACCEPTANCE_HEADS['seo']
    assert factory.REVIEWED_ACCEPTANCE_HEADS['geo'] == {GEO_PIN}
    # The existing initializer remains separate from source activation: no media
    # DDL is added to either entry's initialization or runtime construction.
    for function in (entry.initialize, entry.activate, factory.initialize, factory.application):
        import inspect
        assert 'seo_distribution_media_schema.sql' not in inspect.getsource(function)


def test_manifest_audits_exact_native_bytes_without_installing_schema(factory, native_root):
    manifest = {}
    factory.record_seo_media_manifest(native_root, 'seo', manifest)
    assert set(manifest['pilot_native_files']) == set(MEDIA_FILES)
    for name in MEDIA_FILES:
        assert manifest['pilot_native_files'][name] == hashlib.sha256((native_root / name).read_bytes()).hexdigest()
    assert manifest['seo_media_schema'] == {
        'source': MEDIA_FILES[-1], 'sha256': manifest['pilot_native_files'][MEDIA_FILES[-1]],
        'target_schema': 'acceptance_seo', 'automatic_install': False,
        'database_status': 'not_inspected_by_manifest',
    }


def test_non_seo_never_imports_media_or_changes_manifest(factory):
    app = FastAPI()
    before = list(app.routes)
    factory.mount_seo_media_routes(app, 'geo')
    assert app.routes == before
    manifest = {'untouched': True}
    factory.record_seo_media_manifest(Path('/not-a-real-native-root'), 'geo', manifest)
    assert manifest == {'untouched': True}


def test_manifest_missing_native_artifact_fails_closed(factory, tmp_path):
    with pytest.raises(FileNotFoundError):
        factory.record_seo_media_manifest(tmp_path, 'seo', {})


def load_native_router(monkeypatch, native_root):
    """Actual frozen API bytecode; explicit auth/storage sentinels for routing."""
    calls = []
    database = object()
    async def get_session():
        calls.append('db')
        yield database
    async def require_auth(request: Request):
        calls.append('auth')
        if request.headers.get('authorization') != 'Bearer synthetic-routing-only':
            raise HTTPException(401, 'synthetic route authentication required')
        return types.SimpleNamespace(user_id=100007)
    async def preview(db, actor, tenant, site, variant):
        assert db is database and actor == 100007
        calls.append(('preview', tenant, site, variant))
        return {'sentinel_only': True}
    async def authorize_scope(*args):
        raise AssertionError('No native write should execute in routing inspection')
    def denied(*args):
        return HTTPException(403, 'synthetic scope denial')
    modules = {
        'app.database': types.SimpleNamespace(get_session=get_session),
        'app.security.auth': types.SimpleNamespace(require_auth=require_auth),
        'app.seo_distribution_media': types.SimpleNamespace(MAX_TOTAL=2000, MAX_IMAGE=1000, MAX_IMAGES=9, preview=preview),
        'app.seo_distribution_sources': types.SimpleNamespace(authorize_scope=authorize_scope, denied=denied),
    }
    import app
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
        if name.count('.') == 1:
            monkeypatch.setattr(app, name.split('.')[-1], module, raising=False)
    spec = importlib.util.spec_from_file_location('app.api.seo_distribution_media', native_root / MEDIA_FILES[2])
    native = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, native)
    spec.loader.exec_module(native)
    return native, calls


def test_exact_native_media_routes_keep_private_route_and_dependencies(factory, native_root, monkeypatch):
    async def run():
        native, calls = load_native_router(monkeypatch, native_root)
        app = FastAPI()
        factory.mount_seo_media_routes(app, 'seo')
        mounted = [route for route in app.routes if getattr(route, 'path', '').startswith('/api/seo/distribution-media')]
        assert {route.endpoint.__name__ for route in mounted} == {'drafts', 'preview', 'upload', 'preview_asset', 'review'}
        originals = {route.endpoint.__name__: route for route in native.router.routes}
        for route in mounted:
            assert type(route) is native.PrivateMediaRoute
            assert route.endpoint is originals[route.endpoint.__name__].endpoint
            assert {dep.call for dep in route.dependant.dependencies} == {dep.call for dep in originals[route.endpoint.__name__].dependant.dependencies}
        assert not any(route.endpoint.__name__ in {'workspace', 'ui_file'} for route in mounted)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://127.0.0.1') as client:
            path = '/api/seo/distribution-media/variants/2?tenant_id=15&site_id=6'
            assert (await client.get(path)).status_code == 401
            reply = await client.get(path, headers={'authorization': 'Bearer synthetic-routing-only'})
            assert reply.status_code == 200 and reply.json() == {'sentinel_only': True}
            assert reply.headers['cache-control'] == 'no-store'
            assert reply.headers['x-content-type-options'] == 'nosniff'
            assert (await client.get('/api/seo/distribution-media/workspace')).status_code == 404
            assert (await client.get('/api/seo/distribution-media/ui/app.js')).status_code == 404
        assert calls.count(('preview', 15, 6, 2)) == 1
    asyncio.run(run())


@pytest.mark.parametrize('damage', ['missing', 'method_changed'])
def test_changed_native_media_router_is_not_partially_mounted(factory, native_root, monkeypatch, damage):
    native, _ = load_native_router(monkeypatch, native_root)
    target = next(route for route in native.router.routes if route.endpoint.__name__ == 'review')
    if damage == 'missing': native.router.routes.remove(target)
    else: target.methods = {'GET'}
    app = FastAPI()
    before = list(app.routes)
    with pytest.raises(RuntimeError): factory.mount_seo_media_routes(app, 'seo')
    assert app.routes == before


def test_frozen_native_advisor_assignment_and_customer_write_guard_remain(native_root):
    # Read native handlers rather than inventing scope/role grants in a fixture.
    source = (native_root / 'app/api/seo.py').read_text(encoding='utf-8')
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == 'upsert_advisor_assignment')
    assignment = ast.get_source_segment(source, node)
    for clause in ('ctx.ensure_tenant(req.tenant_id)', 'ctx.user_id is None',
                   'ctx.can_edit("seo.content")', 'ctx.can_edit("settings.accounts")',
                   'advisor.tenant_id != req.tenant_id', 'advisor_permissions.get("seo.content") != "edit"',
                   '.with_for_update()', 'await session.commit()'):
        assert clause in assignment
    factory_source = (ROOT / 'scripts/distribution_server_pilot_native.py').read_text(encoding='utf-8')
    assert "'upsert_advisor_assignment','list_advisor_assignments'" in factory_source
    assert "ctx.can_edit(module+'.content',module+'.assets',module+'.site','settings.accounts')" in factory_source
    assert "app.dependency_overrides[get_session] = database" in factory_source

