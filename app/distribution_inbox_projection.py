"""Storage-independent field ACL, with no implicit target authorization.

Callers must perform fresh personnel/grant/module/scope checks before supplying
target_visible=True. These functions never accept a raw verification attachment
or return owner/device/event identifiers to a customer publication reader.
"""
from app.distribution_inbox_protocol import PLATFORMS, ProtocolError


def _not_found():
    raise ProtocolError('RECEIPT_NOT_FOUND', 404)


def _raw_fields(row):
    platform = row.get('platform')
    return {
        'platform': platform,
        'platformKind': platform if platform in PLATFORMS else 'other',
        'title': row.get('title'), 'publicUrl': row.get('public_url'),
        'reportedAccount': row.get('reported_account'),
        'result': row.get('result'), 'reasonCode': row.get('reason_code'),
        'occurredAt': row.get('occurred_at'), 'receivedAt': row.get('received_at'),
    }


def _assignment(row):
    return {
        'tenantId': row.get('tenant_id'), 'module': row.get('module'),
        'scopeId': row.get('scope_id'), 'articleId': row.get('article_id'),
        'articleVersion': row.get('article_version'),
        'articleDigest': row.get('article_digest'),
        'publishedAccount': row.get('published_account'),
    }


def personal_receipt(row, *, actor_id, inbox_admin=False, target_visible=False, own_duplicate=False):
    """Owner/admin only. Lost target rights never recover through raw ownership.

    A boolean authorization result is explicit and defaults to denial. History
    stays opaque even when the current target is visible: old targets can have
    different permissions. Name/actor resolution needs its own future adapter.
    """
    if (type(actor_id) is not int or actor_id < 1 or not row
            or row.get('state') == 'deleted'
            or (row.get('owner_user_id') != actor_id and inbox_admin is not True)):
        _not_found()
    active = row.get('label_state') == 'active'
    visible = target_visible is True
    assignment = _assignment(row) if active and visible else {'hidden': True} if active else None
    return {
        'id': row['id'], 'revision': row['revision'], 'state': row['state'],
        **_raw_fields(row), 'attemptId': row.get('attempt_id'),
        'duplicate': own_duplicate is True, 'assignment': assignment,
        'verificationStatus': ('unavailable' if row.get('article_id') else 'unlinked') if visible or not active else 'unavailable',
        'history': [{'action': 'assignment_changed', 'at': item.get('at')}
                    for item in row.get('history', []) if isinstance(item, dict)],
    }


def publication_receipt(row, *, actor_id, expected_tenant, expected_module, target_visible=False, inbox_admin=False):
    """External projection only; no native publication state or KPI mutation."""
    if (type(actor_id) is not int or actor_id < 1 or not row or row.get('state') == 'deleted'
            or row.get('label_state') != 'active' or target_visible is not True
            or type(expected_tenant) is not int or expected_tenant < 1
            or expected_module not in {'seo', 'geo'}
            or row.get('tenant_id') != expected_tenant or row.get('module') != expected_module
            or (row.get('scope_id') is None and row.get('owner_user_id') != actor_id and inbox_admin is not True)):
        _not_found()
    raw = _raw_fields(row)
    raw.pop('reportedAccount')
    return {
        'id': row['id'], 'revision': row['revision'], 'source': 'external_report',
        'sourceLabel': '外部回传', **raw,
        'publishedAccount': row.get('published_account') or row.get('reported_account'),
        'assignment': _assignment(row),
        # A row claiming verified is insufficient. No verification evidence
        # adapter is wired while the shared-storage/intent work is blocked.
        'verificationStatus': 'unavailable' if row.get('article_id') else 'unlinked',
    }
