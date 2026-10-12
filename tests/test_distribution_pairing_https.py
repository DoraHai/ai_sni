"""Actual native JWT/PG and trusted HTTPS, with a synthetic PC bootstrap client."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import struct
import time
from uuid import uuid4
import zlib
import httpx
import pytest

ROOT = Path(os.environ.get('DEVICE_PAIRING_TEST_ROOT', ''))
if not os.environ.get('DEVICE_PAIRING_TEST_ROOT'):
    pytest.skip('Owned pairing HTTPS fixture required', allow_module_level=True)
if ROOT.resolve().parent != Path(os.environ['TEMP']).resolve() or ROOT.name != 'distribution-device-pairing-tests-20261012':
    raise RuntimeError('Exact owned pairing fixture required')
PREFIX = '/api/distribution/v1'
SCOPE = {'module': 'seo', 'tenant_id': 15, 'scope_id': 6}


class Fixture:
    def __init__(self):
        self.context = ssl.create_default_context(cafile=str(ROOT / 'loopback.pem'))
        self.client = httpx.Client(base_url='https://127.0.0.1:55881', verify=self.context, trust_env=False, timeout=20)
        password = json.loads((ROOT / 'secrets.json').read_text(encoding='utf-8'))['password']
        self.tokens, self.pairings, self.secrets = {}, [], []
        for actor in ('admin', 'rescue', 'advisor', 'reviewer', 'customer', 'foreign'):
            response = self.client.post('/api/v1/auth/login', json={'username': actor, 'password': password})
            assert response.status_code == 200, 'Actual native login failed'
            self.tokens[actor] = response.json()['token']
        for tenant, site in ((15, 6), (16, 7)):
            self.call('PUT', '/api/v1/seo/workbench/advisor-assignments', json={
                'tenant_id': tenant, 'site_id': site, 'advisor_user_id': 100007, 'active': True})

    def call(self, method, path, actor='admin', expected=200, **kwargs):
        response = self.client.request(method, path, headers={'Authorization': 'Bearer ' + self.tokens[actor]}, **kwargs)
        assert response.status_code == expected, (method, path, response.status_code)
        if path.startswith(PREFIX):
            assert response.headers['cache-control'] == 'no-store'
        return response.json()

    def issue(self, **changes):
        result = self.call('POST', PREFIX + '/device-pairings', json={
            'label': 'Synthetic company Windows PC', 'request_id': str(uuid4()), **changes})
        self.pairings.append(result)
        self.secrets.append(result['pairing_code'])
        return result

    def claim(self, pairing, expected=200, **changes):
        response = self.client.post(PREFIX + '/device-pairings/claim', json={
            'pairing_code': pairing['pairing_code'], 'request_id': str(uuid4()), **changes})
        assert response.status_code == expected, ('PC claim', response.status_code)
        assert response.headers['cache-control'] == 'no-store'
        value = response.json()
        if expected == 200:
            self.secrets.append(value['device']['credential'])
        return value

    def revoke(self, pairing, actor='rescue'):
        return self.call('POST', PREFIX + '/device-pairings/' + pairing['pairing']['id'] + '/revoke',
            actor=actor, json={'request_id': str(uuid4())})

    def bind(self, device, scope=SCOPE):
        request = {**scope, 'device_id': device['id'],
            'account_id': 'synthetic-' + uuid4().hex[:12], 'external_account_id': 'wx-' + uuid4().hex,
            'platform': 'wechat-article', 'confirm_account_ownership': True}
        binding = self.call('POST', PREFIX + '/bindings', json=request)['binding']
        return {**binding, 'external_account_id': request['external_account_id']}

    def discover(self, device, expected=200, **changes):
        response = self.client.post(PREFIX + '/device/bindings', headers={'Authorization': 'Bearer ' + device['credential']},
            json={'device_id': device['id'], **changes})
        assert response.status_code == expected, ('Device discovery', response.status_code)
        assert response.headers['cache-control'] == 'no-store'
        return response.json()

    def finish(self):
        for pairing in self.pairings:
            try:
                self.revoke(pairing)
            except AssertionError:
                pass
        self.client.close()

    def native_task(self, device, binding):
        keyword = self.call('POST', '/api/v1/seo/keywords', actor='advisor', json={
            'tenant_id': 15, 'site_id': 6, 'keyword': '配对本地验收 ' + uuid4().hex[:8]})
        master = self.call('POST', '/api/v1/seo/content-assets', actor='advisor', json={
            'tenant_id': 15, 'site_id': 6, 'title': keyword['keyword'] + ' 合成稿', 'keyword_ids': [keyword['id']],
            'content_type': 'article', 'draft': keyword['keyword'] + '\n\n' + ('这是隔离设备配对测试合成文章，仅核授权与当前版本。\n' * 30), 'status': 'drafting'})
        version = master.get('version_count') or 1
        self.call('POST', f'/api/v1/seo/content-assets/{master["id"]}/submit-review', actor='advisor',
            params={'tenant_id': 15}, json={'version_count': version, 'note': 'Synthetic pairing test'})
        self.call('POST', f'/api/v1/seo/content-assets/{master["id"]}/review', actor='reviewer',
            params={'tenant_id': 15}, json={'version_count': version, 'decision': 'approve', 'note': 'Separate local reviewer'})
        delivery = self.call('GET', f'/api/v1/seo/workbench/content-assets/{master["id"]}/delivery', actor='advisor',
            params={'tenant_id': 15, 'site_id': 6})
        self.call('POST', f'/api/v1/seo/workbench/content-assets/{master["id"]}/confirmations', actor='advisor',
            params={'tenant_id': 15}, json={'version_count': delivery['content']['version_count'],
                'payload_hash': delivery['content']['payload_hash'], 'decision': 'approve',
                'actor_mode': 'advisor_proxy', 'note': 'Explicit local version confirmation'})
        connection = self.call('POST', '/api/v1/seo/content-distribution/connections', actor='advisor', json={
            'tenant_id': 15, 'platform_code': 'wechat_browser', 'name': 'Pairing test ' + uuid4().hex[:8], 'enabled': True})
        adapted = self.call('POST', '/api/v1/seo/content-distribution/adapt', actor='advisor', json={
            'tenant_id': 15, 'site_id': 6, 'content_id': master['id'], 'connection_id': connection['id'], 'use_ai': False})
        variant = self.call('POST', '/api/v1/seo/content-distribution/variants', actor='advisor', json={
            'tenant_id': 15, 'site_id': 6, 'content_id': master['id'], 'connection_id': connection['id'],
            'source_version': adapted['source_version'], 'title': adapted['title'], 'content': adapted['content'],
            'status': 'pending_review', 'ai_generated': False})
        self.call('POST', f'/api/v1/seo/content-distribution/variants/{variant["id"]}/review', actor='reviewer',
            json={'tenant_id': 15, 'site_id': 6, 'decision': 'approve', 'note': 'Separate local channel review'})
        source = self.call('GET', PREFIX + '/source', actor='advisor', params={**SCOPE, 'variant_id': variant['id'], 'platform': 'wechat-article'})
        control = self.call('GET', PREFIX + '/scope', actor='advisor', params=SCOPE)['project']
        if control['state'] == 'paused':
            self.call('POST', PREFIX + '/control', actor='advisor', json={**SCOPE,
                'action': 'start' if control['revision'] == 0 else 'resume', 'expected_revision': control['revision'], 'request_id': str(uuid4())})
        task = self.call('POST', PREFIX + '/tasks', actor='advisor', json={**SCOPE,
            'binding_id': binding['id'], 'variant_id': variant['id'], 'source_revision': source['source_revision'],
            'expected_digest': source['content_digest'], 'action': 'preflight', 'confirm_reviewed_content': True,
            'confirm_manual_publication': False, 'expires_in_seconds': 600, 'request_id': str(uuid4())})['task']
        exchange = self.client.post(PREFIX + '/device/exchange', headers={'Authorization': 'Bearer ' + device['credential']},
            json={'contractVersion': 1, 'deviceId': device['id'], 'receipts': []})
        assert exchange.status_code == 200 and len(exchange.json()['tasks']) == 1
        return task


@pytest.fixture
def f():
    fixture = Fixture()
    try:
        yield fixture
    finally:
        fixture.finish()


def test_current_real_admin_only_and_legacy_web_credential_denied(f):
    for actor in ('advisor', 'reviewer', 'customer', 'foreign'):
        f.call('POST', PREFIX + '/device-pairings', actor=actor, expected=403,
            json={'label': 'Forbidden PC', 'request_id': str(uuid4())})
        f.call('GET', PREFIX + '/device-pairings', actor=actor, expected=403)
    f.call('POST', PREFIX + '/devices', expected=409, json={'label': 'Legacy web credential blocked'})
    pairing = f.issue()
    for actor in ('advisor', 'customer'):
        f.call('GET', PREFIX + '/device-pairings/' + pairing['pairing']['id'], actor=actor, expected=403)
        f.call('POST', PREFIX + '/device-pairings/' + pairing['pairing']['id'] + '/revoke', actor=actor,
            expected=403, json={'request_id': str(uuid4())})


def test_claim_once_has_no_bindings_and_no_web_secret_getter(f):
    pairing = f.issue()
    assert set(pairing) == {'schema', 'pairing', 'pairing_code', 'code_once'}
    metadata = f.call('GET', PREFIX + '/device-pairings/' + pairing['pairing']['id'])
    assert 'pairing_code' not in json.dumps(metadata) and 'credential' not in json.dumps(metadata)
    devices = f.call('GET', PREFIX + '/devices')['items']
    assert any(d['id'] == pairing['pairing']['device_id'] and d['active'] is False for d in devices)
    f.call('POST', PREFIX + '/device-pairings', expected=409, json={'label': pairing['pairing']['label'], 'request_id': pairing['pairing']['request_id']})
    claimed = f.claim(pairing)
    assert claimed['pairing_id'] == pairing['pairing']['id']
    assert claimed['automatic_submit'] is claimed['bindings_configured'] is False
    assert set(claimed['device']) == {'id', 'label', 'active', 'credential', 'credential_once'}
    assert f.discover(claimed['device'])['items'] == []
    for _ in range(2):
        assert f.claim(pairing, expected=409)['detail']['code'] == 'PAIRING_CODE_UNAVAILABLE'
    read = f.call('GET', PREFIX + '/device-pairings/' + pairing['pairing']['id'])['pairing']
    assert read['state'] == 'claimed' and read['claimed_at'] is not None
    assert not any(secret in json.dumps(read) for secret in f.secrets)


def test_atomic_concurrent_claims_return_only_one_credential(f):
    pairing = f.issue()
    async def run():
        async with httpx.AsyncClient(base_url='https://127.0.0.1:55881', verify=f.context, trust_env=False, timeout=20) as client:
            return await asyncio.gather(*(client.post(PREFIX + '/device-pairings/claim',
                json={'pairing_code': pairing['pairing_code'], 'request_id': str(uuid4())}) for _ in range(8)))
    responses = asyncio.run(run())
    assert sum(r.status_code == 200 for r in responses) == 1
    assert sum(r.status_code == 409 for r in responses) == 7
    winner = next(r.json() for r in responses if r.status_code == 200)
    f.secrets.append(winner['device']['credential'])
    assert f.discover(winner['device'])['items'] == []


def test_concurrent_claim_and_admin_revoke_cannot_leave_device_active(f):
    pairing = f.issue()
    async def run():
        async with httpx.AsyncClient(base_url='https://127.0.0.1:55881', verify=f.context, trust_env=False, timeout=20) as client:
            return await asyncio.gather(
                client.post(PREFIX + '/device-pairings/claim', json={'pairing_code': pairing['pairing_code'], 'request_id': str(uuid4())}),
                client.post(PREFIX + '/device-pairings/' + pairing['pairing']['id'] + '/revoke',
                    headers={'Authorization': 'Bearer ' + f.tokens['admin']}, json={'request_id': str(uuid4())}))
    claimed, revoked = asyncio.run(run())
    assert claimed.status_code in (200, 409) and revoked.status_code == 200
    assert revoked.json()['pairing']['state'] == 'revoked'
    f.claim(pairing, expected=409)
    if claimed.status_code == 200:
        device = claimed.json()['device']
        f.secrets.append(device['credential'])
        f.discover(device, expected=401)


def test_expiry_and_pending_device_revoke_never_reactivate(f):
    expired = f.issue()
    f.call('POST', '/test/mutate', json={'kind': 'expire-pairing', 'id': expired['pairing']['id']})
    assert f.call('GET', PREFIX + '/device-pairings/' + expired['pairing']['id'])['pairing']['state'] == 'expired'
    f.claim(expired, expected=409)
    pending = f.issue()
    f.call('POST', PREFIX + '/devices/' + pending['pairing']['device_id'] + '/revoke')
    f.claim(pending, expected=409)
    assert f.call('GET', PREFIX + '/device-pairings/' + pending['pairing']['id'])['pairing']['state'] == 'revoked'


def test_current_issuer_permission_withdrawal_is_rechecked(f):
    pairing = f.issue()
    f.call('POST', '/test/mutate', actor='rescue', json={'kind': 'admin-role', 'active': False})
    try:
        f.claim(pairing, expected=409)
        f.call('POST', PREFIX + '/device-pairings', expected=403, json={'label': 'No admin role', 'request_id': str(uuid4())})
        f.call('GET', PREFIX + '/device-pairings', expected=403)
    finally:
        f.call('POST', '/test/mutate', actor='rescue', json={'kind': 'admin-role', 'active': True})


def test_pairing_expiry_is_rechecked_after_real_issuer_lock_wait(f):
    import asyncpg
    pairing = f.issue()
    config = json.loads((ROOT / 'environment.json').read_text(encoding='utf-8'))
    async def race():
        db = await asyncpg.connect('postgresql://device_pairing_test@127.0.0.1:55547/device_pairing_test', server_settings={'search_path': config['schema']})
        pending = None
        try:
            expiry = int(time.time() * 1000) + 2000
            await db.execute('UPDATE distribution_device_pairings SET expires_at=$1 WHERE id=$2', expiry, __import__('uuid').UUID(pairing['pairing']['id']))
            async with httpx.AsyncClient(base_url='https://127.0.0.1:55881', verify=f.context, trust_env=False, timeout=15) as client:
                async with db.transaction():
                    await db.fetchval('SELECT id FROM roles WHERE id=2 FOR UPDATE')
                    pending = asyncio.create_task(client.post(PREFIX + '/device-pairings/claim', json={
                        'pairing_code': pairing['pairing_code'], 'request_id': str(uuid4())}))
                    blocked = False
                    for _ in range(30):
                        await db.fetchval('SELECT pg_stat_clear_snapshot()')
                        if await db.fetchval("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%roles%')"):
                            blocked = True
                            break
                        await asyncio.sleep(.05)
                    assert blocked, 'Actual claim did not wait on issuer role lock'
                    await asyncio.sleep(max(0, (expiry - int(time.time() * 1000)) / 1000) + .1)
                response = await pending
                assert response.status_code == 409, 'Expired claim activated after issuer lock wait'
        finally:
            if pending and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await db.close()
    asyncio.run(race())


@pytest.mark.parametrize('header', ['authorization', 'origin', 'sec-fetch-site'])
def test_browser_or_jwt_claim_cannot_download_credential(f, header):
    pairing = f.issue()
    value = 'Bearer ' + f.tokens['admin'] if header == 'authorization' else 'same-origin'
    response = f.client.post(PREFIX + '/device-pairings/claim', headers={header: value},
        json={'pairing_code': pairing['pairing_code'], 'request_id': str(uuid4())})
    assert response.status_code == 400 and response.json()['detail']['code'] == 'PAIRING_DEVICE_ONLY'
    assert f.call('GET', PREFIX + '/device-pairings/' + pairing['pairing']['id'])['pairing']['state'] == 'pending'


def test_device_only_binding_discovery_is_exact_and_operational(f):
    first = f.claim(f.issue())['device']
    second = f.claim(f.issue())['device']
    binding = f.bind(first)
    f.bind(second, {'module': 'seo', 'tenant_id': 16, 'scope_id': 7})
    result = f.discover(first)
    assert len(result['items']) == 1
    item = result['items'][0]
    assert set(item) == {'binding_id', 'device_id', 'module', 'tenant_id', 'scope_id', 'account_id', 'external_account_id', 'platform', 'login_state'}
    assert item['binding_id'] == binding['id'] and item['external_account_id'] == binding['external_account_id']
    assert item['login_state'] == 'unverified' and item['tenant_id'] == 15
    f.discover(first, expected=401, device_id=second['id'])
    f.call('POST', PREFIX + '/device/bindings', expected=401, json={'device_id': first['id']})
    for kind in ('site-status', 'module-status'):
        f.call('POST', '/test/mutate', actor='rescue', json={'kind': kind, 'active': False})
        try:
            assert f.discover(first)['items'] == []
        finally:
            f.call('POST', '/test/mutate', actor='rescue', json={'kind': kind, 'active': True})
    f.call('PUT', '/api/v1/seo/workbench/advisor-assignments', json={'tenant_id': 15, 'site_id': 6, 'advisor_user_id': 100007, 'active': False})
    assert f.discover(first)['items'] == []


def test_missing_native_structure_is_503_not_empty_bindings(f):
    device = f.claim(f.issue())['device']
    f.bind(device)
    f.call('POST', '/test/mutate', actor='rescue', json={'kind': 'scope-schema', 'active': False})
    try:
        assert f.discover(device, expected=503)['detail']['code'] == 'PAIRING_UNAVAILABLE'
    finally:
        f.call('POST', '/test/mutate', actor='rescue', json={'kind': 'scope-schema', 'active': True})


@pytest.mark.parametrize('phase', ['create', 'claim'])
@pytest.mark.parametrize('mode', ['audit', 'commit'])
def test_actual_pg_fault_atomicity_requires_explicit_repair_not_claim_retry(f, phase, mode):
    pairing = f.issue() if phase == 'claim' else None
    f.call('POST', '/test/fault', json={'mode': mode})
    if phase == 'create':
        f.call('POST', PREFIX + '/device-pairings', expected=503,
            json={'label': 'Faulting bootstrap', 'request_id': str(uuid4())})
    else:
        f.claim(pairing, expected=503)
        state = f.call('GET', PREFIX + '/device-pairings/' + pairing['pairing']['id'])['pairing']['state']
        assert state == 'pending'
        f.revoke(pairing)  # Explicit admin repair: do not retry the unknown claim.
        f.claim(pairing, expected=409)
    replacement = f.issue()
    assert f.claim(replacement)['device']['active'] is True


def test_claim_unknown_is_revoked_and_repaired_without_secret_replay(f):
    pairing = f.issue()
    claimed = f.claim(pairing)  # Treat delivered response as if the PC discarded it.
    revoked = f.revoke(pairing)
    assert revoked['pairing']['state'] == 'revoked'
    f.claim(pairing, expected=409)
    f.discover(claimed['device'], expected=401)
    replacement = f.claim(f.issue())['device']
    assert replacement['id'] != claimed['device']['id']
    assert f.discover(replacement)['items'] == []


def test_pairing_request_bounds_query_https_and_no_sensitive_error_echo(f):
    for payload in ({'label': 'x', 'expires_in_seconds': True}, {'label': 'x', 'expires_in_seconds': 59},
            {'label': 'x', 'expires_in_seconds': 601}, {'label': '\n'}, {'label': 'x', 'credential': 'synthetic-secret'}):
        value = f.call('POST', PREFIX + '/device-pairings', expected=422, json={'request_id': str(uuid4()), **payload})
        assert 'synthetic-secret' not in json.dumps(value)
    f.call('GET', PREFIX + '/device-pairings?code=synthetic', expected=400)
    response = f.client.post(PREFIX + '/device-pairings/claim', json={'pairing_code': 'x' * 32, 'request_id': str(uuid4())})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'PAIRING_CODE_UNAVAILABLE'
    response = f.client.post(PREFIX + '/device-pairings/claim', content=b'x' * 4097, headers={'Content-Type': 'application/json'})
    assert response.status_code == 413
    response = f.client.get(PREFIX + '/device-pairings', headers={
        'Authorization': 'Bearer ' + f.tokens['admin'], 'X-Forwarded-Proto': 'http'})
    assert response.status_code == 426


def test_plaintext_code_credential_absent_from_pg_and_fixture_logs(f):
    import asyncpg
    pairing = f.issue()
    f.claim(pairing)
    config = json.loads((ROOT / 'environment.json').read_text(encoding='utf-8'))
    async def check():
        db = await asyncpg.connect('postgresql://device_pairing_test@127.0.0.1:55547/device_pairing_test', server_settings={'search_path': config['schema']})
        try:
            async with db.transaction(readonly=True):
                for table in ('distribution_device_pairings', 'distribution_devices', 'distribution_events'):
                    rows = await db.fetch(f'SELECT row_to_json(t)::text AS value FROM {table} t')
                    assert not any(secret in row['value'] for row in rows for secret in f.secrets), 'Plaintext bootstrap secret persisted'
        finally:
            await db.close()
    asyncio.run(check())
    for name in ('serve-private.log', 'postgres.log', 'last-error-private.log'):
        raw = (ROOT / name).read_text(encoding='utf-8', errors='replace')
        assert not any(secret in raw for secret in f.secrets), 'Plaintext bootstrap secret logged'


def test_claimed_device_revoke_closes_remote_caps_and_real_leased_task(f):
    import asyncpg
    pairing = f.issue()
    device = f.claim(pairing)['device']
    binding = f.bind(device)
    manifest_raw = (Path(__file__).resolve().parents[1] / 'docs/fixtures/mht-distribution-capabilities-v1.json').read_bytes()
    response = f.client.post('/api/distribution/capabilities/v1/device/register',
        headers={'Authorization': 'Bearer ' + device['credential']}, json={'capabilityVersion': 1,
            'deviceId': device['id'], 'adapterVersion': 'reviewed-manual-handoff-v1',
            'manifestDigest': hashlib.sha256(manifest_raw).hexdigest(), 'manifest': json.loads(manifest_raw),
            'bindingIds': [binding['id']], 'expiresAt': int(time.time() * 1000) + 600000,
            'expectedRevision': 0, 'requestId': str(uuid4())})
    assert response.status_code == 200
    task = f.native_task(device, binding)
    remote = f.call('POST', PREFIX + '/remote/sessions', actor='advisor', json={**SCOPE,
        'binding_id': binding['id'], 'purpose': 'account-login', 'request_id': str(uuid4())})
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 32, 24, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\0' + b'\x44\x66\x88\xff' * 32) * 24)) + chunk(b'IEND', b'')
    response = f.client.post(PREFIX + '/remote/device/frame', content=png, headers={
        'Authorization': 'Bearer ' + device['credential'], 'Content-Type': 'image/png', 'X-Remote-Device-Id': device['id'],
        'X-Remote-Session-Id': remote['session']['id'], 'X-Frame-Seq': '1', 'X-Control-Revision': '1',
        'X-Viewport-Width': '32', 'X-Viewport-Height': '24', 'X-Frame-Captured-At': str(int(time.time() * 1000))})
    assert response.status_code == 200
    response = f.client.get(PREFIX + '/remote/sessions/' + remote['session']['id'] + '/frame', headers={'Authorization': 'Bearer ' + f.tokens['advisor']})
    assert response.status_code == 200
    f.call('POST', PREFIX + '/remote/sessions/' + remote['session']['id'] + '/input', actor='advisor', json={
        'command_id': str(uuid4()), 'control_nonce': remote['control_nonce'], 'frame_seq': 1, 'control_revision': 1,
        'input': {'kind': 'text', 'text': 'synthetic-pairing-revoke-input'}})
    f.revoke(pairing)
    f.discover(device, expected=401)
    response = f.client.get('/api/distribution/capabilities/v1/device/' + device['id'] + '/status', headers={'Authorization': 'Bearer ' + device['credential']})
    assert response.status_code == 401
    config = json.loads((ROOT / 'environment.json').read_text(encoding='utf-8'))
    async def check():
        db = await asyncpg.connect('postgresql://device_pairing_test@127.0.0.1:55547/device_pairing_test', server_settings={'search_path': config['schema']})
        try:
            async with db.transaction(readonly=True):
                actual_task = await db.fetchrow('SELECT status,revoked,publication_grant_id FROM distribution_tasks WHERE id=$1', __import__('uuid').UUID(task['id']))
                assert actual_task['status'] == 'unknown' and actual_task['revoked'] is True and actual_task['publication_grant_id'] is None
                actual_remote = await db.fetchrow('SELECT state,code,last_command_state FROM distribution_remote_sessions WHERE id=$1', __import__('uuid').UUID(remote['session']['id']))
                assert actual_remote['state'] == 'closed' and actual_remote['code'] == 'AUTHORIZATION_REVOKED' and actual_remote['last_command_state'] == 'canceled'
                assert await db.fetchval('SELECT active FROM distribution_device_capability_registrations WHERE device_id=$1', device['id']) is False
        finally:
            await db.close()
    asyncio.run(check())
    metadata = f.call('GET', '/test/metadata', actor='rescue')
    assert metadata['nonces'] == metadata['payloads'] == metadata['frames'] == metadata['read_frames'] == 0


def service(action):
    from scripts.distribution_pairing_test_service import PYTHON, CENTRAL
    result = subprocess.run([str(PYTHON), str(CENTRAL / 'scripts/distribution_pairing_test_service.py'),
        '--root', str(ROOT), action], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0


def wait_ready(f, port=55881):
    for _ in range(80):
        try:
            response = f.client.get(f'https://127.0.0.1:{port}/test-health')
            if response.status_code == 200:
                return response.json()
        except httpx.TransportError:
            pass
        time.sleep(.1)
    raise AssertionError('Owned pairing fixture not ready')


def test_pairing_restart_preserves_pending_and_never_replays_claim_secret(f):
    pending = f.issue()
    used = f.issue()
    device = f.claim(used)['device']
    service('stop'); service('start'); wait_ready(f)
    assert f.claim(pending)['device']['active'] is True
    f.claim(used, expected=409)
    assert f.discover(device)['items'] == []


def test_pairing_default_off_keeps_legacy_compatibility_without_owner_conflict(f):
    from scripts.distribution_pairing_test_service import PYTHON, CENTRAL, env
    with (ROOT / 'pairing-default-off-private.log').open('wb') as log:
        proc = subprocess.Popen([str(PYTHON), str(CENTRAL / 'scripts/distribution_pairing_test_service.py'),
            '--root', str(ROOT), 'serve-off'], cwd=ROOT, env=env(ROOT), stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            wait_ready(f, 55882)
            response = f.client.post('https://127.0.0.1:55882' + PREFIX + '/device-pairings',
                headers={'Authorization': 'Bearer ' + f.tokens['admin']}, json={'label': 'Disabled pairing', 'request_id': str(uuid4())})
            assert response.status_code == 503 and response.json()['detail']['code'] == 'PAIRING_DISABLED'
            response = f.client.post('https://127.0.0.1:55882' + PREFIX + '/devices',
                headers={'Authorization': 'Bearer ' + f.tokens['admin']}, json={'label': 'Legacy compatibility only'})
            assert response.status_code == 200
            device_id = response.json()['device']['id']
            f.call('POST', PREFIX + '/devices/' + device_id + '/revoke')
        finally:
            service('stop'); service('start'); wait_ready(f)
