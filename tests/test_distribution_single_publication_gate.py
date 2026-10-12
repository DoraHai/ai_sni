"""Acceptance fence tests only; no native review bypass, DB, or platform publish.

The ASGI endpoint below is a counting sentinel, not a simulated publication.
Linux stat tests inject OS metadata on Windows and are explicitly not a live
Linux permission/deployment or native JWT/PostgreSQL integration claim.
"""
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import pytest

SOURCE = Path(__file__).parents[1] / 'scripts/distribution_single_publication_gate.py'
spec = importlib.util.spec_from_file_location('single_publication_test_gate', SOURCE)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)
AT = 1791800000000


def value(**changes):
    return {'schema': 1, 'purpose': 'isolated-single-seo-publication', **gate.SCOPE,
            'actor_id': 100007, 'device_id': gate.DEVICE, 'binding_id': gate.BINDING,
            'account_id': gate.ACCOUNT, 'external_account_id': gate.EXTERNAL_ACCOUNT,
            'platform': 'wechat-article', 'content_id': 61, 'variant_id': 2,
            'source_revision': 'seo_test_v2', 'expected_digest': 'a' * 64,
            'request_id': 'a097434a-deba-474a-b18a-fb8ae3fbe62c',
            'issued_at': AT - 1000, 'expires_at': AT + 1200000, 'expires_in_seconds': 300,
            'task_id': '331f3c6f-89da-4556-99fd-2300d98f4f86', **changes}


def permit(**changes):
    return gate.parse_permit(json.dumps(value(**changes)).encode(), AT)


def request(path, method='GET', query='', raw=None):
    return Request({'type': 'http', 'method': method, 'scheme': 'https', 'server': ('127.0.0.1', 55861),
                    'path': path, 'raw_path': raw or path.encode(), 'query_string': query.encode(), 'headers': []})


@pytest.mark.parametrize('changes', [
    {'schema': True}, {'schema': 1.0}, {'tenant_id': 16}, {'tenant_id': 15.0}, {'scope_id': 7},
    {'module': 'geo'}, {'actor_id': 100008}, {'device_id': str(uuid4())}, {'binding_id': str(uuid4())},
    {'account_id': 'other'}, {'external_account_id': 'gh_other'}, {'platform': 'xiaohongshu-image'},
    {'content_id': True}, {'variant_id': 0}, {'source_revision': 'bad/version'}, {'expected_digest': 'A' * 64},
    {'request_id': 'bad'}, {'issued_at': AT + 1}, {'expires_at': AT},
    {'issued_at': AT - gate.MAX_WINDOW_MS, 'expires_at': AT + 1}, {'expires_in_seconds': 299},
    {'expires_in_seconds': 901}, {'credential': 'synthetic-never-read'}, {'public_url': 'https://synthetic.invalid'},
])
def test_private_contract_is_exact_and_short_lived(changes):
    with pytest.raises(HTTPException) as exc:
        permit(**changes)
    assert exc.value.status_code == 403 and 'synthetic' not in str(exc.value.detail)


@pytest.mark.parametrize('data', [b'', b'{' + b' ' * gate.MAX_BYTES, b'[]', b'{"schema":1,"schema":1}', b'\xff', b'{'])
def test_bad_file_encoding_size_duplicates_fail_closed(data):
    with pytest.raises(HTTPException):
        gate.parse_permit(data, AT)


def test_runtime_cannot_enable_on_windows_temp_or_production():
    with pytest.raises(HTTPException):
        gate.read_permit(Path('C:/synthetic-temp'), {'production': True}, 'seo')
    with pytest.raises(HTTPException):
        gate.read_permit(gate.WORK, {'production': False}, 'geo')


