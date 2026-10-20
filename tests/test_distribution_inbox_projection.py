from copy import deepcopy
import json

import pytest

from app.distribution_inbox_projection import personal_receipt, publication_receipt
from app.distribution_inbox_protocol import ProtocolError


@pytest.fixture
def receipt():
    return {
        'id': 'synthetic-receipt', 'revision': 3, 'state': 'active', 'label_state': 'active',
        'owner_user_id': 7, 'device_id': 'private-device', 'event_id': 'private-event',
        'attempt_id': 'private-attempt', 'platform': '新平台', 'title': '合成标题',
        'public_url': 'https://example.invalid/article', 'reported_account': '合成上报账号',
        'result': 'success', 'reason_code': None, 'occurred_at': '2026-10-19T11:00:00.000Z',
        'received_at': '2026-10-19T11:01:00.000Z', 'tenant_id': 42, 'module': 'seo',
        'scope_id': 2, 'article_id': 100, 'article_version': 1, 'published_account': '合成标注账号',
        'verification_status': 'verified', 'verification_attachment': 'private-evidence',
        'payload': {'credential': 'synthetic-never-return'},
        'history': [{'action': 'label', 'at': '2026-10-19T11:02:00.000Z', 'tenant_id': 999,
                     'tenant_name': 'private-old-target', 'actor': 8, 'article_id': 999, 'url': 'private-old-url'}],
    }


def test_lost_target_owner_sees_only_own_original_not_assignment_history_or_evidence(receipt):
    before = deepcopy(receipt)
    result = personal_receipt(receipt, actor_id=7)
    assert result['assignment'] == {'hidden': True}
    assert result['reportedAccount'] == '合成上报账号'
    assert result['verificationStatus'] == 'unavailable'
    encoded = json.dumps(result)
    for forbidden in ['private-device', 'private-event', 'private-evidence', 'private-old', 'synthetic-never-return', 'tenantId', 'articleId']:
        assert forbidden not in encoded
    assert result['history'] == [{'action': 'assignment_changed', 'at': '2026-10-19T11:02:00.000Z'}]
    assert receipt == before


def test_owner_with_target_permission_gets_only_current_target_and_no_verified_claim(receipt):
    result = personal_receipt(receipt, actor_id=7, target_visible=True)
    assert result['assignment']['tenantId'] == 42
    assert result['assignment']['publishedAccount'] == '合成标注账号'
    assert result['verificationStatus'] == 'unavailable'
    assert '999' not in json.dumps(result)


def test_unlabeled_rows_are_owner_or_personnel_admin_only(receipt):
    receipt.update(label_state='pending', state='pending')
    assert personal_receipt(receipt, actor_id=7)['assignment'] is None
    with pytest.raises(ProtocolError) as error:
        personal_receipt(receipt, actor_id=8, target_visible=True)
    assert error.value.status == 404
    assert personal_receipt(receipt, actor_id=9, inbox_admin=True)['id'] == receipt['id']
    with pytest.raises(ProtocolError): personal_receipt(receipt, actor_id=None, inbox_admin=True)
    with pytest.raises(ProtocolError): personal_receipt(receipt, actor_id=True, inbox_admin=True)


def test_scope_readers_do_not_receive_owner_device_event_attempt_or_history(receipt):
    result = publication_receipt(receipt, actor_id=8, expected_tenant=42, expected_module='seo', target_visible=True)
    assert result['source'] == 'external_report'
    assert result['publishedAccount'] == '合成标注账号'
    assert result['verificationStatus'] == 'unavailable'
    assert not {'owner_user_id', 'device_id', 'event_id', 'attemptId', 'history', 'payload', 'reportedAccount'} & result.keys()
    assert 'private-' not in json.dumps(result)


@pytest.mark.parametrize('change', [{'target_visible': False}, {'expected_tenant': 43}, {'expected_module': 'geo'},
                                  {'expected_tenant': True}, {'actor_id': None}])
def test_business_target_scope_always_explicit(receipt, change):
    args = dict(actor_id=8, expected_tenant=42, expected_module='seo', target_visible=True)
    with pytest.raises(ProtocolError) as error:
        publication_receipt(receipt, **{**args, **change})
    assert error.value.code == 'RECEIPT_NOT_FOUND'


def test_scope_pending_is_not_shared_with_other_advisors_even_with_customer_rights(receipt):
    receipt['scope_id'] = None
    with pytest.raises(ProtocolError):
        publication_receipt(receipt, actor_id=8, expected_tenant=42, expected_module='seo', target_visible=True)
    assert publication_receipt(receipt, actor_id=7, expected_tenant=42, expected_module='seo', target_visible=True)
    assert publication_receipt(receipt, actor_id=9, expected_tenant=42, expected_module='seo', target_visible=True, inbox_admin=True)


@pytest.mark.parametrize('state,label', [('deleted','active'), ('pending','pending'), ('pending','revoked')])
def test_tombstone_and_unlabel_remove_publication_projection(receipt, state, label):
    receipt.update(state=state, label_state=label)
    with pytest.raises(ProtocolError):
        publication_receipt(receipt, actor_id=7, expected_tenant=42, expected_module='seo', target_visible=True)
    if state == 'deleted':
        with pytest.raises(ProtocolError): personal_receipt(receipt, actor_id=7, inbox_admin=True)


def test_unlinked_record_never_claims_verified_body(receipt):
    receipt.update(article_id=None, article_version=None, published_account=None)
    result = publication_receipt(receipt, actor_id=7, expected_tenant=42, expected_module='seo', target_visible=True)
    assert result['verificationStatus'] == 'unlinked'
    assert result['publishedAccount'] == '合成上报账号'
