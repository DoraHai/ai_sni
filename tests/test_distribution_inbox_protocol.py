"""Synthetic v2 vectors and wire boundaries; never imports application config."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from app.distribution_inbox_protocol import (
    EVENT_BYTES, EVENT_KEYS, PREFIX, ProtocolError, audit_endpoint, canonical_json,
    match_inbox_business_route, match_inbox_identity_route, normalize_url,
    payload_digest, strict_json, validate_ack_query, validate_claim, validate_event,
    validate_label, validate_pairing, validate_revision,
)

VECTORS = json.loads((Path(__file__).parent / 'fixtures/inbox_vectors_v2.json').read_text(encoding='utf-8'))
NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
ID = '11111111-1111-4111-8111-111111111111'


def event(**changes):
    value = {**VECTORS['events'][0]['event'], **changes}
    value['payloadDigest'] = payload_digest(value)
    return value


@pytest.mark.parametrize('vector', VECTORS['events'])
def test_cross_language_vectors_and_immutable_digest(vector):
    value = vector['event']
    original = deepcopy(value)
    assert canonical_json(value) == vector['canonicalJson']
    assert payload_digest(value) == value['payloadDigest']
    parsed = validate_event(strict_json(json.dumps(value, ensure_ascii=False).encode()), now=NOW)
    assert value == original
    if value['eventId'] == ID:
        assert value['platform'] == '新平台'
        assert value['title'] == '合成标题 😀'
        assert parsed['platform'] == '新平台' and parsed['platform_kind'] == 'other'
    if value['publicUrl']:
        assert parsed['canonical_url'] == normalize_url(value['publicUrl'])


@pytest.mark.parametrize('vector', VECTORS['urlExamples'])
def test_scoped_simple_url_vectors(vector):
    assert normalize_url(vector['input']) == vector['canonical']


@pytest.mark.parametrize('url,expected', [
    ('http://NewPlatform.invalid:8080/A?identity=1#section', 'http://newplatform.invalid:8080/A?identity=1'),
    ('https://[2001:DB8::1]:444/A#x', 'https://[2001:db8::1]:444/A'),
    ('http://127.0.0.1/path', 'http://127.0.0.1/path'),
    ('https://未知.invalid/路径?业务=是', 'https://未知.invalid/路径?业务=是'),
    ('https://Example.invalid:443/a%2Fb?X=Y&b=2', 'https://example.invalid:443/a%2Fb?X=Y&b=2'),
    ('https://EXAMPLE.invalid/a?#f', 'https://example.invalid/a?'),
    ('HTTP://EXAMPLE.invalid/a?X=1', 'HTTP://example.invalid/a?X=1'),
    ('https://EXAMPLE.invalid/\ue000', 'https://example.invalid/\ue000'),
])
def test_scope_allows_any_host_and_port_without_fetching(url, expected):
    assert normalize_url(url) == expected


@pytest.mark.parametrize('url', [None, '', 2, {}, [], 'file:///x', '/relative', 'https:///path',
    'javascript:alert(1)', 'https://user@example.invalid', 'https://user:pass@example.invalid',
    'https://example.invalid/a\n', 'https://example.invalid/a b', 'https://example.invalid:bad/a',
    'https://[no-ip]/', 'https://example.invalid:65536/', 'https://example.invalid\\attacker.invalid/x',
    'https://example.invalid/\ud800', 'https://example.invalid/'+'a'*2049])
def test_minimal_url_shape_rejects_unsafe_inputs_without_echo(url):
    with pytest.raises(ProtocolError) as error:
        normalize_url(url)
    assert error.value.code == 'INVALID_PUBLIC_URL'
    assert set(error.value.detail) == {'code', 'message'}
    assert 'example.invalid' not in str(error.value)


@pytest.mark.parametrize('raw', [b'{"x":1,"x":2}', b'{"x":{"a":1,"a":2}}', b'{"x":NaN}',
    b'{"x":Infinity}', b'{"x":-Infinity}', b'[]', b'null', b'\xef\xbb\xbf{}', b'\xff',
    b'{"x":"\\ud800"}', b'{"x":', b'{"x":'+b'['*2000+b'0'+b']'*2000+b'}'], ids=lambda _: 'malformed-json')
def test_json_duplicate_keys_invalid_utf8_constants_and_recursion(raw):
    with pytest.raises(ProtocolError):
        strict_json(raw)


def test_event_size_limit_is_bytes():
    with pytest.raises(ProtocolError) as error:
        strict_json(b' ' * (EVENT_BYTES+1))
    assert error.value.status == 413


@pytest.mark.parametrize('key,value', [
    ('schema', True), ('schema', 1), ('reviewed', False), ('reviewed', 1),
    ('eventId', ID.upper()), ('eventId', 'not-a-uuid'), ('attemptId', None),
    ('occurredAt', '2026-10-19T11:00:00Z'), ('occurredAt', '2026-13-19T11:00:00.000Z'),
    ('platform', ''), ('platform', '\u200b\n'), ('platform', 'x'*61), ('platform', {}),
    ('title', '😀'*301), ('title', {}), ('reportedAccount', '😀'*61),
    ('result', 'succeeded'), ('result', {}), ('reasonCode', 'arbitrary stack'), ('reasonCode', {}),
])
def test_strict_event_types_and_limits(key, value):
    # Numeric-only UUIDs cannot be uppercased; use an explicit uppercase hex case.
    if key == 'eventId' and value == ID:
        value = 'AAAAAAAA-1111-4111-8111-111111111111'
    with pytest.raises(ProtocolError):
        validate_event(event(**{key: value}), now=NOW)


@pytest.mark.parametrize('key', EVENT_KEYS)
def test_each_event_field_is_required(key):
    value = event()
    del value[key]
    with pytest.raises(ProtocolError):
        validate_event(value, now=NOW)


@pytest.mark.parametrize('key', ['tenant', 'tenantId', 'module', 'scopeId', 'taskId', 'grantId', 'accountId', 'ownerUserId', 'payload'])
def test_device_cannot_smuggle_business_selectors(key):
    with pytest.raises(ProtocolError):
        validate_event(event(**{key: 1}), now=NOW)


@pytest.mark.parametrize('result', ['failed', 'risk_control', 'verification_required', 'pending_review', 'unknown'])
def test_non_success_can_have_no_title_account_or_link(result):
    value = event(result=result, title=None, reportedAccount=None, publicUrl=None)
    assert validate_event(value, now=NOW)['canonical_url'] is None


def test_success_requires_link_and_never_rewrites_original_fields():
    with pytest.raises(ProtocolError) as error:
        validate_event(event(publicUrl=None), now=NOW)
    assert error.value.code == 'INVALID_PUBLIC_URL'
    value = event(platform='新\u200b平台', title='a\nb', reportedAccount='x\x00y')
    before = deepcopy(value)
    parsed = validate_event(value, now=NOW)
    assert parsed['platform'] == '新平台' and parsed['title'] == 'ab' and parsed['reported_account'] == 'xy'
    assert value == before


def test_future_boundary_and_offline_history():
    validate_event(event(occurredAt='2000-01-01T00:00:00.000Z'), now=NOW)
    validate_event(event(occurredAt='2026-10-20T12:00:00.000Z'), now=NOW)
    with pytest.raises(ProtocolError) as error:
        validate_event(event(occurredAt='2026-10-20T12:00:00.001Z'), now=NOW)
    assert error.value.code == 'CLOCK_SKEW'


def test_digest_is_original_case_and_metadata_sensitive():
    original = event()
    for key, value in [('publicUrl', normalize_url(original['publicUrl'])), ('platform', 'other'), ('title', 'changed')]:
        modified = {**original, key: value}
        with pytest.raises(ProtocolError) as error:
            validate_event(modified, now=NOW)
        assert error.value.code == 'PAYLOAD_DIGEST_INVALID'


def test_pairing_claim_and_ack_shape():
    assert validate_pairing({}) is None
    assert validate_pairing({'label': ''}) == ''
    assert validate_claim({'pairingCode': 'DHT2-'+'a'*32, 'requestId': ID})
    assert validate_ack_query({'schema': 2, 'eventId': ID, 'payloadDigest': 'a'*64})
    for code in ['DHT2:'+'a'*32, 'a'*32, 'DHT2-'+'a'*31]:
        with pytest.raises(ProtocolError): validate_claim({'pairingCode': code, 'requestId': ID})
    with pytest.raises(ProtocolError): validate_pairing({'tenantId': 1})
    with pytest.raises(ProtocolError): validate_ack_query({'schema': True, 'eventId': ID, 'payloadDigest': 'a'*64})


@pytest.mark.parametrize('value', [True, -1, 1.0, None, '1'])
def test_revision_is_strict(value):
    with pytest.raises(ProtocolError): validate_revision(value)


def test_label_shape_and_optional_reference_consistency():
    base = {'expectedRevision': 0, 'targetTenant': 1}
    assert validate_label(base) == base
    assert validate_label({**base, 'scopeId': 2, 'articleId': 3, 'articleVersion': 1, 'articleDigest': 'a'*64})
    for change in [{'module': 'geo'}, {'ownerUserId': 3}, {'articleId': 2}, {'articleVersion': 1},
                   {'articleDigest': 'a'*64}, {'scopeId': True}, {'targetTenant': True}, {'publishedAccount': 'x'*61}]:
        with pytest.raises(ProtocolError): validate_label({**base, **change})


IDENTITY_ROUTES = [('POST','/pairings'), ('POST',f'/pairings/{ID}/cancel'),
    ('GET','/receipts'), ('GET','/receipts/count'), ('GET',f'/receipts/{ID}'), ('GET','/devices'),
    ('POST',f'/devices/{ID}/revoke'), ('POST',f'/receipts/{ID}/archive'), ('POST',f'/receipts/{ID}/delete')]


@pytest.mark.parametrize('method,suffix', IDENTITY_ROUTES)
def test_identity_match_is_exact(method, suffix):
    assert match_inbox_identity_route(method, PREFIX+suffix)
    for path in [PREFIX+suffix+'/', PREFIX+suffix+'/extra', PREFIX+suffix+'?tenant_id=1',
                 PREFIX+suffix.replace(ID, '%31'+ID[1:]) if ID in suffix else PREFIX+suffix+'%2f']:
        assert not match_inbox_identity_route(method, path)
    assert not match_inbox_identity_route('DELETE', PREFIX+suffix)


@pytest.mark.parametrize('suffix', ['/device/results','/device/ack','/device-pairings/claim', '/pairings/not-uuid/cancel'])
def test_device_or_malformed_paths_do_not_gain_identity_bypass(suffix):
    assert not match_inbox_identity_route('POST', PREFIX+suffix)


def test_business_match_and_audit_redaction_are_separate():
    path = f'/api/v1/seo/distribution/v2/receipts/{ID}/label'
    assert match_inbox_business_route('POST', path)
    assert not match_inbox_identity_route('POST', path)
    assert audit_endpoint('POST', path).endswith('/{uuid}/label')
    assert audit_endpoint('GET', PREFIX+'/receipts/unknown') == '/api/v1/distribution/v2/{unmatched}'
    assert audit_endpoint('GET', '/api/v1/seo/content') == '/api/v1/seo/content'