def test_valid_prepared_exact_intent_and_bound_read_routes(monkeypatch):
    monkeypatch.setattr(gate, 'now_ms', lambda: AT)
    prepared = permit(task_id=None)
    assert gate.route_parameters(request(gate.PREFIX + '/tasks', 'POST'), prepared, prepared.task_request()) == 'create'
    for name in ('source', 'monitor'):
        path = gate.PREFIX + '/publication-' + name
        query = 'module=seo&tenant_id=15&scope_id=6&task_id=' + str(permit().task_id)
        assert gate.route_parameters(request(path, query=query), permit(), None) == 'read'
    query = 'module=seo&tenant_id=15&scope_id=6'
    assert gate.route_parameters(request(gate.PREFIX + '/publication-assets/' + str(permit().task_id) + '/cover_1', query=query), permit(), None) == 'read'
    for name in ('check', 'writeback'):
        assert gate.route_parameters(request(gate.PREFIX + '/publication-' + name, 'POST'), permit(),
                                     {**gate.SCOPE, 'task_id': str(permit().task_id)}) == 'write'
    assert gate.route_parameters(request(gate.NATIVE_PUBLICATIONS, query='tenant_id=15&site_id=6&content_id=61'), permit(), None) == 'delivery'


@pytest.mark.parametrize('changes', [
    {'action': 'preflight'}, {'tenant_id': 16}, {'module': 'geo'}, {'scope_id': 7}, {'variant_id': 3},
    {'binding_id': str(uuid4())}, {'source_revision': 'old_v1'}, {'expected_digest': 'b' * 64},
    {'request_id': str(uuid4())}, {'confirm_reviewed_content': False}, {'confirm_reviewed_content': 1},
    {'confirm_manual_publication': False}, {'confirm_manual_publication': 1}, {'expires_in_seconds': 900},
    {'body': 'synthetic-client-content'}, {'tenant_id': 15.0}, {'actor_id': 100007},
])
def test_task_request_cannot_expand_single_intent(monkeypatch, changes):
    monkeypatch.setattr(gate, 'now_ms', lambda: AT)
    item = permit()
    with pytest.raises(HTTPException):
        gate.route_parameters(request(gate.PREFIX + '/tasks', 'POST'), item, {**item.task_request(), **changes})


@pytest.mark.parametrize('path,method,query,raw', [
    (gate.PREFIX + '/tasks/', 'POST', '', None), (gate.PREFIX + '/tasks', 'POST', 'extra=1', None),
    (gate.PREFIX + '/tasks', 'POST', '', (gate.PREFIX + '/%74asks').encode()),
    (gate.NATIVE_PUBLICATIONS, 'POST', '', None), (gate.NATIVE_PUBLICATIONS + '/manual', 'POST', '', None),
    (gate.NATIVE_PUBLICATIONS + '/1/complete', 'POST', '', None), ('/api/v1/seo/push', 'POST', '', None),
    (gate.PREFIX + '/publication-source/', 'GET', '', None),
    (gate.PREFIX + '/publication-monitor', 'GET', 'module=seo&tenant_id=15&scope_id=6&task_id=' + str(uuid4()), None),
    (gate.PREFIX + '/publication-monitor', 'GET', 'module=seo&tenant_id=15&tenant_id=15&scope_id=6&task_id=' + value()['task_id'], None),
    (gate.NATIVE_PUBLICATIONS, 'GET', 'tenant_id=15&site_id=6', None),
    (gate.NATIVE_PUBLICATIONS, 'GET', 'tenant_id=15&site_id=6&content_id=62', None),
    (gate.PREFIX + '/publication-assets/' + str(uuid4()) + '/cover_1', 'GET', 'module=seo&tenant_id=15&scope_id=6', None),
])
def test_path_query_method_bypass_denied(monkeypatch, path, method, query, raw):
    monkeypatch.setattr(gate, 'now_ms', lambda: AT)
    with pytest.raises(HTTPException):
        gate.route_parameters(request(path, method, query, raw), permit(), permit().task_request())


def test_unbound_old_task_and_insufficient_remaining_window(monkeypatch):
    monkeypatch.setattr(gate, 'now_ms', lambda: AT)
    with pytest.raises(HTTPException):
        gate.route_parameters(request(gate.PREFIX + '/publication-check', 'POST'), permit(task_id=None),
                              {**gate.SCOPE, 'task_id': value()['task_id']})
    item = permit(expires_at=AT + 299999)
    with pytest.raises(HTTPException):
        gate.route_parameters(request(gate.PREFIX + '/tasks', 'POST'), item, item.task_request())


