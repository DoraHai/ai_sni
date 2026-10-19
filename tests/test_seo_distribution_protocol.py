from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.seo_distribution_protocol import (KEY, admit_event, content_digest, enabled,
    public_url, registry, validate_event, digest, reported_account)


def test_reported_account_cross_language_vectors_and_original_event_hash():
    vectors = json.loads((Path(__file__).parent / 'fixtures/distribution_report_vectors_b.json').read_text(encoding='utf-8'))
    for vector in vectors['vectors']:
        event = vector['event']
        before = deepcopy(event)
        assert digest(event) == vector['sha256']
        assert bytes.fromhex(vector['utf8Hex']).decode() == vector['input']
        if vector['valid']:
            validate_event(event, 'receipt')
            if 'reportedAccount' in event:
                assert reported_account(event['reportedAccount'])['name'] == vector['normalizedName']
        else:
            with pytest.raises(HTTPException) as exc:
                validate_event(event, 'receipt')
            assert exc.value.detail['code'] == vector['error']
        assert event == before


def test_reported_account_is_immutable_replay_metadata_and_ack_is_unchanged():
    state, task, event = synthetic()
    event['reportedAccount'] = {'name':'  合成\u200b公众号  '}
    ack, fresh = admit_event(state, task, event, 'receipt')
    assert fresh and len(ack) == 6
    assert task['streams']['receipt']['events']['3']['reportedAccount'] == {'name':'合成公众号'}
    assert admit_event(state, task, event, 'receipt') == (ack, False)
    for account in ({'name':'合成公众号'}, {'name':'另一合成号'}):
        with pytest.raises(HTTPException) as exc:
            admit_event(state, task, {**event, 'reportedAccount':account}, 'receipt')
        assert exc.value.detail['code'] == 'IDEMPOTENCY_CONFLICT'
    without = {k:v for k,v in event.items() if k != 'reportedAccount'}
    with pytest.raises(HTTPException) as exc:
        admit_event(state, task, without, 'receipt')
    assert exc.value.detail['code'] == 'IDEMPOTENCY_CONFLICT'


def test_observation_cannot_report_an_account():
    _, _, event = synthetic()
    event = {k:v for k,v in event.items() if k not in {'deviceId','contractVersion','receiptId'}}
    event.update(observationId='synthetic-observation', code='HUMAN_FAILED', status='failed',
        publicUrl=None, reportedAccount={'name':'合成号'})
    with pytest.raises(HTTPException) as exc:
        validate_event(event, 'observation')
    assert exc.value.detail['code'] == 'REPORTED_ACCOUNT_NOT_ALLOWED'


def synthetic():
    target = {'customerId': '101', 'projectId': 'seo-11', 'deviceId': 'synthetic-device',
              'accountId': 'synthetic-account', 'platform': 'wechat-article'}
    task = {'wire': {'id': 'synthetic-task', 'leaseId': 'synthetic-lease'}, 'target': target,
        'content_version': 'v2', 'content_digest': 'a' * 64, 'outcome': 'queued',
        'streams': {s: {'high': 0, 'events': {}} for s in ('receipt', 'observation')}}
    event = {**target, 'receiptId': 'synthetic-receipt', 'sequence': 3, 'contractVersion': 1,
        'taskId': 'synthetic-task', 'leaseId': 'synthetic-lease', 'contentVersion': 'v2',
        'contentDigest': 'a' * 64, 'status': 'succeeded', 'code': 'HUMAN_PUBLISHED',
        'at': 1792375200000, 'evidence': 'human-reported',
        'publicUrl': 'https://mp.weixin.qq.com/s/synthetic_article'}
    state = registry({}, initialize=True)
    return state, task, event


def test_cross_language_digest_vectors():
    vectors = json.loads((Path(__file__).parent / 'fixtures/distribution_report_vectors.json').read_text(encoding='utf-8'))
    for v in vectors['vectors']:
        assert content_digest(v['content']) == v['sha256']
        assert bytes.fromhex(v['utf8Hex']).decode('utf-8') == v['input']


