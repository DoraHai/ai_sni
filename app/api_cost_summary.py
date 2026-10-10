"""Read-only cost aggregation for the named global administrator console."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.api_metering import enabled


async def read_api_costs(session):
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = {'state': 'schema_pending', 'date': local.date().isoformat(),
              'period': start.strftime('%Y-%m'), 'currency': 'CNY',
              'actual_amount': None, 'estimated_amount': None, 'known_amount': None,
              'tenant_totals': [], 'user_totals': [], 'provider_totals': [],
              'unattributed': {}, 'recent': [], 'all_time_count': None,
              'note': 'API 调用费用计量等待启用。'}
    exists = await session.scalar(text("SELECT to_regclass(current_schema() || '.api_usage_events') IS NOT NULL"))
    if not exists:
        return result
    from app.api_usage_review_basis import accounted_amount, review_projection
    amount = await accounted_amount(session)
    projection = await review_projection(session)
    verified = 'NULL::numeric' if amount=='estimated_amount' else 'verified_amount'
    estimate = 'estimated_amount' if amount=='estimated_amount' else 'CASE WHEN review_version=0 THEN estimated_amount END'
    result['state'] = 'recording' if enabled() else 'ready'
    result['all_time_count'] = int(await session.scalar(text('SELECT count(*) FROM api_usage_events')))
    result['started_at'] = await session.scalar(text('SELECT min(started_at) FROM api_usage_events'))
    result['calls_24h'] = int(await session.scalar(text("SELECT count(*) FROM api_usage_events WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'")))
    summary = (await session.execute(text("""SELECT count(*) AS total,
        count(*) FILTER (WHERE state IN ('error','unknown')) AS failed,avg(latency_ms) AS average_latency_ms
        FROM api_usage_events WHERE started_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'"""))).mappings().one()
    result['calls_24h_summary'] = {'state': 'available', 'period': 'last_24_hours', 'coverage': 'metered_providers',
        'total': int(summary['total']), 'failed': int(summary['failed']),
        'average_latency_ms': round(float(summary['average_latency_ms']),1) if summary['average_latency_ms'] is not None else None}
    # Missing usage, pending attempts and missing rates stay visible. The known
    # subtotal may be zero; the full estimate is unknown if any call is unpriced.
    metrics = f'''count(*) AS calls,
        count(*) FILTER (WHERE state IN ('error','unknown')) AS failed,
        count(*) FILTER (WHERE {amount} IS NULL) AS unpriced,
        count(*) FILTER (WHERE state='requested') AS pending,
        count(*) FILTER (WHERE prompt_tokens IS NULL OR completion_tokens IS NULL) AS unknown_usage,
        coalesce(sum(prompt_tokens),0) AS input_tokens,
        coalesce(sum(completion_tokens),0) AS output_tokens,
        coalesce(sum({amount}),0) AS known_amount,
        coalesce(sum({verified}),0) AS verified_amount,
        coalesce(sum({estimate}),0) AS estimated_known_amount,
        count(*) FILTER (WHERE estimated_amount IS NULL) AS estimate_unknown,
        coalesce(sum(estimated_amount),0) AS original_estimate_total'''
    params = {'start': start}
    def normalize(row):
        row = dict(row)
        row['known_amount'] = str(row['known_amount'])
        row['verified_amount'] = str(row['verified_amount'])
        row['estimated_known_amount'] = str(row['estimated_known_amount'])
        original,unknown = row.pop('original_estimate_total'),row.pop('estimate_unknown')
        row['estimated_amount'] = str(original) if not unknown else None
        row['known_amount_basis'] = 'mixed_estimate_and_human_attestation'
        return row
    total = normalize((await session.execute(text(f'SELECT {metrics} FROM api_usage_events WHERE started_at >= :start'), params)).mappings().one())
    result.update(total)
    for key, group in (('tenant_totals','tenant_id'), ('user_totals','user_id')):
        rows = (await session.execute(text(f'SELECT {group}, {metrics} FROM api_usage_events WHERE started_at >= :start GROUP BY {group} ORDER BY {group} NULLS LAST'), params)).mappings()
        result[key] = [normalize(row) for row in rows]
    result['provider_totals'] = [normalize(row) for row in (await session.execute(text(f'''SELECT module,provider,model,endpoint,{metrics}
        FROM api_usage_events WHERE started_at >= :start GROUP BY module,provider,model,endpoint ORDER BY module,provider,model,endpoint'''),params)).mappings()]
    result['unattributed'] = normalize((await session.execute(text(f'''SELECT {metrics} FROM api_usage_events
        WHERE started_at >= :start AND tenant_id IS NULL'''),params)).mappings().one())
    result['recent'] = [dict(row) for row in (await session.execute(text(f'''SELECT id,tenant_id,user_id,origin,module,operation,job_ref,
        provider,model,endpoint,state,status_code,latency_ms,prompt_tokens,cached_tokens,completion_tokens,
        estimated_amount,currency,pricing_version,provider_request_id,started_at,{projection} FROM api_usage_events ORDER BY started_at DESC,id DESC LIMIT 50'''))).mappings()]
    result['note'] = '按北京时间统计本月请求。已知费用小计混合原估算与人工核实费用，二者分列；人工证据由超管核对并声明，系统仅保存索引与指纹，不独立验证账单。DeepSeek 默认估算使用官方高峰价上限，实际扣款以服务商账单为准。'
    return result