def test_actual_asgi_bounded_json_and_exact_dispatch(monkeypatch):
    async def run():
        monkeypatch.setattr(gate, 'now_ms', lambda: AT)
        item = permit()
        calls = []
        app = FastAPI()
        @app.middleware('http')
        async def fence(req, call_next):
            try:
                payload = await gate.request_payload(req)
                gate.route_parameters(req, item, payload)
            except HTTPException:
                return JSONResponse({'detail': 'denied'}, status_code=403)
            return await call_next(req)
        @app.post(gate.PREFIX + '/tasks')
        async def sentinel(req: Request):
            calls.append(await req.json())
            return {'sentinel_only': True}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://127.0.0.1') as client:
            good = await client.post(gate.PREFIX + '/tasks', json=item.task_request())
            assert good.status_code == 200 and calls == [item.task_request()]
            for body in (b'[]', b'{', b'{"action":"publish","action":"publish"}', b'{}', b' ' * 8193,
                         b'{"action":"publish","expected_digest":NaN}'):
                assert (await client.post(gate.PREFIX + '/tasks', content=body)).status_code == 403
            assert (await client.post(gate.PREFIX + '/tasks', json={**item.task_request(), 'confirm_manual_publication': 1})).status_code == 403
            assert len(calls) == 1
    asyncio.run(run())


def test_factory_only_adds_readonly_native_query_and_preserves_native_guards():
    import ast
    factory = (SOURCE.parent / 'distribution_server_pilot_native.py').read_text(encoding='utf-8')
    ast.parse(factory)
    assert "names.add('list_content_publications')" in factory
    assert 'await single.authorize(request, root, config, sessions, module, payload)' in factory
    assert "app.include_router(router)" in factory and "app.dependency_overrides[get_session] = database" in factory
    business = (SOURCE.parents[1] / 'app/distribution_control.py').read_text(encoding='utf-8')
    assert "await source(db,actor_id,scope,request.variant_id,binding['platform'])" in business
    assert "project['state']!='running' or project['owner_user_id']!=actor_id" in business
    assert "'publication':str(uuid4()) if request.action=='publish' else None" in business
    assert "request.action=='publish' and not request.confirm_manual_publication" in business


def binding():
    return {**gate.SCOPE, 'device_id': gate.DEVICE, 'account_id': gate.ACCOUNT,
            'external_account_id': gate.EXTERNAL_ACCOUNT, 'platform': 'wechat-article',
            'active': True, 'device_active': True}


