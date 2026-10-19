"""Channel-independent v2 wire contract. No storage, network or v1 dependencies."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

PREFIX = '/api/v1/seo/distribution/v2/inbox'
UUID_PATTERN = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
PAIRING_PATTERN = r'DHT2-[A-Za-z0-9_-]{32}'
EVENT_KEYS = ('schema', 'eventId', 'attemptId', 'occurredAt', 'platform', 'title',
              'reportedAccount', 'result', 'reasonCode', 'publicUrl', 'reviewed')
RESULTS = frozenset({'success', 'failed', 'risk_control', 'verification_required',
                     'pending_review', 'unknown'})
REASONS = frozenset({'platform_rejected', 'network_error', 'risk_control',
                     'verification_required', 'pending_review', 'unknown'})
PLATFORMS = frozenset({'wechat', 'zhihu', 'toutiao', 'sohu', 'qq', 'xiaohongshu',
                       'weibo', 'kuaishou', 'douyin', 'other'})
EVENT_BYTES = 16 * 1024
UNLABELED_ROWS = 1000
UNLABELED_BYTES = 10 * 1024 * 1024
TOTAL_ROWS = 5000
TOTAL_BYTES = 50 * 1024 * 1024
MESSAGES = {
    'INVALID_SHAPE': '回传格式不正确，请核对后重试',
    'INVALID_PUBLIC_URL': '请填写有效的 http/https 公开链接',
    'CLOCK_SKEW': '电脑时间超前，请校准时间后重新确认',
    'PAYLOAD_DIGEST_INVALID': '回传摘要不一致，请保留本机结果',
    'DEVICE_CREDENTIAL_INVALID': '设备配对已失效，请重新配对',
    'INBOX_FORBIDDEN': '当前身份无权操作此记录',
    'RECEIPT_NOT_FOUND': '记录不存在或无权查看',
    'EVENT_NOT_FOUND': '记录不存在或无权查看',
    'PAIRING_CODE_UNAVAILABLE': '配对码不可用，请生成新码',
    'EVENT_DIGEST_CONFLICT': '同一事件内容不一致，请保留本机结果并核对',
    'REVISION_CONFLICT': '记录已更新，请刷新后重试',
    'CROSS_TARGET_REQUIRES_UNLABEL': '请先在原客户撤销标注，再选择新客户或模块',
    'DUPLICATE_LINK': '已有相同链接，请核对',
    'INBOX_CAPACITY_EXCEEDED': '待标记录已满，结果仍留在本机，请先标注或清理再重试',
    'RATE_LIMITED': '操作过于频繁或设备数量已满，请稍后重试',
    'DEVICE_LIMIT_REACHED': '操作过于频繁或设备数量已满，请稍后重试',
    'INBOX_SCHEMA_NOT_READY': '功能尚未准备好',
}


class ProtocolError(ValueError):
    """Fixed errors never contain input, URL, credentials or database details."""
    def __init__(self, code='INVALID_SHAPE', status=422):
        self.code, self.status = code, status
        super().__init__(MESSAGES[code])

    @property
    def detail(self):
        return {'code': self.code, 'message': MESSAGES[self.code]}


def fail(code='INVALID_SHAPE', status=422):
    raise ProtocolError(code, status)


def identifier(value):
    return isinstance(value, str) and re.fullmatch(UUID_PATTERN, value) is not None


def exact_object(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        fail()
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail()
        result[key] = value
    return result


def strict_json(raw: bytes):
    if len(raw) > EVENT_BYTES:
        fail(status=413)
    try:
        # Reject BOM and unpaired surrogates even when represented by JSON escapes.
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: fail())
        pending = [(value, 0)]
        while pending:
            node, depth = pending.pop()
            if depth > 32:
                fail()
            if isinstance(node, dict):
                pending.extend((child, depth+1) for child in node.values())
            elif isinstance(node, list):
                pending.extend((child, depth+1) for child in node)
        json.dumps(value, ensure_ascii=False).encode('utf-8')
        if type(value) is not dict:
            fail()
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ProtocolError):
            raise
        fail()


def clean_text(value, maximum, *, nullable=False, nonempty=False):
    if value is None and nullable:
        return None
    if type(value) is not str or len(value) > maximum:
        fail()
    try:
        value.encode('utf-8')
    except UnicodeError:
        fail()
    value = ''.join(c for c in value if unicodedata.category(c) not in {'Cc', 'Cf'})
    if nonempty and not value.strip():
        fail()
    return value


def normalize_url(value):
    """SCOPE simple-v1: remove fragment and lowercase host, preserve everything else.

    Recording a URL never authorizes fetching it. No domain/platform inference.
    """
    if type(value) is not str or not value or len(value) > 2048:
        fail('INVALID_PUBLIC_URL')
    if any(c.isspace() or unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} for c in value):
        fail('INVALID_PUBLIC_URL')
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {'http', 'https'} or not parts.netloc or not parts.hostname
                or parts.username is not None or parts.password is not None or '\\' in parts.netloc):
            fail('INVALID_PUBLIC_URL')
        # Accessing port validates malformed/out-of-range ports. Preserve its spelling.
        _ = parts.port
        host = parts.hostname
        if '[' in parts.netloc:
            end = parts.netloc.index(']')
            netloc = '[' + host.lower() + ']' + parts.netloc[end + 1:]
        else:
            netloc = host.lower() + parts.netloc[len(host):]
        without_fragment = value.split('#', 1)[0]
        authority_start = value.index('://') + 3
        canonical = (without_fragment[:authority_start] + netloc
                     + without_fragment[authority_start + len(parts.netloc):])
        canonical.encode('utf-8')
        return canonical
    except (ValueError, UnicodeError):
        fail('INVALID_PUBLIC_URL')


def canonical_json(event):
    return json.dumps([event[k] for k in EVENT_KEYS], ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def payload_digest(event):
    return hashlib.sha256(canonical_json(event).encode('utf-8')).hexdigest()


def parse_timestamp(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', value):
        fail()
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        fail()


def validate_event(value, *, now=None):
    """Validate a *new* event; the receiver must recover persisted ACKs first."""
    exact_object(value, (*EVENT_KEYS, 'payloadDigest'))
    if type(value['schema']) is not int or value['schema'] != 2 or value['reviewed'] is not True:
        fail()
    if not identifier(value['eventId']) or not identifier(value['attemptId']):
        fail()
    occurred = parse_timestamp(value['occurredAt'])
    now = now or datetime.now(timezone.utc)
    if occurred > now + timedelta(hours=24):
        fail('CLOCK_SKEW')
    platform = clean_text(value['platform'], 60, nonempty=True)
    title = clean_text(value['title'], 300, nullable=True)
    account = clean_text(value['reportedAccount'], 60, nullable=True)
    if type(value['result']) is not str or value['result'] not in RESULTS:
        fail()
    if value['reasonCode'] is not None and (type(value['reasonCode']) is not str or value['reasonCode'] not in REASONS):
        fail()
    url = value['publicUrl']
    canonical = normalize_url(url) if url is not None else None
    if value['result'] == 'success' and canonical is None:
        fail('INVALID_PUBLIC_URL')
    digest = value['payloadDigest']
    if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest) or payload_digest(value) != digest:
        fail('PAYLOAD_DIGEST_INVALID')
    return {
        'platform': platform, 'platform_kind': platform if platform in PLATFORMS else 'other',
        'title': title, 'reported_account': account, 'public_url': canonical,
        'canonical_url': canonical,
        'url_hash': hashlib.sha256(canonical.encode('utf-8')).hexdigest() if canonical else None,
        'normalizer_version': 'simple-v1', 'occurred_at': occurred,
    }


def validate_pairing(value):
    exact_object(value, (), ('label',))
    return clean_text(value.get('label'), 80, nullable=True)


def validate_claim(value):
    exact_object(value, ('pairingCode', 'requestId'))
    if (not isinstance(value['pairingCode'], str) or not re.fullmatch(PAIRING_PATTERN, value['pairingCode'])
            or not identifier(value['requestId'])):
        fail()
    return value


def validate_ack_query(value):
    exact_object(value, ('schema', 'eventId', 'payloadDigest'))
    if (type(value['schema']) is not int or value['schema'] != 2 or not identifier(value['eventId'])
            or type(value['payloadDigest']) is not str or not re.fullmatch('[0-9a-f]{64}', value['payloadDigest'])):
        fail()
    return value


def validate_revision(value):
    if type(value) is not int or value < 0:
        fail()
    return value


def validate_label(value):
    exact_object(value, ('expectedRevision', 'targetTenant'),
                 ('scopeId', 'articleId', 'articleVersion', 'articleDigest', 'publishedAccount', 'reason'))
    validate_revision(value['expectedRevision'])
    if type(value['targetTenant']) is not int or value['targetTenant'] < 1:
        fail()
    for key in ('scopeId', 'articleId', 'articleVersion'):
        if value.get(key) is not None and (type(value[key]) is not int or value[key] < 1):
            fail()
    article = value.get('articleId')
    if article is not None:
        if (value.get('scopeId') is None or value.get('articleVersion') is None
                or type(value.get('articleDigest')) is not str or not re.fullmatch('[0-9a-f]{64}', value['articleDigest'])):
            fail()
    elif value.get('articleVersion') is not None or value.get('articleDigest') is not None:
        fail()
    clean_text(value.get('publishedAccount'), 60, nullable=True)
    clean_text(value.get('reason'), 200, nullable=True)
    return value


_IDENTITY_FIXED = {
    ('POST', '/pairings'), ('GET', '/receipts'), ('GET', '/receipts/count'), ('GET', '/devices'),
}
_IDENTITY_DYNAMIC = (
    ('POST', r'/pairings/UUID/cancel'), ('POST', r'/devices/UUID/revoke'),
    ('POST', r'/receipts/UUID/archive'), ('POST', r'/receipts/UUID/delete'),
    ('GET', r'/receipts/UUID'),
)


def match_inbox_identity_route(method, path):
    if not path.startswith(PREFIX):
        return False
    suffix = path[len(PREFIX):]
    return (method, suffix) in _IDENTITY_FIXED or any(
        method == verb and re.fullmatch(pattern.replace('UUID', UUID_PATTERN), suffix)
        for verb, pattern in _IDENTITY_DYNAMIC)


def valid_inbox_identity_request(request):
    if not match_inbox_identity_route(request.method, request.url.path):
        return False
    # ASGI path is decoded. An encoded alias must not gain the exact-route bypass.
    if request.scope.get('raw_path', b'') != request.url.path.encode('ascii'):
        return False
    suffix = request.url.path[len(PREFIX):]
    allowed = ({'state', 'q', 'ownerUserId', 'limit', 'offset'} if suffix == '/receipts' else
               {'state', 'q', 'ownerUserId'} if suffix == '/receipts/count' else
               {'ownerUserId'} if suffix == '/devices' else set())
    pairs = request.query_params.multi_items()
    return len(pairs) == len(request.query_params) and set(request.query_params) <= allowed


def match_inbox_business_route(method, path, module='seo'):
    prefix = '/api/v1/' + module + '/distribution/v2/'
    if method == 'GET' and path == prefix + 'publications':
        return True
    return method == 'POST' and re.fullmatch(prefix + 'receipts/' + UUID_PATTERN + r'/(?:label|unlabel)', path) is not None


def audit_endpoint(method, path):
    """Template v2 UUIDs without parsing/logging any input body or query."""
    if match_inbox_identity_route(method, path) or any(match_inbox_business_route(method, path, m) for m in ('seo', 'geo')):
        return re.sub(UUID_PATTERN, '{uuid}', path)
    # Fail closed on malformed v2 paths as well; never persist a guessed ID/code.
    if path.startswith('/api/v1/seo/distribution/v2/') or path.startswith('/api/v1/geo/distribution/v2/'):
        return '/api/v1/distribution/v2/{unmatched}'
    return path
