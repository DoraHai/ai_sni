"""Frozen distribution v1 wire rules; no credentials, storage or network here."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import unicodedata

from fastapi import HTTPException

PREFIX = '/api/v1/seo/distribution/v1'
KEY = 'distribution_report_v1'
MAX_SAFE_INTEGER = 2**53 - 1
TARGET = ('customerId', 'projectId', 'deviceId', 'accountId', 'platform')
OBSERVATIONS = {
    **dict.fromkeys(('LOGIN_REQUIRED', 'CAPTCHA', 'RISK_CONTROL', 'PAGE_UNVERIFIED',
                     'OFFLINE', 'PLATFORM_REVIEW_PENDING'), 'awaiting-human'),
    **dict.fromkeys(('UPLOAD_RESULT_UNKNOWN', 'SUBMISSION_RESULT_UNKNOWN'), 'unknown'),
    **dict.fromkeys(('PLATFORM_PUBLISH_FAILED', 'HUMAN_FAILED'), 'failed'),
}
RECEIPTS = {
    'ACCEPTED': 'queued', 'DISPATCHED': 'running', 'PREFLIGHT_OK': 'succeeded',
    **dict.fromkeys(('HUMAN_REQUIRED', 'LOGIN_REQUIRED', 'CAPTCHA', 'ASSET_REQUIRED',
                     'ASSET_UNAVAILABLE', 'ASSET_CHANGED', 'INVALID_ASSET'), 'awaiting-human'),
    **dict.fromkeys(('EXECUTION_RESULT_UNKNOWN', 'AUTHORIZATION_CHANGED',
                     'AUTHORIZATION_OR_LEASE_INVALID', 'CRASH_RESULT_UNKNOWN', 'HUMAN_UNKNOWN'), 'unknown'),
    'HUMAN_PUBLISHED': 'succeeded', 'HUMAN_FAILED': 'failed',
}
EVENT_FIELDS = {'sequence', 'taskId', 'leaseId', 'customerId', 'projectId', 'accountId',
                'platform', 'contentVersion', 'contentDigest', 'status', 'code', 'at', 'evidence', 'publicUrl'}


def deny(code, status=409):
    # One fixed message: never render arbitrary input, SQL errors or validators.
    raise HTTPException(status, {'code': code, 'message': '结果回传未获受理，请核对授权和当前任务后重试'})


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def content_digest(content):
    # Byte-compatible with JS JSON.stringify, for the protocol's integer assets.
    return digest([content['version'], content['title'], content['body'], [
        [a['id'], a['sha256'], a['mediaType'], a['bytes']] for a in content['assets']]])


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value) is not None


def positive(value):
    return type(value) is int and 0 < value <= MAX_SAFE_INTEGER


def shape(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        deny('INVALID_SHAPE', 422)


def public_url(value):
    if not isinstance(value, str) or not re.fullmatch(r'https://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]{1,200}', value):
        deny('INVALID_PUBLIC_URL', 422)
    return value


def registry(settings, *, initialize=False):
    state = settings.get(KEY) if type(settings) is dict else None
    if state is None and initialize:
        return {'schema': 1, 'revision': 0, 'enabled': False, 'scopes': {},
                'pairings': {}, 'devices': {}, 'tasks': {}, 'events': {}, 'audit': []}
    if (type(state) is not dict or type(state.get('schema')) is not int or state['schema'] != 1
            or type(state.get('revision')) is not int or type(state.get('enabled')) is not bool
            or any(type(state.get(k)) is not dict for k in ('scopes', 'pairings', 'devices', 'tasks', 'events'))
            or type(state.get('audit')) is not list):
        deny('REPORT_SCHEMA_UNAVAILABLE', 503)
    return deepcopy(state)


def enabled(state, scope):
    config = state.get('scopes', {}).get(str(scope))
    return (state.get('enabled') is True and type(config) is dict
            and config.get('enabled') is True and type(config.get('revision')) is int)


def validate_event(event, stream):
    id_key = 'receiptId' if stream == 'receipt' else 'observationId'
    fields = EVENT_FIELDS | {id_key} | ({'contractVersion', 'deviceId'} if stream == 'receipt' else set())
    has_account = type(event) is dict and 'reportedAccount' in event
    shape(event, fields | ({'reportedAccount'} if has_account else set()))
    if has_account:
        if stream != 'receipt' or event.get('code') != 'HUMAN_PUBLISHED' or event.get('status') != 'succeeded':
            deny('REPORTED_ACCOUNT_NOT_ALLOWED', 422)
        reported_account(event['reportedAccount'])
    for key in (id_key, 'taskId', 'leaseId', 'customerId', 'projectId', 'accountId', 'contentVersion'):
        if not identifier(event[key]):
            deny('INVALID_SHAPE', 422)
    if stream == 'receipt' and (event['contractVersion'] != 1 or type(event['contractVersion']) is not int
                                or not identifier(event['deviceId'])):
        deny('INVALID_SHAPE', 422)
    if not positive(event['sequence']) or not positive(event['at']) or not 946684800000 <= event['at'] <= 4102444800000:
        deny('INVALID_SHAPE', 422)
    if event['platform'] != 'wechat-article' or not isinstance(event['contentDigest'], str) or not re.fullmatch('[a-f0-9]{64}', event['contentDigest']):
        deny('INVALID_SHAPE', 422)
    mapping = RECEIPTS if stream == 'receipt' else OBSERVATIONS
    code = event['code']
    if not isinstance(code, str) or code not in mapping or event['status'] != mapping[code]:
        deny('INVALID_STATE', 422)
    if code == 'HUMAN_PUBLISHED':
        if event['evidence'] != 'human-reported':
            deny('INVALID_STATE', 422)
        public_url(event['publicUrl'])
    elif event['publicUrl'] is not None or event['evidence'] not in {'none', 'human-reported'}:
        deny('INVALID_STATE', 422)
    return id_key


def reported_account(value):
    """Clean display metadata without mutating the event used for replay hashes."""
    if type(value) is not dict or set(value) != {'name'} or not isinstance(value['name'], str):
        deny('INVALID_REPORTED_ACCOUNT', 422)
    name = re.sub(r'\s+', ' ', ''.join(c for c in value['name']
        if not unicodedata.category(c).startswith('C'))).strip()
    if not 1 <= len(name) <= 60:
        deny('INVALID_REPORTED_ACCOUNT', 422)
    return {'name': name}


def admit_event(state, task, event, stream):
    """Pure ledger admission under module row lock. Unknown old events fail shut."""
    id_key = validate_event(event, stream)
    task_id = task['wire']['id']
    wire = task['wire']
    target = task['target']
    if any(event[k] != target[k] for k in TARGET if k in event):
        deny('SCOPE_FORBIDDEN', 403)
    if (event['taskId'] != task_id or event['leaseId'] != wire['leaseId']
            or event['contentVersion'] != task['content_version'] or event['contentDigest'] != task['content_digest']):
        deny('SOURCE_CHANGED')
    event_hash = digest(event)
    event_id = event[id_key]
    prior = state['events'].get(event_id)
    if prior is not None:
        if prior != {'hash': event_hash, 'task': task_id, 'stream': stream}:
            deny('IDEMPOTENCY_CONFLICT')
        return task['streams'][stream]['events'][str(event['sequence'])]['ack'], False
    ledger = task['streams'][stream]
    sequence = event['sequence']
    if str(sequence) in ledger['events']:
        deny('IDEMPOTENCY_CONFLICT')
    if sequence <= ledger['high']:
        deny('SEQUENCE_STALE')
    if len(ledger['events']) >= 64:
        deny('REPORT_LEDGER_CAPACITY', 429)
    # Only terminal human publication/failed outcomes close the report attempt.
    # A later observation is retained without downgrading the successful fact.
    if stream == 'receipt' and task['outcome'] in {'human-reported-published', 'failed'}:
        deny('INVALID_STATE')
    if event['code'] in {'ACCEPTED', 'DISPATCHED'} and task['outcome'] != 'queued':
        deny('INVALID_STATE')
    ack_keys = [id_key, 'sequence', 'taskId', 'leaseId', 'status']
    if stream == 'observation':
        ack_keys.append('code')
    ack = {k: event[k] for k in ack_keys + ['at']}
    ledger['high'] = sequence
    ledger['events'][str(sequence)] = {'id': event_id, 'hash': event_hash, 'ack': ack,
        **({'reportedAccount': reported_account(event['reportedAccount'])} if 'reportedAccount' in event else {})}
    state['events'][event_id] = {'hash': event_hash, 'task': task_id, 'stream': stream}
    return ack, True
