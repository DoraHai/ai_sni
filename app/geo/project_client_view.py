"""Pure allowlisted projections for the GEO client v1 contract."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.geo.acceptance_readiness import build_h3_h4_summary
from app.geo.content.sample_provenance import sample_provenance, sample_exclusion_reasons
from app.geo.content.time_windows import TENANT_TZ, shanghai_day_bounds_utc_naive, to_utc_naive
from app.geo.integration_metrics import (
    MENTIONS, RATE, SCORE, build_weekly_snapshot, domain, patrol_evidence_reasons, verified_patrol_rows,
)
from app.geo.project_client_protocol import digest, path, public_host, safe_url
from app.geo.read_model import MINIMUM, insufficient, iso, period_context

METRICS = (MENTIONS, RATE, SCORE)


def enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'unknown'


def latest_time(values):
    return iso(max((to_utc_naive(t) for t in values if isinstance(t, datetime)), default=None))


def parsed_time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return value if value.utcoffset() is not None else None
        except (ValueError, TypeError):
            pass
    return None


def timestamp_order(value):
    # Fixed fractional precision preserves chronological order at whole-second
    # boundaries ("...00Z" otherwise sorts after "...00.000001Z").
    return to_utc_naive(parsed_time(value)).isoformat(timespec='microseconds')


def week_rows(rows, end):
    start = shanghai_day_bounds_utc_naive(end - timedelta(days=7))[0]
    stop = shanghai_day_bounds_utc_naive(end)[0]
    return [r for r in rows if r.captured_at and start <= to_utc_naive(r.captured_at) < stop]


def period(end, *, include_week=False):
    result = {'timezone': 'Asia/Shanghai',
              'start': datetime.combine(end-timedelta(days=7), datetime.min.time(), tzinfo=TENANT_TZ).isoformat(),
              'end': datetime.combine(end, datetime.min.time(), tzinfo=TENANT_TZ).isoformat(), 'closed': True}
    if include_week:
        result['week_end'] = str(end)
    return result


def evidence(row, records):
    run = records.runs.get(row.patrol_run_id)
    if records.cells:
        return run, records.cells.get((row.patrol_run_id, row.id))
    cells = (run.items or []) if run else []
    matches = [c for c in cells if isinstance(c, dict) and c.get('snapshot_id') == row.id]
    cell = matches[0] if len(matches) == 1 else None
    return run, cell


def qualification(row, records):
    run, cell = evidence(row, records)
    codes = sample_exclusion_reasons(row) + patrol_evidence_reasons(row, run, cell)
    if records.prompts[row.prompt_id].is_brand_probe:
        codes.append('brand_probe')
    if row.captured_at is None:
        codes.append('unknown_capture_time')
    return list(dict.fromkeys(codes))


def observation(rows):
    real = [r for r in rows if sample_provenance(r)['sample_kind'] == 'real'
            and sample_provenance(r)['analysis_status'] == 'completed' and type(r.mentions_brand) is bool]
    x, y = sum(r.mentions_brand for r in real), len(real)
    return {'mentioned': x, 'total': y, 'status': 'observed' if y else 'no_observations',
            'display_text': f'观测中提及 {x}/{y} 次' if y else '尚无可判读的真实观测',
            'basis_code': 'saved_real_analyzed_answers', 'official_question_rate': None}


def engine_groups(rows, records, *, with_question_count=False):
    groups = []
    for engine in sorted({r.engine for r in rows}):
        selected = [r for r in rows if r.engine == engine]
        qualified = [r for r in selected if not qualification(r, records)]
        item = {'engine_key': engine, 'observation': observation(selected), 'qualified_sample_count': len(qualified)}
        if with_question_count:
            item['qualified_question_count'] = len({r.prompt_id for r in qualified})
        groups.append(item)
    return groups


def weekly_data(records, end):
    # Copies carry historical comparison metadata without modifying ORM records.
    candidates = []
    for row in records.answers:
        if qualification(row, records):
            continue
        copy = SimpleNamespace(**{key: getattr(row, key) for key in (
            'id', 'tenant_id', 'prompt_id', 'engine', 'captured_at', 'sample_mode', 'simulated', 'note',
            'citation_accuracy', 'raw_text', 'mentions_brand', 'cited_urls', 'competitors', 'patrol_run_id')})
        candidates.append(copy)
    # Reuse the exact historical evidence binding and weekly math in one pass.
    candidates = verified_patrol_rows(candidates, list(records.runs.values()))
    current = build_weekly_snapshot(candidates, records.own_domains, end)
    previous = build_weekly_snapshot(candidates, records.own_domains, end-timedelta(days=7))
    context = period_context(records.project.tenant_id, end, current, previous)

    def public(state, boundary):
        failures = insufficient(state)
        selected = week_rows(candidates, boundary)
        metrics = []
        for key in METRICS:
            value = next(m['value'] for m in state['metrics'] if m['metric_key'] == key)
            codes = failures + (['missing_own_domain'] if key == SCORE and not records.own_domains else [])
            metrics.append({'key': key, 'unit': 'score' if key == SCORE else 'percent' if key == RATE else 'count',
                            'value': value, 'status': 'insufficient' if failures else 'unavailable' if codes else 'available',
                            'reason_codes': codes, 'trend_7d': None})
        citations = sum(any(any((host := domain(url)) == own or host.endswith('.' + own) for own in records.own_domains)
                            for url in (r.cited_urls or [])) for r in selected)
        return {'week_end': str(boundary), 'period': period(boundary),
                'sample_status': 'insufficient' if failures else 'ready',
                'message': '检测数据还不够' if failures else None,
                'qualified_counts': {'samples': len(selected), 'questions': len({r.prompt_id for r in selected}),
                                     'engines': len({r.engine for r in selected})},
                'minimum_counts': dict(MINIMUM), 'reason_codes': failures,
                'own_domain_configured': bool(records.own_domains), 'own_domains': records.own_domains,
                'qualified_mention_count': sum(bool(r.mentions_brand) for r in selected),
                'qualified_own_domain_citation_count': citations, 'metrics': metrics}
    now, before = public(current, end), public(previous, end-timedelta(days=7))
    if context['comparison']['comparable']:
        for metric in now['metrics']:
            metric['trend_7d'] = next(m['trend_7d'] for m in current['metrics'] if m['metric_key'] == metric['key'])
    return {'current': now, 'previous': before, 'comparison': context['comparison'],
            'engines': engine_groups(week_rows(records.answers, end), records, with_question_count=True),
            'definitions': {'mention_count': '合格回答中提及品牌的条数，每条最多计一次。',
                'mention_rate': '品牌提及条数除以合格回答数乘 100。',
                'visibility_score': '50 ×（品牌提及条数 + 项目自有域引用回答数）÷ 合格回答数。',
                'qualification': '上海时区已结束完整周，真实非点名 v2 采样且判读和巡检证据通过；至少 8 条、3 题、2 引擎。',
                'ownership_basis': '按当前项目业务归属和当前认可域名重算已有记录。'}}


def basis(records, *, end=None, rows=(), unknown_rows=(), single=False, last_data_at=None):
    source = dict.fromkeys(('real', 'manual', 'simulated', 'unknown'), 0) if end else None
    exclusions = Counter()
    if end:
        for row in rows:
            source[sample_provenance(row)['sample_kind']] += 1
            exclusions.update(qualification(row, records))
    return {'kind': 'saved_records', 'aggregation_complete': True,
            'last_data_at': latest_time(r.captured_at for r in rows) if end else last_data_at,
            'period': period(end, include_week=True) if end else None, 'source_counts': source,
            'unknown_time_count': sum(r.captured_at is None for r in unknown_rows) if end else None,
            'unknown_time_scope': ('single_answer' if single else 'current_project_history') if end else None,
            'exclusion_counts': [{'code': k, 'count': v} for k, v in sorted(exclusions.items())], 'note_codes': []}


def envelope(records, params, data, resource_basis):
    return {'schema_version': 'geo.client.v1', 'tenant_id': params['tenant_id'], 'project_id': params['project_id'],
            'evaluated_at': iso(datetime.now(timezone.utc)), 'read_only': True,
            'scope': {'ownership_basis': 'current_project_binding', 'binding_revision': records.revision,
                      'binding_state': 'bound' if records.businesses else 'unbound',
                      'business_count': len(records.businesses), 'question_count': len(records.prompts)},
            'basis': resource_basis, 'data': data}


def link(records, suffix, *, end=None, **query):
    return path(records.project.id, records.project.tenant_id, suffix, week_end=end, **query)


def question_row(prompt, records, end, rows):
    selected = [r for r in rows if r.prompt_id == prompt.id]
    observed = observation(selected)
    reasons = []
    if prompt.status == 'active' and not prompt.is_brand_probe:
        if not observed['total']:
            reasons = ['no_real_observations']
        elif observed['mentioned'] < observed['total']:
            reasons = ['not_mentioned_in_some_observations']
    unit = records.units[prompt.unit_id]
    business = records.businesses[unit.business_id]
    return {'id': prompt.id, 'question': prompt.question or '',
            'status': 'inactive' if prompt.status in {'inactive', 'paused'} else enum(prompt.status, {'active', 'archived'}),
            'is_brand_probe': bool(prompt.is_brand_probe), 'business': {'id': business.id, 'name': business.name or ''},
            'unit': {'id': unit.id, 'name': unit.name or ''}, 'observation': observed,
            'qualified_sample_count': sum(not qualification(r, records) for r in selected),
            'latest_answer_at': latest_time(r.captured_at for r in selected), 'attention_reason_codes': reasons,
            'detail_path': link(records, f'/questions/{prompt.id}', end=end)}


def answer_row(row, records, end, weekly):
    prompt = records.prompts[row.prompt_id]
    run, cell = evidence(row, records)
    matches = bool(cell and cell.get('prompt_id') == row.prompt_id and cell.get('engine') == row.engine
                   and str(cell.get('raw_text') or '').strip() == str(row.raw_text or '').strip())
    historical = cell if matches else {}
    historical_text = historical.get('prompt_question')
    provider, model = historical.get('provider'), historical.get('model')
    historical_text = historical_text if isinstance(historical_text, str) and historical_text else None
    provider = provider if isinstance(provider, str) and provider else None
    model = model if isinstance(model, str) and model else None
    complete = bool(historical_text and provider and model)
    codes = qualification(row, records)
    in_week = bool(week_rows([row], end))
    membership = list(dict.fromkeys(codes + ([] if in_week else ['unknown_capture_time' if row.captured_at is None else 'outside_selected_week'])))
    source = sample_provenance(row)
    adoption = []
    for metric in weekly['current']['metrics']:
        adoption.append({'key': metric['key'], 'status': 'excluded' if membership else
                         'included' if metric['status'] == 'available' else 'unavailable',
                         'reason_codes': membership if membership else metric['reason_codes']})
    text = row.raw_text or ''
    item = {'id': row.id, 'question_id': row.prompt_id,
            'question': {'historical_text': historical_text, 'current_text': prompt.question or '',
                         'historical_text_source': 'patrol_item' if historical_text else None},
            'engine': {'key': row.engine, 'provider': provider, 'model': model, 'model_revision': None,
                       'metadata_source': 'patrol_item' if matches else None},
            'captured_at': iso(row.captured_at), 'captured_at_local': iso(row.captured_at, True),
            'time_basis': 'stored_utc' if row.captured_at else 'unknown',
            'source': {'kind': source['sample_kind'],
                       'sampling_method': enum(source['sampling_method'], {'unprimed_json_v2', 'legacy', 'unknown'}),
                       'analysis_status': source['analysis_status'], 'verified_server_record': not patrol_evidence_reasons(row, run, cell)},
            'answer_excerpt': text[:300], 'excerpt_truncated': len(text) > 300,
            'mentions_brand': row.mentions_brand if type(row.mentions_brand) is bool else None,
            'sample_eligibility': {'eligible': not codes, 'reason_codes': codes},
            'week_membership': {'within_window': in_week, 'included_in_cohort': in_week and not codes, 'reason_codes': membership},
            'metric_adoption': adoption, 'detail_path': link(records, f'/answers/{row.id}', end=end)}
    citations, seen = [], set()
    for url in row.cited_urls or []:
        normalized = str(url or '').strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        safe, state = safe_url(normalized)
        # Ownership is a host classification, independent of clickability.
        # A suppressed query must not turn a valid own-domain citation into an
        # apparent foreign citation; the original URL is never serialized.
        host = public_host(domain(normalized))
        citations.append({'url': safe, 'url_state': state, 'is_own_domain': bool(host and any(
            host == own or host.endswith('.' + own) for own in records.own_domains))})
    return item, {'item': item, 'raw_text': text, 'citations': citations,
                  'comparison_metadata': {'complete': complete, 'reason_codes': [] if complete else ['model_metadata_missing'],
                                          'model_identity_basis': 'recorded_request_model_alias' if model else None,
                                          'exact_model_revision_known': False}}


def current_master(records, task_id):
    return max((a for a in records.articles.values() if a.task_id == task_id), key=lambda a: (a.version_no, a.id), default=None)


def article_row(article):
    return {'id': article.id, 'task_id': article.task_id, 'version_no': article.version_no, 'kind': 'master',
            'title': article.title or '', 'body_markdown': article.body_markdown or '', 'created_at': iso(article.created_at)}


def review(task, records):
    master = current_master(records, task.id)
    status = enum(task.review_status, {'none', 'pending', 'approved', 'rejected'})
    covers = bool(status == 'approved' and task.reviewed_at and master and master.created_at
                  and to_utc_naive(task.reviewed_at) >= to_utc_naive(master.created_at))
    text = {'none': '尚未提交客户确认', 'pending': '待客户确认', 'approved': '已确认，发布状态请查看交付记录',
            'rejected': '客户要求修改', 'unknown': '确认状态未知'}[status]
    if status == 'approved' and not covers:
        text = '历史版本已确认，当前版本尚无有效确认记录'
    return {'status': status, 'reviewed_at': iso(task.reviewed_at), 'covers_current_master': covers, 'display_text': text}


def task_row(task, records):
    master = current_master(records, task.id)
    variants = [v for v in records.variants.values() if v.task_id == task.id]
    ids = {v.id for v in variants}
    count = sum(p.status == 'published' and safe_url(p.published_url)[1] == 'available'
                for p in records.publications if p.variant_id in ids)
    return {'id': task.id, 'title': task.title or '', 'question_id': task.prompt_id,
            'question': records.prompts[task.prompt_id].question or '',
            'stored_status': enum(task.status, {'draft', 'facts_bound', 'generating', 'editing', 'needs_fix', 'adapting', 'ready',
                                              'exported', 'published', 'failed', 'archived', 'cancelled'}),
            'pipeline_step': enum(task.pipeline_step, {'opportunity', 'evidence', 'draft', 'adapt', 'publish'}),
            'review': review(task, records),
            'latest_master': {k: article_row(master)[k] for k in ('id', 'version_no', 'title', 'created_at')} if master else None,
            'variant_count': len(variants), 'published_record_count': count,
            'updated_at': iso(task.updated_at or task.created_at), 'detail_path': link(records, f'/content/{task.id}')}


def variant_row(variant, records):
    article = records.articles[variant.article_version_id]
    master = current_master(records, variant.task_id)
    return {'id': variant.id, 'task_id': variant.task_id, 'article_id': article.id, 'article_version_no': article.version_no,
            'channel': variant.channel or '', 'title': variant.title or '',
            'stored_status': enum(variant.status, {'draft', 'exported', 'published'}),
            'created_at': iso(variant.created_at), 'updated_at': iso(variant.updated_at),
            'is_current_master': bool(master and master.id == article.id),
            'detail_path': link(records, f'/content/{variant.task_id}/variants/{variant.id}')}


def delivery_entries(variant):
    meta = variant.adapt_meta if isinstance(variant.adapt_meta, dict) else {}
    entries = meta.get('push_deliveries')
    return [(k, v) for k, v in entries.items() if isinstance(v, dict)] if isinstance(entries, dict) else []


def receipt_rows(records, variants):
    rows = []
    for variant in variants:
        master = current_master(records, variant.task_id)
        for key, entry in delivery_entries(variant):
            state = enum(entry.get('state'), {'sending', 'succeeded', 'failed', 'unknown'})
            article_id = entry.get('article_id')
            article = records.articles.get(article_id) if type(article_id) is int else None
            valid = bool(article and article.task_id == variant.task_id)
            reason = None
            if not valid:
                reason = 'article_reference_invalid'
            elif not isinstance(entry.get('state'), str) or entry.get('state') not in {'sending', 'succeeded', 'failed', 'unknown'}:
                reason = 'unrecognized_receipt_state'
            elif state in {'failed', 'unknown'}:
                reason = entry.get('reason') if isinstance(entry.get('reason'), str) and entry['reason'] in {
                    'timeout', 'authorization_failed', 'quota_exceeded'} else 'execution_failed'
            rows.append({'record_type': 'receipt', 'receipt_id': digest([variant.id, str(key)]),
                         'task_id': variant.task_id, 'variant_id': variant.id, 'article_id': article.id if valid else None,
                         'article_version_no': article.version_no if valid else None,
                         'is_current_master': bool(valid and master and article.id == master.id),
                         'title': variant.title or '', 'channel': variant.channel or '', 'state': state,
                         'updated_at': iso(parsed_time(entry.get('updated_at'))), 'reason_code': reason,
                         'display_text': {'sending': '投递处理中', 'succeeded': '已有投递成功回执，发布登记与页面核验请分别查看',
                                          'failed': '投递失败', 'unknown': '投递结果未知'}[state],
                         'task_path': link(records, f'/content/{variant.task_id}'),
                         'variant_path': link(records, f'/content/{variant.task_id}/variants/{variant.id}')})
    return rows


def publication_rows(records, publications):
    results = []
    monitor = {}
    for task in records.tasks.values():
        articles = [a for a in records.articles.values() if a.task_id == task.id]
        variants = [v for v in records.variants.values() if v.task_id == task.id]
        safe_variants = []
        for variant in variants:
            meta = variant.adapt_meta if isinstance(variant.adapt_meta, dict) else {}
            states = meta.get('publication_monitor')
            states = states if isinstance(states, dict) else {}
            safe_states = {key: {field: state.get(field) for field in (
                'state', 'expected_fingerprint', 'article_id', 'checked_at')}
                for key, state in states.items() if isinstance(state, dict)}
            safe_variants.append(SimpleNamespace(id=variant.id, task_id=variant.task_id,
                article_version_id=variant.article_version_id, channel=variant.channel,
                title=variant.title, body_markdown=variant.body_markdown,
                adapt_meta={'publication_monitor': safe_states}))
        # The H3/H4 pure summary validates the fingerprint, version and checked_at.
        summary = build_h3_h4_summary(task, articles, safe_variants, publications)
        monitor.update({item['publication_ref']['id']: item for item in summary['h4']['monitoring']})
    for publication in publications:
        variant = records.variants[publication.variant_id]
        article = records.articles[variant.article_version_id]
        master = current_master(records, variant.task_id)
        current = bool(master and master.id == article.id)
        meta = variant.adapt_meta if isinstance(variant.adapt_meta, dict) else {}
        saved = meta.get('publication_monitor')
        saved = saved.get(str(publication.id)) if isinstance(saved, dict) else None
        saved = saved if isinstance(saved, dict) else {}
        raw_state = saved.get('state', 'pending')
        state = enum(raw_state, {'healthy', 'pending', 'unverified', 'unreachable', 'mismatch', 'version_changed', 'unhealthy'})
        if state in {'unreachable', 'mismatch', 'version_changed'}:
            state = 'unhealthy'
        checked_at = iso(parsed_time(saved.get('checked_at')))
        item = monitor.get(publication.id)
        valid = bool(item and item['evidence_valid'] and current)
        reasons = list(item['evidence_reasons']) if item else []
        if not current:
            state, valid = 'unverified', False
            reasons = ['historical_article']
        elif saved and item is None:
            # A non-published record can never acquire valid delivery evidence.
            from app.geo.acceptance_readiness import _variant_fingerprint
            reasons = ([] if raw_state == 'healthy' else ['monitor_not_healthy'])
            if saved.get('expected_fingerprint') != _variant_fingerprint(variant):
                reasons.append('fingerprint_missing_or_mismatch')
            if saved.get('article_id') != article.id:
                reasons.append('article_version_mismatch')
            if checked_at is None:
                reasons.append('checked_at_missing_or_invalid')
        elif not saved:
            state, checked_at, valid, reasons = 'pending', None, False, []
        url, url_state = safe_url(publication.published_url) if publication.published_url else (None, 'missing')
        results.append({'record_type': 'publication', 'id': publication.id, 'task_id': variant.task_id,
                        'variant_id': variant.id, 'article_id': article.id, 'article_version_no': article.version_no,
                        'is_current_master': current, 'title': variant.title or '', 'channel': publication.channel or '',
                        'publish_mode': enum(publication.publish_mode, {'manual_export', 'api', 'browser'}),
                        'stored_status': enum(publication.status, {'pending', 'published', 'failed'}),
                        'published_url': url, 'url_state': url_state, 'published_at': iso(publication.published_at),
                        'updated_at': iso(publication.updated_at),
                        'verification': {'state': state, 'checked_at': checked_at, 'evidence_valid': valid, 'reason_codes': reasons},
                        'task_path': link(records, f'/content/{variant.task_id}'),
                        'variant_path': link(records, f'/content/{variant.task_id}/variants/{variant.id}'),
                        'article_path': link(records, f'/content/{variant.task_id}/articles/{article.id}')})
    return results
