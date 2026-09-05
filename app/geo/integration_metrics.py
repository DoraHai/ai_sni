"""Read-only weekly evidence for the cross-module five-field metric contract."""
from datetime import date, datetime, timedelta
from hashlib import sha256
from collections import Counter
from urllib.parse import urlsplit

from sqlalchemy import select
from app.models import GeoAnswerSnapshot, GeoPrompt, GeoPublishingChannel, GeoVisibilityPatrolRun, GeoActionTicket
from app.geo.content.sample_provenance import eligible_visibility_sample
from app.geo.content.time_windows import TENANT_TZ, shanghai_today, shanghai_day_bounds_utc_naive, to_utc_naive

MENTIONS = 'geo.visibility.ai_mention_count_7d'
SCORE = 'geo.visibility.ai_visibility_score'
RATE = 'geo.visibility.ai_mention_rate_7d'


def closed_week_end(today=None):
    today = today or shanghai_today()
    return today - timedelta(days=today.weekday())


def competitor_key(name):
    return 'geo.competitor.' + sha256(name.strip().casefold().encode()).hexdigest()[:20] + '_mention_count_7d'


def qualified(rows):
    return [row for row in rows if eligible_visibility_sample(row)]


def cohort(rows):
    return [list(pair) for pair in sorted({(row.prompt_id, row.engine) for row in rows})]


def sufficient(rows):
    return len(rows) >= 8 and len({r.prompt_id for r in rows}) >= 3 and len({r.engine for r in rows}) >= 2


def domain(url):
    try:
        p = urlsplit(url or '')
        return (p.hostname or '').lower().rstrip('.') if p.scheme in {'http', 'https'} else ''
    except ValueError:
        return ''


def weekly_values(rows, own_domains, competitor_names):
    enough = sufficient(rows)
    mentions = sum(bool(r.mentions_brand) for r in rows)
    citations = sum(any(any((d := domain(url)) == own or d.endswith('.' + own) for own in own_domains)
                        for url in (r.cited_urls or [])) for r in rows)
    counts = Counter(name.strip().casefold() for row in rows for name in set(str(n).strip().casefold() for n in (row.competitors or []) if str(n).strip()))
    values = {MENTIONS: mentions if enough else None,
              RATE: round(100 * mentions / len(rows), 4) if enough else None,
              SCORE: round(50 * (mentions + citations) / len(rows), 4) if enough and own_domains else None}
    values.update({competitor_key(name): counts[name] if enough else None for name in competitor_names})
    return values


def metric_trend(value, previous, *, comparable=True):
    if not comparable or value is None or previous is None:
        return None
    change = value - previous
    return dict(direction='up' if change > 0 else 'down' if change < 0 else 'flat',
                change_pct=round(change / abs(previous) * 100, 4) if previous != 0 else None,
                change_abs=round(change, 4))


def build_weekly_snapshot(rows, own_domains, week_end, tracked_names=()):
    start, end = shanghai_day_bounds_utc_naive(week_end - timedelta(days=7))[0], shanghai_day_bounds_utc_naive(week_end)[0]
    previous_start = shanghai_day_bounds_utc_naive(week_end - timedelta(days=14))[0]
    rows = qualified(rows)
    current = [r for r in rows if start <= to_utc_naive(r.captured_at) < end]
    previous = [r for r in rows if previous_start <= to_utc_naive(r.captured_at) < start]
    names = sorted(set(tracked_names) | {str(n).strip().casefold() for row in current + previous for n in (row.competitors or []) if str(n).strip()})
    current_values = weekly_values(current, own_domains, names)
    prior_values = weekly_values(previous, own_domains, names)
    as_of = datetime.combine(week_end, datetime.min.time(), tzinfo=TENANT_TZ).isoformat()
    comparable = cohort(current) == cohort(previous)
    metrics = [dict(metric_key=key, value=value, unit='score' if key == SCORE else 'percent' if key == RATE else 'count',
                    as_of=as_of, trend_7d=metric_trend(value, prior_values[key], comparable=comparable))
               for key, value in current_values.items()]
    sample_counts = [[prompt, engine, count] for (prompt, engine), count
                     in sorted(Counter((r.prompt_id, r.engine) for r in current).items())]
    return dict(metrics=metrics, sample_ids=sorted(r.id for r in current), cohort=cohort(current),
                sample_counts=sample_counts,
                own_domains=sorted(own_domains), window_start=start.isoformat()+'Z',
                competitor_names={competitor_key(name): name for name in names})