def task():
    item = permit()
    result = {k: v for k, v in binding().items() if k not in {'active', 'device_active', 'external_account_id'}}
    return {**result, 'id': str(item.task_id), 'variant_id': item.variant_id,
            'source_revision': item.source_revision, 'content_digest': item.expected_digest,
            'advisor_user_id': item.actor_id, 'action': 'publish', 'binding_id': item.binding_id,
            'request_id': item.request_id, 'grant_id': str(uuid4()), 'publication_grant_id': str(uuid4()),
            'lease_id': str(uuid4()), 'request_fingerprint': hashlib.sha256(json.dumps(item.task_request(),
                ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


@pytest.mark.parametrize('changes', [
    {'tenant_id': 16}, {'scope_id': 7}, {'device_id': str(uuid4())}, {'account_id': 'other'},
    {'external_account_id': 'gh_other'}, {'active': False}, {'device_active': False},
])
def test_current_database_binding_must_be_exact(changes):
    with pytest.raises(HTTPException):
        gate.assert_binding(permit(), {**binding(), **changes}, 'create')


@pytest.mark.parametrize('changes', [
    {'id': str(uuid4())}, {'action': 'handoff'}, {'advisor_user_id': 100008}, {'tenant_id': 16},
    {'scope_id': 7}, {'variant_id': 3}, {'source_revision': 'old_v1'}, {'content_digest': 'b' * 64},
    {'request_id': str(uuid4())}, {'binding_id': str(uuid4())}, {'grant_id': None},
    {'publication_grant_id': None}, {'lease_id': None}, {'request_fingerprint': 'b' * 64},
])
def test_stored_task_never_upgrades_verification_or_handoff_grant(changes):
    with pytest.raises(HTTPException):
        gate.assert_task(permit(), {**task(), **changes}, binding())


def test_bound_actual_table_shape_and_two_distinct_grants():
    row = task()
    assert 'external_account_id' not in row
    gate.assert_task(permit(), row, binding())
    with pytest.raises(HTTPException):
        gate.assert_task(permit(), {**row, 'publication_grant_id': row['grant_id']}, binding())
    gate.assert_source(permit(), {'content_asset_id': 61, 'tenant_id': 15, 'site_id': 6})
    for row in (None, {'content_asset_id': 62, 'tenant_id': 15, 'site_id': 6},
                {'content_asset_id': 61, 'tenant_id': 16, 'site_id': 6}):
        with pytest.raises(HTTPException):
            gate.assert_source(permit(), row)


def test_private_linux_stat_guards_are_exercised_with_simulated_os_metadata(monkeypatch):
    # Local host is Windows: only OS metadata is simulated, never described as
    # actual Linux file permission verification. No real WORK file is opened.
    import stat
    class PrivatePath:
        def __init__(self, kind='root'):
            self.kind = kind
        def __truediv__(self, name):
            return PrivatePath(name)
        def __str__(self):
            return '/synthetic-private-work'
        def resolve(self):
            return self
        def exists(self):
            return False
        @property
        def parents(self):
            return ()
        def lstat(self):
            return state['file'] if self.kind == gate.FILE else state['root']
        def stat(self):
            return self.lstat()
    root = PrivatePath()
    good = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=1000, st_nlink=1, st_dev=1, st_ino=2, st_size=1000)
    state = {'root': SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1000), 'file': good, 'fd': good}
    monkeypatch.setattr(gate, 'WORK', root)
    monkeypatch.setattr(gate.sys, 'platform', 'linux')
    monkeypatch.setattr(gate.Path, 'cwd', staticmethod(lambda: root))
    monkeypatch.setattr(gate.os, 'getuid', lambda: 1000, raising=False)
    monkeypatch.setattr(gate.os, 'O_NOFOLLOW', 0, raising=False)
    monkeypatch.setattr(gate.os, 'O_NONBLOCK', 0, raising=False)
    monkeypatch.setattr(gate.os, 'open', lambda *args: 42)
    monkeypatch.setattr(gate.os, 'fstat', lambda fd: state['fd'])
    monkeypatch.setattr(gate, 'now_ms', lambda: AT)
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def fileno(self): return 42
        def read(self, count): return json.dumps(value()).encode()
    monkeypatch.setattr(gate.os, 'fdopen', lambda *args: Stream())
    config = {'root': str(root), 'platform': 'linux-acceptance', 'production': False,
              'ports': {'pg': 55483, 'seo': 55861, 'geo': 55862}}
    assert gate.read_permit(root, config, 'seo').actor_id == 100007
    for changes in ({'st_mode': stat.S_IFLNK | 0o600}, {'st_mode': stat.S_IFIFO | 0o600},
                    {'st_mode': stat.S_IFREG | 0o644}, {'st_uid': 1001}, {'st_nlink': 2},
                    {'st_ino': 3}, {'st_size': 8193}):
        state['file'] = good
        state['fd'] = SimpleNamespace(**{**good.__dict__, **changes})
        with pytest.raises(HTTPException): gate.read_permit(root, config, 'seo')
    state['fd'] = good
    state['file'] = SimpleNamespace(**{**good.__dict__, 'st_mode': stat.S_IFLNK | 0o600})
    with pytest.raises(HTTPException): gate.read_permit(root, config, 'seo')
    state['file'] = good
    state['root'] = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=1000)
    with pytest.raises(HTTPException): gate.read_permit(root, config, 'seo')
