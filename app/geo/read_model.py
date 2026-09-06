"""Pure serialization/diagnostics for the GEO workbench. No I/O or mutations."""
from datetime import datetime, timedelta, timezone
from app.geo.content.time_windows import TENANT_TZ, to_utc_naive
from app.geo.content.sample_provenance import sample_provenance, sample_exclusion_reasons
from app.geo.integration_metrics import SCORE, complete_model_counts, patrol_evidence_reasons

MINIMUM = {'samples': 8, 'questions': 3, 'engines': 2}
LABELS = {
    'simulated_sample': '模拟回答不进入正式指标', 'manual_sample': '人工记录不进入正式指标',
    'unknown_source': '来源未知', 'unsupported_sampling_method': '不是无品牌诱导的 v2 采样',
    'analysis_incomplete': '回答判读尚未完成', 'citation_inaccurate': '引用已标记不准确',
    'brand_probe': '品牌点名问题不进入正式指标', 'missing_server_evidence': '缺少同租户服务端巡检证据',
    'patrol_not_completed': '关联巡检尚未完成', 'capture_outside_patrol': '采样时间不在巡检起止范围内',
    'snapshot_patrol_mismatch': '回答与服务端巡检原始结果不一致',
    'outside_selected_week': '回答不在所选正式完整周', 'insufficient_samples': '合格回答少于 8 条',
    'insufficient_questions': '有效问题少于 3 个', 'insufficient_engines': '有效引擎少于 2 个',
    'missing_own_domain': '未配置启用的官网或文档域名',
}


def iso(value, local=False):
    if value is None:
        return None
    aware = to_utc_naive(value).replace(tzinfo=timezone.utc)
    return aware.astimezone(TENANT_TZ).isoformat() if local else aware.isoformat().replace('+00:00', 'Z')


def ref(kind, ident):
    return {'module': 'geo', 'type': kind, 'id': ident}


def reason(codes, scope):
    return [{'code': code, 'scope': scope, 'message': LABELS.get(code, code)} for code in dict.fromkeys(codes)]


def coverage(state):
    cells = state['sample_counts']
    return {'samples': len(state['sample_ids']), 'questions': len({c[0] for c in cells}),
            'engines': len({c[1] for c in cells})}


def insufficient(state):
    counts = coverage(state)
    return ['insufficient_' + key for key, minimum in MINIMUM.items() if counts[key] < minimum]


def period_context(tenant_id, end, current, previous):
    def window(state, boundary):
        failures = insufficient(state)
        return {'start': datetime.combine(boundary-timedelta(days=7), datetime.min.time(), tzinfo=TENANT_TZ).isoformat(),
                'end': datetime.combine(boundary, datetime.min.time(), tzinfo=TENANT_TZ).isoformat(),
                'closed': True, 'status': 'insufficient' if failures else 'ready',
                'qualified_counts': coverage(state), 'reasons': reason(failures, 'week')}
    checks = {
        'current_week_sufficient': not insufficient(current), 'previous_week_sufficient': not insufficient(previous),
        'same_cohort': current['cohort'] == previous['cohort'],
        'same_historical_questions': current['questions'] == previous['questions'],
        'complete_model_metadata': complete_model_counts(current['model_counts']) and complete_model_counts(previous['model_counts']),
        'same_model_distribution': current['model_counts'] == previous['model_counts'],
        'same_sample_distribution': current['sample_counts'] == previous['sample_counts'],
    }
    comparison_codes = dict(zip(checks, ['current_week_insufficient', 'previous_week_insufficient', 'cohort_changed',
                                        'question_changed', 'model_metadata_missing', 'model_distribution_changed', 'sample_distribution_changed']))
    statuses = []
    for metric in current['metrics']:
        codes = insufficient(current)
        if metric['metric_key'] == SCORE and not current['own_domains']:
            codes = codes + ['missing_own_domain']
        statuses.append({'metric_key': metric['metric_key'], 'status': 'unavailable' if codes else 'available', 'reason_codes': codes})
    return {'tenant_id': tenant_id, 'evaluated_at': iso(datetime.now(timezone.utc)), 'timezone': 'Asia/Shanghai',
            'week_end': end.isoformat(), 'current': window(current, end), 'previous': window(previous, end-timedelta(days=7)),
            'minimum_counts': MINIMUM, 'own_domain_configured': bool(current['own_domains']), 'metric_status': statuses,
            'comparison': {'comparable': all(checks.values()), 'checks': checks,
                           'reason_codes': [comparison_codes[key] for key, passed in checks.items() if not passed]},
            'metrics_url': f'/api/v1/geo/integration/metrics/snapshot?tenant_id={tenant_id}&week_end={end}',
            'dictionary_url': f'/api/v1/geo/integration/metrics/dictionary?tenant_id={tenant_id}&week_end={end}'}


