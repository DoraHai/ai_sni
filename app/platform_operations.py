"""Console operations reuse the reviewed append-only management audit table."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.api_controls import ControlConflict, enabled

BACKUP_STATUS = Path('/opt/sem-backend/platform-backup-status.json')
ALERT_ACTIONS = ('alert.claim', 'alert.resolve', 'alert.reopen')


async def available(session):
    return bool(await session.scalar(text("SELECT to_regclass(current_schema() || '.api_control_audit') IS NOT NULL")))


async def append_audit(session, actor_id, resource, action, before, after, request_id=None, digest=None):
    request_id = request_id or str(uuid4())
    payload = {'actor': actor_id or 0, 'resource': resource, 'action': action, 'before': before, 'after': after}
    digest = digest or hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    await session.execute(text('''INSERT INTO api_control_audit
        (id,actor_id,resource,action,request_hash,before_value,after_value,created_at)
        VALUES(CAST(:id AS uuid),:actor,:resource,:action,:hash,CAST(:before AS jsonb),CAST(:after AS jsonb),clock_timestamp())'''),
        {'id': request_id, 'actor': actor_id or 0, 'resource': resource, 'action': action, 'hash': digest,
         'before': json.dumps(before), 'after': json.dumps(after)})


async def audit_business(session, ctx, resource, action, before, after):
    if not enabled():
        return
    try:
        await append_audit(session, ctx.user_id, resource, action, before, after)
    except Exception:
        # The business write and its audit use the SAME transaction.
        await session.rollback()
        raise HTTPException(503, '管理审计暂时不可用，账号或权限变更未保存') from None


def alert_identity(alert, source, signal):
    alert['id'] = hashlib.sha256(source.encode()).hexdigest()
    alert['signal'] = hashlib.sha256(str(signal).encode()).hexdigest()
    return alert


async def provider_health(session):
    exists = await session.scalar(text("SELECT to_regclass(current_schema() || '.api_usage_events') IS NOT NULL"))
    if not exists:
        return []
    return [dict(r) for r in (await session.execute(text('''SELECT module,provider,
        count(*) AS calls,count(*) FILTER (WHERE state IN ('error','unknown')) AS failed,
        avg(latency_ms) AS average_latency_ms,
        max(started_at) FILTER (WHERE state IN ('error','unknown')) AS last_failure
        FROM api_usage_events WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
        GROUP BY module,provider ORDER BY module,provider'''))).mappings()]


async def attach_alert_states(session, alerts):
    present = await available(session)
    state = 'enabled' if present and enabled() else 'ready' if present else 'schema_pending'
    resources = ['alert:' + a['id'] for a in alerts]
    saved = {}
    if present and resources:
        saved = {r['resource']: r['after_value'] for r in (await session.execute(text('''
            SELECT DISTINCT ON (resource) resource,after_value FROM api_control_audit
            WHERE resource=ANY(:resources) AND action=ANY(:actions)
            ORDER BY resource,(after_value->>'revision')::bigint DESC,created_at DESC,id DESC'''), {'resources': resources, 'actions': list(ALERT_ACTIONS)})).mappings()}
    for alert in alerts:
        last = saved.get('alert:' + alert['id'], {})
        status = last.get('status', 'open')
        if status == 'resolved' and last.get('signal') != alert['signal']:
            status = 'open'
        alert['handling'] = {'status': status, 'revision': last.get('revision', 0),
                             'owner_id': last.get('owner_id'), 'note': last.get('note', ''),
                             'updated_at': last.get('updated_at')}
    return state


async def read_suppliers(session):
    if not await available(session):
        return []
    return [dict(r['after_value'], host=r['resource'][9:]) for r in (await session.execute(text('''
        SELECT DISTINCT ON (resource) resource,after_value FROM api_control_audit
        WHERE action='supplier.update' AND resource LIKE 'supplier:%'
        ORDER BY resource,(after_value->>'revision')::bigint DESC,created_at DESC,id DESC'''))).mappings()]


def supplier_value(value):
    fields = {'balance', 'currency', 'remaining_calls', 'expires_on', 'warning_balance', 'warning_calls'}
    if not isinstance(value, dict) or set(value) != fields or value['currency'] not in {'CNY', 'USD'}:
        raise ValueError('额度登记字段无效')
    result = {'currency': value['currency']}
    for field in ('balance', 'warning_balance'):
        raw = value[field]
        if raw is None:
            result[field] = None
            continue
        try:
            amount = Decimal(str(raw))
            if isinstance(raw, bool) or not amount.is_finite() or amount < 0 or amount > 10**12 or amount.as_tuple().exponent < -6:
                raise ValueError
            result[field] = str(amount)
        except (InvalidOperation, ValueError):
            raise ValueError('余额与提醒阈值必须是非负数，最多六位小数') from None
    for field in ('remaining_calls', 'warning_calls'):
        raw = value[field]
        if raw is not None and (type(raw) is not int or not 0 <= raw <= 10**12):
            raise ValueError('套餐次数必须是非负整数')
        result[field] = raw
    expiry = value['expires_on']
    if expiry is not None:
        expiry = date.fromisoformat(expiry)
        if not date(2000, 1, 1) <= expiry <= date(2100, 1, 1):
            raise ValueError('套餐到期时间无效')
        expiry = expiry.isoformat()
    result['expires_on'] = expiry
    return result


async def mutate_operation(session, actor_id, data, alerts):
    if not enabled() or not await available(session):
        raise ValueError('管理操作等待数据库审核启用')
    if not isinstance(data, dict) or set(data) != {'request_id', 'kind', 'key', 'expected_revision', 'value'}:
        raise ValueError('操作请求无效')
    request_id = str(UUID(data['request_id']))
    kind, key, revision = data['kind'], data['key'], data['expected_revision']
    if kind not in {'alert', 'supplier'} or not isinstance(key, str) or len(key) > 220 or type(revision) is not int or revision < 0:
        raise ValueError('操作范围或版本无效')
    digest = hashlib.sha256(json.dumps({'actor': actor_id, **data}, sort_keys=True).encode()).hexdigest()
    resource = kind + ':' + key
    lock_id = int.from_bytes(hashlib.sha256(resource.encode()).digest()[:8], 'big', signed=True)
    await session.execute(text("SET LOCAL statement_timeout='3000ms'"))
    await session.execute(text('SELECT pg_advisory_xact_lock(:id)'), {'id': lock_id})
    previous = (await session.execute(text('SELECT actor_id,request_hash,after_value FROM api_control_audit WHERE id=CAST(:id AS uuid)'),
                                      {'id': request_id})).mappings().first()
    if previous:
        if previous['actor_id'] != actor_id or previous['request_hash'] != digest:
            raise ControlConflict('请求编号已被其他操作使用')
        return {'revision': previous['after_value']['revision'], 'replayed': True}
    last = await session.scalar(text("SELECT after_value FROM api_control_audit WHERE resource=:resource ORDER BY (after_value->>'revision')::bigint DESC,created_at DESC,id DESC LIMIT 1"),
                                {'resource': resource}) or {}
    if last.get('revision', 0) != revision:
        raise ControlConflict('记录版本已变化，请刷新后重试')
    value = data['value']
    if kind == 'alert':
        alert = next((a for a in alerts if a['id'] == key), None)
        if not alert or not isinstance(value, dict) or set(value) != {'action', 'note', 'signal'} or value['action'] not in {'claim', 'resolve', 'reopen'}:
            raise ValueError('告警已变化或操作无效，请刷新')
        if value['signal'] != alert['signal']:
            raise ControlConflict('告警有新变化，请刷新后处理')
        note = value['note']
        if not isinstance(note, str) or len(note) > 500 or any(ord(c) < 32 and c not in '\n\t' for c in note):
            raise ValueError('处理说明无效')
        if value['action'] == 'resolve' and not note.strip():
            raise ValueError('标记已处理时必须填写处理说明')
        action = 'alert.' + value['action']
        after = {'status': {'claim': 'in_progress', 'resolve': 'resolved', 'reopen': 'open'}[value['action']],
                 'signal': value['signal'], 'note': note.strip(),
                 'owner_id': actor_id if value['action'] == 'claim' else last.get('owner_id', actor_id)}
    else:
        found = await session.scalar(text('SELECT EXISTS(SELECT 1 FROM api_control_bindings WHERE host=:host)'), {'host': key})
        if not found:
            raise ValueError('只能登记已接入服务商的额度')
        after, action = supplier_value(value), 'supplier.update'
        after['source'] = 'manual'
    after.update(revision=revision + 1, updated_at=datetime.now(timezone.utc).isoformat(), updated_by=actor_id)
    await append_audit(session, actor_id, resource, action, last or None, after, request_id, digest)
    await session.commit()
    return {'revision': revision + 1, 'replayed': False}


def read_backup_status(path=None):
    result = {'state': 'unavailable', 'records': [], 'note': '尚未收到数据库备份结果；发布回滚不代表数据库恢复已验证。'}
    try:
        target = path or BACKUP_STATUS
        if target.stat().st_size > 32768:
            raise ValueError
        raw = json.loads(target.read_text(encoding='utf-8'))
        if set(raw) != {'schema', 'records'} or type(raw['schema']) is not int or raw['schema'] != 1 or not isinstance(raw['records'], list) or len(raw['records']) > 20:
            raise ValueError
        records = []
        for row in raw['records']:
            fields = {'id', 'completed_at', 'scope', 'state', 'bytes', 'archive_verified', 'restore_verified'}
            if set(row) != fields or row['scope'] != 'public_schema' or row['state'] not in {'succeeded', 'failed'}:
                raise ValueError
            completed = datetime.fromisoformat(row['completed_at'])
            if completed.tzinfo is None or completed > datetime.now(timezone.utc):
                raise ValueError
            if type(row['bytes']) is not int or row['bytes'] < 0 or type(row['archive_verified']) is not bool or type(row['restore_verified']) is not bool:
                raise ValueError
            if row['state'] == 'failed' and (row['archive_verified'] or row['restore_verified']):
                raise ValueError
            if row['restore_verified'] and not row['archive_verified']:
                raise ValueError
            records.append({**row, 'id': str(UUID(row['id']))})
        result.update(state='available', records=sorted(records, key=lambda r: r['completed_at'], reverse=True),
                      note='数据库备份与恢复验证分别记录；此页面不提供备份文件下载。')
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, KeyError):
        result.update(state='invalid', note='备份结果暂时无法验证，请检查运维记录。')
    return result
