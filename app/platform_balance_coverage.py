"""Balance coverage from the connection catalogue and read-only registry evidence.

Independent service environment variables are never inferred from SEM settings.
Only explicitly managed credentials may be queried here; no schema activation.
"""
from __future__ import annotations

import asyncio
import json
from sqlalchemy import text
from app.api_connection_config import CATALOG, credential_id, public_defaults
from app.api_controls import enabled
from app.security.crypto import decrypt
from app import platform_balances as balances


DIRECT = {'deepseek', 'geo_deepseek', 'geo_kimi', 'dataforseo'}


def strategy(code):
    if code in DIRECT:
        return 'direct', '官方余额接口；需该连接的托管查询凭据。独立服务环境密钥不会由本服务代读。'
    if code in {'dashscope', 'geo_qwen'}:
        return 'billing_authorization', '需阿里云账务查询授权；同一云账户下的模型共享余额，模型 Key 不用于识别账务账户。'
    if code == 'baidu':
        return 'account', '按百度推广账户分别查询，见上方账户余额。'
    if code == 'chinaz':
        return 'package', '按商品查看剩余次数与到期日；套餐查询接口尚待确认，不能用调用次数推算剩余。'
    if code == 'pagespeed':
        return 'quota', '查看 Google 项目调用配额；本页未接通配额查询，不按现金余额展示。'
    if code in {'geo_doubao', 'geo_hunyuan', 'geo_qianfan', 'tencent_wsa'}:
        return 'billing_authorization', '需该云账户的账务/套餐查询授权；当前模型或搜索 Key 不等于账务权限。'
    return 'pending', '余额查询尚未接入；保留服务清单，余额与预警状态未知。'


def coverage_rows(settings, records=(), registry_state='unavailable'):
    registered = {r['label'].removeprefix('connection:'): r for r in records}
    result = []
    for spec in CATALOG.values():
        code = spec['id'].split('.', 1)[1]
        record = registered.get(spec['id'])
        runtime = public_defaults(spec, settings) if spec['module'] == 'sem' else None
        source = 'sem_runtime' if runtime else 'service_registry' if record else 'unknown'
        secrets = runtime['secrets'] if runtime else (record or {}).get('secret_status')
        is_enabled = runtime['parameters'].get('enabled') if runtime else (record or {}).get('enabled')
        capability, note = strategy(code)
        items = list(spec['secrets'].items()) if code == 'chinaz' else [(None, None)]
        if code == 'chinaz' and spec['module'] == 'seo':
            # These existing SEO services predate the shared connection form.
            # List them without inventing registered configuration evidence.
            items.extend((name, {'label': label}) for name, label in (
                ('baidu_pc_ranking_api_key', '百度 PC 关键词排名'),
                ('baidu_mobile_ranking_api_key', '百度移动关键词排名'),
                ('sogou_pc_keywords_api_key', '搜狗 PC 网站关键词'),
                ('sogou_mobile_keywords_api_key', '搜狗移动网站关键词'),
                ('360_pc_ranking_api_key', '360 PC 关键词排名'),
                ('360_mobile_keywords_api_key', '360 移动网站关键词')))
        for secret_name, field in items:
            if secret_name:
                status = (secrets or {}).get(secret_name)
                common = (secrets or {}).get('api_key')
                configured = (status is True or common is True) if secrets is not None else None
                if secrets is not None and status is not True and common is not True and (status is not False or common is not False):
                    configured = None
                name = spec['label'] + ' / ' + field['label']
                row_id = spec['id'] + '.' + secret_name
            else:
                values = [(secrets or {}).get(k) for k in spec['secrets']]
                configured = all(v is True for v in values) if values and all(type(v) is bool for v in values) else None
                name, row_id = spec['label'], spec['id']
            result.append({'id': row_id, 'connection_id': spec['id'], 'module': spec['module'], 'name': name,
                'configured': configured, 'enabled': is_enabled if type(is_enabled) is bool else None,
                'configuration_source': source, 'configuration_seen_at': (record or {}).get('seen_at'),
                'capability': capability, 'note': note, 'balance_row_id': 'deepseek' if spec['id'] == 'sem.deepseek' else None})
    return {'state': registry_state, 'rows': result,
            'note': '清单包含系统支持的接口。独立服务未登记时配置状态未知；接口项数不等于余额账户数，金额不能直接相加。'}


