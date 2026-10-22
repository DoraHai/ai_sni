"""One pure saved-evidence projection for advisors, clients and exports."""
from collections import Counter

from app.geo import project_client_view as view
from app.geo.content.report_data import normalize_report_url
from app.geo.content.time_windows import to_utc_naive, shanghai_day_bounds_utc_naive
from app.geo.integration_metrics import sufficient
from app.geo.project_client_protocol import safe_url

ENGINES = (('doubao', '豆包'), ('deepseek', 'DeepSeek'), ('qwen', '千问'),
           ('hunyuan', '元宝'), ('wenxin', '文心'), ('kimi', 'Kimi'))
FOOTNOTES = ['元宝数据取自腾讯混元模型接口', '模型 API 的已保存回答观测，不代表各平台 App 实测。',
             '按当前项目业务绑定重算；无数据及资格不足显示暂无。',
             '文章引用为已保存回答中可解析 URL 的精准引用观测；宽松匹配不计入。']


def cohort(records, end):
    return [r for r in view.week_rows(records.answers, end) if not view.qualification(r, records)]


def metrics(rows, *, enough):
    mentions = [r for r in rows if r.mentions_brand is True]
    positions = Counter(getattr(r, 'brand_position', None) for r in mentions)
    distribution = {key: positions[key] for key in ('first', 'alternative', 'mentioned')}
    position_count = sum(distribution.values())
    sentiments = Counter(getattr(r, 'sentiment', None) for r in mentions)
    annotated = sum(sentiments[key] for key in ('positive', 'neutral', 'negative'))
    return {'brand_mention_rate': round(100 * len(mentions) / len(rows), 4) if enough and rows else None,
            'brand_mention_answer_count': len(mentions) if enough and rows else None,
            'average_recommendation_position': round(sum((i+1) * distribution[key] for i, key in enumerate(distribution))
                / position_count, 4) if enough and position_count else None,
            'valid_position_count': position_count, 'position_distribution': distribution,
            'brand_positive_rate': round(100 * sentiments['positive'] / annotated, 4) if enough and annotated else None,
            'annotated_mention_count': annotated, 'mention_count': len(mentions), 'sample_count': len(rows)}


def summary(records, end):
    rows = cohort(records, end)
    enough = sufficient(rows)
    return {'period': view.period(end), 'sample_status': 'ready' if enough else 'insufficient',
            'qualified_counts': {'samples': len(rows), 'questions': len({r.prompt_id for r in rows}),
                                 'engines': len({r.engine for r in rows})},
            'minimum_counts': {'samples': 8, 'questions': 3, 'engines': 2},
            'metrics': metrics(rows, enough=enough),
            'by_engine': [{'engine_key': key, 'label': label,
                           'metrics': metrics([r for r in rows if r.engine == key], enough=enough)} for key, label in ENGINES],
            'footnotes': list(FOOTNOTES)}


def question_cells(prompt_id, records, end, qualified=None):
    rows = qualified if qualified is not None else cohort(records, end)
    results = []
    for engine, label in ENGINES:
        selected = [r for r in rows if r.prompt_id == prompt_id and r.engine == engine]
        x, y = sum(r.mentions_brand is True for r in selected), len(selected)
        state = 'small_sample' if 0 < y < 3 else 'observed' if y else 'not_tested'
        if not y:
            from datetime import timedelta
            start = shanghai_day_bounds_utc_naive(end - timedelta(days=7))[0]
            stop = shanghai_day_bounds_utc_naive(end)[0]
            attempts = [(view.iso(run.finished_at or run.started_at), c) for run in records.runs.values()
                        if run.started_at and start <= to_utc_naive(run.started_at) < stop
                        for c in run.items or [] if c.get('prompt_id') == prompt_id and c.get('engine') == engine]
            if attempts:
                _, cell = max(attempts, key=lambda pair: pair[0] or '')
                reason = str(cell.get('skipped_reason') or '')
                if reason in {'skipped:real_only_no_platform_key', 'skipped:prefer_real_no_platform_key',
                              'skipped:dashscope_only_for_deepseek'}:
                    state = 'not_configured'
                elif not cell.get('ok'):
                    state = 'failed'
        results.append({'engine_key': engine, 'label': label, 'mentioned': x if y else None,
                        'total': y or None, 'percentage': round(100*x/y, 4) if y else None,
                        'last_sample_at': view.latest_time(r.captured_at for r in selected),
                        'status': state, 'small_sample': 0 < y < 3})
    return results


