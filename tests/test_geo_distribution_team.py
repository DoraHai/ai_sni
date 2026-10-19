"""Team pairing limits, durable failure accounting and display-only profile."""
import asyncio
import copy
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.geo.content import distribution_protocol as p, distribution_report as s, distribution_routes as r


def store_fixture():
    session = NS(flush=AsyncMock(), commit=AsyncMock(), scalar=AsyncMock())
    return s.Store(session, 7, NS(id=1, module_settings={'other': {'kept': True}}), p.registry({}))


def native_request(path='/device-pairings/claim', data=None, extra=None, query=b''):
    raw = json.dumps(data or {}).encode()
    req = Request({'type': 'http', 'method': 'GET' if path.endswith('profile') else 'POST',
        'path': p.PREFIX + path, 'query_string': query, 'client': ('127.0.0.1', 1234),
        'headers': [(k.encode(), v.encode()) for k, v in (extra or {}).items()]})
    req._body = raw
    return req


@pytest.mark.parametrize('label', ['', '   ', '\t', '\u200b', 'x\n', 'x' * 81])
def test_blank_or_control_device_remark_is_rejected(label):
    async def run():
        with pytest.raises(HTTPException) as denied:
            await s.create_pairing(store_fixture(), 5, {'user_id': 9},
                {'label': label, 'platform': 'wechat-article', 'account_id': '1', 'expected_revision': 0})
        assert denied.value.status_code == 422
    asyncio.run(run())


def test_twenty_pending_codes_and_twenty_active_devices_are_tenant_scoped():
    async def run():
        store = store_fixture()
        with patch.object(s, 'account_binding', AsyncMock()):
            for i in range(20):
                await s.create_pairing(store, 5 if i % 2 else 6, {'user_id': 9},
                    {'label': '  团队电脑  ', 'platform': 'wechat-article', 'account_id': '1', 'expected_revision': i})
            assert len(store.book['pairings']) == 20
            assert all(pair['label'] == '团队电脑' for pair in store.book['pairings'].values())
            with pytest.raises(HTTPException) as denied:
                await s.create_pairing(store, 5, {'user_id': 9},
                    {'label': 'another', 'platform': 'wechat-article', 'account_id': '1', 'expected_revision': 20})
            assert denied.value.status_code == 429
            store.book['pairings'].clear()
            store.book['devices'] = {str(i): {'revoked': False, 'expires_at': s.now_ms() + 100000} for i in range(20)}
            with pytest.raises(HTTPException):
                await s.create_pairing(store, 5, {'user_id': 9},
                    {'label': 'another', 'platform': 'wechat-article', 'account_id': '1', 'expected_revision': 20})
            other = store_fixture()
            await s.create_pairing(other, 5, {'user_id': 9},
                {'label': 'other tenant', 'platform': 'wechat-article', 'account_id': '1', 'expected_revision': 0})
            assert len(other.book['pairings']) == 1
    asyncio.run(run())


def test_known_failure_survives_reload_and_http_error_commit_success_is_free():
    async def run():
        store = store_fixture()
        code = 'a' * 32
        store.book['pairings']['pair'] = {'id': 'pair', 'code_hash': s.sha(code), 'consumed': False,
            'expires_at': s.now_ms() + 100000, 'scope_id': 5, 'account_id': 1, 'label': 'team', 'actor': {'user_id': 9}}
        r._claim_failures.clear()
        with patch.object(s, 'hash_locator', AsyncMock(return_value=7)), patch.object(s, 'open_store', AsyncMock(return_value=store)), \
             patch.object(s, 'actor_authorized', AsyncMock(side_effect=HTTPException(403, {'code': 'ACTOR_AUTHORIZATION_REVOKED'}))), \
             patch.object(s, 'account_binding', AsyncMock()):
            for _ in range(6):
                with pytest.raises(s.PairingRejected):
                    await r.claim(native_request(data={'pairing_code': code, 'request_id': str(uuid4())}), store.session)
                # Reload what save flushed, simulating a fresh worker/process.
                store.book = p.registry(copy.deepcopy(store.row.module_settings))
                assert all(not value for value in r._claim_failures.values())
                r._claim_failures.clear()
            assert store.book['pairings']['pair']['claim_failures']['count'] == 6
            assert store.session.commit.await_count == 6
            assert not store.book['devices']
            with pytest.raises(HTTPException) as denied:
                await r.claim(native_request(data={'pairing_code': code, 'request_id': str(uuid4())}), store.session)
            assert denied.value.status_code == 429
            assert all(not value for value in r._claim_failures.values())
            store.book['pairings']['pair']['claim_failures']['until'] = 0
        with patch.object(s, 'hash_locator', AsyncMock(return_value=7)), patch.object(s, 'open_store', AsyncMock(return_value=store)), \
             patch.object(s, 'actor_authorized', AsyncMock()), patch.object(s, 'account_binding', AsyncMock()):
            result = await r.claim(native_request(data={'pairing_code': code, 'request_id': str(uuid4())}), store.session)
            assert result.status_code == 200
            assert store.book['pairings']['pair']['claim_failures']['count'] == 6
            assert store.row.module_settings['other'] == {'kept': True}
    asyncio.run(run())