def verified_patrol_rows(rows, runs):
    """Manual metadata cannot impersonate the immutable server patrol result."""
    from app.geo.content.snapshots import extract_cited_urls_from_text, normalize_competitors, normalize_cited_urls
    by_id = {run.id: run for run in runs}
    cells = {run.id: {cell.get('snapshot_id'): cell for cell in (run.items or [])} for run in runs}
    result = []
    for row in rows:
        run = by_id.get(row.patrol_run_id)
        cell = cells.get(row.patrol_run_id, {}).get(row.id)
        if not run or not cell or run.status != 'completed' or not run.started_at or not run.finished_at:
            continue
        if not (to_utc_naive(run.started_at) <= to_utc_naive(row.captured_at) <= to_utc_naive(run.finished_at)):
            continue
        if (not cell.get('ok') or cell.get('sample_mode') != 'openai_compat' or cell.get('simulated')
                or cell.get('sampling_method') != 'unprimed_json_v2' or cell.get('analysis_status') != 'completed'
                or cell.get('prompt_id') != row.prompt_id or cell.get('engine') != row.engine
                or str(cell.get('raw_text') or '').strip() != row.raw_text.strip()
                or cell.get('suggested_mentions_brand') is None
                or bool(cell['suggested_mentions_brand']) != bool(row.mentions_brand)
                or sorted(normalize_competitors(cell.get('competitors'))) != sorted(normalize_competitors(row.competitors))
                or sorted(normalize_cited_urls(extract_cited_urls_from_text(row.raw_text))) != sorted(normalize_cited_urls(row.cited_urls))):
            continue
        result.append(row)
    return result


async def load_weekly_snapshot(session, tenant_id, week_end=None):
    week_end = week_end or closed_week_end()
    if week_end < date(1, 1, 22):
        raise ValueError('week_end 必须留足两个完整周的统计窗口')
    if week_end.weekday() != 0 or week_end > closed_week_end():
        raise ValueError('week_end 必须为不晚于本周周一的上海日期')
    start = shanghai_day_bounds_utc_naive(week_end-timedelta(days=14))[0]
    end = shanghai_day_bounds_utc_naive(week_end)[0]
    rows = list(await session.scalars(select(GeoAnswerSnapshot).join(GeoPrompt, GeoPrompt.id == GeoAnswerSnapshot.prompt_id).where(
        GeoAnswerSnapshot.tenant_id == tenant_id, GeoPrompt.tenant_id == tenant_id,
        GeoPrompt.is_brand_probe.is_(False), GeoAnswerSnapshot.captured_at >= start, GeoAnswerSnapshot.captured_at < end)))
    runs = list(await session.scalars(select(GeoVisibilityPatrolRun).where(
        GeoVisibilityPatrolRun.tenant_id == tenant_id,
        GeoVisibilityPatrolRun.id.in_({row.patrol_run_id for row in rows if row.patrol_run_id}),
        GeoVisibilityPatrolRun.status == 'completed')))
    rows = verified_patrol_rows(rows, runs)
    channels = list(await session.scalars(select(GeoPublishingChannel).where(
        GeoPublishingChannel.tenant_id == tenant_id, GeoPublishingChannel.enabled.is_(True),
        GeoPublishingChannel.channel_type.in_(['website', 'docs']))))
    own = sorted({d for channel in channels if (d := domain(channel.base_url))})
    # A tracked competitor must keep a zero metric after disappearing from both weeks.
    registries = list(await session.scalars(select(GeoActionTicket.baseline_snapshot['competitor_names']).where(
        GeoActionTicket.tenant_id == tenant_id, GeoActionTicket.advice_code == 'cockpit:v1:task')))
    tracked = {name for registry in registries if isinstance(registry, dict) for name in registry.values() if isinstance(name, str)}
    return build_weekly_snapshot(rows, own, week_end, tracked)


def metric_dictionary(names=None):
    common = '上海时区完整自然周，非品牌点名题、真实 v2 API、判读完成且引用未标错，并与已完成服务端巡检原始结果一致的回答；至少8条、3题、2引擎，否则null。'
    docs = {MENTIONS: common+'值为 mentions_brand=true 的回答条数，每条回答至多计1次。',
            RATE: common+'值为品牌提及回答数除以合格回答数乘100。',
            SCORE: common+'值为50×品牌提及率+50×自有域引用率；引用率以全部合格回答为分母，自有域仅取启用的website/docs渠道，无自有域配置返回null。'}
    docs.update({key: common+f'竞品“{name}”提及回答条数，名称strip/casefold归一，每条回答去重；key使用归一名称SHA256前20位。' for key,name in (names or {}).items()})
    return docs
