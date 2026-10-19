"""GEO-local distribution v1 wire rules. No shared SEO runtime dependency."""
import hashlib
import json
import re
import unicodedata

from fastapi import HTTPException

PREFIX = '/api/v1/geo/distribution/v1'
KEY = 'distribution_report_v1'
MAX_EVENTS = 64
MAX_TASKS = 1000
MAX_BYTES = 8 * 1024 * 1024
MAX_REQUEST = 256 * 1024
WINDOW_MS = 300_000
OBSERVATIONS = {
    **dict.fromkeys(['LOGIN_REQUIRED', 'CAPTCHA', 'RISK_CONTROL', 'PAGE_UNVERIFIED',
                     'OFFLINE', 'PLATFORM_REVIEW_PENDING'], 'awaiting-human'),
    **dict.fromkeys(['UPLOAD_RESULT_UNKNOWN', 'SUBMISSION_RESULT_UNKNOWN'], 'unknown'),
    **dict.fromkeys(['PLATFORM_PUBLISH_FAILED', 'HUMAN_FAILED'], 'failed'),
}
# The frozen v1 codes are intentionally separate from the observation extension.
RECEIPTS = {
    'ACCEPTED': 'queued', 'DISPATCHED': 'running', 'HUMAN_REQUIRED': 'awaiting-human',
    'LOGIN_REQUIRED': 'awaiting-human', 'CAPTCHA': 'awaiting-human',
    'HUMAN_PUBLISHED': 'succeeded', 'HUMAN_FAILED': 'failed',
    'HUMAN_UNKNOWN': 'unknown', 'EXECUTION_RESULT_UNKNOWN': 'unknown',
    'CRASH_RESULT_UNKNOWN': 'unknown', 'AUTHORIZATION_CHANGED': 'canceled',
    'AUTHORIZATION_OR_LEASE_INVALID': 'canceled',
    **dict.fromkeys(['ASSET_REQUIRED', 'ASSET_UNAVAILABLE', 'ASSET_CHANGED', 'INVALID_ASSET'], 'failed'),
}
TARGET = ('customerId', 'projectId', 'accountId', 'platform', 'contentVersion', 'contentDigest', 'leaseId')
EVENT = {'sequence', 'taskId', 'leaseId', 'customerId', 'projectId', 'accountId', 'platform',
         'contentVersion', 'contentDigest', 'status', 'code', 'at', 'evidence', 'publicUrl'}


def fail(code, status=409):
    raise HTTPException(status, {'code': code, 'message': '多号通回传请求未获准，请刷新并核对授权与稿件'},
                        headers={'Cache-Control': 'private, no-store', **({'Retry-After': '60'} if status == 429 else {})})


def exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        fail('INVALID_SHAPE', 422)
    return value


def integer(value, minimum=1):
    if type(value) is not int or not minimum <= value <= 9007199254740991:
        fail('INVALID_SHAPE', 422)
    return value


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        fail('INVALID_SHAPE', 422)
    return value


def encode(value):
    # JSON.stringify emits UTF-8 without whitespace or ASCII escapes. Assets in
    # this phase are empty; a missing controlled asset path must never drop images.
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def content_digest(content):
    return digest([content['version'], content['title'], content['body'],
                   [[a['id'], a['sha256'], a['mediaType'], a['bytes']] for a in content['assets']]])


def registry(settings):
    value = settings.get(KEY) if isinstance(settings, dict) else None
    if value is None:
        return {'schema': 1, 'revision': 0, 'enabled': False, 'scopes': {},
                'pairings': {}, 'devices': {}, 'tasks': {}, 'audit': []}
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
            or type(value.get('enabled')) is not bool or type(value.get('revision')) is not int
            or any(not isinstance(value.get(k), dict) for k in ('scopes', 'pairings', 'devices', 'tasks'))
            or not isinstance(value.get('audit'), list)):
        fail('REPORT_SCHEMA_UNAVAILABLE', 503)
    return json.loads(encode(value))


def enabled(book, scope):
    value = book['scopes'].get(str(scope))
    return (book['enabled'] is True and isinstance(value, dict)
            and value.get('enabled') is True and type(value.get('revision')) is int)