def test_many_successful_customer_pairings_from_same_computer_do_not_rate_limit():
    async def run():
        r._claim_failures.clear()
        session = NS(commit=AsyncMock())
        with patch.object(s, 'claim', AsyncMock(return_value={'schema': 1})):
            for _ in range(90):
                assert (await r.claim(native_request(data={'pairing_code': 'a' * 32}), session)).status_code == 200
        assert all(not value for value in r._claim_failures.values())
        assert session.commit.await_count == 90
    asyncio.run(run())


def test_unknown_code_failures_are_bounded_and_do_not_block_other_codes():
    async def run():
        r._claim_failures.clear()
        with patch.object(s, 'claim', AsyncMock(side_effect=HTTPException(409, {'code': 'PAIRING_CODE_UNAVAILABLE'}))):
            for _ in range(6):
                with pytest.raises(HTTPException):
                    await r.claim(native_request(data={'pairing_code': 'a' * 32}), NS())
            with pytest.raises(HTTPException) as denied:
                await r.claim(native_request(data={'pairing_code': 'a' * 32}), NS())
            assert denied.value.status_code == 429
        with patch.object(s, 'claim', AsyncMock(return_value={'schema': 1})):
            assert (await r.claim(native_request(data={'pairing_code': 'b' * 32}), NS(commit=AsyncMock()))).status_code == 200
        for i in range(2100):
            r.claim_failure_bucket(native_request(), {'pairing_code': str(i)})
        assert len(r._claim_failures) == 2048
    asyncio.run(run())


def test_profile_exact_projection_sanitizes_names_and_does_not_advance_sequence():
    async def run():
        store = store_fixture()
        store.session.scalar.side_effect = ['  客户\u200b 名  ', '项目\x00名称', '公众号😀' * 80]
        device = {'id': 'device-1', 'scope_id': 5, 'account_id': 9, 'label': ' 团队\u202e电脑 ', 'request_seq': 77}
        before = copy.deepcopy(device)
        with patch.object(s, 'authenticate', AsyncMock(return_value=(store, device))):
            response = await r.profile(native_request('/device/profile'), store.session)
        value = json.loads(response.body)
        assert set(value) == {'schema', 'device_id', 'customer_name', 'scope_name', 'account_name', 'label'}
        assert value['customer_name'] == '客户 名' and value['scope_name'] == '项目名称'
        assert value['label'] == '团队电脑' and len(value['account_name']) == 120
        assert response.headers['cache-control'] == 'private, no-store'
        assert device == before
        store.session.flush.assert_not_awaited()
        store.session.commit.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('extra,query', [({}, b''), ({'authorization': 'Bearer ' + 'z' * 64}, b''),
    ({'origin': 'https://example.invalid'}, b''), ({'cookie': 'synthetic=1'}, b''), ({}, b'tenant_id=8')])
def test_profile_rejects_missing_forged_seo_browser_or_selector_credentials(extra, query):
    async def run():
        # A valid-format SEO token is absent from the GEO locator namespace.
        with patch.object(s, 'hash_locator', AsyncMock(return_value=None)) as locator:
            with pytest.raises(HTTPException) as denied:
                await r.profile(native_request('/device/profile', extra=extra, query=query), NS())
            assert denied.value.status_code in {401, 422}
            if locator.await_count:
                assert locator.call_args.args[1:3] == ('devices', 'credential_hash')
    asyncio.run(run())