async def read_registry(session):
    present = await session.scalar(text("SELECT to_regclass(current_schema() || '.api_control_bindings') IS NOT NULL"))
    if not present:
        return 'schema_pending', [], []
    records = [dict(r) for r in (await session.execute(text('''SELECT label,seen_at,
        metadata->'secrets' AS secret_status,
        metadata->'parameters'->'enabled' AS enabled,
        metadata->'parameters'->>'base_url' AS base_url
        FROM api_control_bindings WHERE label LIKE 'connection:%' ORDER BY module,label'''))).mappings()]
    for record in records:
        status = record['secret_status']
        record['secret_status'] = {k:v for k,v in status.items() if type(v) is bool} if isinstance(status, dict) else {}
    managed = []
    # Disabled/unapproved controls never activate stored overrides or read secrets.
    if not enabled():
        return 'available', records, managed
    overrides = [dict(r) for r in (await session.execute(text('''SELECT key,value->'parameters' AS parameters,
        value->'secrets' AS secret_status FROM api_control_settings
        WHERE kind='connection' AND key LIKE 'connection:%' ORDER BY key'''))).mappings()]
    # The older fingerprint-based rotation layer is applied by each module's
    # own admission path. Do not query an old connection key when its supplier
    # has such a rotation whose effective runtime identity we cannot verify.
    rotated_hosts = set((await session.execute(text('''SELECT b.host FROM api_control_bindings b
        JOIN api_control_credentials c ON c.id=b.id
        WHERE c.ciphertext IS NOT NULL AND b.label NOT LIKE 'connection:%' '''))).scalars())
    by_id = {r['label'].removeprefix('connection:'): r for r in records}
    for override in overrides:
        config_id = override['key'].removeprefix('connection:')
        spec = CATALOG.get(config_id)
        if spec is None:
            continue
        record = by_id.get(config_id)
        params = override['parameters'] or {}
        if not isinstance(params, dict):
            continue
        secret_status = override['secret_status']
        secret_status = {k:v for k,v in secret_status.items() if type(v) is bool} if isinstance(secret_status, dict) else {}
        if record:
            record['secret_status'] = {**(record.get('secret_status') or {}), **secret_status}
            for attr in ('base_url', 'enabled'):
                if attr in params:
                    record[attr] = params[attr]
        code = config_id.split('.', 1)[1]
        if spec['module'] == 'sem' or code not in DIRECT or not record or record.get('enabled') is False:
            continue
        ciphertext = await session.scalar(text('SELECT ciphertext FROM api_control_credentials WHERE id=:id'), {'id': credential_id(config_id)})
        if not ciphertext:
            continue
        try:
            secret = json.loads(decrypt(ciphertext))
            if not isinstance(secret, dict):
                continue
            fields = ('login', 'password') if code == 'dataforseo' else ('api_key',)
            if not all(isinstance(secret.get(k), str) and secret[k] for k in fields):
                continue
            from urllib.parse import urlsplit
            if urlsplit(record.get('base_url') or '').hostname in rotated_hosts:
                continue
            # These internal values are never returned by coverage_rows.
            managed.append({'id': config_id, 'module': spec['module'], 'name': spec['label'],
                            'code': code, 'base_url': record.get('base_url'), 'secrets': {k: secret[k] for k in fields}})
        except Exception:
            continue
    return 'available', records, managed


async def load_coverage(settings, session_factory):
    try:
        async with asyncio.timeout(5), session_factory() as session:
            await session.execute(text('SET TRANSACTION READ ONLY'))
            await session.execute(text("SET LOCAL statement_timeout='3000ms'"))
            state, records, managed = await read_registry(session)
    except Exception:
        state, records, managed = 'unavailable', [], []
    return coverage_rows(settings, records, state), managed


async def query_managed(item):
    code, secret = item['code'], item['secrets']
    if code in {'deepseek', 'geo_deepseek'}:
        from types import SimpleNamespace
        return await balances.deepseek(SimpleNamespace(deepseek_base_url=item['base_url'], deepseek_api_key=secret['api_key']))
    if code == 'geo_kimi':
        return await balances.kimi(item['base_url'], secret['api_key'])
    if code == 'dataforseo':
        return await balances.dataforseo(item['base_url'], secret['login'], secret['password'])
    raise ValueError('unsupported connection')