def options(records):
    return {'businesses': [{'id': b.id, 'name': b.name or ''} for b in records.businesses.values()],
            'units': [{'id': u.id, 'business_id': u.business_id, 'name': u.name or '',
                       'keyword': u.keyword, 'display_name': u.keyword or u.name or ''} for u in records.units.values()]}


def article_citations(records, end):
    rows = cohort(records, end)
    stop = shanghai_day_bounds_utc_naive(end)[0]
    publications = {}
    for pub in sorted(records.publications, key=lambda p: p.id):
        if pub.status != 'published' or not pub.published_at or to_utc_naive(pub.published_at) >= stop:
            continue
        url, state = safe_url(pub.published_url)
        # Validate before normalizing. Match original meaningful query parameters.
        normalized = normalize_report_url(pub.published_url) if state == 'available' else None
        if normalized:
            # Multiple registrations of the same URL use the earliest known publication time.
            old = publications.get(normalized)
            if old is None or (to_utc_naive(pub.published_at), pub.id) < (to_utc_naive(old[0].published_at), old[0].id):
                publications[normalized] = (pub, url)
    normalized_answers = {r.id: {normalize_report_url(url) for url in (r.cited_urls or [])
                                if safe_url(url)[1] == 'available'} - {None} for r in rows}
    items = []
    for normalized, (pub, url) in publications.items():
        variant = records.variants[pub.variant_id]
        eligible = [r for r in rows if to_utc_naive(r.captured_at) >= to_utc_naive(pub.published_at)]
        has_evidence = any(normalized_answers[r.id] for r in eligible)
        matches = [r for r in eligible if normalized in normalized_answers[r.id]]
        x, y = len(matches), len(eligible)
        state = 'observed' if has_evidence else 'insufficient_evidence' if y else 'not_tested'
        items.append({'id': pub.id, 'task_id': variant.task_id, 'article_id': variant.article_version_id,
                      'title': variant.title or '', 'url': url, 'published_at': view.iso(pub.published_at),
                      'mentioned': x if has_evidence else None, 'total': y or None,
                      'percentage': round(100*x/y, 4) if has_evidence else None, 'status': state,
                      'evidence': [{'answer_id': r.id, 'question_id': r.prompt_id, 'engine_key': r.engine,
                                    'captured_at': view.iso(r.captured_at),
                                    'answer_path': view.link(records, f'/answers/{r.id}', end=end)} for r in matches]})
    known = bool(rows) and all(item['status'] == 'observed' for item in items)
    state = 'no_publications' if not items else 'not_tested' if not rows else 'observed' if known else 'insufficient_evidence'
    hits = sum(bool(item['evidence']) for item in items)
    return {'items': items, 'coverage': {'cited_articles': hits if known and items else None,
            'published_articles': len(items), 'percentage': round(100*hits/len(items), 4) if known and items else None,
            'status': state}, 'footnotes': list(FOOTNOTES)}


def recommendations(records):
    from app.onsite_workflow import proposal_hash, LABELS
    results = []
    for row in records.recommendations:
        progress = row.progress if isinstance(row.progress, dict) else {}
        stored = progress.get('onsite')
        if not isinstance(stored, dict) or stored.get('project_id') != records.project.id:
            continue
        phase = stored.get('phase')
        recheck = stored.get('recheck') if isinstance(stored.get('recheck'), dict) else {}
        items = stored.get('items') if isinstance(stored.get('items'), list) else []
        approval = stored.get('approval') if isinstance(stored.get('approval'), dict) else {}
        if phase not in {'implementation', 'recheck', 'acceptance', 'done'} or approval.get('hash') != proposal_hash(items):
            continue  # Unreviewed proposals and internal draft material are not deliveries.
        results.append({'id': row.id, 'title': row.title or '',
            'phase': phase if phase in {'draft', 'review', 'implementation', 'recheck', 'acceptance', 'done', 'cancelled'} else None,
            'status': row.status, 'next_action': {'draft': '完善方案', 'review': '人工审核方案',
                'implementation': '实施官网修改', 'recheck': '复检', 'acceptance': '人工验收', 'done': '已完成',
                'cancelled': '已取消'}.get(phase),
            'checked_at': view.iso(view.parsed_time(recheck.get('at'))),
            'recommendations': [{'title': LABELS.get(item.get('kind'), '站内建议'),
                'description': str(item.get('instruction') or '') or None,
                'priority': str(item['priority']) if item.get('priority') else None,
                'status': 'done' if phase == 'done' else 'pending'} for item in items if isinstance(item, dict)]})
    return results
