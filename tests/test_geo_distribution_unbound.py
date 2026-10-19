"""Unbound pairing and optional, display-only reported account contract."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.geo.content import distribution_protocol as p, distribution_report as s


VECTORS = json.loads((Path(__file__).parent / 'fixtures' / 'geo_distribution_report_b_vectors.json').read_text(encoding='utf-8'))['vectors']


@pytest.mark.parametrize('vector', VECTORS, ids=lambda v: v['id'])
def test_shared_original_event_digest_normalization_and_validation(vector):
    event = copy.deepcopy(vector['event'])
    assert p.encode(event).decode() == vector['input']
    assert p.encode(event).hex() == vector['utf8Hex']
    assert p.digest(event) == vector['sha256']
    task = {'wire': {'id': event['taskId']}, 'target': {k: event[k] for k in p.TARGET}}
    if vector['valid']:
        ack = p.validate_event(event, task, event['deviceId'], 'receipt')
        assert set(ack) == {'receiptId', 'sequence', 'taskId', 'leaseId', 'status', 'at'}
        account = p.reported_account(event)
        assert (account['name'] if account else None) == vector['normalizedName']
    else:
        with pytest.raises(HTTPException) as denied:
            p.validate_event(event, task, event['deviceId'], 'receipt')
        assert denied.value.status_code == 422
        assert denied.value.detail['code'] == vector['error']
    assert event == vector['event']


def test_replay_hash_binds_original_name_even_when_normalized_names_match():
    event = copy.deepcopy(next(v['event'] for v in VECTORS if v['id'] == 'simple'))
    task = {'wire': {'id': event['taskId']}, 'target': {k: event[k] for k in p.TARGET},
        'events': {'receipt': {}, 'observation': {}}, 'sequence': {'receipt': 0, 'observation': 0}, 'outcome': 'queued'}
    book = {'tasks': {'one': task}}
    ack = p.validate_event(event, task, event['deviceId'], 'receipt')
    assert p.admit_event(book, task, event, 'receipt', ack) == (ack, True)
    assert p.admit_event(book, task, event, 'receipt', ack) == (ack, False)
    assert task['events']['receipt'][event['receiptId']]['reportedAccount'] == {'name': '合成公众号'}
    for value in [{'name': ' 合成公众号 '}, {'name': '另一个合成号'}, None]:
        changed = copy.deepcopy(event)
        if value is None:
            changed.pop('reportedAccount')
        else:
            changed['reportedAccount'] = value
        with pytest.raises(HTTPException) as denied:
            p.admit_event(book, task, changed, 'receipt', ack)
        assert denied.value.detail['code'] == 'IDEMPOTENCY_CONFLICT'


def test_observations_reject_reported_account_even_with_valid_name():
    event = {'code': 'HUMAN_FAILED', 'status': 'failed', 'reportedAccount': {'name': '合成号'}}
    with pytest.raises(HTTPException) as denied:
        p.reported_account(event, 'observation')
    assert denied.value.detail['code'] == 'REPORTED_ACCOUNT_NOT_ALLOWED'


def test_reported_account_is_only_added_to_management_projection_not_device_verification():
    async def run():
        task = {'wire': {'id': 'task', 'leaseId': 'lease'}, 'target': {'contentVersion': 'v1', 'contentDigest': 'a'*64},
            'native_task_id': 1, 'variant_id': 2, 'article_id': 3, 'outcome': 'queued', 'last_code': 'QUEUED',
            'events': {'receipt': {}, 'observation': {}}, 'publication_id': None, 'reportedAccount': {'name': '合成公众号'}}
        legacy = await s.verification(fixture(), task)
        management = await s.verification(fixture(), task, management=True)
        assert 'reportedAccount' not in legacy
        assert management == {**legacy, 'reportedAccount': {'name': '合成公众号'}}
    asyncio.run(run())


def fixture():
    return s.Store(NS(flush=AsyncMock(), scalar=AsyncMock(), add=lambda _: None), 7,
        NS(module_settings={}), p.registry({}))


@pytest.mark.parametrize('account', ['missing', None])
def test_unbound_pairing_requires_current_authority_and_keeps_legacy_shape(account):
    async def run():
        store = fixture()
        body = {'label': '合成电脑', 'platform': 'wechat-article', 'expected_revision': 0}
        if account != 'missing': body['account_id'] = account
        with patch.object(s, 'actor_authorized', AsyncMock()) as auth, \
             patch.object(s, 'placeholder_account', AsyncMock(return_value=21)) as placeholder:
            result = await s.create_pairing(store, 5, {'user_id': 9}, body)
            auth.assert_awaited_once()
            placeholder.assert_awaited_once()
        assert set(result) == {'schema', 'pairing_id', 'pairing_code', 'expires_at'}
        assert store.book['pairings'][result['pairing_id']]['account_id'] == 21
        assert not store.book['enabled'] and store.book['scopes'] == {}
        store = fixture()
        with patch.object(s, 'actor_authorized', AsyncMock(side_effect=HTTPException(403))) as auth, \
             patch.object(s, 'placeholder_account', AsyncMock()) as placeholder:
            with pytest.raises(HTTPException): await s.create_pairing(store, 5, {'user_id': 9}, body)
            placeholder.assert_not_awaited()
        assert not store.book['pairings']
    asyncio.run(run())


def test_legacy_selected_account_does_not_create_placeholder():
    async def run():
        store = fixture()
        with patch.object(s, 'account_binding', AsyncMock()) as binding, \
             patch.object(s, 'placeholder_account', AsyncMock()) as placeholder:
            await s.create_pairing(store, 5, {'user_id': 9},
                {'label': '合成电脑', 'platform': 'wechat-article', 'account_id': '12', 'expected_revision': 0})
            binding.assert_awaited_once_with(store, 12)
            placeholder.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['foreign', 'disabled', 'inactive'])
def test_never_adopt_user_channel_or_reenable_disabled_placeholder(kind):
    async def run():
        store = fixture()
        channel = NS(id=3, channel_type='wechat', enabled=kind != 'disabled',
                     content_rules={} if kind == 'foreign' else {'duohaotong_placeholder': 1})
        store.session.scalar.side_effect = [channel, NS(id=4, auth_type='manual', status='disabled')]
        with pytest.raises(HTTPException) as denied:
            await s.placeholder_account(store, 5, {'user_id': 9})
        assert denied.value.detail['code'] == ('PLACEHOLDER_CONFLICT' if kind == 'foreign' else 'PLACEHOLDER_DISABLED')
        assert store.book['audit'] == []
    asyncio.run(run())
