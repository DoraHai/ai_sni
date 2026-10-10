"""Read-only provider evidence. No probes, queue inference or paid retries."""
from sqlalchemy import text

from app.api_metering import enabled

STALE_SECONDS = 600


async def read_call_monitor(session):
    result = {
        'state': 'schema_pending', 'period': 'last_24_hours',
        'coverage': 'recorded_provider_attempts', 'stale_after_seconds': STALE_SECONDS,
        'summary': None, 'providers': [],
        'workers': {'state': 'not_connected', 'rows': [],
                    'note': '后台任务心跳与队列契约待接入；供应商调用记录不能证明调度器存活，待命也不表示故障。'},
    }
    if not await session.scalar(text("SELECT to_regclass(current_schema() || '.api_usage_events') IS NOT NULL")):
        return result
    result['state'] = 'recording' if enabled() else 'ready'
    rows = (await session.execute(text('''SELECT module,provider,grouping(module) AS aggregate,
        count(*) FILTER (WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours') AS calls,
        count(*) FILTER (WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours' AND state='succeeded') AS succeeded,
        count(*) FILTER (WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours' AND state='error') AS errors,
        count(*) FILTER (WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours' AND state='unknown') AS unknown,
        count(*) FILTER (WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours' AND estimated_amount IS NULL) AS unpriced,
        count(*) FILTER (WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours' AND pricing_version IS NULL) AS missing_rate,
        count(*) FILTER (WHERE state='requested') AS pending,
        count(*) FILTER (WHERE state='requested' AND started_at < CURRENT_TIMESTAMP - (:stale * INTERVAL '1 second')) AS stale_pending,
        count(*) FILTER (WHERE state <> 'requested' AND estimated_amount IS NULL) AS unresolved_charges,
        min(started_at) FILTER (WHERE state='requested') AS oldest_pending_at,
        max(started_at) FILTER (WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours' AND state IN ('error','unknown')) AS last_failure,
        max(started_at) AS last_attempt_at,
        avg(latency_ms) FILTER (WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours') AS average_latency_ms,
        percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms)
            FILTER (WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours') AS p95_latency_ms
        FROM api_usage_events WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
            OR state='requested' OR estimated_amount IS NULL
        GROUP BY GROUPING SETS ((module,provider),()) ORDER BY aggregate,module,provider'''),
        {'stale': STALE_SECONDS})).mappings()
    for row in rows:
        data = dict(row)
        aggregate = data.pop('aggregate')
        data['failed'] = data['errors'] + data['unknown']
        outcomes = data['succeeded'] + data['errors']
        data['known_outcomes'] = outcomes
        data['success_percent'] = round(data['succeeded'] / outcomes * 100, 1) if outcomes else None
        data['average_latency_ms'] = round(float(data['average_latency_ms']), 1) if data['average_latency_ms'] is not None else None
        if aggregate:
            data.pop('module')
            data.pop('provider')
            result['summary'] = data
        else:
            result['providers'].append(data)
    return result


def monitor_alerts(monitor, identity):
    alerts = []
    for row in monitor['providers']:
        label = f"{row['module'].upper()} / {row['provider']}"
        source = f"provider:{row['module']}:{row['provider']}"
        if row['stale_pending']:
            alerts.append(identity({'kind': 'api_pending', 'severity': 'warning', 'tenant_id': None,
                'message': f"{label} 有 {row['stale_pending']} 次调用超过 10 分钟未结束，付费结果待核查，请勿直接重试"},
                source + ':pending', str(row['oldest_pending_at'])))
        if row['unknown']:
            alerts.append(identity({'kind': 'api_unknown', 'severity': 'warning', 'tenant_id': None,
                'message': f"{label} 近 24 小时有 {row['unknown']} 次结果未知，需核对供应商请求记录与账单"},
                source + ':unknown', str(row['last_failure'])))
        if row['missing_rate']:
            alerts.append(identity({'kind': 'api_unpriced', 'severity': 'warning', 'tenant_id': None,
                'message': f"{label} 近 24 小时有 {row['missing_rate']} 次调用未匹配价格，费用保持未知"},
                source + ':rate', [row['missing_rate'], str(row['last_attempt_at'])]))
    return alerts