@pytest.mark.parametrize('settings', [{}, None, {KEY: None}, {KEY: {'schema': 2}}, {KEY: {'enabled': 'true'}}])
def test_unknown_settings_never_enable(settings):
    try:
        result = registry(settings, initialize=True)
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        assert not enabled(result, 11)


def test_two_independent_switches_are_strict_booleans():
    state, _, _ = synthetic()
    state['scopes']['11'] = {'enabled': True, 'revision': 1}
    assert not enabled(state, 11)
    state['enabled'] = True
    assert enabled(state, 11) and not enabled(state, 12)
    state['scopes']['11']['enabled'] = 'true'
    assert not enabled(state, 11)


def test_exact_six_field_ack_and_duplicate_has_no_native_effect():
    state, task, event = synthetic()
    ack, fresh = admit_event(state, task, event, 'receipt')
    assert fresh
    assert set(ack) == {'receiptId', 'sequence', 'taskId', 'leaseId', 'status', 'at'}
    assert ack['at'] == event['at']
    assert admit_event(state, task, event, 'receipt') == (ack, False)
    changed = {**event, 'publicUrl': 'https://mp.weixin.qq.com/s/different_article'}
    with pytest.raises(HTTPException) as exc:
        admit_event(state, task, changed, 'receipt')
    assert exc.value.detail['code'] == 'IDEMPOTENCY_CONFLICT'


@pytest.mark.parametrize('key,value', [('customerId','202'), ('projectId','seo-12'),
    ('deviceId','different-device'), ('accountId','different-account'), ('contentDigest','b'*64),
    ('contentVersion','v3'), ('leaseId','another-lease'), ('taskId','another-task')])
def test_every_target_component_is_checked(key, value):
    state, task, event = synthetic()
    before = deepcopy(state)
    with pytest.raises(HTTPException):
        admit_event(state, task, {**event, key: value}, 'receipt')
    assert state == before


@pytest.mark.parametrize('url', ['http://mp.weixin.qq.com/s/test', 'https://mp.weixin.qq.com.evil.test/s/test',
    'https://user@mp.weixin.qq.com/s/test', 'https://127.0.0.1/s/test',
    'https://mp.weixin.qq.com:443/s/test', 'https://mp.weixin.qq.com/s?draft=1',
    'https://mp.weixin.qq.com/s/test?x=1', 'https://mp.weixin.qq.com/s/test#x',
    'https://mp.weixin.qq.com/cgi-bin/appmsg', 'https://mp.weixin.qq.com/s/%2e%2e'])
def test_only_public_short_article_urls_are_admitted(url):
    with pytest.raises(HTTPException): public_url(url)


@pytest.mark.parametrize('code,status', [('RISK_CONTROL','awaiting-human'), ('CAPTCHA','awaiting-human'),
    ('PLATFORM_REVIEW_PENDING','awaiting-human'), ('SUBMISSION_RESULT_UNKNOWN','unknown'),
    ('PLATFORM_PUBLISH_FAILED','failed')])
def test_observation_code_mapping_and_no_success_url(code, status):
    state, task, event = synthetic()
    event = {k: v for k, v in event.items() if k not in {'deviceId','contractVersion','receiptId'}}
    event.update(observationId='synthetic-observation', code=code, status=status, evidence='none', publicUrl=None)
    ack, fresh = admit_event(state, task, event, 'observation')
    assert fresh and len(ack) == 7 and ack['code'] == code
    for changes in ({'status':'succeeded'}, {'publicUrl':'https://mp.weixin.qq.com/s/test'}, {'evidence':'simulation'}):
        with pytest.raises(HTTPException): validate_event({**event, **changes}, 'observation')


def test_sequence_gaps_allowed_unknown_old_event_denied_and_conflicts_atomic():
    state, task, event = synthetic()
    admit_event(state, task, event, 'receipt')
    with pytest.raises(HTTPException) as exc:
        admit_event(state, task, {**event, 'receiptId':'old-unknown', 'sequence':2}, 'receipt')
    assert exc.value.detail['code'] == 'SEQUENCE_STALE'
    with pytest.raises(HTTPException) as exc:
        admit_event(state, task, {**event, 'receiptId':'another-id'}, 'receipt')
    assert exc.value.detail['code'] == 'IDEMPOTENCY_CONFLICT'