def public_url(value):
    # Accept the exact public short URL only. Never strip a query to guess a URL.
    if not isinstance(value, str) or not re.fullmatch(r'https://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]{1,256}', value):
        fail('INVALID_PUBLIC_URL', 422)
    return value


def reported_account(event, stream='receipt'):
    if 'reportedAccount' not in event:
        return None
    if stream != 'receipt' or event.get('code') != 'HUMAN_PUBLISHED' or event.get('status') != 'succeeded':
        fail('REPORTED_ACCOUNT_NOT_ALLOWED', 422)
    value = event['reportedAccount']
    if not isinstance(value, dict) or set(value) != {'name'} or not isinstance(value['name'], str):
        fail('INVALID_REPORTED_ACCOUNT', 422)
    name = ' '.join(''.join(c for c in value['name'] if not unicodedata.category(c).startswith('C')).split())
    if not 1 <= len(name) <= 60:
        fail('INVALID_REPORTED_ACCOUNT', 422)
    return {'name': name}


def validate_event(event, task, device_id, stream):
    observation = stream == 'observation'
    event_id = 'observationId' if observation else 'receiptId'
    reported_account(event, stream)
    exact(event, EVENT | {event_id} | (set() if observation else {'contractVersion', 'deviceId'})
          | ({'reportedAccount'} if 'reportedAccount' in event else set()))
    ident(event[event_id]); integer(event['sequence']); integer(event['at'])
    if not observation and (type(event['contractVersion']) is not int or event['contractVersion'] != 1
                            or event['deviceId'] != device_id):
        fail('INVALID_SHAPE', 422)
    if event['taskId'] != task['wire']['id'] or any(event[k] != task['target'][k] for k in TARGET):
        fail('SCOPE_FORBIDDEN', 403)
    statuses = OBSERVATIONS if observation else RECEIPTS
    if (not isinstance(event['code'], str) or event['code'] not in statuses
            or event['status'] != statuses[event['code']]):
        fail('INVALID_STATE', 422)
    if event['code'] == 'HUMAN_PUBLISHED':
        if event['evidence'] != 'human-reported':
            fail('INVALID_STATE', 422)
        public_url(event['publicUrl'])
    elif event['publicUrl'] is not None or event['evidence'] not in {'none', 'human-reported'}:
        fail('INVALID_STATE', 422)
    keys = (event_id, 'sequence', 'taskId', 'leaseId', 'status', *(['code'] if observation else []), 'at')
    return {k: event[k] for k in keys}


def admit_event(book, task, event, stream, ack):
    """Called under the module row lock, after fresh authorization, never before."""
    event_id = event['observationId' if stream == 'observation' else 'receiptId']
    fingerprint = digest(event)
    # IDs are unique across tasks and streams within this module/tenant.
    for other in book['tasks'].values():
        for name in ('receipt', 'observation'):
            old = other['events'][name].get(event_id)
            if old:
                if other is not task or name != stream or old['digest'] != fingerprint:
                    fail('IDEMPOTENCY_CONFLICT')
                return old['ack'], False
    entries = task['events'][stream]
    if event['sequence'] <= task['sequence'][stream]:
        fail('SEQUENCE_STALE')
    if len(entries) >= MAX_EVENTS:
        fail('REPORT_LEDGER_CAPACITY', 429)
    if task['outcome'] in {'succeeded', 'canceled', 'failed'} and stream == 'receipt':
        fail('INVALID_STATE', 422)
    if task['outcome'] == 'unknown' and stream == 'receipt' and event['code'] not in {'HUMAN_PUBLISHED', 'HUMAN_FAILED'}:
        fail('INVALID_STATE', 422)
    if (stream == 'receipt' and task['outcome'] in {'running', 'awaiting-human'}
            and event['status'] == 'queued'):
        fail('INVALID_STATE', 422)
    entries[event_id] = {'digest': fingerprint, 'ack': ack}
    account = reported_account(event, stream)
    if account is not None:
        entries[event_id]['reportedAccount'] = account
    task['sequence'][stream] = event['sequence']
    if task['outcome'] not in {'succeeded', 'canceled', 'failed'}:
        task['outcome'] = event['status']
        task['last_code'] = event['code']
    return ack, True
