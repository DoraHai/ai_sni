"""Server-side API policy admission. No business transaction can erase a hold.

All admissions and policy changes use the same transaction advisory lock. Prices
and credentials are read fresh for each external attempt; no worker-local cache.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.database import async_session_factory
from app.security.crypto import decrypt, encrypt

LOCK_ID = 714102026
SERVICE_MODULE = 'unknown'


class ControlDenied(RuntimeError):
    def __init__(self, message, *, code=None, target=None):
        super().__init__(message)
        self.code, self.target = code, target


class ControlConflict(RuntimeError):
    pass


def enabled():
    return os.environ.get('API_CONTROLS_ENABLED', '').lower() == 'true'


def binding_id(host, reference):
    return hashlib.sha256((host + '\0' + (reference or '')).encode()).hexdigest()


def period_starts(anchor=None):
    local = (anchor or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Shanghai'))
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day, day.replace(day=1)


async def lock(session):
    await session.execute(text("SET LOCAL statement_timeout='3000ms'"))
    await session.execute(text('SELECT pg_advisory_xact_lock(:id)'), {'id': LOCK_ID})


def decimal_value(value):
    if isinstance(value, bool):
        raise ValueError('金额格式无效')
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > 10**9 or number.as_tuple().exponent < -12:
            raise ValueError
        return str(number)
    except (ValueError, InvalidOperation):
        raise ValueError('金额必须是非负数，最多十二位小数') from None


def validate_value(kind, value):
    if not isinstance(value, dict):
        raise ValueError('配置格式无效')
    if kind == 'provider':
        if set(value) != {'enabled'} or type(value['enabled']) is not bool:
            raise ValueError('接口开关格式无效')
        return value
    if kind == 'budget':
        allowed = {'daily_calls', 'monthly_calls', 'daily_cny', 'monthly_cny', 'warning_percent'}
        if not allowed <= set(value) or set(value) - allowed - {'max_concurrent'}:
            raise ValueError('预算字段不完整')
        result = {}
        for name in allowed:
            number = value[name]
            if name.endswith('_cny'):
                result[name] = None if number is None else decimal_value(number)
            elif name == 'warning_percent':
                if type(number) is not int or not 1 <= number <= 100:
                    raise ValueError('提醒阈值必须为 1 至 100 的整数')
                result[name] = number
            else:
                if number is not None and (type(number) is not int or not 0 <= number <= 10**9):
                    raise ValueError('请求上限必须是非负整数')
                result[name] = number
        cap = value.get('max_concurrent')
        if cap is not None and (type(cap) is not int or not 0 <= cap <= 10000):
            raise ValueError('并发上限必须是 0 至 10000 的整数')
        result['max_concurrent'] = cap
        return result
    if kind == 'rate':
        unit = value.get('unit')
        fields = {'unit', 'source', 'per_request'} if unit == 'request' else {'unit', 'source', 'input', 'output', 'cached', 'max_input'}
        if unit not in {'tokens', 'request'} or set(value) != fields:
            raise ValueError('单价字段无效')
        source = value.get('source')
        if not isinstance(source, str) or not 1 <= len(source) <= 200 or any(ord(c) < 32 for c in source):
            raise ValueError('请填写单价依据，最多 200 字')
        result = {'unit': unit, 'currency': 'CNY', 'source': source}
        for name in fields - {'unit', 'source', 'max_input'}:
            result[name] = None if name == 'cached' and value[name] is None else decimal_value(value[name])
        if result.get('cached') is None:
            result.pop('cached', None)
        if unit == 'tokens':
            cap = value.get('max_input')
            if type(cap) is not int or not 1 <= cap <= 10**7:
                raise ValueError('计价输入上限必须是 1 至 10000000 的整数')
            result['max_input'] = cap
        return result
    raise ValueError('不支持的配置类型')


async def usage(session, target):
    # Identifiers are selected from this fixed list, never interpolated input.
    provider_scope = target.startswith('provider:')
    column = 'tenant_id' if target.startswith('tenant:') else 'user_id' if target.startswith('user:') else "split_part(endpoint,'/',1)" if provider_scope else None
    tid = target[9:] if provider_scope else int(target.split(':')[1]) if column else None
    # Match INSERT's transaction timestamp even if waiting for the admission
    # lock crosses local midnight/month end. The host clock cannot move a hold
    # into a different budget period from the one used to authorize it.
    anchor = await session.scalar(text('SELECT CURRENT_TIMESTAMP'))
    day, month = period_starts(anchor)
    where = f'AND {column}=:target' if column else ''
    row = (await session.execute(text(f'''SELECT count(*) AS monthly_calls,
        count(*) FILTER (WHERE started_at >= :day) AS daily_calls,
        coalesce(sum(coalesce(estimated_amount,reserved_amount)),0) AS monthly_cny,
        coalesce(sum(coalesce(estimated_amount,reserved_amount)) FILTER (WHERE started_at >= :day),0) AS daily_cny,
        count(*) FILTER (WHERE estimated_amount IS NULL AND (state <> 'requested' OR reserved_amount IS NULL)) AS monthly_unknown,
        count(*) FILTER (WHERE started_at >= :day AND estimated_amount IS NULL AND (state <> 'requested' OR reserved_amount IS NULL)) AS daily_unknown
        FROM api_usage_events WHERE started_at >= :month {where}'''),
        {'day': day, 'month': month, 'target': tid})).mappings().one()
    result = {k: str(v) if isinstance(v, Decimal) else int(v) for k, v in row.items()}
    # A calendar reset must not release an interrupted attempt or erase an
    # unresolved charge. No timeout or worker PID is proof of a free request.
    outstanding = (await session.execute(text(f'''SELECT
        count(*) FILTER (WHERE state='requested') AS active_calls,
        count(*) FILTER (WHERE estimated_amount IS NULL AND
            (state <> 'requested' OR reserved_amount IS NULL OR started_at < :month)) AS unresolved_calls
        FROM api_usage_events WHERE (state='requested' OR estimated_amount IS NULL) {where}'''),
        {'month': month, 'target': tid})).mappings().one()
    result.update({k: int(v) for k, v in outstanding.items()})
    return result


def budget_status(policy, spent):
    cap = policy.get('max_concurrent')
    if cap is not None and spent.get('active_calls', 0) >= cap:
        return 'blocked'
    state = 'normal'
    for field in ('daily_calls', 'monthly_calls', 'daily_cny', 'monthly_cny'):
        cap = policy.get(field)
        if cap is None:
            continue
        unknown = field.endswith('cny') and (spent[field.split('_')[0] + '_unknown'] or spent.get('unresolved_calls', 0))
        if unknown:
            return 'unknown'
        used = Decimal(str(spent[field]))
        limit = Decimal(str(cap))
        if used >= limit:
            return 'blocked'
        if limit and used / limit * 100 >= policy['warning_percent']:
            state = 'warning'
    return state


def reservation(quote, kwargs):
    """Conservative estimate ceiling, not a provider invoice guarantee.

    Token admission reserves the entire approved input price bracket and an
    enforced output cap. Missing usage retains this hold until actual usage is
    available. Unknown rates cannot pass a monetary budget.
    """
    if not quote:
        raise ControlDenied('此接口缺少单价，无法通过金额预算检查')
    if quote['unit'] == 'request':
        return Decimal(quote['per_request']), kwargs
    payload = kwargs.get('json')
    if not isinstance(payload, dict) or not quote.get('max_input'):
        raise ControlDenied('缺少计价输入上限，无法预留 API 预算')
    payload = dict(payload)
    if payload.get('stream'):
        raise ControlDenied('流式请求尚不能通过金额预算检查')
    output_key = 'max_completion_tokens' if 'max_completion_tokens' in payload else 'max_tokens'
    cap = payload.get(output_key, 4096)
    if type(cap) is not int or not 1 <= cap <= 1000000:
        raise ControlDenied('模型输出上限无效，无法预留 API 预算')
    # Opaque multimodal inputs cannot be bounded by this text-only integration.
    messages = payload.get('messages')
    if not isinstance(messages, list) or any(not isinstance(m, dict) or not isinstance(m.get('content'), str) for m in messages):
        raise ControlDenied('此请求类型尚不能通过金额预算检查')
    # Reject payloads above the declared price bracket, with room for protocol
    # overhead; the reservation still uses the whole bracket, not this estimate.
    if len(json.dumps(payload, ensure_ascii=False).encode()) * 2 + 1024 > quote['max_input']:
        raise ControlDenied('请求超过当前计价输入范围')
    payload[output_key] = cap
    input_rate = max(Decimal(quote['input']), Decimal(quote.get('cached', '0')))
    amount = (Decimal(quote['max_input']) * input_rate + Decimal(cap) * Decimal(quote['output'])) / Decimal(1000000)
    return amount, {**kwargs, 'json': payload}


def replace_credential(kwargs, original, replacement):
    headers = dict(kwargs.get('headers') or {})
    for name, value in headers.items():
        if name.lower() == 'authorization' and value == 'Bearer ' + original:
            headers[name] = 'Bearer ' + replacement
            return {**kwargs, 'headers': headers}
    params = dict(kwargs.get('params') or {})
    for name in ('APIKey', 'key', 'api_key'):
        if params.get(name) == original:
            params[name] = replacement
            return {**kwargs, 'params': params}
    raise ControlDenied('此接口的密钥传递方式尚不支持在线轮换')


async def admit(params, url, api_key, quote, kwargs):
    """Policy check and attempt INSERT are one committed transaction."""
    from app.api_metering import credential_ref, MeteringUnavailable
    host = urlsplit(url).hostname or ''
    model = params['model'] or params['endpoint']
    try:
        async with asyncio.timeout(6), async_session_factory() as session:
            await lock(session)
            settings = {r['key']: r['value'] for r in (await session.execute(text(
                'SELECT key,value FROM api_control_settings'))).mappings()}
            if settings.get('provider:' + host, {}).get('enabled') is False:
                raise ControlDenied('该服务商 API 已被超级管理员停用', code='api_provider_disabled', target='provider:' + host)
            quote = settings.get('rate:' + host + ':' + model, quote)
            selected = ['global', 'provider:' + host]
            if params['tenant_id'] is not None:
                selected.append('tenant:' + str(params['tenant_id']))
            if params['user_id'] is not None:
                selected.append('user:' + str(params['user_id']))
            policies = [(t, settings['budget:' + t]) for t in selected if 'budget:' + t in settings]
            monetary = any(any(p.get(f) is not None for f in ('daily_cny', 'monthly_cny')) for _, p in policies)
            hold = None
            if monetary:
                try:
                    hold, kwargs = reservation(quote, kwargs)
                except ControlDenied as exc:
                    raise ControlDenied(str(exc), code='api_budget_quote_unavailable',
                        target=','.join(t for t, p in policies if any(p.get(f) is not None for f in ('daily_cny', 'monthly_cny')))) from None
            for target, policy in policies:
                spent = await usage(session, target)
                cap = policy.get('max_concurrent')
                if cap is not None and spent['active_calls'] >= cap:
                    raise ControlDenied(f'API 并发上限已达到（{target}），请等待当前请求完成；长期未结束的调用需由超管核查台账',
                                        code='api_concurrency_limit', target=target)
                for field in ('daily_calls', 'monthly_calls', 'daily_cny', 'monthly_cny'):
                    cap = policy.get(field)
                    if cap is None:
                        continue
                    if field.endswith('_cny') and (spent[field.split('_')[0] + '_unknown'] or spent['unresolved_calls']):
                        raise ControlDenied(f'已有无法确定费用的调用（{target}），金额预算暂停新请求，需由超管核对供应商账单',
                                            code='api_charge_unresolved', target=target)
                    increment = hold if field.endswith('_cny') else 1
                    if Decimal(str(spent[field])) + increment > Decimal(str(cap)):
                        raise ControlDenied(f'API 预算额度不足（{target}），新请求已暂停', code='api_budget_exhausted', target=target)
            reference = credential_ref(api_key)
            replacement = await session.scalar(text('SELECT ciphertext FROM api_control_credentials WHERE id=:id'),
                                               {'id': binding_id(host, reference)}) if api_key else None
            if replacement:
                try:
                    key = decrypt(replacement)
                    kwargs = replace_credential(kwargs, api_key, key)
                    params['credential_ref'] = credential_ref(key)
                except ControlDenied:
                    raise
                except Exception:
                    raise ControlDenied('API 密钥配置无法解密，请联系超级管理员') from None
            params.update(pricing_version=quote['version'] if quote else None,
                          rate_quote=json.dumps(quote) if quote else None, reserved_amount=hold)
            await session.execute(text('''INSERT INTO api_usage_events
                (id,tenant_id,user_id,origin,module,operation,job_ref,provider,credential_ref,
                model,endpoint,state,pricing_version,rate_quote,reserved_amount)
                VALUES(CAST(:id AS uuid),:tenant_id,:user_id,:origin,:module,:operation,:job_ref,
                :provider,:credential_ref,:model,:endpoint,'requested',:pricing_version,CAST(:rate_quote AS jsonb),:reserved_amount)'''), params)
            await session.commit()
            return quote, kwargs
    except ControlDenied:
        raise
    except Exception:
        raise MeteringUnavailable('API 管理配置或预算台账暂时不可用，请稍后重试') from None


async def register_runtime(module):
    global SERVICE_MODULE
    SERVICE_MODULE = module
    if not enabled():
        return
    from app.api_metering import enabled as metering_enabled
    if not metering_enabled():
        raise RuntimeError('API 管理必须与费用计量同时启用')
    from app.api_metering import credential_ref
    from app.config import get_settings
    s = get_settings()
    rows = []
    if module == 'sem':
        host = urlsplit(s.baidu_api_base_url).hostname or ''
        rows.append(dict(id=binding_id(host, 'baidu-oauth'), module=module,
                         label='baidu_oauth', host=host, model=None,
                         configured=bool(s.baidu_app_id and s.baidu_secret_key), can_rotate=False))
    if module == 'seo' and hasattr(s, 'seo_dataforseo_base_url'):
        host = urlsplit(s.seo_dataforseo_base_url).hostname or ''
        rows.append(dict(id=binding_id(host, 'dataforseo-basic'), module=module,
                         label='dataforseo', host=host, model=None,
                         configured=bool(s.seo_dataforseo_login and s.seo_dataforseo_password), can_rotate=False))
    for prefix in ('dashscope', 'deepseek', 'geo_openai', 'geo_deepseek', 'geo_qwen',
                   'geo_doubao', 'geo_hunyuan', 'geo_qianfan', 'geo_kimi', 'geo_perplexity'):
        if prefix.startswith('geo_') and module != 'geo':
            continue
        if not hasattr(s, prefix + '_base_url'):
            continue
        host = urlsplit(getattr(s, prefix + '_base_url')).hostname or ''
        key = str(getattr(s, prefix + '_api_key', '') or '').strip()
        rows.append(dict(id=binding_id(host, credential_ref(key) if key else prefix), module=module,
                         label=prefix, host=host, model=getattr(s, prefix + '_model', None),
                         configured=bool(key), can_rotate=bool(key)))
    if module in {'seo', 'geo'}:
        for name in type(s).model_fields:
            if name.startswith('chinaz_') and name.endswith('_api_key'):
                key = str(getattr(s, name) or '').strip()
                rows.append(dict(id=binding_id('openapi.chinaz.net', credential_ref(key) if key else name),
                                 module=module, label=name, host='openapi.chinaz.net', model=None,
                                 configured=bool(key), can_rotate=bool(key)))
    # Metadata refresh only. No credentials, prompts, provider probes or charges.
    async with asyncio.timeout(6), async_session_factory() as session:
        await lock(session)
        for row in rows:
            await session.execute(text('''INSERT INTO api_control_bindings
                (id,module,label,host,model,configured,can_rotate) VALUES(:id,:module,:label,:host,:model,:configured,:can_rotate)
                ON CONFLICT(module,label) DO UPDATE SET id=excluded.id,host=excluded.host,model=excluded.model,configured=excluded.configured,
                can_rotate=excluded.can_rotate,seen_at=CURRENT_TIMESTAMP'''), row)
        from app.api_connection_config import register_connections
        await register_connections(session,module,s)
        await session.commit()


async def read_controls(session):
    present = await session.scalar(text("""SELECT
        to_regclass(current_schema() || '.api_control_settings') IS NOT NULL AND
        to_regclass(current_schema() || '.api_control_bindings') IS NOT NULL AND
        to_regclass(current_schema() || '.api_control_credentials') IS NOT NULL AND
        to_regclass(current_schema() || '.api_control_audit') IS NOT NULL AND
        EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema()
            AND table_name='api_usage_events' AND column_name='reserved_amount')"""))
    from app.api_connection_config import public_connections
    result = {'state': 'schema_pending', 'capabilities': ['budget_concurrency_v1', 'provider_budget_v1'], 'settings': [], 'bindings': [], 'credentials': [], 'audit': [], 'budgets': [], 'connections':public_connections([],[]), 'module_status': []}
    if not present:
        return result
    result['state'] = 'enabled' if enabled() else 'ready'
    result['settings'] = [dict(r) for r in (await session.execute(text('SELECT key,kind,value,revision,updated_by,updated_at FROM api_control_settings ORDER BY key'))).mappings()]
    result['bindings'] = [dict(r) for r in (await session.execute(text('SELECT id,module,label,host,model,configured,can_rotate,seen_at,metadata FROM api_control_bindings ORDER BY module,label'))).mappings()]
    result['module_status'] = [{'module':r['module'],'settings':r['metadata']['runtime'],'seen_at':r['seen_at']}
        for r in result['bindings'] if 'runtime' in r['metadata']]
    result['credentials'] = [dict(r) for r in (await session.execute(text('SELECT id,(ciphertext IS NOT NULL) AS overridden,revision,updated_at FROM api_control_credentials ORDER BY id'))).mappings()]
    result['audit'] = [dict(r) for r in (await session.execute(text('SELECT id,actor_id,resource,action,before_value,after_value,created_at FROM api_control_audit ORDER BY created_at DESC,id DESC LIMIT 50'))).mappings()]
    for row in result['settings']:
        if row['kind'] == 'budget':
            target = row['key'][7:]
            spent = await usage(session, target)
            result['budgets'].append({'target': target, 'revision': row['revision'], 'value': row['value'], 'usage': spent,
                                      'status': budget_status(row['value'], spent)})
    from app.api_metering import DEFAULT_RATES
    result['default_rates'] = DEFAULT_RATES
    result['connections'] = public_connections(result['bindings'],result['settings'])
    return result


async def mutate(session, *, actor_id, request_id, kind, key, expected_revision, value):
    await lock(session)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('配置版本无效')
    if kind=='connection':
        return await mutate_connection(session,actor_id=actor_id,request_id=request_id,key=key,expected_revision=expected_revision,value=value)
    if kind == 'credential':
        if not re.fullmatch(r'[a-f0-9]{64}', key):
            raise ValueError('密钥绑定无效')
        valid = await session.scalar(text('SELECT bool_or(configured AND can_rotate) FROM api_control_bindings WHERE id=:id'), {'id': key})
        if not valid:
            raise ValueError('此密钥尚不支持在线轮换，请使用原授权流程')
        if not isinstance(value, dict) or set(value) != {'key'}:
            raise ValueError('密钥格式无效')
        secret = value['key']
        if secret is not None and (not isinstance(secret, str) or not 8 <= len(secret) <= 4096 or any(c.isspace() for c in secret)):
            raise ValueError('密钥格式无效')
        # Salted HMAC permits idempotency comparison without storing a secret.
        from app.api_metering import credential_ref
        fingerprint_value = {'credential_ref': credential_ref(secret)}
        current = (await session.execute(text('SELECT revision,(ciphertext IS NOT NULL) AS overridden FROM api_control_credentials WHERE id=:id'), {'id': key})).mappings().first()
        before = {'overridden': current['overridden']} if current else None
        after = {'overridden': secret is not None}
        resource = 'credential:' + key
    else:
        value = validate_value(kind, value)
        if kind == 'budget':
            match = re.fullmatch(r'budget:(global|tenant:[1-9][0-9]*|user:[1-9][0-9]*|provider:[a-z0-9.-]{1,200})', key)
            if not match:
                raise ValueError('预算范围无效')
            target = match[1]
            if target.startswith('provider:'):
                from app.api_metering import DEFAULT_RATES
                host = target[9:]
                known = await session.scalar(text('SELECT EXISTS(SELECT 1 FROM api_control_bindings WHERE host=:host)'), {'host': host})
                if not known and host not in {r['host'] for r in DEFAULT_RATES}:
                    raise ValueError('此服务商未在系统配置中登记')
            elif target != 'global':
                table = 'tenants' if target.startswith('tenant:') else 'users'
                if not await session.scalar(text(f'SELECT EXISTS(SELECT 1 FROM {table} WHERE id=:id)'), {'id': int(target.split(':')[1])}):
                    raise ValueError('客户或账号不存在')
        elif kind in {'provider', 'rate'}:
            match = re.fullmatch(r'(provider|rate):([a-z0-9.-]{1,200})(?::([A-Za-z0-9_.:/-]{1,200}))?', key)
            if not match or match[1] != kind or (kind == 'rate') != bool(match[3]):
                raise ValueError('接口或模型范围无效')
            from app.api_metering import DEFAULT_RATES
            known = await session.scalar(text('SELECT EXISTS(SELECT 1 FROM api_control_bindings WHERE host=:host)'), {'host': match[2]})
            if not known and match[2] not in {r['host'] for r in DEFAULT_RATES}:
                raise ValueError('此服务商未在系统配置中登记')
        current = (await session.execute(text('SELECT revision,value FROM api_control_settings WHERE key=:key'), {'key': key})).mappings().first()
        before = current['value'] if current else None
        after = value
        resource = key
        fingerprint_value = value
    request_hash = hashlib.sha256(json.dumps([actor_id,kind,key,expected_revision,fingerprint_value], sort_keys=True).encode()).hexdigest()
    prior = (await session.execute(text('SELECT actor_id,request_hash,after_value FROM api_control_audit WHERE id=CAST(:id AS uuid)'), {'id': request_id})).mappings().first()
    if prior:
        if prior['actor_id'] != actor_id or prior['request_hash'] != request_hash:
            raise ControlConflict('请求编号已用于其他操作，请刷新页面')
        return {'revision': expected_revision + 1, 'value': prior['after_value']['value'], 'replayed': True}
    if (current['revision'] if current else 0) != expected_revision:
        raise ControlConflict('配置已被其他管理员修改，请刷新后重试')
    revision = expected_revision + 1
    if kind == 'credential':
        await session.execute(text('''INSERT INTO api_control_credentials(id,ciphertext,revision,updated_by)
            VALUES(:id,:ciphertext,:revision,:actor) ON CONFLICT(id) DO UPDATE SET
            ciphertext=excluded.ciphertext,revision=excluded.revision,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP'''),
            {'id': key, 'ciphertext': encrypt(secret) if secret is not None else None, 'revision': revision, 'actor': actor_id})
        after = {**after, 'revision': revision}
    else:
        if kind == 'rate':
            after = {**value, 'version': 'admin-' + request_id}
        await session.execute(text('''INSERT INTO api_control_settings(key,kind,value,revision,updated_by)
            VALUES(:key,:kind,CAST(:value AS jsonb),:revision,:actor) ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,revision=excluded.revision,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP'''),
            {'key': key, 'kind': kind, 'value': json.dumps(after), 'revision': revision, 'actor': actor_id})
    await session.execute(text('''INSERT INTO api_control_audit(id,actor_id,resource,action,request_hash,before_value,after_value)
        VALUES(CAST(:id AS uuid),:actor,:resource,:action,:hash,CAST(:before AS jsonb),CAST(:after AS jsonb))'''),
        {'id': request_id, 'actor': actor_id, 'resource': resource, 'action': kind + '.update', 'hash': request_hash,
         'before': json.dumps({'revision': expected_revision, 'value': before}),
         'after': json.dumps({'revision': revision, 'value': after})})
    await session.commit()
    return {'revision': revision, 'value': after, 'replayed': False}


async def mutate_connection(session, *, actor_id, request_id, key, expected_revision, value):
    from app.api_connection_config import validate_connection, spec_for, credential_id
    from app.api_metering import credential_ref
    parameters,secrets,restore=validate_connection(key,value)
    spec=spec_for(key)
    registered=await session.scalar(text('''SELECT (metadata->>'supported')::boolean FROM api_control_bindings
      WHERE module=:module AND label=:label'''),{'module':spec['module'],'label':key})
    if registered is not True:
        raise ValueError('对应服务尚未登记此接口配置，请先核对服务版本')
    fingerprint={'parameters':parameters,'restore':restore,'secrets':{k:credential_ref(v) for k,v in secrets.items()}}
    digest=hashlib.sha256(json.dumps([actor_id,'connection',key,expected_revision,fingerprint],sort_keys=True).encode()).hexdigest()
    prior=(await session.execute(text('SELECT actor_id,request_hash,after_value FROM api_control_audit WHERE id=CAST(:id AS uuid)'),{'id':request_id})).mappings().first()
    if prior:
        if prior['actor_id']!=actor_id or prior['request_hash']!=digest:
            raise ControlConflict('请求编号已用于其他操作，请刷新页面')
        return {'revision':expected_revision+1,'value':prior['after_value']['value'],'replayed':True}
    current=(await session.execute(text('SELECT revision,value FROM api_control_settings WHERE key=:key'),{'key':key})).mappings().first()
    if (current['revision'] if current else 0)!=expected_revision:
        raise ControlConflict('配置已被其他管理员修改，请刷新后重试')
    before=current['value'] if current else None
    ident=credential_id(spec['id'])
    ciphertext=await session.scalar(text('SELECT ciphertext FROM api_control_credentials WHERE id=:id'),{'id':ident})
    try: bundle=json.loads(decrypt(ciphertext)) if ciphertext else {}
    except Exception: raise ValueError('已有密钥无法解密，请核对平台加密配置') from None
    bundle={} if restore else {**bundle,**secrets}
    after={'parameters':{} if restore else {**(before or {}).get('parameters',{}),**parameters},
           'secrets':{name:bool(secret) for name,secret in bundle.items()}}
    revision=expected_revision+1
    await session.execute(text('''INSERT INTO api_control_credentials(id,ciphertext,revision,updated_by)
      VALUES(:id,:ciphertext,:revision,:actor) ON CONFLICT(id) DO UPDATE SET ciphertext=excluded.ciphertext,
      revision=excluded.revision,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP'''),
      {'id':ident,'ciphertext':encrypt(json.dumps(bundle)) if bundle else None,'revision':revision,'actor':actor_id})
    await session.execute(text('''INSERT INTO api_control_settings(key,kind,value,revision,updated_by)
      VALUES(:key,'connection',CAST(:value AS jsonb),:revision,:actor) ON CONFLICT(key) DO UPDATE SET
      value=excluded.value,revision=excluded.revision,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP'''),
      {'key':key,'value':json.dumps(after),'revision':revision,'actor':actor_id})
    await session.execute(text('''INSERT INTO api_control_audit(id,actor_id,resource,action,request_hash,before_value,after_value)
      VALUES(CAST(:id AS uuid),:actor,:resource,'connection.update',:hash,CAST(:before AS jsonb),CAST(:after AS jsonb))'''),
      {'id':request_id,'actor':actor_id,'resource':key,'hash':digest,'before':json.dumps({'revision':expected_revision,'value':before}),
       'after':json.dumps({'revision':revision,'value':after})})
    await session.commit()
    return {'revision':revision,'value':after,'replayed':False}
