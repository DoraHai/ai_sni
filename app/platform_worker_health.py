"""Bounded reads from fixed local service endpoints, using the caller's identity."""
import asyncio
from datetime import datetime, timezone
import json
import re

import httpx

DESTINATIONS = {
    'seo': 'http://127.0.0.1:8020/api/v1/seo/workbench/onsite-ai/health',
    'geo': 'http://127.0.0.1:8010/api/v1/geo/workbench/onsite-ai/health',
}
MAX_BYTES = 32768


def stamp(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('invalid timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError('UTC timestamp required')
    return parsed.isoformat()


def empty(module, state):
    return {'module': module, 'transport_state': state, 'module_observed_at': None,
        'worker': {'scope': None, 'enabled': None, 'state': 'not_connected' if state=='not_connected' else 'unverified', 'verified': False,
            'evidence': None, 'last_tick_at': None, 'last_attempted': None,
            'last_completed': None, 'last_error_code': None},
        'queue': {'state': 'schema_pending', 'queued': None, 'running': None, 'unknown': None,
            'oldest_queued_at': None, 'oldest_running_at': None}}


def normalize(module, data):
    if type(data.get('schema')) is not int or data['schema'] != 1 or data.get('module') != module:
        raise ValueError('health contract mismatch')
    result = empty(module, 'available')
    result['module_observed_at'] = stamp(data['observed_at'])
    observed = datetime.fromisoformat(result['module_observed_at'])
    if abs((datetime.now(timezone.utc) - observed).total_seconds()) > 120:
        raise ValueError('stale health response')
    worker, queue = data['worker'], data['queue']
    if not isinstance(worker, dict) or not isinstance(queue, dict):
        raise ValueError('invalid health payload')
    w = result['worker']
    w['scope'] = 'this_process' if worker.get('scope') == 'this_process' else None
    w['enabled'] = worker.get('enabled') if type(worker.get('enabled')) is bool else None
    state = worker.get('state')
    if state not in {'active', 'degraded', 'stopped', 'disabled', 'unverified', 'not_connected'}:
        raise ValueError('invalid worker state')
    for key in ('last_tick_at',):
        w[key] = stamp(worker.get(key))
    for key in ('last_attempted', 'last_completed'):
        value = worker.get(key)
        if value is not None and (type(value) is not int or not 0 <= value <= 2**63-1):
            raise ValueError('invalid tick counter')
        w[key] = value
    error = worker.get('last_error_code', worker.get('last_error'))
    w['last_error_code'] = error if error in {'worker_batch_failed'} else None
    evidence = worker.get('evidence')
    if isinstance(evidence, dict) and evidence.get('kind') == 'local_tick' and evidence.get('scope') == 'this_process':
        w['evidence'] = {'kind': 'local_tick', 'scope': 'this_process'}
    tick = datetime.fromisoformat(w['last_tick_at']) if w['last_tick_at'] else None
    verified = (worker.get('verified') is True and w['scope'] == 'this_process'
        and w['evidence'] is not None and tick is not None and 0 <= (observed - tick).total_seconds() <= 120)
    w['verified'] = bool(verified)
    # A 200 response or queue data never establishes a live execution tick.
    w['state'] = ('stopped' if state == 'disabled' else state) if state in {'disabled', 'stopped', 'not_connected'} or verified else 'unverified'
    if verified and state == 'active' and (w['enabled'] is not True or error is not None):
        w['state'] = 'unverified'
        w['verified'] = False
    q = result['queue']
    if queue.get('state', 'available') == 'available':
        for key in ('queued', 'running', 'unknown'):
            value = queue[key]
            if type(value) is not int or not 0 <= value <= 2**63-1:
                raise ValueError('invalid queue count')
            q[key] = value
        q['state'] = 'available'
        for key in ('oldest_queued_at', 'oldest_running_at'):
            q[key] = stamp(queue.get(key))
    return result


async def read_workers(authorization):
    result = {'schema': 1, 'state': 'not_connected', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'rows': [empty('sem', 'not_connected')],
        'note': '心跳仅代表响应进程；未验证 owner 时不代表整个服务活跃。SEM 队列与心跳尚未接入。'}
    if not isinstance(authorization, str) or not re.fullmatch(r'Bearer [A-Za-z0-9._-]{20,8192}', authorization):
        result['rows'].extend(empty(module, 'unauthorized') for module in DESTINATIONS)
        return result
    async def read(module, url):
        try:
            async with asyncio.timeout(3), httpx.AsyncClient(timeout=2, trust_env=False, follow_redirects=False) as client:
                async with client.stream('GET', url, headers={'Authorization': authorization, 'Accept': 'application/json'}) as response:
                    if response.status_code in (401, 403):
                        return empty(module, 'unauthorized')
                    if response.status_code != 200:
                        return empty(module, 'unavailable')
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            return empty(module, 'invalid')
                    return normalize(module, json.loads(body))
        except (TimeoutError, httpx.TimeoutException):
            return empty(module, 'timeout')
        except httpx.HTTPError:
            return empty(module, 'unavailable')
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
            return empty(module, 'invalid')
    result['rows'].extend(await asyncio.gather(*(read(module, url) for module, url in DESTINATIONS.items())))
    connected = sum(row['transport_state'] == 'available' for row in result['rows'])
    result['state'] = 'connected' if connected == len(DESTINATIONS) else 'partial' if connected else 'unavailable'
    return result


def worker_alerts(workers, identity, now=None):
    """Stable incident signals; observation timestamps never reopen an alert."""
    now = now or datetime.now(timezone.utc)
    alerts = []
    for row in workers.get('rows', []):
        module = row['module']
        label = module.upper()
        transport = row['transport_state']
        def add(kind, message, signal, severity='warning'):
            alerts.append(identity({'kind':kind,'severity':severity,'tenant_id':None,
                'message':message},'onsite-health:'+module+':'+kind,signal))
        if transport in {'timeout','unavailable','unauthorized','invalid'}:
            add('worker_health_read',label+' 监控读取失败，执行器与队列证据未知',transport)
            continue
        if transport!='available':
            continue
        worker,queue = row['worker'],row['queue']
        if worker['verified'] and worker['scope']=='this_process' and worker['state']=='degraded':
            add('worker_execution',label+' 响应进程的站内 AI 执行器出现异常，证据仅覆盖本进程',
                [worker['scope'],worker['last_error_code'],worker['last_attempted'],worker['last_completed']],'error')
        if queue['state']!='available':
            continue
        for name,threshold,kind,message in [
            ('queued',600,'onsite_queue_stale',' 站内 AI 队列等待超过 10 分钟，请核查执行器与任务'),
            ('running',180,'onsite_running_stale',' 站内 AI 任务运行超过 3 分钟，结果待核查，请勿直接重试')]:
            oldest = queue['oldest_'+name+'_at']
            if queue[name]>0 and oldest and (now-datetime.fromisoformat(oldest)).total_seconds()>threshold:
                add(kind,label+message,[queue[name],oldest])
        if queue['unknown']>0:
            add('onsite_business_unknown',label+' 有 '+str(queue['unknown'])+' 个站内 AI 任务业务结果待顾问核实；费用请另查调用台账',queue['unknown'])
    return alerts
