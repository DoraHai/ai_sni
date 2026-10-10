"""Bounded, authenticated console queries over the existing provider ledger."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

FIELDS = ('id', 'tenant_id', 'user_id', 'origin', 'module', 'operation', 'job_ref',
          'provider', 'model', 'endpoint', 'state', 'status_code', 'latency_ms',
          'prompt_tokens', 'cached_tokens', 'completion_tokens', 'currency',
          'estimated_amount', 'pricing_version', 'provider_request_id', 'started_at')
FILTERS = {'from', 'to', 'tenant_id', 'user_id', 'module', 'provider', 'endpoint',
           'model', 'state', 'unpriced', 'page_size', 'cursor'}
EXPORT_LIMIT = 50000


def parse_query(query):
    if set(query) - FILTERS or any(len(query.getlist(k)) != 1 for k in query):
        raise ValueError('查询条件无效')
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    start = date.fromisoformat(query.get('from', today.replace(day=1).isoformat()))
    end = date.fromisoformat(query.get('to', today.isoformat()))
    if not date(2000, 1, 1) <= start <= end <= today or (end - start).days > 3660:
        raise ValueError('日期范围无效')
    params = {'start': datetime.combine(start, datetime.min.time(), ZoneInfo('Asia/Shanghai')),
              'end': datetime.combine(end + timedelta(days=1), datetime.min.time(), ZoneInfo('Asia/Shanghai')),
              'anchor': now}
    clauses = ['started_at >= :start', 'started_at < :end', 'started_at <= :anchor']
    for key in ('tenant_id', 'user_id'):
        if key not in query or query[key] == '':
            continue
        raw = query[key]
        if not raw.isascii() or not raw.isdigit() or len(raw) > 15:
            raise ValueError('客户或账号条件无效')
        number = int(raw)
        if number == 0:
            clauses.append(key + ' IS NULL')
        else:
            clauses.append(key + ' = :' + key)
            params[key] = number
    for key, maximum in (('module', 12), ('provider', 80), ('endpoint', 200), ('model', 120), ('state', 24)):
        value = query.get(key, '')
        if not value:
            continue
        if len(value) > maximum or any(ord(c) < 32 for c in value):
            raise ValueError('接口条件无效')
        if key == 'module' and value not in {'sem', 'seo', 'geo'}:
            raise ValueError('模块无效')
        if key == 'state' and value not in {'requested', 'succeeded', 'error', 'unknown'}:
            raise ValueError('调用状态无效')
        params[key] = value
        clauses.append(key + ' = :' + key)
    if query.get('unpriced', ''):
        if query['unpriced'] not in {'true', 'false'}:
            raise ValueError('定价条件无效')
        clauses.append('estimated_amount IS ' + ('' if query['unpriced'] == 'true' else 'NOT ') + 'NULL')
    size = query.get('page_size', '50')
    if not size.isascii() or not size.isdigit() or not 1 <= int(size) <= 200:
        raise ValueError('每页记录数必须为 1 至 200')
    # Bind the continuation to its filters; inserts after page one stay out.
    digest = hashlib.sha256(json.dumps({k: v for k, v in query.items() if k not in {'cursor', 'page_size'}},
                                      sort_keys=True).encode()).hexdigest()
    cursor = query.get('cursor')
    if cursor:
        if len(cursor) > 1200:
            raise ValueError('分页游标无效')
        data = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
        if set(data) != {'anchor', 'time', 'id', 'filter'} or data['filter'] != digest:
            raise ValueError('分页条件已变化，请重新查询')
        anchor, boundary = datetime.fromisoformat(data['anchor']), datetime.fromisoformat(data['time'])
        if anchor.tzinfo is None or boundary.tzinfo is None or not boundary <= anchor <= now:
            raise ValueError('分页游标无效')
        params.update(anchor=anchor, boundary=boundary, boundary_id=str(UUID(data['id'])))
    return {'params': params, 'where': ' AND '.join(clauses), 'page_size': int(size),
            'digest': digest, 'from': start.isoformat(), 'to': end.isoformat(), 'cursor': bool(cursor)}


def public_row(raw):
    row = dict(raw)
    from app.api.platform_console import safe_endpoint
    row['endpoint'] = safe_endpoint(row['endpoint'])
    row['estimated_amount'] = str(row['estimated_amount']) if row['estimated_amount'] is not None else None
    # No credential references, rate quotes, prompts or provider bodies.
    return row


async def read_history(session, spec, *, export=False):
    exists = await session.scalar(text("SELECT to_regclass(current_schema() || '.api_usage_events') IS NOT NULL"))
    if not exists:
        return {'state': 'schema_pending', 'rows': [], 'total': None, 'unpriced': None,
                'known_amount': None, 'estimated_amount': None, 'next_cursor': None}
    summary = dict((await session.execute(text(f"""SELECT count(*) AS total,
        count(*) FILTER (WHERE estimated_amount IS NULL) AS unpriced,
        coalesce(sum(estimated_amount),0) AS known_amount
        FROM api_usage_events WHERE {spec['where']}"""), spec['params'])).mappings().one())
    summary['known_amount'] = str(summary['known_amount'])
    summary['estimated_amount'] = summary['known_amount'] if not summary['unpriced'] else None
    if export and (spec['cursor'] or summary['total'] > EXPORT_LIMIT):
        raise ValueError('导出最多 50000 条，请缩小日期或筛选范围；导出不会截断记录')
    where = spec['where']
    if spec['cursor']:
        where += ' AND (started_at,id) < (:boundary,CAST(:boundary_id AS uuid))'
    limit = EXPORT_LIMIT if export else spec['page_size'] + 1
    rows = [public_row(r) for r in (await session.execute(text(
        f"SELECT {','.join(FIELDS)} FROM api_usage_events WHERE {where} ORDER BY started_at DESC,id DESC LIMIT :limit"
    ), {**spec['params'], 'limit': limit})).mappings()]
    next_cursor = None
    if not export and len(rows) > spec['page_size']:
        rows = rows[:spec['page_size']]
        last = rows[-1]
        data = {'anchor': spec['params']['anchor'].isoformat(), 'time': last['started_at'].isoformat(),
                'id': str(last['id']), 'filter': spec['digest']}
        next_cursor = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')
    return {'state': 'available', **summary, 'rows': rows, 'next_cursor': next_cursor,
            'from': spec['from'], 'to': spec['to'], 'as_of': spec['params']['anchor'].isoformat()}


def export_csv(rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(FIELDS)
    for row in rows:
        cells = []
        for key in FIELDS:
            value = row.get(key)
            value = '' if value is None else value.isoformat() if isinstance(value, datetime) else str(value)
            # Customer names, models and request IDs can be untrusted cells.
            if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
                value = "'" + value
            cells.append(value)
        writer.writerow(cells)
    return ('\ufeff' + output.getvalue()).encode('utf-8')
