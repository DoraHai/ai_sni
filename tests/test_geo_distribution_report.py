"""Synthetic wire, authority and publication-boundary regressions."""
import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.geo.content import distribution_protocol as p, distribution_report as s


def task_fixture():
    target = {'customerId': '7', 'projectId': 'geo-5', 'accountId': '9', 'platform': 'wechat-article',
              'contentVersion': 'geo-article-100', 'contentDigest': 'a' * 64, 'leaseId': 'lease-1'}
    task = {'wire': {'id': 'task-1'}, 'target': target, 'events': {'receipt': {}, 'observation': {}},
            'sequence': {'receipt': 0, 'observation': 0}, 'outcome': 'queued', 'last_code': 'QUEUED'}
    event = {**target, 'receiptId': 'receipt-1', 'sequence': 1, 'contractVersion': 1, 'deviceId': 'device-1',
             'taskId': 'task-1', 'status': 'succeeded', 'code': 'HUMAN_PUBLISHED', 'at': 1792375200000,
             'evidence': 'human-reported', 'publicUrl': 'https://mp.weixin.qq.com/s/synthetic'}
    return task, event


@pytest.mark.parametrize('settings', [None, {}, {p.KEY: None}])
def test_missing_configuration_is_disabled(settings):
    assert not p.enabled(p.registry(settings), 5)


@pytest.mark.parametrize('value', ['true', 1, None, {}, []])
def test_invalid_configuration_fails_closed(value):
    book = p.registry({}); book['enabled'] = value
    with pytest.raises(HTTPException) as error:
        p.registry({p.KEY: book})
    assert error.value.status_code == 503


def test_two_switches_and_each_project_are_required():
    book = p.registry({}); book['enabled'] = True
    assert not p.enabled(book, 5)
    book['scopes']['5'] = {'enabled': True, 'revision': 1}
    assert p.enabled(book, 5) and not p.enabled(book, 6)
    book['enabled'] = False
    assert not p.enabled(book, 5)


@pytest.mark.parametrize('key,value', [('customerId', '8'), ('projectId', 'geo-6'), ('accountId', '10'),
    ('contentVersion', 'geo-article-101'), ('contentDigest', 'b' * 64), ('leaseId', 'lease-2'), ('deviceId', 'other')])
def test_every_target_field_is_bound(key, value):
    task, event = task_fixture(); event[key] = value
    with pytest.raises(HTTPException): p.validate_event(event, task, 'device-1', 'receipt')
    assert task['events']['receipt'] == {}


@pytest.mark.parametrize('url', ['http://mp.weixin.qq.com/s/abc', 'https://mp.weixin.qq.com/s/abc?draft=1',
    'https://mp.weixin.qq.com/s/abc#x', 'https://mp.weixin.qq.com.evil.invalid/s/abc',
    'https://user@mp.weixin.qq.com/s/abc', 'https://127.0.0.1/s/abc', 'https://mp.weixin.qq.com:443/s/abc',
    'https://mp.weixin.qq.com/cgi-bin/appmsg', 'https://mp.weixin.qq.com/s/../abc'])
def test_only_exact_public_wechat_short_urls(url):
    with pytest.raises(HTTPException): p.public_url(url)


def test_exact_ack_deduplication_conflict_and_sequence_gaps():
    task, event = task_fixture(); event['sequence'] = 3
    book = {'tasks': {'task-1': task}}
    ack = p.validate_event(event, task, 'device-1', 'receipt')
    assert set(ack) == {'receiptId', 'sequence', 'taskId', 'leaseId', 'status', 'at'}
    assert p.admit_event(book, task, event, 'receipt', ack) == (ack, True)
    assert p.admit_event(book, task, event, 'receipt', ack) == (ack, False)
    changed = {**event, 'publicUrl': 'https://mp.weixin.qq.com/s/different'}
    with pytest.raises(HTTPException) as error: p.admit_event(book, task, changed, 'receipt', ack)
    assert error.value.detail['code'] == 'IDEMPOTENCY_CONFLICT'
    assert task['outcome'] == 'succeeded'


@pytest.mark.parametrize('code', list(p.OBSERVATIONS))
def test_observations_are_never_success_and_never_carry_urls(code):
    task, event = task_fixture()
    event = {k: v for k, v in event.items() if k not in {'receiptId', 'contractVersion', 'deviceId'}}
    event.update(observationId='obs-1', code=code, status=p.OBSERVATIONS[code], evidence='none', publicUrl=None)
    ack = p.validate_event(event, task, 'device-1', 'observation')
    assert len(ack) == 7 and ack['at'] == event['at']
    book = {'tasks': {'task-1': task}}
    p.admit_event(book, task, event, 'observation', ack)
    assert task['outcome'] != 'succeeded'
    event['publicUrl'] = 'https://mp.weixin.qq.com/s/synthetic'
    with pytest.raises(HTTPException): p.validate_event(event, task, 'device-1', 'observation')


def test_late_observation_cannot_downgrade_success_and_old_unknown_sequence_rejected():
    task, event = task_fixture(); task['outcome'] = 'succeeded'
    task['sequence']['observation'] = 5
    event = {**event, 'observationId': 'obs-1', 'sequence': 8, 'status': 'failed', 'code': 'HUMAN_FAILED'}
    p.admit_event({'tasks': {'task-1': task}}, task, event, 'observation', {})
    assert task['outcome'] == 'succeeded'
    event.update(observationId='obs-2', sequence=6)
    with pytest.raises(HTTPException) as error: p.admit_event({'tasks': {'task-1': task}}, task, event, 'observation', {})
    assert error.value.detail['code'] == 'SEQUENCE_STALE'


