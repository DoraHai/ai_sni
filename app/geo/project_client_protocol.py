"""Bounded public protocol for saved, project-owned GEO records. No I/O."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException

from app.config import get_settings
from app.geo.integration_metrics import validated_week_end

PREFIX = '/api/v1/geo/projects/{project_id}/client'
ROUTES = {
    'overview': '/overview', 'visibility': '/visibility', 'questions': '/questions',
    'question': '/questions/{question_id}', 'answers': '/answers',
    'answer': '/answers/{answer_id}', 'content': '/content', 'task': '/content/{task_id}',
    'variants': '/content/{task_id}/variants',
    'variant': '/content/{task_id}/variants/{variant_id}',
    'article': '/content/{task_id}/articles/{article_id}', 'deliveries': '/deliveries',
    'summary': '/summary', 'article_citations': '/article-citations',
    'recommendations': '/recommendations',
    'report_pdf': '/reports/export.pdf', 'report_xlsx': '/reports/export.xlsx',
}
CLIENT_TEMPLATES = frozenset(PREFIX + suffix for suffix in ROUTES.values())
PAGED = {'questions', 'answers', 'content', 'variants', 'deliveries', 'article_citations', 'recommendations'}
WEEKLY = {'overview', 'visibility', 'questions', 'question', 'answers', 'answer',
          'summary', 'article_citations', 'report_pdf', 'report_xlsx'}
QUERY = {
    'questions': {'status', 'is_brand_probe', 'attention', 'q', 'business_id', 'unit_id'},
    'answers': {'question_id', 'engine_key', 'source_kind', 'eligibility'},
    'content': {'question_id', 'review_status', 'include_archived', 'q'},
    'deliveries': {'task_id', 'record_type'},
}
MAX_ID = 2**53 - 1


def fail(status, code, message):
    raise HTTPException(status, {'code': 'GEO_CLIENT_' + code, 'message': message})


def positive(value):
    if not re.fullmatch(r'[0-9]+', str(value)) or not 0 < int(value) <= MAX_ID:
        fail(422, 'INVALID_QUERY', '客户和对象 ID 必须是有效正整数')
    return int(value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def encode_cursor(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    # Same existing runtime signing source as integration/read cursors. No new
    # environment option; workers and restarts can verify each other's pages.
    return base64.urlsafe_b64encode(raw).decode().rstrip('=') + '.' + hmac.new(
        get_settings().admin_api_key.encode(), raw, hashlib.sha256).hexdigest()


def decode_cursor(value):
    try:
        if not value or len(value) > 4096:
            raise ValueError()
        encoded, signature = value.split('.')
        raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        if not hmac.compare_digest(hmac.new(get_settings().admin_api_key.encode(), raw, hashlib.sha256).hexdigest(), signature):
            raise ValueError()
        result = json.loads(raw)
        if (not isinstance(result, dict) or result.get('v') != 1
                or set(result) != {'v', 'context', 'scope', 'week_end', 'watermarks', 'last'}
                or not isinstance(result['watermarks'], dict) or not isinstance(result['last'], list)
                or any(type(v) is not int or v < 0 or v > MAX_ID for v in result['watermarks'].values())):
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError, UnicodeError):
        fail(400, 'INVALID_CURSOR', '分页游标无效，请重新查询')


async def parameters(request, resource):
    allowed = {'tenant_id'} | QUERY.get(resource, set())
    if resource in WEEKLY:
        allowed.add('week_end')
    if resource in PAGED:
        allowed |= {'limit', 'cursor'}
    pairs = list(request.query_params.multi_items())
    if len(pairs) != len(dict(pairs)) or set(dict(pairs)) - allowed or await request.body():
        fail(422, 'INVALID_QUERY', '不接受重复或未知参数及请求正文')
    raw = dict(pairs)
    if 'tenant_id' not in raw:
        fail(422, 'INVALID_QUERY', '必须指定客户')
    out = {'tenant_id': positive(raw['tenant_id'])}
    out.update({k: positive(v) for k, v in request.path_params.items()})
    for key in ('question_id', 'task_id', 'business_id', 'unit_id'):
        if key in QUERY.get(resource, set()):
            out[key] = positive(raw[key]) if key in raw else None
    enums = {
        'status': ({'all', 'active', 'inactive', 'archived'}, 'all'),
        'attention': ({'all', 'needs_attention'}, 'all'),
        'source_kind': ({'real', 'manual', 'simulated', 'unknown'}, None),
        'eligibility': ({'all', 'qualified', 'excluded'}, 'all'),
        'review_status': ({'none', 'pending', 'approved', 'rejected', 'unknown'}, None),
        'record_type': ({'all', 'publication', 'receipt'}, 'all'),
    }
    for key, (choices, default) in enums.items():
        if key not in QUERY.get(resource, set()):
            continue
        value = raw.get(key, default)
        if value is not None and value not in choices:
            fail(422, 'INVALID_QUERY', '筛选值不合法')
        out[key] = value
    for key, default in (('is_brand_probe', None), ('include_archived', False)):
        if key in QUERY.get(resource, set()):
            if key in raw and raw[key] not in {'true', 'false'}:
                fail(422, 'INVALID_QUERY', '布尔筛选必须是 true 或 false')
            out[key] = raw[key] == 'true' if key in raw else default
    if 'q' in QUERY.get(resource, set()):
        out['q'] = raw['q'].strip() if 'q' in raw else None
        if out['q'] is not None and not 1 <= len(out['q']) <= 100:
            fail(422, 'INVALID_QUERY', '查询文字长度必须为 1–100 字符')
    if resource == 'answers':
        out['engine_key'] = raw.get('engine_key')
        if out['engine_key'] is not None and not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', out['engine_key']):
            fail(422, 'INVALID_QUERY', '引擎筛选不合法')
    decoded = None
    if resource in PAGED:
        value = raw.get('limit', '20')
        if not re.fullmatch(r'[0-9]+', value) or not 1 <= int(value) <= 100:
            fail(422, 'INVALID_QUERY', '每页数量必须为 1–100')
        out['limit'] = int(value)
        decoded = decode_cursor(raw['cursor']) if 'cursor' in raw else None
    if resource in WEEKLY:
        supplied = raw.get('week_end')
        if decoded and supplied is not None and supplied != decoded['week_end']:
            fail(400, 'INVALID_CURSOR', '分页周期已改变，请重新查询')
        try:
            selected = supplied or (decoded['week_end'] if decoded else None)
            if selected is not None and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', selected):
                raise ValueError()
            out['week_end'] = validated_week_end(date.fromisoformat(selected) if selected else None)
        except (ValueError, TypeError):
            fail(400, 'INVALID_WEEK', '请选择上海时区已结束的完整周')
    context = digest({'resource': resource, **{k: str(v) if isinstance(v, date) else v for k, v in out.items()}})
    if decoded and decoded['context'] != context:
        fail(400, 'INVALID_CURSOR', '客户、项目、父对象或筛选已改变，请重新查询')
    return out, decoded, context


def public_host(host):
    if not isinstance(host, str):
        return ''
    try:
        host = host.lower().rstrip('.').encode('idna').decode('ascii')
        ipaddress.ip_address(host)
        return ''  # Public IPs are not an ownership/domain boundary either.
    except ValueError:
        pass
    except UnicodeError:
        return ''
    if (len(host) > 253 or '.' not in host or host.endswith(('.localhost', '.local', '.internal', '.lan', '.home', '.test', '.invalid', '.localdomain', '.intranet', '.corp', '.private', '.onion'))
            or re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)', host.split('.')[-1]) or re.fullmatch(r'[0-9.]+', host) or re.fullmatch(r'0x[0-9a-f]+', host)):
        return ''
    labels = host.split('.')
    return host if all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels) else ''


# Decode names before checking; scan all pairs before dropping tracking parameters.
SENSITIVE_QUERY = re.compile(
    r'(?:^|[^a-z0-9])(?:token|access_token|accesstoken|key|apikey|api_key|secret|password|passwd|pwd|'
    r'sig|signature|auth|authorization|session|sessionid|session_id|code|credential|credentials|jwt)(?:$|[^a-z0-9])', re.I)
TRACKING_QUERY = {'gclid', 'dclid', 'fbclid', 'msclkid', 'spm', 'yclid', '_ga', '_gl'}


def url_domain(value):
    """Only a validated public hostname; never serialize userinfo/path/query."""
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value:
        return None
    try:
        parsed = urlsplit(value)
        return (public_host(parsed.hostname) or None) if parsed.scheme in {'http', 'https'} else None
    except (ValueError, UnicodeError):
        return None


def safe_url(value):
    if not isinstance(value, str) or not value:
        return None, 'invalid'
    try:
        if any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value:
            return None, 'invalid'
        parsed = urlsplit(value)
        if parsed.scheme not in {'https', 'http'} or not parsed.hostname:
            return None, 'invalid'
        port = parsed.port
        if (parsed.username is not None or parsed.password is not None
                or not public_host(parsed.hostname) or port not in {None, 80, 443}):
            return None, 'suppressed'
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if any(SENSITIVE_QUERY.search(key) for key, _ in pairs):
            return None, 'suppressed'
        query = urlencode([(key, val) for key, val in pairs
                           if not key.lower().startswith('utm_') and key.lower() not in TRACKING_QUERY])
        host = public_host(parsed.hostname)
        netloc = host + (f':{port}' if port is not None else '')
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, '')), 'available'
    except (ValueError, UnicodeError):
        return None, 'invalid'


def path(project_id, tenant_id, suffix, **query):
    return PREFIX.format(project_id=project_id) + suffix + '?' + urlencode(
        {'tenant_id': tenant_id, **{k: v for k, v in query.items() if v is not None}})


def paginate(rows, key, *, params, decoded, context, scope, watermarks):
    """Rows already obey first-page watermarks and the complete filter scope."""
    if decoded and decoded['scope'] != scope:
        fail(409, 'SCOPE_CHANGED', '项目归属已改变，请刷新列表')
    ordered = sorted(rows, key=key, reverse=True)
    remaining = ordered
    if decoded:
        try:
            last = tuple(decoded['last'])
            remaining = [row for row in ordered if tuple(key(row)) < last]
        except (TypeError, ValueError):
            fail(400, 'INVALID_CURSOR', '分页游标无效，请重新查询')
    items = remaining[:params['limit']]
    more = len(remaining) > len(items)
    cursor = encode_cursor({'v': 1, 'context': context, 'scope': scope,
                            'week_end': str(params['week_end']) if 'week_end' in params else None,
                            'watermarks': watermarks, 'last': list(key(items[-1]))}) if more else None
    return {'items': items, 'pagination': {'limit': params['limit'], 'returned_count': len(items),
            'total_count': len(ordered), 'has_more': more, 'next_cursor': cursor, 'truncated': more}}