def answer_payload(row, prompt, run, context, *, detail=False):
    if run and run.tenant_id != row.tenant_id:
        run = None
    cell = {c.get('snapshot_id'): c for c in (run.items or []) if isinstance(c, dict)}.get(row.id) if run else None
    evidence_codes = patrol_evidence_reasons(row, run, cell)
    codes = sample_exclusion_reasons(row) + evidence_codes
    if prompt.is_brand_probe and 'brand_probe' not in codes:
        codes.append('brand_probe')
    provenance = sample_provenance(row)
    start = to_utc_naive(datetime.fromisoformat(context['current']['start']))
    end = to_utc_naive(datetime.fromisoformat(context['current']['end']))
    in_week = bool(row.captured_at and start <= to_utc_naive(row.captured_at) < end)
    membership = reason(codes, 'sample') if codes else ([] if in_week else reason(['outside_selected_week'], 'window'))
    adoption = []
    for metric in context['metric_status']:
        failures = membership or reason(metric['reason_codes'], 'week')
        adoption.append({'metric_key': metric['metric_key'], 'status': 'excluded' if membership else ('unavailable' if failures else 'included'), 'reasons': failures})
    # Expose historical item metadata only when the identity/text binding matches.
    identity_matches = bool(cell and cell.get('prompt_id') == row.prompt_id and cell.get('engine') == row.engine
                            and str(cell.get('raw_text') or '').strip() == str(row.raw_text or '').strip())
    historical = cell if identity_matches else {}
    complete = bool(historical.get('provider') and historical.get('model') and historical.get('prompt_question'))
    result = {
        'ref': ref('answer_snapshot', row.id),
        'question': {'id': row.prompt_id, 'historical_text': historical.get('prompt_question'), 'current_text': prompt.question,
                     'historical_text_source': 'patrol_item' if historical.get('prompt_question') else None},
        'engine': {'key': row.engine, 'provider': historical.get('provider'), 'model': historical.get('model'),
                   'model_revision': None, 'metadata_source': 'patrol_item' if historical else None},
        'captured_at': iso(row.captured_at), 'captured_at_local': iso(row.captured_at, True),
        'time_basis': 'stored_utc' if row.captured_at else 'unknown',
        'source': {'kind': provenance['sample_kind'], 'stored_sample_mode': row.sample_mode, 'simulated': bool(row.simulated),
                   'sampling_method': provenance['sampling_method'], 'analysis_status': provenance['analysis_status'],
                   'verified_server_record': not evidence_codes},
        'answer_excerpt': (row.raw_text or '')[:300], 'mentions_brand': row.mentions_brand,
        'cited_urls': row.cited_urls or [], 'competitors': row.competitors or [],
        'sample_eligibility': {'eligible': not codes, 'reasons': reason(codes, 'sample')},
        'week_membership': {'within_window': in_week, 'included_in_cohort': in_week and not codes, 'reasons': membership},
        'metric_adoption': adoption,
        'comparison_metadata': {'complete': complete, 'reason_codes': [] if complete else ['model_metadata_missing'],
                                'model_identity_basis': 'recorded_request_model_alias' if historical.get('model') else None,
                                'exact_model_revision_known': False},
        'relations': [{'relation': 'captured_by', 'target': ref('patrol_run', run.id)}] if run else [],
        'detail_url': f'/api/v1/geo/integration/read/answers/{row.id}?tenant_id={row.tenant_id}&week_end={context["week_end"]}',
    }
    if detail:
        result['raw_text'] = row.raw_text or ''
    return result