def test_digest_is_utf8_json_stringify_compatible():
    content = {'version': 'v1', 'title': '中文😀', 'body': '换行\n"\\', 'assets': []}
    expected = hashlib.sha256('["v1","中文😀","换行\\n\\"\\\\",[]]'.encode()).hexdigest()
    assert p.content_digest(content) == expected


def request(path='/device/exchange', seq=1, sent=None, extra=None):
    headers = {'x-distribution-request-seq': str(seq), 'x-distribution-sent-at': str(sent or s.now_ms()), **(extra or {})}
    return Request({'type': 'http', 'method': 'POST', 'path': p.PREFIX + path, 'query_string': b'',
                    'headers': [(k.encode(), v.encode()) for k, v in headers.items()]})


def test_transport_fingerprint_binds_body_path_timestamp_and_high_watermark():
    device = {'request_seq': 0, 'request_digest': None}
    req = request(seq=3)
    s.transport(device, req, b'{}'); s.transport(device, req, b'{}')
    for changed, raw in [(req, b'{ }'), (request('/device/observations', seq=3), b'{}'), (request(seq=1), b'{}')]:
        with pytest.raises(HTTPException): s.transport(device, changed, raw)
    s.transport(device, request(seq=8), b'{}')
    with pytest.raises(HTTPException): s.transport(device, request(seq=9, sent=s.now_ms() - 600_000), b'{}')


@pytest.mark.parametrize('header', ['origin', 'cookie', 'sec-fetch-site', 'sec-fetch-mode'])
def test_browser_requests_rejected(header):
    with pytest.raises(HTTPException) as error: s.native_headers(request(extra={header: 'synthetic'}))
    assert error.value.status_code == 401


@pytest.mark.parametrize('credential', ['Bearer synthetic-human-jwt', 'Bearer dr1.seo.7.device.synthetic', 'Bearer dr1.geo.7.bad.synthetic', ''])
def test_forged_and_other_module_credentials_never_reach_storage(credential):
    with patch.object(s, 'open_store', AsyncMock()) as opened, pytest.raises(HTTPException):
        asyncio.run(s.authenticate(NS(), request(extra={'authorization': credential}), reporting=True))
    opened.assert_not_awaited()


def test_disabled_replay_and_revoked_device_are_rejected_before_acks():
    async def run():
        credential = 'a' * 64
        device = {'id': '00000000-0000-4000-8000-000000000001', 'credential_hash': s.sha(credential), 'revoked': False,
                  'expires_at': s.now_ms() + 100_000, 'actor': {}, 'scope_id': 5, 'account_id': 9}
        store = NS(book={**p.registry({}), 'devices': {device['id']: device}})
        with patch.object(s, 'open_store', AsyncMock(return_value=store)), \
             patch.object(s, 'actor_authorized', AsyncMock()), patch.object(s, 'account_binding', AsyncMock()):
            with pytest.raises(HTTPException) as error:
                await s.authenticate(NS(scalar=AsyncMock(return_value=7)), request(extra={'authorization': 'Bearer ' + credential}), reporting=True)
            assert error.value.detail['code'] == 'REPORTING_DISABLED'
            device['revoked'] = True
            with pytest.raises(HTTPException) as error:
                await s.authenticate(NS(scalar=AsyncMock(return_value=7)), request(extra={'authorization': 'Bearer ' + credential}), reporting=False)
            assert error.value.detail['code'] == 'DEVICE_REVOKED'
    asyncio.run(run())


def test_publication_gate_is_reused_and_failure_does_not_ack():
    from app.geo.content import routes
    from app.geo.content.gate import PublishGateError
    task, event = task_fixture(); task.update(scope_id=5, publication_id=None); event['at'] = s.now_ms()
    task['target']['contentDigest'] = event['contentDigest']
    store = NS(book={'tasks': {'task-1': task}}, session=NS(scalar=AsyncMock()), audit=Mock())
    native, variant = NS(), NS(id=2, adapt_meta={})
    with patch.object(s, 'task_authorized', AsyncMock(return_value=(task, native, variant, NS()))), \
         patch.object(routes, '_write_publication', AsyncMock(side_effect=PublishGateError('synthetic rejection'))) as write, \
         pytest.raises(HTTPException) as error:
        asyncio.run(s.apply_events(store, {'id': 'device-1'}, [event], 'receipt'))
    assert error.value.detail['code'] == 'REVIEW_REQUIRED'
    write.assert_awaited_once()
    store.audit.assert_not_called()


def test_request_body_is_bounded_duplicate_safe_and_reusable():
    from app.geo.content.distribution_routes import body
    async def run(raw):
        async def receive(): return {'type': 'http.request', 'body': raw, 'more_body': False}
        req = Request({'type': 'http', 'headers': []}, receive)
        a = await body(req); b = await body(req)
        assert a == b
    asyncio.run(run(b'{"enabled":true}'))
    for raw in [b'{"enabled":true,"enabled":false}', b'{"x":NaN}', b'x' * (p.MAX_REQUEST + 1)]:
        with pytest.raises(HTTPException): asyncio.run(run(raw))


def test_settings_and_task_projection_never_expose_registry_values(caplog):
    task, _ = task_fixture()
    task.update(native_task_id=12, variant_id=3, article_id=100, publication_id=None)
    task['target']['contentVersion'] = 'v1'; task['target']['contentDigest'] = 'a' * 64
    task['wire']['leaseId'] = 'lease-1'
    task['credential_hash'] = 'synthetic-sensitive-marker'
    assert 'synthetic-sensitive-marker' not in json.dumps(s.task_projection(task))
    assert not caplog.text
